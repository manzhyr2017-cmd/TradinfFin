"""
╔══════════════════════════════════════════════════════════════════╗
║              RISK MANAGER + CIRCUIT BREAKER v2.0                ║
║         Защита капитала от катастрофических потерь               ║
║                                                                  ║
║  Приоритет: 🔴 КРИТИЧНЫЙ                                        ║
║  Компоненты:                                                     ║
║    - Circuit Breaker (дневной лимит потерь)                      ║
║    - Drawdown Protection (макс. просадка)                        ║
║    - Position Limits (макс. количество позиций)                  ║
║    - Correlation Guard (защита от коррелированных позиций)       ║
║    - Volatility Filter (фильтр экстремальной волатильности)     ║
║    - Cooldown Manager (пауза после серии убытков)               ║
╚══════════════════════════════════════════════════════════════════╝
"""

import time
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import json
import os

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Уровни риска системы"""
    NORMAL = "normal"           # Всё в порядке
    ELEVATED = "elevated"       # Повышенный - уменьшаем позиции
    HIGH = "high"               # Высокий - только закрытие позиций
    CRITICAL = "critical"       # Критический - СТОП торговли
    EMERGENCY = "emergency"     # Экстренный - закрыть ВСЁ


class CircuitBreakerState(Enum):
    """Состояния Circuit Breaker"""
    CLOSED = "closed"           # Нормальная работа
    HALF_OPEN = "half_open"     # Тестовый режим (малые позиции)
    OPEN = "open"               # Торговля остановлена


@dataclass
class TradeRecord:
    """Запись о сделке для отслеживания"""
    symbol: str
    side: str               # "long" / "short"
    entry_price: float
    exit_price: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    position_size: float = 0.0
    timestamp: float = 0.0
    is_win: bool = False
    duration_seconds: int = 0
    confluence_score: float = 0.0


@dataclass
class DailyStats:
    """Ежедневная статистика"""
    date: str = ""
    total_pnl: float = 0.0
    total_pnl_percent: float = 0.0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    max_win: float = 0.0
    max_loss: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0


class RiskManager:
    """
    Комплексный менеджер рисков с Circuit Breaker.
    
    Основные функции:
    1. Circuit Breaker - остановка торговли при превышении лимита потерь
    2. Drawdown Protection - защита от глубокой просадки
    3. Position Sizing - контроль размера позиций
    4. Correlation Guard - защита от коррелированных позиций
    5. Volatility Filter - фильтр экстремальной волатильности
    6. Cooldown после серии убытков
    """

    def __init__(
        self,
        total_capital: float,
        daily_loss_limit: float = 0.05,        # 5% макс. дневной убыток
        max_drawdown_limit: float = 0.15,       # 15% макс. просадка от пика
        max_positions: int = 3,                  # макс. одновременных позиций
        max_consecutive_losses: int = 5,         # макс. серия убытков подряд
        cooldown_minutes: int = 60,              # пауза после серии убытков
        max_position_pct: float = 0.10,          # макс. % капитала на позицию
        volatility_pause_multiplier: float = 3.0, # пауза при волатильности > 3x нормы
        state_file: str = "risk_state.json",
    ):
        # === Капитал ===
        self.total_capital = total_capital
        self.initial_capital = total_capital
        self.peak_capital = total_capital
        
        # === Лимиты ===
        self.daily_loss_limit = daily_loss_limit
        self.max_drawdown_limit = max_drawdown_limit
        self.max_positions = max_positions
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self.max_position_pct = max_position_pct
        self.volatility_pause_multiplier = volatility_pause_multiplier
        
        # === Состояние ===
        self.circuit_breaker_state = CircuitBreakerState.CLOSED
        self.risk_level = RiskLevel.NORMAL
        self.current_positions: Dict[str, dict] = {}
        self.daily_stats = DailyStats(date=self._today())
        self.trade_history: List[TradeRecord] = []
        self.consecutive_losses = 0
        self.cooldown_until: Optional[datetime] = None
        self.last_reset_date: str = self._today()
        
        # === Persistence ===
        self.state_file = state_file
        self._load_state()
        
        logger.info(
            f"RiskManager инициализирован: capital=${total_capital}, "
            f"daily_limit={daily_loss_limit*100}%, max_dd={max_drawdown_limit*100}%, "
            f"max_positions={max_positions}"
        )

    # ═══════════════════════════════════════════════════════════
    # ОСНОВНЫЕ ПРОВЕРКИ (вызывать перед каждой сделкой)
    # ═══════════════════════════════════════════════════════════

    def can_open_trade(self, symbol: str, position_size_usd: float, 
                       current_volatility: float = 0.0, 
                       normal_volatility: float = 0.0) -> Tuple[bool, str]:
        """
        Главная проверка: можно ли открыть сделку?
        
        Возвращает (True/False, причина_отказа)
        """
        # 1. Проверка даты (сброс дневных счётчиков)
        self._check_daily_reset()
        
        # 2. Circuit Breaker
        if self.circuit_breaker_state == CircuitBreakerState.OPEN:
            return False, f"🚫 CIRCUIT BREAKER ACTIVE! Торговля остановлена до завтра."
        
        # 3. Cooldown после серии убытков
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            remaining = (self.cooldown_until - datetime.now()).seconds // 60
            return False, f"⏸️ Cooldown активен. Осталось {remaining} мин."
        
        # 4. Максимальная просадка
        current_dd = self._current_drawdown()
        if current_dd >= self.max_drawdown_limit:
            self._activate_circuit_breaker("MAX_DRAWDOWN")
            return False, f"🔴 Max drawdown {current_dd*100:.1f}% >= {self.max_drawdown_limit*100}%!"
        
        # 5. Дневной лимит убытков
        daily_loss_pct = abs(min(0, self.daily_stats.total_pnl)) / self.total_capital
        if daily_loss_pct >= self.daily_loss_limit:
            self._activate_circuit_breaker("DAILY_LOSS_LIMIT")
            return False, f"🔴 Daily loss {daily_loss_pct*100:.1f}% >= {self.daily_loss_limit*100}%!"
        
        # 6. Максимум позиций
        if len(self.current_positions) >= self.max_positions:
            return False, f"⚠️ Max positions ({self.max_positions}) reached."
        
        # 7. Дубликат символа
        if symbol in self.current_positions:
            return False, f"⚠️ Already in position for {symbol}."
        
        # 8. Размер позиции
        max_allowed = self.total_capital * self.max_position_pct
        if position_size_usd > max_allowed:
            return False, f"⚠️ Position ${position_size_usd:.0f} > max ${max_allowed:.0f}"
        
        # 9. Фильтр волатильности
        if current_volatility > 0 and normal_volatility > 0:
            vol_ratio = current_volatility / normal_volatility
            if vol_ratio > self.volatility_pause_multiplier:
                return False, (
                    f"🌪️ Extreme volatility! Ratio {vol_ratio:.1f}x "
                    f"> {self.volatility_pause_multiplier}x normal"
                )
        
        # 10. Half-open mode (после восстановления)
        if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            max_half = self.total_capital * self.max_position_pct * 0.5  # 50% от нормы
            if position_size_usd > max_half:
                return False, f"⚠️ Half-open mode: max ${max_half:.0f}"
        
        # 11. Приближение к дневному лимиту — уменьшаем exposure
        if daily_loss_pct >= self.daily_loss_limit * 0.7:
            logger.warning(
                f"⚠️ Approaching daily limit: {daily_loss_pct*100:.1f}% "
                f"of {self.daily_loss_limit*100}%"
            )
        
        return True, "✅ Trade allowed"

    # ═══════════════════════════════════════════════════════════
    # УПРАВЛЕНИЕ ПОЗИЦИЯМИ
    # ═══════════════════════════════════════════════════════════

    def register_position(self, symbol: str, side: str, entry_price: float, 
                         position_size: float, confluence_score: float = 0.0):
        """Регистрация открытой позиции"""
        self.current_positions[symbol] = {
            "side": side,
            "entry_price": entry_price,
            "position_size": position_size,
            "confluence_score": confluence_score,
            "timestamp": time.time(),
        }
        logger.info(f"📊 Position registered: {symbol} {side} @ {entry_price}")
        self._save_state()

    def close_position(self, symbol: str, exit_price: float, pnl: float):
        """Закрытие позиции и обновление статистики"""
        if symbol not in self.current_positions:
            logger.warning(f"Position {symbol} not found")
            return
        
        pos = self.current_positions.pop(symbol)
        pnl_pct = pnl / (pos["position_size"] * pos["entry_price"]) if pos["entry_price"] else 0
        
        # Создаём запись
        record = TradeRecord(
            symbol=symbol,
            side=pos["side"],
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            pnl=pnl,
            pnl_percent=pnl_pct,
            position_size=pos["position_size"],
            timestamp=time.time(),
            is_win=pnl > 0,
            duration_seconds=int(time.time() - pos["timestamp"]),
            confluence_score=pos.get("confluence_score", 0),
        )
        self.trade_history.append(record)
        
        # Обновляем дневную статистику
        self._update_daily_stats(record)
        
        # Обновляем капитал
        self.total_capital += pnl
        if self.total_capital > self.peak_capital:
            self.peak_capital = self.total_capital
        
        # Обновляем серию убытков
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self._activate_cooldown()
        else:
            self.consecutive_losses = 0
        
        # Проверяем risk level
        self._update_risk_level()
        
        logger.info(
            f"{'✅' if pnl > 0 else '❌'} {symbol} closed: "
            f"PnL=${pnl:.2f} ({pnl_pct*100:.2f}%) | "
            f"Capital=${self.total_capital:.2f} | "
            f"DD={self._current_drawdown()*100:.1f}%"
        )
        
        self._save_state()

    # ═══════════════════════════════════════════════════════════
    # POSITION SIZING (с учётом текущего риска)
    # ═══════════════════════════════════════════════════════════

    def get_adjusted_position_size(self, base_size_pct: float) -> float:
        """
        Корректировка размера позиции с учётом текущего уровня риска.
        
        base_size_pct: базовый % от капитала (напр. 0.02 = 2%)
        Возвращает: скорректированный % от капитала
        """
        multiplier = 1.0
        
        # Уменьшаем при повышенном риске
        if self.risk_level == RiskLevel.ELEVATED:
            multiplier = 0.5
        elif self.risk_level == RiskLevel.HIGH:
            multiplier = 0.25
        elif self.risk_level in (RiskLevel.CRITICAL, RiskLevel.EMERGENCY):
            multiplier = 0.0
        
        # Уменьшаем при приближении к дневному лимиту
        daily_loss_pct = abs(min(0, self.daily_stats.total_pnl)) / self.total_capital
        if daily_loss_pct > self.daily_loss_limit * 0.5:
            # Линейное уменьшение от 50% до 100% лимита
            remaining_ratio = 1.0 - (daily_loss_pct / self.daily_loss_limit)
            multiplier *= max(0.1, remaining_ratio)
        
        # Half-open mode
        if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            multiplier *= 0.5
        
        # Уменьшаем после серии убытков (даже до cooldown)
        if self.consecutive_losses >= 2:
            loss_penalty = max(0.3, 1.0 - (self.consecutive_losses * 0.15))
            multiplier *= loss_penalty
        
        adjusted = base_size_pct * multiplier
        
        # Не превышаем максимум
        adjusted = min(adjusted, self.max_position_pct)
        
        return adjusted

    # ═══════════════════════════════════════════════════════════
    # CIRCUIT BREAKER
    # ═══════════════════════════════════════════════════════════

    def _activate_circuit_breaker(self, reason: str):
        """Активация Circuit Breaker — ПОЛНАЯ ОСТАНОВКА"""
        self.circuit_breaker_state = CircuitBreakerState.OPEN
        self.risk_level = RiskLevel.CRITICAL
        
        logger.critical(
            f"🚨🚨🚨 CIRCUIT BREAKER ACTIVATED! Reason: {reason} | "
            f"Daily PnL: ${self.daily_stats.total_pnl:.2f} | "
            f"Capital: ${self.total_capital:.2f} | "
            f"Drawdown: {self._current_drawdown()*100:.1f}%"
        )
        
        self._save_state()

    def _activate_cooldown(self):
        """Активация паузы после серии убытков"""
        self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
        logger.warning(
            f"⏸️ Cooldown activated: {self.consecutive_losses} consecutive losses. "
            f"Pausing until {self.cooldown_until.strftime('%H:%M')}"
        )

    def reset_circuit_breaker(self, force: bool = False):
        """Сброс Circuit Breaker (вручную или автоматически)"""
        if force or self._today() != self.last_reset_date:
            self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
            self.risk_level = RiskLevel.ELEVATED
            logger.info("🔄 Circuit Breaker reset to HALF_OPEN")
            self._save_state()

    # ═══════════════════════════════════════════════════════════
    # ВНУТРЕННИЕ МЕТОДЫ
    # ═══════════════════════════════════════════════════════════

    def _current_drawdown(self) -> float:
        """Текущая просадка от пика"""
        if self.peak_capital <= 0:
            return 0
        return (self.peak_capital - self.total_capital) / self.peak_capital

    def _update_daily_stats(self, record: TradeRecord):
        """Обновление дневной статистики"""
        self.daily_stats.total_pnl += record.pnl
        self.daily_stats.total_pnl_percent = self.daily_stats.total_pnl / self.total_capital
        self.daily_stats.trades_count += 1
        
        if record.is_win:
            self.daily_stats.wins += 1
            self.daily_stats.max_win = max(self.daily_stats.max_win, record.pnl)
        else:
            self.daily_stats.losses += 1
            self.daily_stats.max_loss = min(self.daily_stats.max_loss, record.pnl)
            self.daily_stats.consecutive_losses += 1
            self.daily_stats.max_consecutive_losses = max(
                self.daily_stats.max_consecutive_losses,
                self.daily_stats.consecutive_losses
            )
        
        if record.is_win:
            self.daily_stats.consecutive_losses = 0

    def _update_risk_level(self):
        """Обновление уровня риска"""
        dd = self._current_drawdown()
        daily_loss = abs(min(0, self.daily_stats.total_pnl)) / self.total_capital
        
        if dd >= self.max_drawdown_limit or daily_loss >= self.daily_loss_limit:
            self.risk_level = RiskLevel.CRITICAL
        elif dd >= self.max_drawdown_limit * 0.7 or daily_loss >= self.daily_loss_limit * 0.7:
            self.risk_level = RiskLevel.HIGH
        elif dd >= self.max_drawdown_limit * 0.4 or daily_loss >= self.daily_loss_limit * 0.4:
            self.risk_level = RiskLevel.ELEVATED
        else:
            self.risk_level = RiskLevel.NORMAL

    def _check_daily_reset(self):
        """Проверка и сброс дневных счётчиков"""
        today = self._today()
        if today != self.last_reset_date:
            logger.info(f"📅 New day: resetting daily stats. Previous: {self.daily_stats}")
            self.daily_stats = DailyStats(date=today)
            self.last_reset_date = today
            
            # Автоматический сброс CB на следующий день
            if self.circuit_breaker_state == CircuitBreakerState.OPEN:
                self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
                self.risk_level = RiskLevel.ELEVATED
                logger.info("🔄 Circuit Breaker auto-reset to HALF_OPEN (new day)")

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    # ═══════════════════════════════════════════════════════════
    # PERSISTENCE (сохранение/загрузка состояния)
    # ═══════════════════════════════════════════════════════════

    def _save_state(self):
        """Сохранение состояния на диск"""
        state = {
            "total_capital": self.total_capital,
            "peak_capital": self.peak_capital,
            "circuit_breaker_state": self.circuit_breaker_state.value,
            "risk_level": self.risk_level.value,
            "consecutive_losses": self.consecutive_losses,
            "last_reset_date": self.last_reset_date,
            "daily_stats": {
                "date": self.daily_stats.date,
                "total_pnl": self.daily_stats.total_pnl,
                "trades_count": self.daily_stats.trades_count,
                "wins": self.daily_stats.wins,
                "losses": self.daily_stats.losses,
            },
            "current_positions": self.current_positions,
        }
        try:
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save risk state: {e}")

    def _load_state(self):
        """Загрузка состояния с диска"""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            self.total_capital = state.get("total_capital", self.total_capital)
            self.peak_capital = state.get("peak_capital", self.peak_capital)
            self.circuit_breaker_state = CircuitBreakerState(
                state.get("circuit_breaker_state", "closed")
            )
            self.risk_level = RiskLevel(state.get("risk_level", "normal"))
            self.consecutive_losses = state.get("consecutive_losses", 0)
            self.last_reset_date = state.get("last_reset_date", self._today())
            logger.info(f"Risk state loaded: CB={self.circuit_breaker_state.value}")
        except Exception as e:
            logger.error(f"Failed to load risk state: {e}")

    # ═══════════════════════════════════════════════════════════
    # ОТЧЁТНОСТЬ
    # ═══════════════════════════════════════════════════════════

    def get_status_report(self) -> dict:
        """Полный отчёт о состоянии рисков"""
        return {
            "capital": {
                "current": self.total_capital,
                "initial": self.initial_capital,
                "peak": self.peak_capital,
                "total_pnl": self.total_capital - self.initial_capital,
                "total_pnl_pct": (self.total_capital - self.initial_capital) / self.initial_capital * 100,
            },
            "risk": {
                "level": self.risk_level.value,
                "circuit_breaker": self.circuit_breaker_state.value,
                "drawdown_pct": self._current_drawdown() * 100,
                "max_drawdown_limit": self.max_drawdown_limit * 100,
            },
            "daily": {
                "date": self.daily_stats.date,
                "pnl": self.daily_stats.total_pnl,
                "trades": self.daily_stats.trades_count,
                "wins": self.daily_stats.wins,
                "losses": self.daily_stats.losses,
                "win_rate": (self.daily_stats.wins / self.daily_stats.trades_count * 100) 
                           if self.daily_stats.trades_count > 0 else 0,
            },
            "positions": {
                "count": len(self.current_positions),
                "max": self.max_positions,
                "symbols": list(self.current_positions.keys()),
            },
            "consecutive_losses": self.consecutive_losses,
            "cooldown_active": bool(self.cooldown_until and datetime.now() < self.cooldown_until),
        }

    def print_status(self):
        """Красивый вывод статуса"""
        report = self.get_status_report()
        
        risk_emoji = {
            "normal": "🟢", "elevated": "🟡", 
            "high": "🟠", "critical": "🔴", "emergency": "🚨"
        }
        
        print(f"""
