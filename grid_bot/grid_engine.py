"""
GRID BOT 2026 — Grid Engine
Ядро сеточного бота: расчёт уровней, управление состоянием, rebalancing
"""

import sqlite3
import os
import math
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict
from datetime import datetime
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
    total_profit: float = 0
    total_trades: int = 0
    start_balance: float = 0
    started_at: str = ""
    last_update: str = ""


class GridEngine:
    """
    Рассчитывает уровни сетки, управляет состоянием.

    Логика:
    1. Сетка = N уровней от lower до upper
    2. Ниже текущей цены → Buy ордера
    3. Выше текущей цены → Sell ордера
    4. Когда Buy исполняется → ставим Sell на уровень выше
    5. Когда Sell исполняется → ставим Buy на уровень ниже
    """

    def __init__(self, upper: float, lower: float, count: int, mode: str = "neutral",
                 start_balance: float = 0.0, db_path: str = "grid_state.db"):
        self.upper = upper
        self.lower = lower
        self.count = count
        self.mode = mode
        self.levels: List[GridLevel] = []
        self.qty_per_level: float = 0
        self.total_profit: float = 0.0
        self.total_trades: int = 0
        self.start_balance: float = start_balance
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Создает таблицы в SQLite, если их нет."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS grid_state (
                        id INTEGER PRIMARY KEY DEFAULT 1,
                        upper REAL,
                        lower REAL,
                        qty_per_level REAL,
                        total_profit REAL,
                        total_trades INTEGER,
                        start_balance REAL,
                        updated_at TEXT
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS grid_levels (
                        price REAL,
                        side TEXT,
                        status TEXT,
                        order_id TEXT,
                        filled_at TEXT,
                        pair_order_id TEXT,
                        PRIMARY KEY (price, side)
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.error(f"[GridEngine] Ошибка инициализации БД: {e}")

    def calculate_levels(self, current_price: float) -> List[GridLevel]:
        """
        Рассчитывает уровни сетки.
        Уровни ниже текущей цены = Buy
        Уровни выше текущей цены = Sell
        """
        if self.upper <= self.lower:
            raise ValueError(f"Upper ({self.upper}) must be > Lower ({self.lower})")

        step = (self.upper - self.lower) / (self.count - 1) if self.count > 1 else 0
        self.levels = []

        for i in range(self.count):
            price = self.lower + (step * i)
            # Округляем до 2 знаков (будет уточнено по symbol info)
            price = round(price, 4)

            if price < current_price:
                side = "Buy"
            elif price > current_price:
                side = "Sell"
            else:
                # Цена точно на уровне — пропускаем
                continue

            self.levels.append(GridLevel(price=price, side=side))

        return self.levels

    def get_step_size(self) -> float:
        """Размер шага сетки"""
        if self.count <= 1:
            return 0
        return (self.upper - self.lower) / (self.count - 1)

    def calculate_qty_per_level(
        self,
        balance: float,
        leverage: int,
        current_price: float,
        qty_step: float = 0.001,
        min_qty: float = 0.001
    ) -> float:
        """
        Рассчитывает количество на каждый уровень.
        Делим баланс × плечо на количество уровней.
        """
        total_margin = balance * leverage
        # Количество активных уровней (вычитаем 1-2 ближайших к цене)
        active_levels = max(len(self.levels), 1)
        margin_per_level = total_margin / active_levels
        qty = margin_per_level / current_price

        # Округляем вниз до qty_step
        qty = math.floor(qty / qty_step) * qty_step
        qty = max(qty, min_qty)

        # Округлим до нужного кол-ва знаков
        qty_str = str(qty_step).rstrip('0')
        precision = len(qty_str.split('.')[1]) if '.' in qty_str else 0
        qty = round(qty, precision)

        self.qty_per_level = qty
        return qty

    def get_opposite_level(self, filled_level: GridLevel) -> Optional[GridLevel]:
        """
        После исполнения ордера определяет цену обратного ордера.
        Buy filled @ 1980 → Sell @ 1980 + step
        Sell filled @ 2020 → Buy @ 2020 - step
        """
        step = self.get_step_size()
        if step <= 0:
            return None

        if filled_level.side == "Buy":
            tp_price = round(filled_level.price + step, 4)
            return GridLevel(price=tp_price, side="Sell")
        else:
            tp_price = round(filled_level.price - step, 4)
            return GridLevel(price=tp_price, side="Buy")

    def record_profit(self, profit: float):
        """Записывает профит от закрытой пары grid-ордеров"""
        self.total_profit += profit
        self.total_trades += 1

    def should_rebalance(self, current_price: float, threshold: float = 0.8) -> bool:
        """
        Надо ли перестраивать сетку?
        True, если цена ушла дальше threshold (80%) от края.
        """
        total_range = self.upper - self.lower
        if total_range <= 0:
            return True

        # Расстояние от ближайшего края
        dist_to_upper = self.upper - current_price
        dist_to_lower = current_price - self.lower

        # Если цена вышла за пределы — однозначно rebalance
        if current_price >= self.upper or current_price <= self.lower:
            return True

        # Если цена в крайних 20% — перестраиваем
        edge_zone = total_range * (1.0 - threshold)
        if dist_to_upper < edge_zone or dist_to_lower < edge_zone:
            return True

        return False

    def recenter_grid(self, current_price: float):
        """Recalculates the grid bounds centered around the new price and clears active levels."""
        half_range = (self.upper - self.lower) / 2
        self.upper = current_price + half_range
        self.lower = current_price - half_range
        self.calculate_levels(current_price)

    def rebalance(self, new_price: float, range_pct: float = 3.0):
        """
        Перестраивает сетку вокруг новой цены.
        Сохраняет количество уровней и qty.
        """
        old_upper = self.upper
        old_lower = self.lower
        
        self.upper = round(new_price * (1 + range_pct / 100), 4)
        self.lower = round(new_price * (1 - range_pct / 100), 4)
        
        if new_price > old_upper:
            logger.info(f"[rebalance] Price moved UP. Old range: [{old_lower}, {old_upper}], New range: [{self.lower}, {self.upper}]")
        elif new_price < old_lower:
            logger.info(f"[rebalance] Price moved DOWN. Old range: [{old_lower}, {old_upper}], New range: [{self.lower}, {self.upper}]")
        else:
            logger.info(f"[rebalance] Recalculating grid around {new_price}. New range: [{self.lower}, {self.upper}]")

        self.calculate_levels(new_price)

    def check_max_drawdown(self, current_balance: float, max_drawdown_pct: float) -> bool:
        """
        Проверяет не превышен ли максимальный drawdown.
        Returns True если нужно ОСТАНОВИТЬ бота.
        """
        if self.start_balance <= 0:
            return False
        drawdown = (self.start_balance - current_balance) / self.start_balance * 100
        return drawdown >= max_drawdown_pct

    # === Сохранение / Восстановление состояния ===

    def save_state(self, filepath: str = None):
        """Сохраняет состояние бота и уровней сетки в SQLite (filepath игнорируется, используется db_path)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Сохраняем основное состояние (upsert row with id=1)
                cursor.execute('''
                    INSERT OR REPLACE INTO grid_state 
                    (id, upper, lower, qty_per_level, total_profit, total_trades, start_balance, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                ''', (self.upper, self.lower, self.qty_per_level, 
                      self.total_profit, self.total_trades, self.start_balance, datetime.utcnow().isoformat()))
                
                # Сохраняем уровни 
                cursor.execute('DELETE FROM grid_levels') # Clear old levels
                for lvl in self.levels:
                    cursor.execute('''
                        INSERT INTO grid_levels (price, side, status, order_id, filled_at, pair_order_id)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (lvl.price, lvl.side, lvl.status, lvl.order_id, lvl.filled_at, lvl.pair_order_id))
                    
                conn.commit()
        except Exception as e:
            logger.error(f"[GridEngine] Ошибка сохранения состояния в БД: {e}")

    def load_state(self, filepath: str = None) -> Optional['GridEngine']:
        """Загружает состояние из SQLite (filepath игнорируется)."""
        if not os.path.exists(self.db_path):
            logger.info(f"[GridEngine] База данных не найдена по пути: {self.db_path}. Создаем новое состояние.")
            return None
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Загружаем основное состояние
                cursor.execute('SELECT upper, lower, qty_per_level, total_profit, total_trades, start_balance FROM grid_state WHERE id=1')
                state_row = cursor.fetchone()
                
                if not state_row:
                    logger.info("[GridEngine] Основное состояние не найдено в БД. Создаем новое состояние.")
                    return None
                    
                self.upper, self.lower, self.qty_per_level, self.total_profit, self.total_trades, self.start_balance = state_row
                
                # Загружаем уровни
                cursor.execute('SELECT price, side, status, order_id, filled_at, pair_order_id FROM grid_levels ORDER BY price DESC')
                level_rows = cursor.fetchall()
                
                if level_rows:
                    self.levels = [
                        GridLevel(
                            price=row[0],
                            side=row[1],
                            status=row[2],
                            order_id=row[3],
                            filled_at=row[4],
                            pair_order_id=row[5]
                        ) for row in level_rows
                    ]
                else:
                    self.levels = []
                
                logger.info("[GridEngine] Состояние успешно загружено из БД.")
                return self
        except Exception as e:
            logger.error(f"[GridEngine] Ошибка загрузки состояния из БД: {e}")
            return None
