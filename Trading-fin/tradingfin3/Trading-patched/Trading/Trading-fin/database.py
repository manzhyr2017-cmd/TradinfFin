import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional
import os

logger = logging.getLogger(__name__)

DB_FILE = "trades.db"

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Таблица сделок
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        entry_price REAL NOT NULL,
        qty REAL NOT NULL,
        stop_loss REAL,
        take_profit REAL,
        status TEXT NOT NULL, -- OPEN, CLOSED, ERROR
        pnl REAL DEFAULT 0,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        order_id TEXT
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("Database initialized")

def log_trade(symbol: str, side: str, entry_price: float, qty: float, 
              stop_loss: float, take_profit: float, order_id: str, status: str = "OPEN"):
    """Логирование новой сделки"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO trades (symbol, side, entry_price, qty, stop_loss, take_profit, order_id, status, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, side, entry_price, qty, stop_loss, take_profit, order_id, status, datetime.now()))
        
        conn.commit()
        conn.close()
        logger.info(f"Trade logged: {symbol} {side}")
    except Exception as e:
        logger.error(f"Failed to log trade: {e}")

def update_trade_status(order_id: str, status: str, pnl: float = 0):
    """Обновление статуса сделки (например, при закрытии)"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
        UPDATE trades SET status = ?, pnl = ? WHERE order_id = ?
        ''', (status, pnl, order_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to update trade: {e}")

def get_trades(limit: int = 50) -> List[Dict]:
    """Получение истории сделок"""
    try:
        conn = sqlite3.connect(DB_FILE)
        # Позволяет обращаться к полям по имени
        conn.row_factory = sqlite3.Row 
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        
        trades = []
        for row in rows:
            trades.append(dict(row))
            
        conn.close()
        return trades
    except Exception as e:
        logger.error(f"Failed to fetch trades: {e}")
        return []

# Инициализируем при импорте, если файла нет
if not os.path.exists(DB_FILE):
    init_db()
