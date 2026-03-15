import logging
import numpy as np
from decimal import Decimal
from typing import Dict, Any

log = logging.getLogger("AvellanedaStoikov")

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