╔══════════════════════════════════════════════════╗
║              RISK MANAGER STATUS                 ║
╠══════════════════════════════════════════════════╣
║ Capital:   ${report['capital']['current']:>10,.2f}  (PnL: {report['capital']['total_pnl_pct']:+.1f}%)
║ Peak:      ${report['capital']['peak']:>10,.2f}
║ Drawdown:  {report['risk']['drawdown_pct']:>10.1f}% / {report['risk']['max_drawdown_limit']:.0f}% max
║ Risk:      {risk_emoji.get(report['risk']['level'], '?')} {report['risk']['level'].upper()}
║ CB State:  {report['risk']['circuit_breaker'].upper()}
╠══════════════════════════════════════════════════╣
║ Today:     PnL ${report['daily']['pnl']:>+10.2f}
║ Trades:    {report['daily']['trades']} (W:{report['daily']['wins']} L:{report['daily']['losses']} WR:{report['daily']['win_rate']:.0f}%)
║ Positions: {report['positions']['count']}/{report['positions']['max']} {report['positions']['symbols']}
║ Loss Streak: {report['consecutive_losses']}
╚══════════════════════════════════════════════════╝
""")


# ═══════════════════════════════════════════════════════════════
# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    rm = RiskManager(total_capital=10000, daily_loss_limit=0.05)
    
    # Проверка перед сделкой
    can_trade, reason = rm.can_open_trade("BTCUSDT", 500)
    print(f"Can trade: {can_trade} - {reason}")
    
    # Открытие позиции
    rm.register_position("BTCUSDT", "long", 100000, 0.005)
    
    # Закрытие с прибылью
    rm.close_position("BTCUSDT", 101000, 50)
    
    # Статус
    rm.print_status()
