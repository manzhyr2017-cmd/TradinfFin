import logging
import numpy as np
import config
from decimal import Decimal
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

log = logging.getLogger("AvellanedaStoikov")

@dataclass
class GridLevel:
    price: float
    side: str
    skewed_price: Decimal
    recommended_qty: Decimal
    index: int = 0
    qty_mult: float = 1.0

@dataclass
class ASQuotes:
    bid: Decimal
    ask: Decimal
    reservation_price: Decimal
    spread: Decimal

class AvellanedaStoikovModel:
    """
    Модель Авелланеды-Стойкова для маркет-мейкинга.
    Рассчитывает оптимальные котировки (bid/ask) на основе инвентаря и волатильности.
    """
    
    def __init__(self, client):
        self.client = client
        self.gamma = 0.1 # Коэффициент неприятия риска
        self.kappa = 1.5 # Параметр интенсивности ордеров
        self.current_inventory = Decimal("0")
        self.last_quotes: Optional[ASQuotes] = None
        
    def update_inventory(self, side: str, qty: Decimal, price: Decimal):
        """Обновление текущего инвентаря."""
        if side == "Buy":
            self.current_inventory += qty
        else:
            self.current_inventory -= qty
        log.info(f"📊 AS Inventory Update: {self.current_inventory} (after {side} {qty})")

    def calculate_quotes(self, mid_price: float, volatility: float, inventory: float, time_left: float = 1.0) -> ASQuotes:
        """
        mid_price: текущая средняя цена
        volatility: волатильность за период
        inventory: текущая позиция (дельтa)
        time_left: время до конца периода (0 to 1)
        """
        # 1. Резервная цена (Indifference Price)
        # s - (q * gamma * sigma^2 * (T-t))
        reservation_price = mid_price - (inventory * self.gamma * (volatility**2) * time_left)
        
        # 2. Оптимальный спред
        # gamma * sigma^2 * (T-t) + (2/gamma) * ln(1 + gamma/kappa)
        spread = (2 / self.gamma) * np.log(1 + (self.gamma / self.kappa))
        
        quotes = ASQuotes(
            bid=Decimal(str(reservation_price - (spread / 2))),
            ask=Decimal(str(reservation_price + (spread / 2))),
            reservation_price=Decimal(str(reservation_price)),
            spread=Decimal(str(spread))
        )
        self.last_quotes = quotes
        return quotes

    def skew_grid_levels(self, levels: List[float], past_prices: List[Any], current_price: float) -> List[GridLevel]:
        """
        Преобразует список ценовых уровней в объекты GridLevel.
        """
        skewed = []
        base_qty = Decimal(str(config.BASE_ORDER_QTY))
        
        # Сортируем уровни чтобы индекс был последовательным
        sorted_levels = sorted(levels)
        
        for i, p in enumerate(sorted_levels):
            side = "Buy" if p < current_price else "Sell"
            mult = 1.0
            
            p_dec = Decimal(str(p))
            qty_dec = base_qty * Decimal(str(mult))
            
            skewed.append(GridLevel(
                price=p, 
                side=side, 
                skewed_price=p_dec, 
                recommended_qty=qty_dec,
                index=i,
                qty_mult=mult
            ))
            
        return skewed

