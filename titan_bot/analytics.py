"""
TITAN BOT 2026 - Analytics & Trade Journal
Аналитика для понимания что работает, а что нет
"""

import pandas as pd
import json
import os
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Optional
import config

@dataclass
class TradeRecord:
    """Запись о сделке"""
    id: str
    timestamp: datetime
    symbol: str
    side: str
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percent: float
    r_multiple: float  # Сколько R заработали/потеряли
    signal_type: str   # SFP_LONG, ORDER_BLOCK и т.д.
    session: str       # Торговая сессия
    holding_time: int  # Минут в сделке
    notes: str = ""


class TradingAnalytics:
    """
    Аналитика торговли.
    
    Это КРИТИЧЕСКИ важно для 20% в месяц:
    - Видишь, какие паттерны работают
    - Видишь, в какое время лучше торговать
    - Видишь свои ошибки
    
    Без журнала ты слепой.
    """
    
    def __init__(self, journal_path: str = "trade_journal.json"):
        self.journal_path = journal_path
        self.trades: List[TradeRecord] = []
        self._load_journal()
    
    def record_trade(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        initial_risk: float,
        signal_type: str,
        session: str,
        entry_time: datetime,
        exit_time: datetime,
        notes: str = ""
    ):
        """Записывает сделку в журнал."""
        
        # Расчёт P&L
        if side == 'LONG':
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity
        
        pnl_percent = (pnl / (entry_price * quantity)) * 100
        
        # R-Multiple (сколько рисков заработали)
        r_multiple = pnl / initial_risk if initial_risk > 0 else 0
        
        # Время в сделке
        holding_time = int((exit_time - entry_time).total_seconds() / 60)
        
        trade = TradeRecord(
            id=f"{symbol}_{entry_time.strftime('%Y%m%d_%H%M%S')}",
            timestamp=exit_time,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            pnl=pnl,
            pnl_percent=pnl_percent,
            r_multiple=r_multiple,
            signal_type=signal_type,
            session=session,
            holding_time=holding_time,
            notes=notes
        )
        
        self.trades.append(trade)
        self._save_journal()
        
        print(f"\n[Analytics] 📊 Сделка записана:")
        print(f"  P&L: ${pnl:.2f} ({pnl_percent:+.2f}%)")
        print(f"  R-Multiple: {r_multiple:+.2f}R")
    
    def get_statistics(self, days: int = 30) -> dict:
        """
        Возвращает статистику за период.
        
        Ключевые метрики для 20% в месяц:
        - Win Rate должен быть > 40% при RR 1:2
        - Средний R должен быть положительным
        - Expectancy (ожидание) должно быть > 0
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_trades = [t for t in self.trades if t.timestamp > cutoff]
        
        if not recent_trades:
            return {'error': 'Нет сделок за период'}
        
        total = len(recent_trades)
        winners = [t for t in recent_trades if t.pnl > 0]
        losers = [t for t in recent_trades if t.pnl < 0]
        
        win_rate = len(winners) / total if total > 0 else 0
        
        avg_win = sum(t.pnl for t in winners) / len(winners) if winners else 0
        avg_loss = abs(sum(t.pnl for t in losers) / len(losers)) if losers else 0
        
        # Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)
        
        # Profit Factor = Gross Profit / Gross Loss
        gross_profit = sum(t.pnl for t in winners)
        gross_loss = abs(sum(t.pnl for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Средний R
        avg_r = sum(t.r_multiple for t in recent_trades) / total
        
        # Статистика по типам сигналов
        signal_stats = {}
        for signal_type in set(t.signal_type for t in recent_trades):
            signal_trades = [t for t in recent_trades if t.signal_type == signal_type]
            signal_winners = [t for t in signal_trades if t.pnl > 0]
            signal_stats[signal_type] = {
                'total': len(signal_trades),
                'win_rate': len(signal_winners) / len(signal_trades) if signal_trades else 0,
                'avg_r': sum(t.r_multiple for t in signal_trades) / len(signal_trades)
            }
        
        # Статистика по сессиям
        session_stats = {}
        for session in set(t.session for t in recent_trades):
            session_trades = [t for t in recent_trades if t.session == session]
            session_winners = [t for t in session_trades if t.pnl > 0]
            session_stats[session] = {
                'total': len(session_trades),
                'win_rate': len(session_winners) / len(session_trades) if session_trades else 0,
                'total_pnl': sum(t.pnl for t in session_trades)
            }
        
        return {
            'period_days': days,
            'total_trades': total,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'expectancy': expectancy,
            'avg_r_multiple': avg_r,
            'total_pnl': sum(t.pnl for t in recent_trades),
            'best_trade': max(t.pnl for t in recent_trades),
            'worst_trade': min(t.pnl for t in recent_trades),
            'avg_holding_time_min': sum(t.holding_time for t in recent_trades) / total,
            'signal_breakdown': signal_stats,
            'session_breakdown': session_stats
        }
    
    def print_report(self, days: int = 30):
        """Выводит красивый отчёт."""
        stats = self.get_statistics(days)
        
        if 'error' in stats:
            print(f"[Analytics] {stats['error']}")
            return
        
        report = f"""
