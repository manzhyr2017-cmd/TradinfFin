import sqlite3
import json
import datetime
from typing import Optional, Tuple, List, Dict
from passlib.context import CryptContext
import logging
import os

# Config
from pathlib import Path
# Config - Unified Database in Project Root
DB_PATH = Path(__file__).parent.parent / "trading_bot.db"
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
logger = logging.getLogger("Database")

class DatabaseManager:
    """Универсальный менеджер базы данных для Trading AI"""
    
    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Инициализация всех таблиц системы"""
        with self._get_connection() as conn:
            c = conn.cursor()
            # Пользователи
            c.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    hashed_password TEXT NOT NULL
                )
            ''')
            # Сделки (Trading History)
            c.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    qty REAL DEFAULT 0,
                    exit_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    pnl REAL DEFAULT 0,
                    pnl_percent REAL DEFAULT 0,
                    status TEXT DEFAULT 'OPEN',
                    order_id TEXT,
                    confluence_score INTEGER,
                    risk_reward REAL,
                    regime TEXT,
                    is_win INTEGER,
                    duration_minutes INTEGER,
                    notes TEXT
                )
            ''')
            # Логи системы
            c.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    level TEXT,
                    module TEXT,
                    message TEXT
                )
            ''')
            # Настройки (Key-Value)
            c.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            # Сигналы (Market Scanner Results)
            c.execute('''
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    type TEXT,
                    score INTEGER,
                    ml_prob REAL,
                    indicators TEXT
                )
            ''')
            conn.commit()
        logger.info(f"Database initialized: {self.db_path}")

    # --- Auth ---
    def verify_password(self, plain_password, hashed_password):
        return pwd_context.verify(plain_password, hashed_password)

    def get_password_hash(self, password):
        return pwd_context.hash(password)

    def create_user(self, username, password) -> bool:
        with self._get_connection() as conn:
            c = conn.cursor()
            hashed_pw = self.get_password_hash(password)
            try:
                c.execute("INSERT INTO users (username, hashed_password) VALUES (?, ?)", (username, hashed_pw))
                conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def get_user(self, username) -> Optional[Tuple[int, str, str]]:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT id, username, hashed_password FROM users WHERE username = ?", (username,))
            return c.fetchone()

    # --- Trades ---
    def log_trade(self, symbol, side, price, qty, status="OPEN", pnl=0.0, order_id=None, stop_loss=None, take_profit=None, **kwargs):
        with self._get_connection() as conn:
            c = conn.cursor()
            ts = datetime.datetime.now().isoformat()
            
            # Extract additional fields from kwargs
            confluence = kwargs.get('confluence_score')
            rr = kwargs.get('risk_reward')
            regime = kwargs.get('regime')
            notes = kwargs.get('notes')
            
            c.execute(
                """INSERT INTO trades (timestamp, symbol, side, price, qty, pnl, status, order_id, stop_loss, take_profit, confluence_score, risk_reward, regime, notes) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts, symbol, side, price, qty, pnl, status, order_id, stop_loss, take_profit, confluence, rr, regime, notes)
            )
            conn.commit()

    def get_trades(self, limit: int = 100) -> List[Dict]:
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(row) for row in c.fetchall()]

    def get_trade_stats(self):
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*), SUM(pnl), SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) FROM trades WHERE status != 'OPEN'")
            total, pnl, wins = c.fetchone()
            
        total = total or 0
        pnl = pnl or 0.0
        wins = wins or 0
        losses = total - wins
        win_rate = (wins / total * 100) if total > 0 else 0
        
        return {
            'total': total,
            'pnl': round(pnl, 2),
            'wins': wins,
            'losses': losses,
            'win_rate': round(win_rate, 2)
        }

    # --- Logs ---
    def add_log(self, level, module, message):
        with self._get_connection() as conn:
            c = conn.cursor()
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO logs (timestamp, level, module, message) VALUES (?, ?, ?, ?)",
                (ts, level, module, message)
            )
            conn.commit()

    def get_logs(self, limit: int = 100):
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,))
            return [f"{row['timestamp']} | {row['level']} | {row['module']} | {row['message']}" for row in c.fetchall()]

    # --- Settings ---
    def save_setting(self, key: str, value):
        with self._get_connection() as conn:
            c = conn.cursor()
            json_val = json.dumps(value)
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, json_val))
            conn.commit()

    def get_setting(self, key: str, default=None):
        with self._get_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = c.fetchone()
            if row:
                return json.loads(row['value'])
            return default

# Singleton instance
db = DatabaseManager()

# Legacy functions for compatibility (to be removed after full migration)
def init_db(): db._init_db()
def get_trades(limit=100): return db.get_trades(limit)
def log_trade(**kwargs): db.log_trade(**kwargs)
def verify_password(p, h): return db.verify_password(p, h)
def get_password_hash(p): return db.get_password_hash(p)
def create_user(u, p): return db.create_user(u, p)
def get_user(u): return db.get_user(u)
def get_trade_stats(): return db.get_trade_stats()
