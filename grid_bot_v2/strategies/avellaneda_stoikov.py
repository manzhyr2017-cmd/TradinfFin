import logging
import numpy as np
import config
from decimal import Decimal
from dataclasses import dataclass
from typing import Dict, Any, List

log = logging.getLogger("AvellanedaStoikov")

@dataclass
class GridLevel:
    price: float
    side: str
    skewed_price: Decimal
    recommended_qty: Decimal
    index: int = 0
    qty_mult: float = 1.0

class AvellanedaStoikovModel:
    """
    Модель Авелланеды-Стойкова для маркет-мейкинга.
    Рассчитывает оптимальные котировки (bid/ask) на основе инвентаря и волатильности.
    """
    
    def __init__(self, client):
        self.client = client
        self.gamma = 0.1 # Коэффициент неприятия риска
        self.kappa = 1.5 # Параметр интенсивности ордеров
        
    def calculate_quotes(self, mid_price: float, volatility: float, inventory: float, time_left: float = 1.0) -> Dict[str, float]:
        """
        mid_price: текущая средняя цена
        volatility: волатильность за период
        inventory: текущая позиция (дельтa)
        time_left: время до конца периода (0 to 1)
        """
        # 1. Резервная цена (Indifference Price)
        reservation_price = mid_price - (inventory * self.gamma * (volatility**2) * time_left)
        
        # 2. Оптимальный спред
        spread = (2 / self.gamma) * np.log(1 + (self.gamma / self.kappa))
        
        return {
            "bid": reservation_price - (spread / 2),
            "ask": reservation_price + (spread / 2),
            "reservation_price": reservation_price,
            "spread": spread
        }

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
import config
from decimal import Decimal