╔══════════════════════════════════════════════════════════╗
║              TRADING REPORT - Last {days} days                ║
╠══════════════════════════════════════════════════════════╣
║  Total Trades:     {stats['total_trades']:<10}                          ║
║  Win Rate:         {stats['win_rate']*100:.1f}%                               ║
║  Profit Factor:    {stats['profit_factor']:.2f}                               ║
║  Expectancy:       ${stats['expectancy']:.2f}                             ║
║  Avg R-Multiple:   {stats['avg_r_multiple']:+.2f}R                             ║
╠══════════════════════════════════════════════════════════╣
║  Total P&L:        ${stats['total_pnl']:<10.2f}                       ║
║  Best Trade:       ${stats['best_trade']:<10.2f}                       ║
║  Worst Trade:      ${stats['worst_trade']:<10.2f}                       ║
║  Avg Hold Time:    {stats['avg_holding_time_min']:.0f} min                            ║
╠══════════════════════════════════════════════════════════╣
║  SIGNAL BREAKDOWN:                                        ║"""
        
        for signal, data in stats['signal_breakdown'].items():
            report += f"\n║    {signal}: {data['total']} trades, {data['win_rate']*100:.0f}% WR, {data['avg_r']:+.2f}R    ║"
        
        report += """
╠══════════════════════════════════════════════════════════╣
║  SESSION BREAKDOWN:                                       ║"""
        
        for session, data in stats['session_breakdown'].items():
            report += f"\n║    {session}: {data['total']} trades, {data['win_rate']*100:.0f}% WR, ${data['total_pnl']:.2f}    ║"
        
        report += """
╚══════════════════════════════════════════════════════════╝"""
        
        print(report)
        
        # Рекомендации
        self._print_recommendations(stats)
    
    def _print_recommendations(self, stats: dict):
        """Выводит рекомендации на основе статистики."""
        print("\n📋 РЕКОМЕНДАЦИИ:")
        
        # Win Rate
        if stats['win_rate'] < 0.4:
            print("  ⚠️ Win Rate низкий (<40%). Проверь качество сигналов.")
        
        # Profit Factor
        if stats['profit_factor'] < 1.5:
            print("  ⚠️ Profit Factor низкий (<1.5). Улучши соотношение риск/прибыль.")
        
        # Лучшие сигналы
        best_signal = max(stats['signal_breakdown'].items(), 
                         key=lambda x: x[1]['avg_r'], default=None)
        if best_signal:
            print(f"  ✅ Лучший сигнал: {best_signal[0]} ({best_signal[1]['avg_r']:+.2f}R)")
        
        # Лучшая сессия
        best_session = max(stats['session_breakdown'].items(),
                          key=lambda x: x[1]['total_pnl'], default=None)
        if best_session:
            print(f"  ✅ Лучшая сессия: {best_session[0]} (${best_session[1]['total_pnl']:.2f})")
    
    def _save_journal(self):
        """Сохраняет журнал на диск."""
        data = []
        for trade in self.trades:
            d = asdict(trade)
            d['timestamp'] = trade.timestamp.isoformat()
            data.append(d)
        
        with open(self.journal_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _load_journal(self):
        """Загружает журнал с диска."""
        if not os.path.exists(self.journal_path):
            return
        
        try:
            with open(self.journal_path, 'r') as f:
                data = json.load(f)
            
            for d in data:
                d['timestamp'] = datetime.fromisoformat(d['timestamp'])
                self.trades.append(TradeRecord(**d))
                
            print(f"[Analytics] Загружено {len(self.trades)} сделок из журнала")
        except Exception as e:
            print(f"[Analytics] Ошибка загрузки журнала: {e}")
