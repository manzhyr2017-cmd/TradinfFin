"""
TITAN BOT 2026 - Database Manager
Хранение сделок для аналитики и обучения (SQLite).
"""

import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path

class TitanDatabase:
    def __init__(self, db_path="data/titan_main.db"):
        self.db_path = db_path
        # Создаем папку если нет
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Инициализация таблиц базы данных"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Таблица сделок (Trade Journal)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    symbol TEXT,
                    side TEXT,
                    entry_time DATETIME,
                    entry_price REAL,
                    qty REAL,
                    sl REAL,
                    tp REAL,
                    status TEXT DEFAULT 'OPEN', -- OPEN, CLOSED
                    exit_time DATETIME,
                    exit_price REAL,
                    pnl REAL,
                    pnl_percent REAL,
                    score_total REAL,
                    score_details TEXT, -- JSON c компонентами (M, S, O)
                    features TEXT -- JSON с вектором признаков для обучения
                )
            ''')
            
            # Таблица логов системы (для аудита)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME,
                    level TEXT,
                    module TEXT,
                    message TEXT
                )
            ''')
            
            conn.commit()

    def record_trade_entry(self, trade_id, symbol, side, price, qty, sl, tp, score, details, features=None):
        """Запись входа в сделку"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO trades (id, symbol, side, entry_time, entry_price, qty, sl, tp, status, score_total, score_details, features)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    trade_id, symbol, side, datetime.now().isoformat(), price, qty, sl, tp, 'OPEN',
                    score, json.dumps(details), json.dumps(features) if features else None
                ))
                conn.commit()
        except Exception as e:
            print(f"[Database] Error recording entry: {e}")

    def record_trade_exit(self, trade_id, exit_price, pnl, exit_time=None):
        """Запись выхода из сделки"""
        try:
            if exit_time is None:
                exit_time = datetime.now()
                
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Сначала получаем цену входа и объем, чтобы посчитать %
                cursor.execute("SELECT entry_price, qty FROM trades WHERE id = ?", (trade_id,))
                row = cursor.fetchone()
                if not row: return
                
                entry_price, qty = row
                pnl_percent = (pnl / (entry_price * qty)) * 100 if entry_price and qty else 0

                cursor.execute('''
                    UPDATE trades 
                    SET status = 'CLOSED', exit_time = ?, exit_price = ?, pnl = ?, pnl_percent = ?
                    WHERE id = ?
                ''', (exit_time.isoformat(), exit_price, pnl, pnl_percent, trade_id))
                conn.commit()
        except Exception as e:
            print(f"[Database] Error recording exit: {e}")

    def get_open_trades(self):
        """Возвращает список ID открытых сделок"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, symbol, side, entry_price, qty FROM trades WHERE status = 'OPEN'")
                return cursor.fetchall()
        except:
            return []

    def log_event(self, module, message, level="INFO"):
        """Системный лог в БД"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO logs (timestamp, level, module, message) VALUES (?, ?, ?, ?)",
                               (datetime.now().isoformat(), level, module, message))
                conn.commit()
        except:
            pass
