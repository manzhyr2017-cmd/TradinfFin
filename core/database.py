import sqlite3
import logging
import json
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime

log = logging.getLogger("Database")

class Database:
    """
    Класс для работы с SQLite БД.
    Обеспечивает сохранение трейдов и состояния бота.
    """
    
    def __init__(self, db_path: str = "trading_bot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE,
                    symbol TEXT,
                    side TEXT,
                    qty TEXT,
                    price TEXT,
                    trade_type TEXT,
                    status TEXT,
                    profit_usdt TEXT,
                    reason TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.commit()

    def save_trade(self, trade_data: Dict[str, Any]):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO trades (order_id, symbol, side, qty, price, trade_type, status, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade_data.get('order_id'),
                    trade_data.get('symbol'),
                    trade_data.get('side'),
                    str(trade_data.get('qty', '0')),
                    str(trade_data.get('price', '0')),
                    trade_data.get('trade_type'),
                    trade_data.get('status', 'NEW'),
                    trade_data.get('reason', 'N/A')
                ))
                conn.commit()
        except Exception as e:
            log.error(f"DB Error (save_trade): {e}")

    def get_order_by_id(self, order_id: str) -> Optional[Dict]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM trades WHERE order_id = ?", (order_id,)).fetchone()
                return dict(row) if row else None
        except Exception as e:
            log.error(f"DB Error (get_order_by_id): {e}")
            return None

    def update_trade_profit(self, order_id: str, profit: Decimal, reason: Optional[str] = None):
        with sqlite3.connect(self.db_path) as conn:
            if reason:
                conn.execute("UPDATE trades SET profit_usdt = ?, status = 'FILLED', reason = ? WHERE order_id = ?", (str(profit), reason, order_id))
            else:
                conn.execute("UPDATE trades SET profit_usdt = ?, status = 'FILLED' WHERE order_id = ?", (str(profit), order_id))
            conn.commit()

    def get_total_profit(self) -> Decimal:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT SUM(CAST(profit_usdt AS REAL)) FROM trades WHERE profit_usdt IS NOT NULL").fetchone()
            return Decimal(str(row[0])) if row[0] else Decimal("0")

    def get_trades_today(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades WHERE DATE(timestamp) = DATE('now')").fetchall()
            return [dict(r) for r in rows]

    def get_all_trades(self) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM trades ORDER BY timestamp ASC").fetchall()
            return [dict(r) for r in rows]

    def get_recent_trades(self, limit: int = 50) -> List[Dict]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)).fetchall()
                return [dict(r) for r in rows]
        except Exception as e:
            log.error(f"DB Error (get_recent_trades): {e}")
            return []

    def get_trade_count(self) -> int:
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute("SELECT COUNT(*) FROM trades WHERE status = 'FILLED'").fetchone()
                return row[0] if row else 0
        except Exception as e:
            log.error(f"DB Error (get_trade_count): {e}")
            return 0

    def save_state(self, key: str, value: Any):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
    def save_trade_reason(self, order_id: str, reason: str):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("UPDATE trades SET reason = ? WHERE order_id = ?", (reason, order_id))
                conn.commit()
        except Exception as e:
            log.error(f"DB Error (save_trade_reason): {e}")

    def load_state(self, key: str, default: Any = None) -> Any:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            return row[0] if row else default

    def clear_active_orders(self):
        """Очистка всех 'NEW' ордеров в БД (например, при смене монеты)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM trades WHERE status = 'NEW'")
                conn.commit()
        except Exception as e:
            log.error(f"DB Error (clear_active_orders): {e}")
