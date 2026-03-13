"""
GRID BOT 2026 — Grid Engine (Multi-Symbol Support)
Ядро сеточного бота: расчёт уровней, управление состоянием, rebalancing
"""

import sqlite3
import os
import math
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
from datetime import datetime, timezone
from logger import logger

@dataclass
class GridLevel:
    """Один уровень сетки"""
    price: float
    side: str  # "Buy" или "Sell"
    order_id: str = ""
    status: str = "pending"  # pending / active / filled / cancelled
    filled_at: str = ""
    pair_order_id: str = ""  # ID обратного ордера (TP)

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class GridState:
    """Полное состояние сетки для сохранения/восстановления"""
    symbol: str = ""
    upper: float = 0
    lower: float = 0
    grid_count: int = 0
    qty_per_level: float = 0
    levels: List[dict] = field(default_factory=list)
    total_trades: int = 0
    realized_profit: float = 0 # Чистая прибыль после комиссий
    fees_paid: float = 0
    max_equity_seen: float = 0 # Для трейлинг-стопа профита
    start_balance: float = 0
    started_at: str = ""
    last_update: str = ""

class GridEngine:
    def __init__(self, symbol: str, upper: float, lower: float, count: int, mode: str = "neutral",
                 start_balance: float = 0.0, db_path: str = "grid_state.db"):
        self.symbol = symbol
        self.upper = upper
        self.lower = lower
        self.count = count
        self.mode = mode
        self.levels: List[GridLevel] = []
        self.qty_per_level: float = 0
        self.qty_per_level: float = 0
        self.total_profit: float = 0.0 # Это грязная база (step * qty)
        self.realized_profit: float = 0.0 # Это чистая (profit - fees)
        self.fees_paid: float = 0.0
        self.max_equity_seen: float = 0.0
        self.total_trades: int = 0
        self.start_balance: float = start_balance
        self.last_fill_at: str = datetime.now(timezone.utc).isoformat()
        
        # Разрешаем пути до папки data/
        if not os.path.exists(os.path.dirname(db_path)) and os.path.dirname(db_path):
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Создает таблицы в SQLite, если их нет (Multi-Symbol)"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS grid_state (
                        symbol TEXT PRIMARY KEY,
                        upper REAL,
                        lower REAL,
                        qty_per_level REAL,
                        total_profit REAL,
                        realized_profit REAL,
                        fees_paid REAL,
                        max_equity_seen REAL,
                        total_trades INTEGER,
                        start_balance REAL,
                        last_fill_at TEXT,
                        updated_at TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS grid_levels (
                        symbol TEXT,
                        price REAL,
                        side TEXT,
                        status TEXT,
                        order_id TEXT,
                        filled_at TEXT,
                        pair_order_id TEXT,
                        PRIMARY KEY (symbol, price, side)
                    )
                ''')
                
                # Миграция: Проверяем наличие новых колонок
                cursor.execute("PRAGMA table_info(grid_state)")
                columns = [col[1] for col in cursor.fetchall()]
                
                new_cols = {
                    "realized_profit": "REAL DEFAULT 0",
                    "fees_paid": "REAL DEFAULT 0",
                    "max_equity_seen": "REAL DEFAULT 0",
                    "last_fill_at": "TEXT"
                }
                
                for col_name, col_def in new_cols.items():
                    if col_name not in columns:
                        logger.info(f"[DB] Миграция: Добавление колонки {col_name}")
                        cursor.execute(f"ALTER TABLE grid_state ADD COLUMN {col_name} {col_def}")
                
                conn.commit()
        except Exception as e:
            logger.error(f"[{self.symbol}] Ошибка инициализации БД: {e}")

    def calculate_levels(self, current_price: float) -> List[GridLevel]:
        if self.upper <= self.lower:
            raise ValueError(f"Upper ({self.upper}) must be > Lower ({self.lower})")

        step = (self.upper - self.lower) / (self.count - 1) if self.count > 1 else 0
        self.levels = []

        for i in range(self.count):
            price = self.lower + (step * i)
            price = round(price, 4)

            if price < current_price:
                side = "Buy"
            elif price > current_price:
                side = "Sell"
            else:
                continue

            self.levels.append(GridLevel(price=price, side=side))

        return self.levels

    def get_step_size(self) -> float:
        if self.count <= 1:
            return 0
        return (self.upper - self.lower) / (self.count - 1)

    def calculate_qty_per_level(self, balance: float, leverage: int, current_price: float, qty_step: float = 0.001, min_qty: float = 0.001) -> float:
        total_margin = balance * leverage
        active_levels = max(len(self.levels), 1)
        margin_per_level = total_margin / active_levels
        qty = margin_per_level / current_price

        qty = math.floor(qty / qty_step) * qty_step
        qty = max(qty, min_qty)

        qty_str = str(qty_step).rstrip('0')
        precision = len(qty_str.split('.')[1]) if '.' in qty_str else 0
        qty = round(qty, precision)

        self.qty_per_level = qty
        return qty

    def get_opposite_level(self, filled_level: GridLevel) -> Optional[GridLevel]:
        step = self.get_step_size()
        if step <= 0: return None

        if filled_level.side == "Buy":
            tp_price = round(filled_level.price + step, 4)
            return GridLevel(price=tp_price, side="Sell")
        else:
            tp_price = round(filled_level.price - step, 4)
            return GridLevel(price=tp_price, side="Buy")

    def record_profit(self, profit: float, fee_rate: float = 0.0006):
        """
        Записывает прибыль и реально считает комиссию Bybit (0.06% для Taker).
        """
        # При исполнении уровня Buy и затем Sell мы платим комиссию дважды.
        # Оборот одной "петли" (Buy+Sell) примерно: qty * price * 2
        trade_volume = self.qty_per_level * (self.upper + self.lower) / 2
        fees = trade_volume * fee_rate * 2
        
        self.total_profit += profit
        self.fees_paid += fees
        self.realized_profit += (profit - fees)
        self.total_trades += 1
        self.last_fill_at = datetime.now(timezone.utc).isoformat()
        
        logger.debug(f"[{self.symbol}] Profit: +${profit:.2f}, Fee: -${fees:.2f}, Net: +${profit-fees:.2f}")

    def update_max_equity(self, current_equity: float):
        if current_equity > self.max_equity_seen:
            self.max_equity_seen = current_equity

    def check_profit_protection(self, current_equity: float, threshold_pct: float, cutoff_pct: float) -> bool:
        """
        Если профит вырос выше 5%, и упал на 20% от пика - пора закрывать.
        """
        if self.start_balance <= 0 or self.max_equity_seen <= self.start_balance:
            return False
            
        profit_pct = (self.max_equity_seen - self.start_balance) / self.start_balance * 100
        if profit_pct < threshold_pct:
            return False
            
        peak_profit = self.max_equity_seen - self.start_balance
        current_profit = current_equity - self.start_balance
        
        if current_profit < peak_profit * (1 - cutoff_pct / 100):
            return True
        return False

    def should_rebalance(self, current_price: float, threshold: float = 0.8) -> bool:
        total_range = self.upper - self.lower
        if total_range <= 0: return True

        dist_to_upper = self.upper - current_price
        dist_to_lower = current_price - self.lower

        if current_price >= self.upper or current_price <= self.lower:
            return True

        edge_zone = total_range * (1.0 - threshold)
        if dist_to_upper < edge_zone or dist_to_lower < edge_zone:
            return True

        return False

    def recenter_grid(self, current_price: float):
        half_range = (self.upper - self.lower) / 2
        self.upper = current_price + half_range
        self.lower = current_price - half_range
        self.calculate_levels(current_price)

    def rebalance(self, new_price: float, range_pct: float = 3.0):
        old_upper = self.upper
        old_lower = self.lower
        
        self.upper = round(new_price * (1 + range_pct / 100), 4)
        self.lower = round(new_price * (1 - range_pct / 100), 4)
        
        self.calculate_levels(new_price)

    def check_max_drawdown(self, current_balance: float, max_drawdown_pct: float) -> bool:
        if self.start_balance <= 0: return False
        drawdown = (self.start_balance - current_balance) / self.start_balance * 100
        return drawdown >= max_drawdown_pct

    def save_state(self, filepath: str = None):
        """Сохраняет состояние бота и уровней сетки в SQLite."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute('''
                    INSERT OR REPLACE INTO grid_state 
                    (symbol, upper, lower, qty_per_level, total_profit, realized_profit, fees_paid, max_equity_seen, total_trades, start_balance, last_fill_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (self.symbol, self.upper, self.lower, self.qty_per_level, 
                      self.total_profit, self.realized_profit, self.fees_paid, self.max_equity_seen,
                      self.total_trades, self.start_balance, self.last_fill_at, datetime.now(timezone.utc).isoformat()))
                
                cursor.execute('DELETE FROM grid_levels WHERE symbol = ?', (self.symbol,))
                for lvl in self.levels:
                    cursor.execute('''
                        INSERT INTO grid_levels (symbol, price, side, status, order_id, filled_at, pair_order_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (self.symbol, lvl.price, lvl.side, lvl.status, lvl.order_id, lvl.filled_at, lvl.pair_order_id))
                    
                conn.commit()
        except Exception as e:
            logger.error(f"[{self.symbol}] Ошибка сохранения состояния: {e}")

    def load_state(self, filepath: str = None) -> bool:
        """Загружает состояние из SQLite. Return True if restored."""
        if not os.path.exists(self.db_path): return False
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT upper, lower, qty_per_level, total_profit, realized_profit, fees_paid, max_equity_seen, total_trades, start_balance, last_fill_at FROM grid_state WHERE symbol=?', (self.symbol,))
                state_row = cursor.fetchone()
                
                if not state_row: return False
                    
                self.upper, self.lower, self.qty_per_level, self.total_profit, self.realized_profit, self.fees_paid, self.max_equity_seen, self.total_trades, self.start_balance, self.last_fill_at = state_row
                
                cursor.execute('SELECT price, side, status, order_id, filled_at, pair_order_id FROM grid_levels WHERE symbol=? ORDER BY price DESC', (self.symbol,))
                level_rows = cursor.fetchall()
                
                if level_rows:
                    self.levels = [
                        GridLevel(
                            price=row[0], side=row[1], status=row[2],
                            order_id=row[3], filled_at=row[4], pair_order_id=row[5]
                        ) for row in level_rows
                    ]
                else:
                    self.levels = []
                
                logger.info(f"[{self.symbol}] Состояние успешно загружено (Trades: {self.total_trades}, Profit: {self.total_profit}).")
                return True
        except Exception as e:
            logger.error(f"[{self.symbol}] Ошибка загрузки состояния: {e}")
            return False

    @staticmethod
    def get_active_symbols(db_path: str) -> List[str]:
        """Возвращает список запущенных символов из БД, если нужно восстановить сетки."""
        if not os.path.exists(db_path): return []
        try:
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT symbol FROM grid_state')
                rows = cursor.fetchall()
                return [r[0] for r in rows]
        except:
            return []
