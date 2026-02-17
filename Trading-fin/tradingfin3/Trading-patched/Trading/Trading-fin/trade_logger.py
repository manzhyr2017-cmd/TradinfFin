"""
Trade Logger - SQLite Database for Trade History
Sniper Mode: Tracks all trades for performance analysis.
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import Optional, Dict, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "trading_bot.db"

class TradeLogger:
    """
    Logs all trades to SQLite for analysis.
    Also enforces daily trade limit (Sniper Mode).
    """
    
    def __init__(self, db_path: str = None, max_trades_per_day: int = 4):
        self.db_path = db_path or str(DB_PATH)
        self.max_trades_per_day = max_trades_per_day
        self._init_db()
        
    def _init_db(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
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
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                trades_count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info(f"📦 Trade Logger initialized: {self.db_path}")
    
    def can_trade_today(self) -> bool:
        """Check if we haven't hit daily trade limit (Sniper Mode)"""
        today = date.today().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT trades_count FROM daily_stats WHERE date = ?", (today,))
        row = cursor.fetchone()
        conn.close()
        
        # count = row[0] if row else 0
        # remaining = self.max_trades_per_day - count
        
        # if remaining <= 0:
        #     logger.warning(f"🎯 Sniper Mode: Daily limit reached ({self.max_trades_per_day} trades). Wait for tomorrow.")
        #     return False
            
        # logger.info(f"🎯 Sniper Mode: {remaining} trades remaining today.")
        return True # Limit disabled by user request
    
    def log_trade_open(
        self,
        symbol: str,
        side: str,
        price: float,
        stop_loss: float,
        take_profit: float,
        confluence_score: int,
        risk_reward: float,
        qty: float = 0.0,
        status: str = "OPEN",
        order_id: str = None,
        regime: str = None
    ) -> int:
        """Log a new trade when opened. Returns trade ID."""
        today = date.today().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insert trade
        cursor.execute("""
            INSERT INTO trades (timestamp, symbol, side, price, qty, stop_loss, take_profit, confluence_score, risk_reward, status, order_id, regime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(),
            symbol,
            side,
            price,
            qty,
            stop_loss,
            take_profit,
            confluence_score,
            risk_reward,
            status,
            order_id,
            regime
        ))
        
        trade_id = cursor.lastrowid
        
        # Update daily stats
        cursor.execute("""
            INSERT INTO daily_stats (date, trades_count) VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET trades_count = trades_count + 1
        """, (today,))
        
        conn.commit()
        conn.close()
        
        logger.info(f"📝 Trade #{trade_id} logged: {side} {symbol} @ {price}")
        return trade_id
    
    def log_trade_close(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
        is_win: bool,
        duration_minutes: int = 0,
        notes: str = None
    ):
        """Update trade with exit info"""
        today = date.today().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get entry price for PnL %
        cursor.execute("SELECT price FROM trades WHERE id = ?", (trade_id,))
        row = cursor.fetchone()
        price = row[0] if row else 1
        
        pnl_percent = (pnl / price) * 100 if price > 0 else 0
        status = "WIN" if is_win else "LOSS"
        
        cursor.execute("""
            UPDATE trades 
            SET exit_price = ?, pnl = ?, pnl_percent = ?, is_win = ?, duration_minutes = ?, notes = ?, status = ?
            WHERE id = ?
        """, (exit_price, pnl, pnl_percent, 1 if is_win else 0, duration_minutes, notes, status, trade_id))
        
        # Update daily stats
        if is_win:
            cursor.execute("UPDATE daily_stats SET wins = wins + 1, total_pnl = total_pnl + ? WHERE date = ?", (pnl, today))
        else:
            cursor.execute("UPDATE daily_stats SET losses = losses + 1, total_pnl = total_pnl + ? WHERE date = ?", (pnl, today))
        
        conn.commit()
        conn.close()
        
        emoji = "✅" if is_win else "❌"
        logger.info(f"{emoji} Trade #{trade_id} closed: PnL ${pnl:.2f} ({pnl_percent:.2f}%)")

    def sync_external_trade(self, trade_data: dict):
        """
        Sync trade from Bybit ClosedPnL.
        trade_data: {'symbol', 'side', 'entry_price', 'exit_price', 'pnl', 'exit_time', 'qty'}
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Try to find existing OPEN trade (FIFO)
        cursor.execute("SELECT id FROM trades WHERE symbol = ? AND side = ? AND exit_price IS NULL ORDER BY id ASC LIMIT 1", 
                       (trade_data['symbol'], trade_data['side']))
        row = cursor.fetchone()
        
        is_win = trade_data['pnl'] > 0
        status = "WIN" if is_win else "LOSS"
        
        # Format timestamp from ms
        ts = datetime.fromtimestamp(int(trade_data['exit_time'])/1000).isoformat()

        if row:
            trade_id = row[0]
            cursor.execute("""
                UPDATE trades
                SET exit_price = ?, pnl = ?, is_win = ?, status = ?, notes = 'Synced Update', order_id = ?
                WHERE id = ?
            """, (trade_data['exit_price'], trade_data['pnl'], 1 if is_win else 0, status, trade_data.get('order_id'), trade_id))
            logger.info(f"🔄 Synced (Closed) trade #{trade_id} from Bybit PnL")
        else:
            # 2. Check if ALREADY imported (avoid duplicates by Order ID OR strict match)
            # Match by order_id is most reliable
            order_id = trade_data.get('order_id')
            exists = False
            
            if order_id:
                cursor.execute("SELECT id FROM trades WHERE order_id = ?", (order_id,))
                if cursor.fetchone():
                    exists = True
            
            # Fallback to loose match if no order_id (legacy)
            if not exists:
                cursor.execute("SELECT id FROM trades WHERE symbol = ? AND timestamp = ? AND pnl = ?",
                               (trade_data['symbol'], ts, trade_data['pnl']))
                if cursor.fetchone():
                    exists = True
            
            if not exists:
                 cursor.execute("""
                    INSERT INTO trades (timestamp, symbol, side, price, exit_price, pnl, qty, is_win, status, notes, order_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                 """, (ts, trade_data['symbol'], trade_data['side'], 
                       trade_data['entry_price'], trade_data['exit_price'], trade_data['pnl'], 
                       trade_data.get('qty', 0), 1 if is_win else 0, status, "Synced from Bybit", order_id))
                 logger.info(f"📥 Imported external trade {trade_data['symbol']} (PnL: {trade_data['pnl']})")
        
        conn.commit()
        conn.close()

    def get_stats(self, days: int = 7) -> Dict[str, Any]:
        """Get trading stats for last N days"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN is_win = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN is_win = 0 THEN 1 ELSE 0 END) as losses,
                SUM(pnl) as total_pnl,
                AVG(pnl) as avg_pnl,
                AVG(risk_reward) as avg_rr
            FROM trades 
            WHERE timestamp >= date('now', '-' || ? || ' days')
        """, (days,))
        
        row = cursor.fetchone()
        conn.close()
        
        total = row[0] or 0
        wins = row[1] or 0
        losses = row[2] or 0
        
        return {
            'total_trades': total,
            'wins': wins,
            'losses': losses,
            'win_rate': (wins / total * 100) if total > 0 else 0,
            'total_pnl': row[3] or 0,
            'avg_pnl': row[4] or 0,
            'avg_rr': row[5] or 0
        }
    
    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Get most recent trades"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]


# Singleton instance
_logger_instance = None

def get_trade_logger() -> TradeLogger:
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = TradeLogger(max_trades_per_day=4)
    return _logger_instance
