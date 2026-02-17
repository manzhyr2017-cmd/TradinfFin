"""
TITAN BOT 2026 - Cooldown System
Защита от тильта и мести рынку
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum
import config

class CooldownReason(Enum):
    CONSECUTIVE_LOSSES = "CONSECUTIVE_LOSSES"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    BIG_LOSS = "BIG_LOSS"
    MANUAL = "MANUAL"

@dataclass
class CooldownState:
    """Состояние кулдауна"""
    is_active: bool
    reason: Optional[CooldownReason]
    started_at: Optional[datetime]
    ends_at: Optional[datetime]
    minutes_remaining: int
    message: str


class CooldownManager:
    """
    Система паузы после убытков.
    
    ПСИХОЛОГИЯ ТРЕЙДИНГА:
    
    После убытка мозг хочет "отыграться". Это называется "тильт".
    В тильте ты:
    - Увеличиваешь размер позиции
    - Входишь без сигнала
    - Игнорируешь стопы
    
    Результат: ещё больший убыток.
    
    РЕШЕНИЕ:
    - После 2 убытков подряд → пауза 30 минут
    - После 3 убытков подряд → пауза 2 часа
    - После большого убытка (>3%) → пауза до конца дня
    
    Это спасёт твой депозит от эмоциональных сливов.
    """
    
    def __init__(self):
        self.consecutive_losses = 0
        self.daily_losses = 0
        self.last_trade_result = None  # 'WIN' или 'LOSS'
        self.cooldown_until = None
        self.cooldown_reason = None
        self.last_reset_date = None
        
        # Настройки (можно вынести в config)
        self.settings = {
            'losses_before_cooldown': 2,      # После скольких убытков пауза
            'short_cooldown_minutes': 30,      # Короткая пауза
            'medium_cooldown_minutes': 120,    # Средняя пауза  
            'big_loss_threshold': 0.03,        # 3% = большой убыток
            'max_consecutive_losses': 4,       # После 4 — стоп на день
        }
    
    def record_trade_result(self, pnl: float, pnl_percent: float):
        """
        Записывает результат сделки и проверяет нужен ли кулдаун.
        
        Args:
            pnl: Абсолютный PnL в долларах
            pnl_percent: PnL в процентах от депозита
        """
        self._reset_daily_if_needed()
        
        if pnl >= 0:
            # Выигрыш — сбрасываем счётчик
            self.consecutive_losses = 0
            self.last_trade_result = 'WIN'
            print(f"[Cooldown] ✅ Профит ${pnl:.2f}. Серия убытков сброшена.")
            
        else:
            # Убыток
            self.consecutive_losses += 1
            self.daily_losses += abs(pnl)
            self.last_trade_result = 'LOSS'
            
            print(f"[Cooldown] ❌ Убыток ${pnl:.2f}. Подряд: {self.consecutive_losses}")
            
            # Проверяем нужен ли кулдаун
            self._check_cooldown_triggers(pnl_percent)
    
    def _check_cooldown_triggers(self, pnl_percent: float):
        """Проверяет триггеры для активации кулдауна."""
        
        # 1. Большой убыток (>3%) — стоп до конца дня
        if abs(pnl_percent) >= self.settings['big_loss_threshold']:
            self._activate_cooldown(
                reason=CooldownReason.BIG_LOSS,
                minutes=self._minutes_until_midnight()
            )
            return
        
        # 2. Слишком много убытков подряд — стоп на день
        if self.consecutive_losses >= self.settings['max_consecutive_losses']:
            self._activate_cooldown(
                reason=CooldownReason.DAILY_LOSS_LIMIT,
                minutes=self._minutes_until_midnight()
            )
            return
        
        # 3. Несколько убытков подряд — короткая пауза
        if self.consecutive_losses >= self.settings['losses_before_cooldown']:
            if self.consecutive_losses == 2:
                minutes = self.settings['short_cooldown_minutes']
            else:
                minutes = self.settings['medium_cooldown_minutes']
            
            self._activate_cooldown(
                reason=CooldownReason.CONSECUTIVE_LOSSES,
                minutes=minutes
            )
    
    def _activate_cooldown(self, reason: CooldownReason, minutes: int):
        """Активирует кулдаун."""
        self.cooldown_until = datetime.now() + timedelta(minutes=minutes)
        self.cooldown_reason = reason
        
        print(f"\n{'⏸️'*20}")
        print(f"[Cooldown] ПАУЗА АКТИВИРОВАНА!")
        print(f"[Cooldown] Причина: {reason.value}")
        print(f"[Cooldown] Длительность: {minutes} минут")
        print(f"[Cooldown] Торговля возобновится: {self.cooldown_until.strftime('%H:%M')}")
        print(f"{'⏸️'*20}\n")
    
    def can_trade(self) -> CooldownState:
        """
        Проверяет, можно ли торговать.
        
        Returns:
            CooldownState с информацией о состоянии
        """
        self._reset_daily_if_needed()
        
        # Проверяем активный кулдаун
        if self.cooldown_until:
            if datetime.now() < self.cooldown_until:
                remaining = (self.cooldown_until - datetime.now()).seconds // 60
                
                return CooldownState(
                    is_active=True,
                    reason=self.cooldown_reason,
                    started_at=self.cooldown_until - timedelta(minutes=remaining),
                    ends_at=self.cooldown_until,
                    minutes_remaining=remaining,
                    message=f"⏸️ Пауза ещё {remaining} мин. Причина: {self.cooldown_reason.value}"
                )
            else:
                # Кулдаун закончился
                self.cooldown_until = None
                self.cooldown_reason = None
                print("[Cooldown] ✅ Пауза окончена. Торговля разрешена.")
        
        # Предупреждение если близко к лимиту
        warning = ""
        if self.consecutive_losses == self.settings['losses_before_cooldown'] - 1:
            warning = f"⚠️ Внимание: ещё 1 убыток = пауза!"
        
        return CooldownState(
            is_active=False,
            reason=None,
            started_at=None,
            ends_at=None,
            minutes_remaining=0,
            message=warning if warning else "✅ Торговля разрешена"
        )
    
    def force_cooldown(self, minutes: int = 60):
        """Принудительная пауза (можно вызвать вручную)."""
        self._activate_cooldown(CooldownReason.MANUAL, minutes)
    
    def reset(self):
        """Сброс кулдауна (использовать осторожно!)."""
        self.cooldown_until = None
        self.cooldown_reason = None
        self.consecutive_losses = 0
        print("[Cooldown] Состояние сброшено")
    
    def _reset_daily_if_needed(self):
        """Сброс в полночь."""
        today = datetime.now().date()
        
        if self.last_reset_date != today:
            self.consecutive_losses = 0
            self.daily_losses = 0
            self.cooldown_until = None
            self.cooldown_reason = None
            self.last_reset_date = today
            print(f"[Cooldown] Новый день. Счётчики сброшены.")
    
    def _minutes_until_midnight(self) -> int:
        """Минут до полуночи."""
        now = datetime.now()
        midnight = datetime(now.year, now.month, now.day) + timedelta(days=1)
        return int((midnight - now).seconds / 60)
    
    def get_stats(self) -> dict:
        """Статистика для отображения."""
        return {
            'consecutive_losses': self.consecutive_losses,
            'daily_losses': self.daily_losses,
            'last_result': self.last_trade_result,
            'cooldown_active': self.cooldown_until is not None,
            'cooldown_reason': self.cooldown_reason.value if self.cooldown_reason else None
        }
