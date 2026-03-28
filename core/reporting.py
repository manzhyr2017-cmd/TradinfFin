import pandas as pd
from decimal import Decimal
from datetime import datetime, timedelta
import logging

log = logging.getLogger("Reporting")

class ReportingService:
    """
    Профессиональный сервис отчётов а-ля Freqtrade.
    Генерирует сводные таблицы PnL, Drawdown и статистику сделок.
    """
    
    def __init__(self, db):
        self.db = db

    def generate_daily_summary(self):
        """Генерирует таблицу профита по дням."""
        trades = self.db.get_all_trades()
        if not trades:
            return "📭 Нет сделок для отчета."

        df = pd.DataFrame(trades)
        if 'timestamp' not in df.columns: return "❌ Ошибка данных."
        
        df['dt'] = pd.to_datetime(df['timestamp'])
        df['profit'] = df['profit_usdt'].fillna(0).astype(float)
        
        # Группировка по дням
        daily = df.groupby(df['dt'].dt.date)['profit'].agg(['sum', 'count']).reset_index()
        daily.columns = ['Date', 'PnL (USDT)', 'Trades']
        
        # Формируем красивую строку
        report = "\n📊 --- DAILY PERFORMANCE --- 📊\n"
        report += daily.to_string(index=False)
        report += f"\n💰 Total PnL: {self.db.get_total_profit():.2f} USDT"
        return report

    def generate_performance_stats(self):
        """Freqtrade-style performance metrics with Sharpe and Sortino."""
        trades = self.db.get_all_trades()
        if not trades: return "📭 Статистика пуста."
        
        df = pd.DataFrame(trades)
        df['profit'] = df['profit_usdt'].fillna(0).astype(float)
        
        # Убираем нулевые прибыли (открытые ордера)
        filled_trades = df[df['profit'] != 0].copy()
        if filled_trades.empty: return "📭 Нет закрытых сделок."

        wins = filled_trades[filled_trades['profit'] > 0]
        losses = filled_trades[filled_trades['profit'] < 0]
        
        win_rate = (len(wins) / len(filled_trades) * 100) if len(filled_trades) > 0 else 0
        avg_win = wins['profit'].mean() if len(wins) > 0 else 0
        avg_loss = losses['profit'].mean() if len(losses) > 0 else 0
        
        # Sharpe & Sortino (упрощенно по доходности сделок)
        sharpe = 0
        sortino = 0
        if not filled_trades.empty:
            roi_series = filled_trades['profit']
            std = roi_series.std()
            if std > 0:
                sharpe = (roi_series.mean() / std) * (len(filled_trades)**0.5)
            
            neg_std = roi_series[roi_series < 0].std()
            if neg_std > 0:
                sortino = (roi_series.mean() / neg_std) * (len(filled_trades)**0.5)

        # Max Drawdown
        filled_trades['cum_profit'] = filled_trades['profit'].cumsum()
        filled_trades['peak'] = filled_trades['cum_profit'].cummax()
        filled_trades['drawdown'] = filled_trades['peak'] - filled_trades['cum_profit']
        max_dd = filled_trades['drawdown'].max()
        
        stats = [
            f"📈 Win Rate: {win_rate:.1f}%",
            f"✅ Wins: {len(wins)} | ❌ Losses: {len(losses)}",
            f"🟢 Average Win: {avg_win:.2f} USDT",
            f"🔴 Average Loss: {avg_loss:.2f} USDT",
            f"⚖️ Profit Factor: {abs(wins['profit'].sum() / losses['profit'].sum()):.2f}" if losses['profit'].sum() != 0 else "∞",
            f"🎯 Sharpe Ratio: {sharpe:.2f}",
            f"🛡️ Sortino Ratio: {sortino:.2f}",
            f"📉 Max Drawdown: {max_dd:.2f} USDT"
        ]
        
        report = "\n🏆 --- PERFORMANCE STATS --- 🏆\n"
        report += "\n".join(stats)
        return report

    def log_full_report(self):
        """Записывает полный отчет в логи и консоль."""
        log.info(self.generate_daily_summary())
        log.info(self.generate_performance_stats())
