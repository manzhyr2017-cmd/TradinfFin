"""
╔══════════════════════════════════════════════════════════════════╗
║           KELLY CRITERION + PERFORMANCE TRACKER v2.0             ║
║                                                                  ║
║  Компоненты:                                                     ║
║    1. KellyPositionSizer - оптимальный размер позиции            ║
║    2. PerformanceTracker - детальная статистика + аналитика       ║
║                                                                  ║
║  Приоритет: 🟡 ВАЖНЫЙ                                           ║
╚══════════════════════════════════════════════════════════════════╝
"""

import math
import time
import json
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from collections import deque

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# KELLY CRITERION POSITION SIZER
# ═══════════════════════════════════════════════════════════════

class KellyPositionSizer:
    """
    Оптимальный размер позиции на основе формулы Келли.
    
    Kelly % = (W * R - L) / R
    где:
        W = win rate
        R = avg_win / avg_loss (reward/risk ratio)
        L = 1 - W (loss rate)
    
    Используем Conservative Kelly (25-50% от полного Келли)
    для защиты от overfitting и вариации.
    
    Также учитываем:
    - Confluence score (сила сигнала)
    - Текущую волатильность
    - Drawdown state
    """

    def __init__(
        self,
        kelly_fraction: float = 0.25,       # Используем 25% от Келли (conservative)
        min_position_pct: float = 0.005,     # Минимум 0.5% капитала
        max_position_pct: float = 0.10,      # Максимум 10% капитала
        min_trades_for_kelly: int = 30,      # Минимум сделок для расчёта
        default_position_pct: float = 0.02,  # Дефолтный размер до накопления статистики
        lookback_trades: int = 100,          # Окно расчёта (последние N сделок)
    ):
        self.kelly_fraction = kelly_fraction
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.min_trades = min_trades_for_kelly
        self.default_pct = default_position_pct
        self.lookback = lookback_trades
        
        logger.info(
            f"KellyPositionSizer: fraction={kelly_fraction}, "
            f"range=[{min_position_pct*100}%-{max_position_pct*100}%], "
            f"min_trades={min_trades_for_kelly}"
        )

    def calculate(
        self,
        trades: list,
        confluence_score: float = 0.0,       # 0-100 (процент от max)
        current_volatility: float = 0.0,     # Текущий ATR %
        normal_volatility: float = 0.0,      # Нормальный ATR %
        drawdown_pct: float = 0.0,           # Текущая просадка %
    ) -> dict:
        """
        Рассчитать оптимальный размер позиции.
        
        trades: список сделок [{pnl, is_win, pnl_percent}, ...]
        
        Возвращает:
        {
            "position_pct": float,       # Рекомендуемый % от капитала
            "kelly_raw": float,          # Полный Kelly %
            "kelly_adjusted": float,     # Kelly * fraction
            "win_rate": float,
            "reward_risk_ratio": float,
            "method": str,               # "kelly" / "default" / "reduced"
        }
        """
        result = {
            "position_pct": self.default_pct,
            "kelly_raw": 0.0,
            "kelly_adjusted": 0.0,
            "win_rate": 0.0,
            "reward_risk_ratio": 0.0,
            "method": "default",
            "adjustments": [],
        }
        
        # Фильтруем последние N сделок
        recent = trades[-self.lookback:] if len(trades) > self.lookback else trades
        
        if len(recent) < self.min_trades:
            result["method"] = "default"
            result["adjustments"].append(
                f"Недостаточно сделок ({len(recent)}/{self.min_trades}), используем default {self.default_pct*100:.1f}%"
            )
            # Но всё равно применяем корректировки
            result["position_pct"] = self._apply_adjustments(
                self.default_pct, confluence_score, 
                current_volatility, normal_volatility, drawdown_pct
            )
            return result
        
        # === Рассчёт Kelly ===
        wins = [t for t in recent if t.get("is_win", t.get("pnl", 0) > 0)]
        losses = [t for t in recent if not t.get("is_win", t.get("pnl", 0) > 0)]
        
        win_rate = len(wins) / len(recent)
        loss_rate = 1 - win_rate
        
        avg_win = abs(sum(t.get("pnl_percent", t.get("pnl", 0)) for t in wins) / max(1, len(wins)))
        avg_loss = abs(sum(t.get("pnl_percent", t.get("pnl", 0)) for t in losses) / max(1, len(losses)))
        
        if avg_loss == 0:
            avg_loss = 0.001  # Предотвращаем деление на ноль
        
        reward_risk = avg_win / avg_loss
        
        # Kelly Formula: K = (W * R - L) / R
        kelly_raw = (win_rate * reward_risk - loss_rate) / reward_risk
        kelly_adjusted = kelly_raw * self.kelly_fraction
        
        result["win_rate"] = win_rate
        result["reward_risk_ratio"] = reward_risk
        result["kelly_raw"] = kelly_raw
        result["kelly_adjusted"] = kelly_adjusted
        result["method"] = "kelly"
        
        # Если Kelly отрицательный — не торговать
        if kelly_raw <= 0:
            result["position_pct"] = 0
            result["method"] = "kelly_negative"
            result["adjustments"].append("⚠️ Kelly < 0: стратегия убыточна!")
            return result
        
        # Применяем корректировки
        base_pct = max(self.min_position_pct, min(self.max_position_pct, kelly_adjusted))
        result["position_pct"] = self._apply_adjustments(
            base_pct, confluence_score, current_volatility, normal_volatility, drawdown_pct
        )
        
        logger.info(
            f"Kelly: WR={win_rate:.1%}, R/R={reward_risk:.2f}, "
            f"raw={kelly_raw:.3f}, adj={kelly_adjusted:.3f}, "
            f"final={result['position_pct']:.3f} ({result['position_pct']*100:.1f}%)"
        )
        
        return result

    def _apply_adjustments(
        self, base_pct: float, confluence: float,
        vol: float, normal_vol: float, dd: float
    ) -> float:
        """Корректировки размера позиции"""
        adjusted = base_pct
        
        # 1. Confluence score boost/penalty
        if confluence > 0:
            # 80-100% confluence → 1.0-1.5x boost
            # 60-80% → 0.8-1.0x
            # <60% → 0.5-0.8x
            if confluence >= 80:
                adjusted *= 1.0 + (confluence - 80) / 40  # max 1.5x
            elif confluence >= 60:
                adjusted *= 0.8 + (confluence - 60) / 100  # 0.8-1.0x
            else:
                adjusted *= 0.5 + confluence / 200  # 0.5-0.8x
        
        # 2. Volatility adjustment (higher vol → smaller position)
        if vol > 0 and normal_vol > 0:
            vol_ratio = vol / normal_vol
            if vol_ratio > 1.5:
                vol_penalty = 1.0 / vol_ratio
                adjusted *= max(0.3, vol_penalty)
        
        # 3. Drawdown adjustment (deeper DD → smaller position)
        if dd > 0:
            # 0-5% DD → 1.0x
            # 5-10% DD → 0.5-1.0x
            # >10% DD → 0.25-0.5x
            if dd > 0.10:
                adjusted *= 0.25
            elif dd > 0.05:
                adjusted *= 0.5 + (0.10 - dd) * 10  # Linear 0.5-1.0
        
        # Clamp
        return max(self.min_position_pct, min(self.max_position_pct, adjusted))


