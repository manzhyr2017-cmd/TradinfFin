"""
TITAN BOT 2026 - Partial Take Profit
Фиксируй прибыль частями!
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime
import config

@dataclass
class TPLevel:
    """Уровень частичного тейка"""
    price: float
    percent_to_close: int  # % позиции для закрытия
    r_multiple: float      # На каком R закрываем
    executed: bool = False

@dataclass
class PartialTPState:
    """Состояние частичных тейков для позиции"""
    symbol: str
    side: str
    entry_price: float
    initial_quantity: float
    remaining_quantity: float
    tp_levels: List[TPLevel]
    total_realized_pnl: float


class PartialTakeProfitManager:
    """
    Менеджер частичных тейк-профитов.
    
    ПОЧЕМУ ЭТО ВАЖНО ДЛЯ 20%:
    
    Проблема: Ты ставишь TP на +3R. Цена доходит до +2.5R и разворачивается.
    Ты получаешь НОЛЬ вместо хорошего профита.
    
    Решение:
    - На +1R закрываем 30% позиции (фиксируем что-то)
    - На +2R закрываем ещё 40% 
    - Остальные 30% держим до +3R или трейлим
    
    Так ты ВСЕГДА забираешь часть профита с прибыльных движений.
    """
    
    def __init__(self, executor):
        self.executor = executor
        self.active_positions = {}  # symbol -> PartialTPState
        
        # Стандартные уровни тейков (можно настроить в config)
        self.default_tp_structure = [
            {'r_multiple': 1.0, 'percent': 30},   # +1R = закрыть 30%
            {'r_multiple': 2.0, 'percent': 40},   # +2R = закрыть 40%
            {'r_multiple': 3.0, 'percent': 30},   # +3R = закрыть остаток
        ]
    
    def register_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        quantity: float,
        custom_levels: List[dict] = None
    ):
        """
        Регистрирует позицию для частичных тейков.
        
        Args:
            custom_levels: Кастомные уровни [{r_multiple: 1.5, percent: 50}, ...]
        """
        levels = custom_levels or self.default_tp_structure
        initial_risk = abs(entry_price - stop_loss)
        
        tp_levels = []
        for level in levels:
            r_mult = level['r_multiple']
            
            if side == 'LONG':
                tp_price = entry_price + (initial_risk * r_mult)
            else:
                tp_price = entry_price - (initial_risk * r_mult)
            
            tp_levels.append(TPLevel(
                price=tp_price,
                percent_to_close=level['percent'],
                r_multiple=r_mult,
                executed=False
            ))
        
        self.active_positions[symbol] = PartialTPState(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            initial_quantity=quantity,
            remaining_quantity=quantity,
            tp_levels=tp_levels,
            total_realized_pnl=0
        )
        
        print(f"\n[PartialTP] Зарегистрирована позиция {side} {symbol}")
        for tp in tp_levels:
            print(f"  TP{tp.r_multiple}R @ {tp.price:.6g} → закрыть {tp.percent_to_close}%")
    
    def check_and_execute(self, symbol: str, current_price: float) -> Optional[dict]:
        """
        Проверяет и исполняет частичные тейки.
        
        Returns:
            dict с информацией о закрытии, если было исполнение
        """
        if symbol not in self.active_positions:
            return None
        
        state = self.active_positions[symbol]
        
        for tp in state.tp_levels:
            if tp.executed:
                continue
            
            # Проверяем достижение уровня
            hit = False
            if state.side == 'LONG' and current_price >= tp.price:
                hit = True
            elif state.side == 'SHORT' and current_price <= tp.price:
                hit = True
            
            if hit:
                # Считаем сколько закрывать
                qty_to_close = state.initial_quantity * (tp.percent_to_close / 100)
                
                # Проверяем что есть что закрывать
                if qty_to_close > state.remaining_quantity:
                    qty_to_close = state.remaining_quantity
                
                if qty_to_close <= 0:
                    continue
                
                # Исполняем закрытие
                close_side = 'Sell' if state.side == 'LONG' else 'Buy'
                
                result = self.executor.place_order(
                    symbol=symbol,
                    side=close_side,
                    quantity=qty_to_close,
                    order_type='Market'
                )
                
                if result.success:
                    tp.executed = True
                    state.remaining_quantity -= qty_to_close
                    
                    # Считаем реализованный PnL
                    if state.side == 'LONG':
                        pnl = (current_price - state.entry_price) * qty_to_close
                    else:
                        pnl = (state.entry_price - current_price) * qty_to_close
                    
                    state.total_realized_pnl += pnl
                    
                    print(f"\n[PartialTP] ✅ ЧАСТИЧНЫЙ ТЕЙК ИСПОЛНЕН!")
                    print(f"  Уровень: +{tp.r_multiple}R @ {tp.price:.6g}")
                    print(f"  Закрыто: {qty_to_close} ({tp.percent_to_close}%)")
                    print(f"  PnL: ${pnl:.2f}")
                    print(f"  Осталось: {state.remaining_quantity}")
                    
                    return {
                        'type': 'PARTIAL_TP',
                        'r_multiple': tp.r_multiple,
                        'quantity_closed': qty_to_close,
                        'pnl': pnl,
                        'remaining': state.remaining_quantity
                    }
        
        return None
    
    def get_next_tp_level(self, symbol: str) -> Optional[TPLevel]:
        """Возвращает следующий уровень тейка."""
        if symbol not in self.active_positions:
            return None
        
        state = self.active_positions[symbol]
        
        for tp in state.tp_levels:
            if not tp.executed:
                return tp
        
        return None
    
    def close_remaining(self, symbol: str, current_price: float) -> Optional[dict]:
        """Закрывает остаток позиции (например, по трейлинг-стопу)."""
        if symbol not in self.active_positions:
            return None
        
        state = self.active_positions[symbol]
        
        if state.remaining_quantity <= 0:
            return None
        
        close_side = 'Sell' if state.side == 'LONG' else 'Buy'
        
        result = self.executor.place_order(
            symbol=symbol,
            side=close_side,
            quantity=state.remaining_quantity,
            order_type='Market'
        )
        
        if result.success:
            if state.side == 'LONG':
                pnl = (current_price - state.entry_price) * state.remaining_quantity
            else:
                pnl = (state.entry_price - current_price) * state.remaining_quantity
            
            state.total_realized_pnl += pnl
            
            total_pnl = state.total_realized_pnl
            state.remaining_quantity = 0
            
            # Удаляем позицию
            del self.active_positions[symbol]
            
            return {
                'type': 'FULL_CLOSE',
                'final_pnl': pnl,
                'total_pnl': total_pnl
            }
        
        return None
    
    def remove_position(self, symbol: str):
        """Удаляет позицию из отслеживания."""
        if symbol in self.active_positions:
            del self.active_positions[symbol]
