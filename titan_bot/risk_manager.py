"""
TITAN BOT 2026 - Risk Manager
Управление рисками и размером позиций
"""

import pandas as pd
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
import config

@dataclass
class PositionSize:
    """Результат расчета размера позиции"""
    quantity: float
    risk_amount: float
    position_value: float
    leverage_suggested: int
    is_valid: bool
    rejection_reason: str = ""

@dataclass
class RiskMetrics:
    """Метрики риска"""
    daily_pnl: float
    daily_pnl_percent: float
    open_risk: float
    available_risk: float
    can_trade: bool
    reason: str = ""


class RiskManager:
    """
    Менеджер рисков.
    
    Правила:
    1. Риск на сделку = 1-2% от депозита
    2. Размер позиции зависит от расстояния до стопа
    3. Дневной лимит потерь = 6%
    4. Не более 1 открытой позиции одновременно
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        self.trades_today = []
        self.daily_start_balance = None
        self.last_reset_date = None
        
    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss: float,
        symbol: str = None,
        risk_percent: float = None
    ) -> PositionSize:
        """
        Рассчитывает оптимальный размер позиции.
        
        Формула:
        Quantity = Risk_Amount / |Entry - StopLoss|
        
        Где Risk_Amount = Balance * RISK_PER_TRADE
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем баланс
        balance = self.data.get_balance()
        
        # Проверяем, можем ли торговать
        risk_check = self.check_risk_limits()
        if not risk_check.can_trade:
            return PositionSize(
                quantity=0,
                risk_amount=0,
                position_value=0,
                leverage_suggested=1,
                is_valid=False,
                rejection_reason=risk_check.reason
            )
        
        # Расстояние до стопа
        stop_distance = abs(entry_price - stop_loss)
        
        if stop_distance == 0:
            return PositionSize(
                quantity=0,
                risk_amount=0,
                position_value=0,
                leverage_suggested=1,
                is_valid=False,
                rejection_reason="Stop distance is zero"
            )
        
        # Сумма риска
        r_percent = risk_percent if risk_percent is not None else config.RISK_PER_TRADE
        risk_amount = balance * r_percent
        
        # Размер позиции в базовой валюте (ETH, BTC и т.д.)
        quantity = risk_amount / stop_distance
        
        # Стоимость позиции в USDT
        position_value = quantity * entry_price
        
        # Проверка минимального размера (Bybit обычно требует минимум $5)
        min_order_value = 5.0
        if position_value < min_order_value:
            return PositionSize(
                quantity=0,
                risk_amount=risk_amount,
                position_value=position_value,
                leverage_suggested=1,
                is_valid=False,
                rejection_reason=f"Position value ${position_value:.2f} below minimum ${min_order_value}"
            )
        
        # Рассчитываем рекомендуемое плечо
        # Плечо = Стоимость позиции / Доступный баланс
        leverage = max(1, min(10, int(position_value / balance) + 1))
        
        # Округляем quantity до нужной точности (зависит от инструмента)
        quantity = self._round_quantity(quantity, symbol)
        
        return PositionSize(
            quantity=quantity,
            risk_amount=risk_amount,
            position_value=position_value,
            leverage_suggested=leverage,
            is_valid=True
        )
    
    def check_risk_limits(self) -> RiskMetrics:
        """
        Проверяет, не превышены ли лимиты риска.
        """
        self._reset_daily_if_needed()
        
        balance = self.data.get_balance()
        
        # Инициализируем дневной баланс
        if self.daily_start_balance is None:
            self.daily_start_balance = balance
        
        # Считаем дневной P&L
        daily_pnl = balance - self.daily_start_balance
        daily_pnl_percent = daily_pnl / self.daily_start_balance if self.daily_start_balance > 0 else 0
        
        # Проверяем открытые позиции
        positions = self.data.get_positions()
        open_risk = sum(abs(p.get('unrealized_pnl', 0)) for p in positions)
        
        # Доступный риск на сегодня
        max_daily_loss = self.daily_start_balance * config.MAX_DAILY_LOSS
        available_risk = max_daily_loss - abs(min(0, daily_pnl))
        
        # Проверки
        can_trade = True
        reason = ""
        
        # 1. Проверка дневного лимита
        if daily_pnl_percent <= -config.MAX_DAILY_LOSS:
            can_trade = False
            reason = f"Daily loss limit reached: {daily_pnl_percent*100:.1f}%"
        
        # 2. Проверка количества позиций
        elif len(positions) >= config.MAX_POSITIONS:
            can_trade = False
            reason = f"Max positions reached: {len(positions)}/{config.MAX_POSITIONS}"
        
        # 3. Проверка минимального баланса
        elif balance < 10:
            can_trade = False
            reason = f"Balance too low: ${balance:.2f}"
        
        return RiskMetrics(
            daily_pnl=daily_pnl,
            daily_pnl_percent=daily_pnl_percent,
            open_risk=open_risk,
            available_risk=available_risk,
            can_trade=can_trade,
            reason=reason
        )
    
    def calculate_dynamic_stop(
        self,
        entry_price: float,
        atr: float,
        direction: str,
        multiplier: float = 1.5
    ) -> float:
        """
        Рассчитывает динамический стоп-лосс на основе ATR.
        
        Волатильный рынок = широкий стоп
        Спокойный рынок = узкий стоп
        """
        stop_distance = atr * multiplier
        
        if direction == 'LONG':
            return entry_price - stop_distance
        else:
            return entry_price + stop_distance
    
    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss: float,
        rr_ratio: float = None
    ) -> float:
        """
        Рассчитывает тейк-профит на основе Risk/Reward.
        """
        if rr_ratio is None:
            rr_ratio = config.MIN_RR_RATIO
        
        risk = abs(entry_price - stop_loss)
        reward = risk * rr_ratio
        
        if entry_price > stop_loss:  # Long
            return entry_price + reward
        else:  # Short
            return entry_price - reward
    
    def record_trade(self, pnl: float):
        """Записывает результат сделки."""
        self.trades_today.append({
            'timestamp': datetime.now(),
            'pnl': pnl
        })
    
    def _reset_daily_if_needed(self):
        """Сбрасывает дневную статистику в полночь."""
        today = datetime.now().date()
        
        if self.last_reset_date != today:
            self.trades_today = []
            self.daily_start_balance = self.data.get_balance()
            self.last_reset_date = today
            print(f"[RiskManager] Daily reset. Start balance: ${self.daily_start_balance:.2f}")
    
    def _round_quantity(self, quantity: float, symbol: str) -> float:
        """
        Округляет количество до допустимой точности на основе данных биржи.
        """
        symbol_info = self.data.get_symbol_info(symbol)
        precision = symbol_info['qty_precision']
        
        # Округляем до нужного количества знаков
        qty = round(quantity, precision)
        
        # Проверяем на кратность qty_step (Bybit требует, чтобы qty был кратен шагу)
        qty_step = symbol_info['qty_step']
        if qty_step > 0:
            qty = (qty // qty_step) * qty_step
            qty = round(qty, precision) # Еще раз от микро-ошибок float
            
        return qty
    

    def has_position(self, symbol: str) -> bool:
        """Проверяет, есть ли открытая позиция по конкретному символу."""
        try:
            positions = self.data.get_positions(symbol)
            return len(positions) > 0
        except:
            return False

    def get_risk_report(self) -> str:
        """Генерирует отчет о рисках."""
        metrics = self.check_risk_limits()
        balance = self.data.get_balance()
        positions = self.data.get_positions()
        
        report = f"""
╔══════════════════════════════════════╗
║         RISK REPORT - TITAN BOT       ║
╠══════════════════════════════════════╣
║ Balance:        ${balance:>10.2f}          ║
║ Daily P&L:      ${metrics.daily_pnl:>10.2f} ({metrics.daily_pnl_percent*100:>+.1f}%)  ║
║ Open Positions: {len(positions):>10}          ║
║ Available Risk: ${metrics.available_risk:>10.2f}          ║
║ Can Trade:      {'YES' if metrics.can_trade else 'NO':>10}          ║
╚══════════════════════════════════════╝
        """
        return report