# ═══════════════════════════════════════════════════════════════
# PERFORMANCE TRACKER
# ═══════════════════════════════════════════════════════════════

@dataclass
class TradeEntry:
    """Запись о сделке"""
    id: str = ""
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    position_size: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    is_win: bool = False
    entry_time: str = ""
    exit_time: str = ""
    duration_seconds: int = 0
    confluence_score: float = 0.0
    market_regime: str = ""
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_reason: str = ""  # "tp", "sl", "signal", "manual", "circuit_breaker"


class PerformanceTracker:
    """
    Полный трекер производительности торгового бота.
    
    Отслеживает:
    - Win rate, profit factor, Sharpe ratio
    - Max drawdown, avg drawdown
    - Equity curve
    - Per-symbol, per-regime, per-timeframe статистику
    - Best/worst trades
    - Streak analysis
    """

    def __init__(self, initial_capital: float = 10000, history_file: str = "trade_history.json"):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        self.history_file = history_file
        
        self.trades: List[TradeEntry] = []
        self.equity_curve: List[Tuple[str, float]] = [(datetime.now().isoformat(), initial_capital)]
        
        # Загрузка истории
        self._load_history()

    def add_trade(self, trade: dict):
        """
        Добавить завершённую сделку.
        
        trade = {
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 100000,
            "exit_price": 101500,
            "position_size": 0.005,
            "pnl": 7.5,
            "confluence_score": 85,
            "market_regime": "ranging_narrow",
            "stop_loss": 99000,
            "take_profit": 102000,
            "exit_reason": "tp",
            "duration_seconds": 3600,
        }
        """
        entry = TradeEntry(
            id=f"T{len(self.trades)+1:06d}",
            symbol=trade.get("symbol", ""),
            side=trade.get("side", ""),
            entry_price=trade.get("entry_price", 0),
            exit_price=trade.get("exit_price", 0),
            position_size=trade.get("position_size", 0),
            pnl=trade.get("pnl", 0),
            pnl_percent=trade.get("pnl_percent", 0),
            is_win=trade.get("pnl", 0) > 0,
            entry_time=trade.get("entry_time", ""),
            exit_time=trade.get("exit_time", datetime.now().isoformat()),
            duration_seconds=trade.get("duration_seconds", 0),
            confluence_score=trade.get("confluence_score", 0),
            market_regime=trade.get("market_regime", ""),
            stop_loss=trade.get("stop_loss", 0),
            take_profit=trade.get("take_profit", 0),
            exit_reason=trade.get("exit_reason", ""),
        )
        
        self.trades.append(entry)
        self.current_capital += entry.pnl
        
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        
        self.equity_curve.append((datetime.now().isoformat(), self.current_capital))
        
        self._save_history()

    def get_statistics(self, last_n: Optional[int] = None) -> dict:
        """
        Полная статистика. last_n = только последние N сделок.
        """
        trades = self.trades[-last_n:] if last_n else self.trades
        
        if not trades:
            return {"error": "No trades yet"}
        
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        
        total_profit = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        
        # === Базовые метрики ===
        stats = {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(trades) * 100,
            "total_pnl": sum(t.pnl for t in trades),
            "total_pnl_pct": (self.current_capital - self.initial_capital) / self.initial_capital * 100,
        }
        
        # === Profit Factor ===
        stats["profit_factor"] = total_profit / total_loss if total_loss > 0 else float('inf')
        
        # === Средние значения ===
        stats["avg_win"] = total_profit / len(wins) if wins else 0
        stats["avg_loss"] = total_loss / len(losses) if losses else 0
        stats["avg_pnl"] = sum(t.pnl for t in trades) / len(trades)
        stats["avg_win_pct"] = sum(t.pnl_percent for t in wins) / len(wins) * 100 if wins else 0
        stats["avg_loss_pct"] = sum(t.pnl_percent for t in losses) / len(losses) * 100 if losses else 0
        
        # === Лучшие/Худшие ===
        stats["best_trade"] = max(t.pnl for t in trades) if trades else 0
        stats["worst_trade"] = min(t.pnl for t in trades) if trades else 0
        
        # === Reward/Risk Ratio ===
        stats["reward_risk_ratio"] = stats["avg_win"] / stats["avg_loss"] if stats["avg_loss"] > 0 else 0
        
        # === Drawdown ===
        stats["max_drawdown_pct"] = self._calc_max_drawdown(trades) * 100
        stats["current_drawdown_pct"] = ((self.peak_capital - self.current_capital) / self.peak_capital * 100) if self.peak_capital > 0 else 0
        
        # === Sharpe Ratio (упрощённый) ===
        stats["sharpe_ratio"] = self._calc_sharpe(trades)
        
        # === Серии ===
        stats["max_consecutive_wins"] = self._max_streak(trades, True)
        stats["max_consecutive_losses"] = self._max_streak(trades, False)
        
        # === Средняя длительность ===
        durations = [t.duration_seconds for t in trades if t.duration_seconds > 0]
        stats["avg_duration_minutes"] = sum(durations) / len(durations) / 60 if durations else 0
        
        # === Капитал ===
        stats["capital"] = {
            "initial": self.initial_capital,
            "current": self.current_capital,
            "peak": self.peak_capital,
        }
        
        return stats

    def get_per_symbol_stats(self) -> Dict[str, dict]:
        """Статистика по символам"""
        symbols: Dict[str, list] = {}
        for t in self.trades:
            symbols.setdefault(t.symbol, []).append(t)
        
        result = {}
        for symbol, trades in symbols.items():
            wins = [t for t in trades if t.is_win]
            result[symbol] = {
                "trades": len(trades),
                "win_rate": len(wins) / len(trades) * 100 if trades else 0,
                "total_pnl": sum(t.pnl for t in trades),
                "avg_pnl": sum(t.pnl for t in trades) / len(trades),
            }
        
        return result

    def get_per_regime_stats(self) -> Dict[str, dict]:
        """Статистика по рыночным режимам"""
        regimes: Dict[str, list] = {}
        for t in self.trades:
            if t.market_regime:
                regimes.setdefault(t.market_regime, []).append(t)
        
        result = {}
        for regime, trades in regimes.items():
            wins = [t for t in trades if t.is_win]
            result[regime] = {
                "trades": len(trades),
                "win_rate": len(wins) / len(trades) * 100 if trades else 0,
                "total_pnl": sum(t.pnl for t in trades),
            }
        
        return result

    def get_kelly_input(self) -> list:
        """Подготовка данных для Kelly Calculator"""
        return [
            {
                "pnl": t.pnl,
                "pnl_percent": t.pnl_percent,
                "is_win": t.is_win,
            }
            for t in self.trades
        ]

    # === Internal Methods ===

    def _calc_max_drawdown(self, trades: list) -> float:
        """Расчёт максимальной просадки"""
        peak = self.initial_capital
        max_dd = 0
        capital = self.initial_capital
        
        for t in trades:
            capital += t.pnl
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        
        return max_dd

    def _calc_sharpe(self, trades: list, risk_free_rate: float = 0.0) -> float:
        """Упрощённый Sharpe Ratio"""
        if len(trades) < 2:
            return 0
        
        returns = [t.pnl_percent for t in trades]
        avg_return = sum(returns) / len(returns)
        
        variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001
        
        # Аннуализированный (предполагаем ~250 торговых дней)
        sharpe = (avg_return - risk_free_rate) / std_dev * math.sqrt(250)
        return round(sharpe, 2)

    @staticmethod
    def _max_streak(trades: list, is_win: bool) -> int:
        """Максимальная серия побед/поражений"""
        max_streak = 0
        current = 0
        for t in trades:
            if t.is_win == is_win:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    def print_report(self):
        """Красивый вывод отчёта"""
        stats = self.get_statistics()
        if "error" in stats:
            print(f"⚠️ {stats['error']}")
            return
        
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║               PERFORMANCE REPORT                             ║
╠══════════════════════════════════════════════════════════════╣
║ Total Trades:     {stats['total_trades']:>6}                                   
║ Win Rate:         {stats['win_rate']:>6.1f}%  (W:{stats['wins']} L:{stats['losses']})          
║ Profit Factor:    {stats['profit_factor']:>6.2f}                                   
║ Sharpe Ratio:     {stats['sharpe_ratio']:>6.2f}                                   
║ R/R Ratio:        {stats['reward_risk_ratio']:>6.2f}                                   
╠══════════════════════════════════════════════════════════════╣
║ Total PnL:        ${stats['total_pnl']:>+10.2f}  ({stats['total_pnl_pct']:+.1f}%)        
║ Avg Win:          ${stats['avg_win']:>+10.2f}  ({stats['avg_win_pct']:+.1f}%)        
║ Avg Loss:         ${stats['avg_loss']:>10.2f}  ({stats['avg_loss_pct']:.1f}%)         
║ Best Trade:       ${stats['best_trade']:>+10.2f}                          
║ Worst Trade:      ${stats['worst_trade']:>+10.2f}                          
╠══════════════════════════════════════════════════════════════╣
║ Max Drawdown:     {stats['max_drawdown_pct']:>6.1f}%                                  
║ Current DD:       {stats['current_drawdown_pct']:>6.1f}%                                  
║ Max Win Streak:   {stats['max_consecutive_wins']:>6}                                   
║ Max Loss Streak:  {stats['max_consecutive_losses']:>6}                                   
║ Avg Duration:     {stats['avg_duration_minutes']:>6.0f} min                                
╠══════════════════════════════════════════════════════════════╣
║ Capital: ${stats['capital']['initial']:,.0f} → ${stats['capital']['current']:,.0f} (Peak: ${stats['capital']['peak']:,.0f})
╚══════════════════════════════════════════════════════════════╝
""")

    # === Persistence ===

    def _save_history(self):
        try:
            data = {
                "initial_capital": self.initial_capital,
                "current_capital": self.current_capital,
                "peak_capital": self.peak_capital,
                "trades": [asdict(t) for t in self.trades[-1000:]],  # Последние 1000
            }
            with open(self.history_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save history: {e}")

    def _load_history(self):
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
            self.current_capital = data.get("current_capital", self.initial_capital)
            self.peak_capital = data.get("peak_capital", self.initial_capital)
            for t in data.get("trades", []):
                self.trades.append(TradeEntry(**t))
            if self.trades:
                logger.info(f"Loaded {len(self.trades)} trades from history")
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.error(f"Failed to load history: {e}")


# ═══════════════════════════════════════════════════════════════
# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Создаём трекер
    tracker = PerformanceTracker(initial_capital=10000)
    
    # Симулируем сделки
    import random
    random.seed(42)
    
    for i in range(50):
        is_win = random.random() < 0.78  # 78% win rate
        pnl = random.uniform(50, 200) if is_win else -random.uniform(30, 100)
        
        tracker.add_trade({
            "symbol": random.choice(["BTCUSDT", "ETHUSDT", "SOLUSDT"]),
            "side": random.choice(["long", "short"]),
            "entry_price": 100000,
            "exit_price": 100000 + pnl * 10,
            "position_size": 0.005,
            "pnl": pnl,
            "pnl_percent": pnl / 10000,
            "confluence_score": random.uniform(60, 95),
            "market_regime": random.choice(["ranging_narrow", "ranging_wide", "weak_trend_up"]),
            "exit_reason": "tp" if is_win else "sl",
            "duration_seconds": random.randint(300, 7200),
        })
    
    # Отчёт
    tracker.print_report()
    
    # Kelly sizing
    kelly = KellyPositionSizer()
    kelly_data = tracker.get_kelly_input()
    result = kelly.calculate(kelly_data, confluence_score=85)
    
    print(f"\n📊 Kelly Position Size: {result['position_pct']*100:.2f}%")
    print(f"   Method: {result['method']}")
    print(f"   Win Rate: {result['win_rate']:.1%}")
    print(f"   R/R: {result['reward_risk_ratio']:.2f}")
    print(f"   Kelly Raw: {result['kelly_raw']:.3f}")
    
    # По символам
    print("\n📊 Per-Symbol Stats:")
    for symbol, stats in tracker.get_per_symbol_stats().items():
        print(f"   {symbol}: {stats['trades']} trades, WR={stats['win_rate']:.0f}%, PnL=${stats['total_pnl']:.2f}")
