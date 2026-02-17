"""
TITAN BOT 2026 - Trailing Stop Manager
Защита прибыли и максимизация профита
"""

from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import config

@dataclass
class TrailingStopState:
    """Состояние трейлинг стопа"""
    symbol: str
    side: str  # 'LONG' или 'SHORT'
    entry_price: float
    current_stop: float
    highest_price: float  # Для лонга
    lowest_price: float   # Для шорта
    breakeven_activated: bool
    trailing_activated: bool
    last_update: datetime


class TrailingStopManager:
    """
    Менеджер трейлинг-стопа.
    
    Логика:
    1. Цена прошла +1R → переносим стоп в безубыток
    2. Цена прошла +1.5R → включаем трейлинг
    3. Трейлинг следует за ценой на расстоянии 1 ATR
    
    Это критически важно для 20% в месяц:
    - Не даём прибыльным сделкам стать убыточными
    - Даём прибыли расти, но фиксируем при откате
    """
    
    def __init__(self, executor):
        self.executor = executor
        self.active_stops = {}  # symbol -> TrailingStopState
        
    def register_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        initial_stop: float,
        atr: float
    ):
        """Регистрирует новую позицию для отслеживания."""
        
        self.active_stops[symbol] = TrailingStopState(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_stop=initial_stop,
            highest_price=entry_price,
            lowest_price=entry_price,
            breakeven_activated=False,
            trailing_activated=False,
            last_update=datetime.now()
        )
        
        # Сохраняем ATR для расчётов
        self.active_stops[symbol].atr = atr
        self.active_stops[symbol].initial_risk = abs(entry_price - initial_stop)
        
        print(f"[TrailingStop] Позиция зарегистрирована: {side} {symbol} @ {entry_price}")
    
    def update(self, symbol: str, current_price: float) -> Optional[float]:
        """
        Обновляет трейлинг стоп на основе текущей цены.
        
        Returns:
            Новый уровень стопа, если он изменился, иначе None
        """
        if symbol not in self.active_stops:
            return None
        
        state = self.active_stops[symbol]
        new_stop = None
        
        if state.side == 'LONG':
            new_stop = self._update_long(state, current_price)
        else:
            new_stop = self._update_short(state, current_price)
        
        # Если стоп изменился — обновляем на бирже
        if new_stop and new_stop != state.current_stop:
            state.current_stop = new_stop
            state.last_update = datetime.now()
            
            # Отправляем на биржу
            self.executor.modify_sl_tp(symbol, stop_loss=new_stop)
            
            return new_stop
        
        return None
    
    def _update_long(self, state: TrailingStopState, current_price: float) -> Optional[float]:
        """Логика трейлинга для лонга."""
        
        # Обновляем максимальную цену
        if current_price > state.highest_price:
            state.highest_price = current_price
        
        # Считаем текущий профит в R (риск-юнитах)
        profit = current_price - state.entry_price
        profit_in_r = profit / state.initial_risk
        
        # === ЭТАП 1: Безубыток при +1R ===
        if profit_in_r >= 1.0 and not state.breakeven_activated:
            # Переносим стоп в точку входа + небольшой буфер
            new_stop = state.entry_price + (state.atr * 0.1)
            state.breakeven_activated = True
            print(f"[TrailingStop] ✅ БЕЗУБЫТОК активирован @ {new_stop:.2f}")
            return new_stop
        
        # === ЭТАП 2: Трейлинг при +1.5R ===
        if profit_in_r >= 1.5 and not state.trailing_activated:
            state.trailing_activated = True
            print(f"[TrailingStop] 🚀 ТРЕЙЛИНГ активирован")
        
        # === ЭТАП 3: Двигаем стоп за ценой ===
        if state.trailing_activated:
            # Стоп следует на расстоянии 1.5 ATR от максимума
            trailing_distance = state.atr * 1.5
            potential_stop = state.highest_price - trailing_distance
            
            # Стоп двигается только ВВЕРХ (для лонга)
            if potential_stop > state.current_stop:
                print(f"[TrailingStop] 📈 Стоп поднят: {state.current_stop:.2f} → {potential_stop:.2f}")
                return potential_stop
        
        return None
    
    def _update_short(self, state: TrailingStopState, current_price: float) -> Optional[float]:
        """Логика трейлинга для шорта."""
        
        # Обновляем минимальную цену
        if current_price < state.lowest_price:
            state.lowest_price = current_price
        
        profit = state.entry_price - current_price
        profit_in_r = profit / state.initial_risk
        
        # Безубыток
        if profit_in_r >= 1.0 and not state.breakeven_activated:
            new_stop = state.entry_price - (state.atr * 0.1)
            state.breakeven_activated = True
            print(f"[TrailingStop] ✅ БЕЗУБЫТОК активирован @ {new_stop:.2f}")
            return new_stop
        
        # Трейлинг
        if profit_in_r >= 1.5 and not state.trailing_activated:
            state.trailing_activated = True
            print(f"[TrailingStop] 🚀 ТРЕЙЛИНГ активирован")
        
        if state.trailing_activated:
            trailing_distance = state.atr * 1.5
            potential_stop = state.lowest_price + trailing_distance
            
            # Стоп двигается только ВНИЗ (для шорта)
            if potential_stop < state.current_stop:
                print(f"[TrailingStop] 📉 Стоп опущен: {state.current_stop:.2f} → {potential_stop:.2f}")
                return potential_stop
        
        return None
    
    def remove_position(self, symbol: str):
        """Удаляет позицию из отслеживания."""
        if symbol in self.active_stops:
            del self.active_stops[symbol]
            print(f"[TrailingStop] Позиция {symbol} удалена")
