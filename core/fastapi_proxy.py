from fastapi import FastAPI, HTTPException
import logging
import threading
import uvicorn
from datetime import datetime, timedelta
from typing import Dict, List, Any
from decimal import Decimal

import config
from core.database import Database

log = logging.getLogger("DashboardAPI")

class DashboardAPI:
    """
    FastAPI прослойка для визуализации состояния бота.
    Эмулирует некоторые эндпоинты Freqtrade для совместимости.
    """
    def __init__(self, brain):
        self.brain = brain
        self.app = FastAPI(title="TitanBot Frankenstein Dashboard")
        self.db = Database()
        self._setup_routes()
        
    def _setup_routes(self):
        @self.app.get("/status")
        async def get_status():
            """Основной статус бота."""
            return {
                "status": "running",
                "symbol": self.brain.current_symbol,
                "balance": float(self.brain.client.get_balance()),
                "pnl_24h": float(self.db.get_total_profit()), # Упрощенно
                "active_orders": len(self.brain.active_orders),
                "uptime": str(datetime.now() - self.brain._start_time).split('.')[0] if hasattr(self.brain, '_start_time') else "N/A"
            }

        @self.app.get("/trades")
        async def get_trades(limit: int = 50):
            """Список последних сделок."""
            trades = self.db.get_recent_trades(limit=limit)
            return trades

        @self.app.get("/performance")
        async def get_performance():
            """Метрики производительности."""
            return {
                "total_trades": self.db.get_trade_count(),
                "win_rate": self._calculate_win_rate(),
                "profit_all_time": float(self.db.get_total_profit()),
                "max_drawdown": float(getattr(config, 'MAX_DRAWDOWN_USDT', 0))
            }

        @self.app.get("/health")
        async def health_check():
            return {"status": "ok", "timestamp": datetime.now().isoformat()}

    def _calculate_win_rate(self) -> float:
        try:
            trades = self.db.get_recent_trades(limit=100)
            if not trades: return 0.0
            wins = sum(1 for t in trades if float(t.get('pnl', 0)) > 0)
            return (wins / len(trades)) * 100
        except:
            return 0.0

    def start(self, host: str = "0.0.0.0", port: int = 8080):
        """Запуск сервера в отдельном потоке."""
        def run():
            uvicorn.run(self.app, host=host, port=port, log_level="error")
            
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        log.info(f"🚀 Dashboard API started at http://{host}:{port}")
