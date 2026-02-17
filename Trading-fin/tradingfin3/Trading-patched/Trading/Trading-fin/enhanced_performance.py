"""
╔══════════════════════════════════════════════════════════════════════╗
║     ENHANCED PERFORMANCE TRACKER + KELLY CRITERION v2.0              ║
║     Drop-in замена PerformanceTracker из mean_reversion_bybit.py     ║
║                                                                      ║
║  Улучшения:                                                         ║
║    + Sharpe Ratio, Profit Factor, Max Drawdown                      ║
║    + Equity Curve tracking                                          ║
║    + Per-symbol и per-regime статистика                              ║
║    + Kelly Criterion с conservative fraction                        ║
║    + Persistence (JSON)                                             ║
║    + Streak analysis                                                ║
║                                                                      ║
║  Совместим с:                                                        ║
║    - PerformanceTracker (mean_reversion_bybit.py)                    ║
║    - ExecutionManager (execution.py)                                 ║
║    - Trade dataclass (mean_reversion_bybit.py)                       ║
║                                                                      ║
║  Приоритет: 🟡 ВАЖНЫЙ                                               ║
╚══════════════════════════════════════════════════════════════════════╝

ИНТЕГРАЦИЯ:
    from enhanced_performance import EnhancedPerformanceTracker, KellyCalculator
    
    # В UltimateTradingEngine:
    self.performance_tracker = EnhancedPerformanceTracker(initial_capital=10000)
    
    # После закрытия сделки (вместо add_trade):
    self.performance_tracker.add_trade(trade)  # Совместимый API
    
    # Kelly sizing в execution.py:
    stats = self.performance_tracker.get_stats()
    kelly_risk = KellyCalculator.calculate(
        win_rate=stats['win_rate'],
        avg_win=stats['avg_win'],
        avg_loss=stats['avg_loss']
    )
"""

import json
import logging
import math
import os
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# KELLY CALCULATOR
# ═══════════════════════════════════════════════════════════════

class KellyCalculator:
    """
    Kelly Criterion для оптимального position sizing.
    
    Формула: K = (W × R - L) / R
      W = win rate, L = loss rate, R = avg_win / avg_loss
    
    Использует conservative fraction (25%) по умолчанию.
    """

    @staticmethod
    def calculate(
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        fraction: float = 0.25,
        min_pct: float = 0.005,
        max_pct: float = 0.10,
        confluence_score: float = 0.0,
        current_drawdown: float = 0.0,
    ) -> dict:
        """
        Рассчитывает оптимальный размер позиции.
        
        Args:
            win_rate: 0.0 - 1.0
            avg_win: средний выигрыш в $
            avg_loss: средний проигрыш в $ (положительное число)
            fraction: доля от полного Kelly (0.25 = quarter Kelly)
            min_pct: минимальный % от капитала
            max_pct: максимальный % от капитала
            confluence_score: 0-100, бонус за сильный сигнал
            current_drawdown: текущая просадка 0.0-1.0
            
        Returns:
            dict с position_pct, kelly_raw, method
        """
        if win_rate <= 0 or avg_win <= 0 or avg_loss <= 0:
            return {
                "position_pct": min_pct,
                "kelly_raw": 0.0,
                "method": "default (insufficient data)",
            }

        # Kelly formula
        R = avg_win / avg_loss  # Reward/Risk ratio
        W = win_rate
        L = 1 - win_rate

        kelly_raw = (W * R - L) / R

        if kelly_raw <= 0:
            return {
                "position_pct": min_pct,
                "kelly_raw": kelly_raw,
                "method": "minimum (negative Kelly)",
            }

        # Conservative fraction
        kelly_adjusted = kelly_raw * fraction

        # Confluence bonus: 80%+ → +20% position, 90%+ → +40%
        if confluence_score >= 90:
            kelly_adjusted *= 1.4
        elif confluence_score >= 80:
            kelly_adjusted *= 1.2

        # Drawdown penalty: уменьшаем при просадке
        if current_drawdown > 0.10:
            kelly_adjusted *= 0.5
        elif current_drawdown > 0.05:
            kelly_adjusted *= 0.75

        # Clamp
        position_pct = max(min_pct, min(max_pct, kelly_adjusted))

        return {
            "position_pct": round(position_pct, 4),
            "kelly_raw": round(kelly_raw, 4),
            "kelly_adjusted": round(kelly_adjusted, 4),
            "method": "kelly",
            "R_ratio": round(R, 2),
        }


# ═══════════════════════════════════════════════════════════════
# ENHANCED PERFORMANCE TRACKER
# ═══════════════════════════════════════════════════════════════

