"""
╔══════════════════════════════════════════════════════════════════════╗
║          ENHANCED RISK MANAGER v2.0                                  ║
║     Drop-in апгрейд для execution.py и mean_reversion_bybit.py      ║
║                                                                      ║
║  Расширяет существующий RiskManager:                                 ║
║    + Полноценный Circuit Breaker (3 состояния)                       ║
║    + Max Drawdown Protection (от пика)                               ║
║    + Volatility Filter (ATR-based)                                   ║
║    + Position correlation check (улучшенный)                        ║
║    + Persistence (сохранение состояния)                              ║
║    + Risk Level система (5 уровней)                                  ║
║    + Cooldown после серии убытков (улучшенный)                      ║
║                                                                      ║
║  Совместим с ExecutionManager и UltimateTradingEngine                ║
║                                                                      ║
║  Приоритет: 🔴 КРИТИЧНЫЙ                                            ║
╚══════════════════════════════════════════════════════════════════════╝

ИНТЕГРАЦИЯ:
    # В execution.py заменить:
    from enhanced_risk_manager import EnhancedRiskManager
    
    # В __init__ ExecutionManager:
    self.risk_mgr = EnhancedRiskManager(
        total_capital=self.client.get_total_equity(),
        daily_loss_limit=0.05,
        max_drawdown_limit=0.15,
        state_file="risk_state.json"
    )
    
    # В can_trade():
    can, reason = self.risk_mgr.can_open_trade(symbol, position_usd)
    if not can: return False, reason
    
    # После закрытия сделки:
    self.risk_mgr.on_trade_closed(pnl)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════

class CircuitBreakerState(Enum):
    CLOSED = "closed"           # Всё ОК, торговля разрешена
    HALF_OPEN = "half_open"     # Тестовый режим (уменьшенный размер)
    OPEN = "open"               # СТОП: торговля запрещена


class RiskLevel(Enum):
    NORMAL = "normal"           # 100% позиция
    ELEVATED = "elevated"       # 75% позиция
    HIGH = "high"               # 50% позиция
    CRITICAL = "critical"       # 25% позиция
    EMERGENCY = "emergency"     # 0% — торговля остановлена


# ═══════════════════════════════════════════════════════════════
# ENHANCED RISK MANAGER
# ═══════════════════════════════════════════════════════════════

class EnhancedRiskManager:
    """
    Продвинутый риск-менеджер. Замена для встроенного RiskManager.
    
    Совместим с:
        - ExecutionManager (execution.py)
        - UltimateTradingEngine (mean_reversion_bybit.py)
        - RiskManager (mean_reversion_bybit.py) — drop-in замена
    """

    def __init__(
        self,
        total_capital: float = 10000.0,
        daily_loss_limit: float = 0.05,       # 5% макс. дневной убыток
        max_drawdown_limit: float = 0.15,      # 15% макс. просадка от пика
        max_positions: int = 5,
        max_consecutive_losses: int = 5,
        cooldown_minutes: int = 60,
        max_position_pct: float = 0.10,        # Макс 10% капитала на сделку
        volatility_cutoff: float = 3.0,        # ATR > 3x normal → стоп
        state_file: str = "risk_state.json",
    ):
        # Основные параметры
        self.total_capital = total_capital
        self.starting_capital = total_capital
        self.peak_capital = total_capital
        self.daily_loss_limit = daily_loss_limit
        self.max_drawdown_limit = max_drawdown_limit
        self.max_positions = max_positions
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self.max_position_pct = max_position_pct
        self.volatility_cutoff = volatility_cutoff
        self.state_file = state_file

        # Состояние
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.daily_wins = 0
        self.daily_losses_count = 0
        self.last_reset_date = datetime.now().strftime("%Y-%m-%d")

        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.cooldown_until: Optional[datetime] = None

        self.circuit_breaker_state = CircuitBreakerState.CLOSED
        self.circuit_breaker_active = False  # Совместимость со старым кодом
        self.risk_level = RiskLevel.NORMAL

        self.open_positions: Dict[str, dict] = {}

        # Загрузка сохранённого состояния
        self._load_state()
        self._reset_daily_if_needed()
        self._update_risk_level()

        logger.info(
            f"EnhancedRiskManager: capital=${total_capital:.0f}, "
            f"daily_limit={daily_loss_limit*100}%, "
            f"max_dd={max_drawdown_limit*100}%, "
            f"max_pos={max_positions}"
        )

    # ═══════════════════════════════════════════════════════════
    # ОСНОВНОЙ МЕТОД: МОЖНО ЛИ ТОРГОВАТЬ?
    # ═══════════════════════════════════════════════════════════

    def can_open_trade(
        self,
        symbol: str = "",
        position_size_usd: float = 0.0,
        current_volatility: float = 0.0,
        normal_volatility: float = 0.0,
    ) -> Tuple[bool, str]:
        """
        Главная проверка. Совместима с ExecutionManager.can_trade()
        
        Returns: (can_trade: bool, reason: str)
        """
        self._reset_daily_if_needed()
        self._update_risk_level()

        # 1. Circuit Breaker
        if self.circuit_breaker_state == CircuitBreakerState.OPEN:
            return False, "🚨 CIRCUIT BREAKER OPEN: торговля остановлена"

        # 2. Emergency risk level
        if self.risk_level == RiskLevel.EMERGENCY:
            return False, "🚨 EMERGENCY: риск на максимуме"

        # 3. Cooldown после серии убытков
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            remaining = int((self.cooldown_until - datetime.now()).total_seconds() / 60)
            return False, f"❄️ Cooldown: {remaining} мин (после {self.consecutive_losses} убытков)"

        # Cooldown истёк
        if self.cooldown_until and datetime.now() >= self.cooldown_until:
            self.cooldown_until = None
            self.consecutive_losses = 0
            logger.info("✅ Cooldown завершён")

        # 4. Daily loss limit
        if self.total_capital > 0:
            daily_loss_pct = abs(min(0, self.daily_pnl)) / self.starting_capital
            if daily_loss_pct >= self.daily_loss_limit:
                self._trigger_circuit_breaker("daily_loss")
                return False, f"🚨 Дневной убыток {daily_loss_pct*100:.1f}% >= {self.daily_loss_limit*100}%"

        # 5. Max drawdown от пика
        dd = self._current_drawdown()
        if dd >= self.max_drawdown_limit:
            self._trigger_circuit_breaker("max_drawdown")
            return False, f"🚨 Просадка {dd*100:.1f}% >= {self.max_drawdown_limit*100}%"

        # 6. Max positions
        if len(self.open_positions) >= self.max_positions:
            return False, f"⛔ Макс позиций: {len(self.open_positions)}/{self.max_positions}"

        # 7. Duplicate symbol
        if symbol and symbol in self.open_positions:
            return False, f"⛔ Уже есть позиция по {symbol}"

        # 8. Position size check
        if position_size_usd > 0:
            max_allowed = self.total_capital * self.max_position_pct
            if position_size_usd > max_allowed:
                return False, f"⚠️ Размер ${position_size_usd:.0f} > макс ${max_allowed:.0f} ({self.max_position_pct*100}%)"

        # 9. Volatility filter
        if current_volatility > 0 and normal_volatility > 0:
            vol_ratio = current_volatility / normal_volatility
            if vol_ratio > self.volatility_cutoff:
                return False, f"🌪️ Волатильность {vol_ratio:.1f}x > {self.volatility_cutoff}x нормы"

        # 10. Half-open: разрешаем, но с предупреждением
        if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            return True, f"⚠️ HALF_OPEN: тестовый режим (уменьшите размер)"

        return True, "✅ Trade allowed"

    # Совместимость со старым API
    def can_open_position(self) -> bool:
        """Совместимость с RiskManager из mean_reversion_bybit.py"""
        can, _ = self.can_open_trade()
        return can

    def check_circuit_breaker(self) -> bool:
        """Совместимость с RiskManager.check_circuit_breaker()"""
        return self.circuit_breaker_state == CircuitBreakerState.OPEN

    # ═══════════════════════════════════════════════════════════
    # РЕГИСТРАЦИЯ ПОЗИЦИЙ
    # ═══════════════════════════════════════════════════════════

    def register_position(self, symbol: str, side: str, entry_price: float,
                         position_size: float, confluence_score: float = 0.0):
        """Регистрирует открытую позицию"""
        self.open_positions[symbol] = {
            "side": side,
            "entry_price": entry_price,
            "position_size": position_size,
            "confluence_score": confluence_score,
            "open_time": datetime.now().isoformat(),
        }
        logger.info(f"📝 Позиция зарегистрирована: {symbol} {side} @ {entry_price}")
        self._save_state()

    def close_position(self, symbol: str, exit_price: float = 0.0, pnl: float = 0.0):
        """Закрывает позицию и обновляет статистику"""
        if symbol in self.open_positions:
            del self.open_positions[symbol]

        self.on_trade_closed(pnl)
        logger.info(f"📝 Позиция закрыта: {symbol}, PnL=${pnl:+.2f}")

    def on_trade_closed(self, pnl: float):
        """
        Обновляет состояние после закрытия сделки.
        Совместим с ExecutionManager.record_trade_result()
        """
        self.total_capital += pnl
        self.daily_pnl += pnl
        self.daily_trades += 1

        # Обновляем пик
        if self.total_capital > self.peak_capital:
            self.peak_capital = self.total_capital

        is_win = pnl > 0

        if is_win:
            self.consecutive_losses = 0
            self.consecutive_wins += 1
            self.daily_wins += 1

            # Если были в HALF_OPEN и выиграли → закрываем CB
            if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
                self.circuit_breaker_state = CircuitBreakerState.CLOSED
                self.circuit_breaker_active = False
                logger.info("✅ Circuit Breaker CLOSED (тестовая сделка прибыльная)")
        else:
            self.consecutive_wins = 0
            self.consecutive_losses += 1
            self.daily_losses_count += 1

            # Cooldown после серии убытков
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
                logger.warning(
                    f"❄️ COOLDOWN: {self.cooldown_minutes} мин "
                    f"(после {self.consecutive_losses} убытков подряд)"
                )

            # HALF_OPEN → OPEN при убытке
            if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
                self.circuit_breaker_state = CircuitBreakerState.OPEN
                self.circuit_breaker_active = True
                logger.warning("🚨 Circuit Breaker RE-OPENED (тестовая сделка убыточная)")

        self._update_risk_level()
        self._save_state()

    # Совместимость со старым API
    def record_trade_result(self, is_win: bool, pnl: float = 0.0):
        """Совместимость с ExecutionManager.record_trade_result()"""
        self.on_trade_closed(pnl if is_win else -abs(pnl))

    # ═══════════════════════════════════════════════════════════
    # POSITION SIZING
    # ═══════════════════════════════════════════════════════════

    def get_adjusted_position_size(self, base_pct: float) -> float:
        """
        Корректирует размер позиции по текущему risk level.
        
        base_pct: базовый % от капитала (например 0.02 = 2%)
        Returns: скорректированный %
        """
        multipliers = {
            RiskLevel.NORMAL: 1.0,
            RiskLevel.ELEVATED: 0.75,
            RiskLevel.HIGH: 0.50,
            RiskLevel.CRITICAL: 0.25,
            RiskLevel.EMERGENCY: 0.0,
        }
        mult = multipliers.get(self.risk_level, 1.0)

        # HALF_OPEN → только 50%
        if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            mult = min(mult, 0.50)

        adjusted = base_pct * mult
        return max(0.005, min(adjusted, self.max_position_pct))  # 0.5% — 10%

    def calculate_kelly_size_usd(self, win_rate: float, avg_win: float,
                                  avg_loss: float, stop_loss_pct: float) -> float:
        """
        Kelly Criterion с risk level корректировкой.
        Совместимость с RiskManager.calculate_kelly_size_usd()
        """
        if win_rate <= 0 or avg_win <= 0 or avg_loss <= 0:
            return self.total_capital * 0.01 / max(stop_loss_pct, 0.005)

        loss_rate = 1 - win_rate
        kelly_pct = (win_rate * avg_win - loss_rate * avg_loss) / avg_win

        # Quarter Kelly
        kelly_pct = max(0, min(kelly_pct * 0.25, 0.05))

        # Risk level корректировка
        kelly_pct = self.get_adjusted_position_size(kelly_pct)

        risk_amount = self.total_capital * kelly_pct
        position_usd = risk_amount / max(stop_loss_pct, 0.005)

        return float(position_usd)

    # ═══════════════════════════════════════════════════════════
    # ВНУТРЕННИЕ МЕТОДЫ
    # ═══════════════════════════════════════════════════════════

    def _current_drawdown(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.total_capital) / self.peak_capital

    def _trigger_circuit_breaker(self, reason: str):
        self.circuit_breaker_state = CircuitBreakerState.OPEN
        self.circuit_breaker_active = True
        logger.critical(f"🚨 CIRCUIT BREAKER TRIGGERED: {reason}")
        logger.critical(
            f"   Capital: ${self.total_capital:.2f}, "
            f"Peak: ${self.peak_capital:.2f}, "
            f"Daily PnL: ${self.daily_pnl:+.2f}"
        )
        self._save_state()

    def _update_risk_level(self):
        dd = self._current_drawdown()
        daily_loss_pct = abs(min(0, self.daily_pnl)) / max(self.starting_capital, 1)

        if dd >= self.max_drawdown_limit or daily_loss_pct >= self.daily_loss_limit:
            self.risk_level = RiskLevel.EMERGENCY
        elif dd >= self.max_drawdown_limit * 0.75 or daily_loss_pct >= self.daily_loss_limit * 0.75:
            self.risk_level = RiskLevel.CRITICAL
        elif dd >= self.max_drawdown_limit * 0.50 or self.consecutive_losses >= 3:
            self.risk_level = RiskLevel.HIGH
        elif dd >= self.max_drawdown_limit * 0.25 or self.consecutive_losses >= 2:
            self.risk_level = RiskLevel.ELEVATED
        else:
            self.risk_level = RiskLevel.NORMAL

    def _reset_daily_if_needed(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.last_reset_date:
            logger.info(f"📊 Дневной сброс. Вчера: trades={self.daily_trades}, PnL=${self.daily_pnl:+.2f}")
            self.daily_pnl = 0.0
            self.daily_trades = 0
            self.daily_wins = 0
            self.daily_losses_count = 0
            self.last_reset_date = today
            self.starting_capital = self.total_capital

            # CB может быть сброшен на HALF_OPEN после нового дня
            if self.circuit_breaker_state == CircuitBreakerState.OPEN:
                self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
                self.circuit_breaker_active = False
                logger.info("🔄 Circuit Breaker → HALF_OPEN (новый день)")

            self._save_state()

    # ═══════════════════════════════════════════════════════════
    # PERSISTENCE
    # ═══════════════════════════════════════════════════════════

    def _save_state(self):
        try:
            state = {
                "total_capital": self.total_capital,
                "peak_capital": self.peak_capital,
                "starting_capital": self.starting_capital,
                "daily_pnl": self.daily_pnl,
                "daily_trades": self.daily_trades,
                "last_reset_date": self.last_reset_date,
                "consecutive_losses": self.consecutive_losses,
                "consecutive_wins": self.consecutive_wins,
                "circuit_breaker_state": self.circuit_breaker_state.value,
                "risk_level": self.risk_level.value,
                "open_positions": self.open_positions,
                "cooldown_until": self.cooldown_until.isoformat() if self.cooldown_until else None,
                "saved_at": datetime.now().isoformat(),
            }
            with open(self.state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения risk state: {e}")

    def _load_state(self):
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)

            self.total_capital = state.get("total_capital", self.total_capital)
            self.peak_capital = state.get("peak_capital", self.peak_capital)
            self.starting_capital = state.get("starting_capital", self.starting_capital)
            self.daily_pnl = state.get("daily_pnl", 0.0)
            self.daily_trades = state.get("daily_trades", 0)
            self.last_reset_date = state.get("last_reset_date", self.last_reset_date)
            self.consecutive_losses = state.get("consecutive_losses", 0)
            self.consecutive_wins = state.get("consecutive_wins", 0)
            self.open_positions = state.get("open_positions", {})

            cb = state.get("circuit_breaker_state", "closed")
            self.circuit_breaker_state = CircuitBreakerState(cb)
            self.circuit_breaker_active = (cb == "open")

            rl = state.get("risk_level", "normal")
            self.risk_level = RiskLevel(rl)

            cd = state.get("cooldown_until")
            if cd:
                self.cooldown_until = datetime.fromisoformat(cd)

            logger.info(f"📂 Risk state loaded: capital=${self.total_capital:.2f}, CB={cb}, risk={rl}")
        except Exception as e:
            logger.warning(f"Ошибка загрузки risk state: {e}")

    # ═══════════════════════════════════════════════════════════
    # СТАТУС
    # ═══════════════════════════════════════════════════════════

    def get_status(self) -> dict:
        dd = self._current_drawdown()
        return {
            "capital": self.total_capital,
            "peak_capital": self.peak_capital,
            "drawdown_pct": round(dd * 100, 2),
            "daily_pnl": self.daily_pnl,
            "daily_trades": self.daily_trades,
            "circuit_breaker": self.circuit_breaker_state.value,
            "risk_level": self.risk_level.value,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": len(self.open_positions),
            "cooldown_active": self.cooldown_until is not None and datetime.now() < self.cooldown_until,
        }

    def print_status(self):
        s = self.get_status()
        cb_emoji = {"closed": "🟢", "half_open": "🟡", "open": "🔴"}
        rl_emoji = {"normal": "🟢", "elevated": "🟡", "high": "🟠", "critical": "🔴", "emergency": "🚨"}

        print(f"\n{'═'*50}")
        print(f"  RISK MANAGER STATUS")
        print(f"{'═'*50}")
        print(f"  💰 Capital:     ${s['capital']:,.2f}")
        print(f"  📉 Drawdown:    {s['drawdown_pct']:.1f}% (max {self.max_drawdown_limit*100}%)")
        print(f"  📊 Daily PnL:   ${s['daily_pnl']:+.2f} ({s['daily_trades']} trades)")
        print(f"  {cb_emoji.get(s['circuit_breaker'], '❓')} CB: {s['circuit_breaker']}")
        print(f"  {rl_emoji.get(s['risk_level'], '❓')} Risk: {s['risk_level']}")
        print(f"  📋 Positions:   {s['open_positions']}/{self.max_positions}")
        if s['cooldown_active']:
            print(f"  ❄️  Cooldown:   ACTIVE")
        print(f"{'═'*50}\n")
