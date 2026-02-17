import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Any
from web_ui.database import DatabaseManager

logger = logging.getLogger(__name__)

class AnalyticsService:
    """Сервис для расчета финансовых показателей и аналитики портфеля"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db

    def get_equity_curve(self, initial_balance: float = 10000.0) -> List[Dict[str, Any]]:
        """Возвращает точки кривой доходности"""
        trades = self.db.get_trades(limit=1000)
        if not trades:
            return [{"timestamp": "Initial", "balance": initial_balance}]
        
        # Сортируем по времени (в БД они могут быть в обратном порядке)
        trades_df = pd.DataFrame(trades, columns=[
            'id', 'timestamp', 'symbol', 'side', 'price', 'qty', 'pnl', 'status', 'order_id', 'stop_loss', 'take_profit'
        ])
        trades_df['timestamp'] = pd.to_datetime(trades_df['timestamp'])
        trades_df = trades_df.sort_values('timestamp')
        
        # Расчет баланса
        trades_df['cumulative_pnl'] = trades_df['pnl'].cumsum()
        trades_df['balance'] = initial_balance + trades_df['cumulative_pnl']
        
        result = [{"timestamp": "Start", "balance": initial_balance}]
        for _, row in trades_df.iterrows():
            result.append({
                "timestamp": row['timestamp'].strftime("%Y-%m-%d %H:%M"),
                "balance": float(row['balance']),
                "pnl": float(row['pnl']),
                "symbol": row['symbol']
            })
            
        return result

    def calculate_metrics(self, initial_balance: float = 10000.0) -> Dict[str, Any]:
        """Рассчитывает ключевые метрики эффективности"""
        trades = self.db.get_trades(limit=5000)
        if not trades:
            return self._empty_metrics()
        
        df = pd.DataFrame(trades, columns=[
            'id', 'timestamp', 'symbol', 'side', 'price', 'qty', 'pnl', 'status', 'order_id', 'stop_loss', 'take_profit'
        ])
        
        # Фильтруем только закрытые сделки (с PnL != 0)
        closed_trades = df[df['pnl'] != 0].copy()
        if closed_trades.empty:
            return self._empty_metrics()
            
        pnls = closed_trades['pnl'].values
        
        # 1. Общий PnL и Win Rate
        total_pnl = float(np.sum(pnls))
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        win_rate = len(wins) / len(pnls) * 100 if len(pnls) > 0 else 0
        
        # 2. Profit Factor
        gross_profit = np.sum(wins) if len(wins) > 0 else 0
        gross_loss = abs(np.sum(losses)) if len(losses) > 0 else 1 # Avoid div by zero
        profit_factor = gross_profit / gross_loss
        
        # 3. Sharpe Ratio (Simplified daily estimation)
        # Если сделок мало, Шарп будет неточным
        avg_ret = np.mean(pnls)
        std_ret = np.std(pnls)
        sharpe = (avg_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0
        
        # 4. Max Drawdown
        closed_trades['timestamp'] = pd.to_datetime(closed_trades['timestamp'])
        closed_trades = closed_trades.sort_values('timestamp')
        equity = initial_balance + closed_trades['pnl'].cumsum()
        peak = equity.cummax()
        drawdown = (equity - peak) / peak
        max_dd = float(drawdown.min() * 100) if not drawdown.empty else 0
        
        # 5. Average Win / Loss
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0
        avg_loss = float(np.mean(losses)) if len(losses) > 0 else 0
        
        # 6. Expectancy
        win_rate_val = len(wins) / len(pnls)
        loss_rate_val = 1 - win_rate_val
        expectancy = (win_rate_val * avg_win) + (loss_rate_val * avg_loss) # Note: avg_loss is negative here
        
        return {
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd, 2),
            "total_trades": len(pnls),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "expectancy": round(expectancy, 2),
            "recovery_factor": round(abs(total_pnl / (initial_balance * max_dd / 100)) if max_dd != 0 else 0, 2)
        }

    def _empty_metrics(self) -> Dict[str, Any]:
        return {
            "total_pnl": 0, "win_rate": 0, "profit_factor": 0,
            "sharpe_ratio": 0, "max_drawdown": 0, "total_trades": 0,
            "avg_win": 0, "avg_loss": 0, "recovery_factor": 0,
            "expectancy": 0
        }

    def export_trades_csv(self, filepath: str):
        """Экспорт сделок в CSV"""
        trades = self.db.get_trades(limit=10000)
        df = pd.DataFrame(trades, columns=[
            'id', 'timestamp', 'symbol', 'side', 'price', 'qty', 'pnl', 'status', 'order_id', 'stop_loss', 'take_profit'
        ])
        df.to_csv(filepath, index=False)
        return filepath
