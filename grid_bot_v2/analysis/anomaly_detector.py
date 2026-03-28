import logging
import numpy as np
from decimal import Decimal
from typing import Tuple

log = logging.getLogger("AnomalyDetector")

class AnomalyDetector:
    """
    Детектор аномалий на рынке.
    Использует статистические методы для обнаружения Pump & Dump или сбоев API.
    """
    
    def __init__(self, window: int = 20, sigma: float = 3.0):
        self.window = window
        self.sigma = sigma
        self.price_history = []
        
    def should_pause(self, current_price: Decimal = None) -> Tuple[bool, str]:
        """
        Проверяет, нужно ли остановить торговлю из-за аномалии.
        """
        if current_price is None:
            return False, ""
            
        price_float = float(current_price)
        self.price_history.append(price_float)
        
        if len(self.price_history) > self.window:
            self.price_history.pop(0)
            
        if len(self.price_history) < self.window:
            return False, "Collecting history"
            
        # 1. Проверка на Z-Score (выброс цены)
        mean = np.mean(self.price_history[:-1])
        std = np.std(self.price_history[:-1])
        
        if std == 0: return False, ""
        
        z_score = abs(price_float - mean) / std
        
        if z_score > self.sigma:
            reason = f"Price Anomaly! Z-Score: {z_score:.2f} (Price spike/crash)"
            log.warning(reason)
            return True, reason
            
        # 2. Проверка на мгновенное изменение (Flash Crash)
        last_price = self.price_history[-2]
        change_pct = abs(price_float - last_price) / last_price * 100
        
        if change_pct > 2.0: # Резкое изменение более 2% за один тик
            reason = f"Flash Action! Sudden {change_pct:.2f}% move"
            log.warning(reason)
            return True, reason
            
        return False, ""

    def reset(self):
        self.price_history = []