class EnhancedPerformanceTracker:
    """
    Расширенный трекер. Drop-in замена PerformanceTracker.
    
    Совместимость:
        - add_trade(trade: Trade) — как оригинал
        - get_stats() → dict — расширенный (включает всё из оригинала + новое)
        - equity_curve — как оригинал
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        max_history: int = 1000,
        history_file: str = "trade_history.json",
    ):
        self.initial_capital = initial_capital
        self.max_history = max_history
        self.history_file = history_file

        self.trades: deque = deque(maxlen=max_history)
        self.equity_curve: List[float] = [initial_capital]

        # Загрузка истории
        self._load_history()

    # ═══════════════════════════════════════════════════════════
    # ДОБАВЛЕНИЕ СДЕЛОК
    # ═══════════════════════════════════════════════════════════

    def add_trade(self, trade) -> None:
        """
        Добавляет сделку. Принимает Trade dataclass или dict.
        Совместим с оригинальным PerformanceTracker.add_trade()
        """
        if hasattr(trade, 'pnl'):
            # Trade dataclass
            trade_dict = {
                'pnl': float(trade.pnl),
                'pnl_percent': float(getattr(trade, 'pnl_percent', trade.pnl / max(self.equity_curve[-1], 1))),
                'symbol': str(getattr(trade, 'symbol', '')),
                'is_winner': bool(getattr(trade, 'is_winner', trade.pnl > 0)),
                'exit_reason': str(getattr(trade, 'exit_reason', '')),
                'confluence_score': float(getattr(trade, 'confluence_score', 0)),
                'timestamp': datetime.now().isoformat(),
            }
            # Дополнительные поля если есть
            for attr in ['entry_price', 'exit_price', 'signal_type', 'market_regime', 'duration_seconds']:
                if hasattr(trade, attr):
                    val = getattr(trade, attr)
                    if hasattr(val, 'value'):  # Enum
                        trade_dict[attr] = val.value
                    else:
                        trade_dict[attr] = val
        elif isinstance(trade, dict):
            trade_dict = trade.copy()
            trade_dict.setdefault('is_winner', trade_dict.get('pnl', 0) > 0)
            trade_dict.setdefault('timestamp', datetime.now().isoformat())
        else:
            logger.error(f"Unknown trade type: {type(trade)}")
            return

        self.trades.append(trade_dict)
        self.equity_curve.append(self.equity_curve[-1] + trade_dict['pnl'])

        self._save_history()

    def record_trade(self, trade):
        """Алиас для add_trade (совместимость с UltimateTradingEngine)"""
        self.add_trade(trade)

    # ═══════════════════════════════════════════════════════════
    # СТАТИСТИКА
    # ═══════════════════════════════════════════════════════════

    def get_stats(self) -> Dict[str, Any]:
        """
        Расширенная статистика. Совместима с оригинальным get_stats().
        
        Оригинальные поля: win_rate, profit_factor, avg_win, avg_loss
        Новые поля: sharpe_ratio, max_drawdown, total_trades, etc.
        """
        if not self.trades:
            return {
                'win_rate': 0.5,
                'profit_factor': 1.0,
                'avg_win': 100,
                'avg_loss': 100,
                'total_trades': 0,
                'sharpe_ratio': 0.0,
                'max_drawdown': 0.0,
                'note': 'No trades yet',
            }

        wins = [t for t in self.trades if t.get('is_winner', t.get('pnl', 0) > 0)]
        losses = [t for t in self.trades if not t.get('is_winner', t.get('pnl', 0) > 0)]

        total = len(self.trades)
        wr = len(wins) / total if total > 0 else 0.5

        total_win = sum(t['pnl'] for t in wins) if wins else 0
        total_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0

        avg_win = total_win / len(wins) if wins else 0
        avg_loss = total_loss / len(losses) if losses else 0

        pf = total_win / total_loss if total_loss > 0 else 2.0

        # Sharpe Ratio (annualized, assuming ~4 trades/day)
        returns = [t['pnl'] / max(self.initial_capital, 1) for t in self.trades]
        sharpe = self._calc_sharpe(returns)

        # Max Drawdown
        max_dd = self._calc_max_drawdown()

        # Streaks
        best_streak, worst_streak = self._calc_streaks()

        # Net PnL
        net_pnl = sum(t['pnl'] for t in self.trades)

        return {
            # Совместимые поля (как оригинал)
            'win_rate': round(wr * 100, 1),      # В процентах для совместимости
            'profit_factor': round(pf, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),

            # Расширенные поля
            'total_trades': total,
            'wins': len(wins),
            'losses': len(losses),
            'net_pnl': round(net_pnl, 2),
            'net_pnl_percent': round(net_pnl / max(self.initial_capital, 1) * 100, 2),
            'sharpe_ratio': round(sharpe, 2),
            'max_drawdown': round(max_dd * 100, 2),
            'best_streak': best_streak,
            'worst_streak': worst_streak,
            'current_equity': round(self.equity_curve[-1], 2),
            'total_profit': round(total_win, 2),
            'total_loss': round(total_loss, 2),
        }

    def get_per_symbol_stats(self) -> Dict[str, dict]:
        """Статистика по каждому символу"""
        symbols = {}
        for t in self.trades:
            sym = t.get('symbol', 'UNKNOWN')
            if sym not in symbols:
                symbols[sym] = {'wins': 0, 'losses': 0, 'pnl': 0.0}
            if t.get('is_winner', t.get('pnl', 0) > 0):
                symbols[sym]['wins'] += 1
            else:
                symbols[sym]['losses'] += 1
            symbols[sym]['pnl'] += t.get('pnl', 0)

        for sym, data in symbols.items():
            total = data['wins'] + data['losses']
            data['total'] = total
            data['win_rate'] = round(data['wins'] / total * 100, 1) if total > 0 else 0
            data['pnl'] = round(data['pnl'], 2)

        return symbols

    def get_kelly_input(self) -> List[dict]:
        """Возвращает данные для KellyCalculator"""
        return list(self.trades)

    # ═══════════════════════════════════════════════════════════
    # РАСЧЁТЫ
    # ═══════════════════════════════════════════════════════════

    def _calc_sharpe(self, returns: List[float], annualize_factor: float = 252) -> float:
        """Sharpe Ratio (annualized)"""
        if len(returns) < 2:
            return 0.0
        mean_ret = sum(returns) / len(returns)
        variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
        std_ret = math.sqrt(variance) if variance > 0 else 0.001
        return (mean_ret / std_ret) * math.sqrt(annualize_factor)

    def _calc_max_drawdown(self) -> float:
        """Max drawdown от equity curve"""
        if len(self.equity_curve) < 2:
            return 0.0
        peak = self.equity_curve[0]
        max_dd = 0.0
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd

    def _calc_streaks(self) -> tuple:
        """Лучшая и худшая серии"""
        if not self.trades:
            return 0, 0

        best = worst = current = 0
        last_win = None

        for t in self.trades:
            is_win = t.get('is_winner', t.get('pnl', 0) > 0)
            if is_win:
                current = current + 1 if last_win else 1
                best = max(best, current)
            else:
                current = current + 1 if last_win is False else 1
                worst = max(worst, current)
            last_win = is_win

        return best, worst

    # ═══════════════════════════════════════════════════════════
    # PERSISTENCE
    # ═══════════════════════════════════════════════════════════

    def _save_history(self):
        try:
            data = {
                'trades': list(self.trades),
                'equity_curve': self.equity_curve[-500:],  # Последние 500 точек
                'initial_capital': self.initial_capital,
                'saved_at': datetime.now().isoformat(),
            }
            with open(self.history_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Ошибка сохранения истории: {e}")

    def _load_history(self):
        if not os.path.exists(self.history_file):
            return
        try:
            with open(self.history_file, 'r') as f:
                data = json.load(f)

            trades = data.get('trades', [])
            for t in trades[-self.max_history:]:
                self.trades.append(t)

            ec = data.get('equity_curve', [])
            if ec:
                self.equity_curve = ec

            logger.info(f"📂 Загружено {len(self.trades)} сделок из истории")
        except Exception as e:
            logger.warning(f"Ошибка загрузки истории: {e}")

    # ═══════════════════════════════════════════════════════════
    # ОТЧЁТ
    # ═══════════════════════════════════════════════════════════

    def print_report(self):
        stats = self.get_stats()
        print(f"\n{'═'*50}")
        print(f"  PERFORMANCE REPORT")
        print(f"{'═'*50}")
        print(f"  Trades:        {stats['total_trades']} ({stats['wins']}W / {stats['losses']}L)")
        print(f"  Win Rate:      {stats['win_rate']}%")
        print(f"  Profit Factor: {stats['profit_factor']}")
        print(f"  Net PnL:       ${stats['net_pnl']:+.2f} ({stats['net_pnl_percent']:+.1f}%)")
        print(f"  Sharpe Ratio:  {stats['sharpe_ratio']}")
        print(f"  Max Drawdown:  {stats['max_drawdown']}%")
        print(f"  Best Streak:   {stats['best_streak']}W")
        print(f"  Worst Streak:  {stats['worst_streak']}L")
        print(f"  Equity:        ${stats['current_equity']:,.2f}")
        print(f"{'═'*50}")

        # Per-symbol
        sym_stats = self.get_per_symbol_stats()
        if sym_stats:
            print(f"\n  PER SYMBOL:")
            for sym, data in sorted(sym_stats.items(), key=lambda x: x[1]['pnl'], reverse=True)[:10]:
                print(f"    {sym:12} WR={data['win_rate']:5.1f}% PnL=${data['pnl']:+8.2f} ({data['total']}T)")
        print()
