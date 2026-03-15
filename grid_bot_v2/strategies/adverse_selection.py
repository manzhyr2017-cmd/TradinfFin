from dataclasses import dataclass
import logging
import time
from typing import List

log = logging.getLogger("AdverseSelection")

@dataclass
class GridLevel:
    price: float
    side: str
    qty_mult: float = 1.0

class AdverseSelectionDetector:
    """
    Детектор неблагоприятного отбора (Toxic Flow).
    Анализирует, как цена ведет себя ПОСЛЕ наших исполнений.
    """
    
    def __init__(self, window: int = 5):
        self.executions = [] # List of (timestamp, side, price)
        self.toxicity_score = 0.0 # 0 to 1
        
    def record_execution(self, side: str, price: float):
        self.executions.append({
            "time": time.time(),
            "side": side,
            "price": price
        })
        if len(self.executions) > 100:
            self.executions.pop(0)

    def analyze(self) -> "AdverseSelectionDetector":
        """Рассчитывает текущий скор токсичности."""
        # Мок логика
        return self
        
    def is_toxic(self) -> bool:
        return self.toxicity_score > 0.8

    def skew_grid_levels(self, levels: List[float], past_prices: List[float], current_price: float) -> List[GridLevel]:
        """
        Преобразует список ценовых уровней в объекты GridLevel, 
        смещая объемы (qty_mult) в зависимости от токсичности потока.
        """
        skewed = []
        for p in levels:
            side = "Buy" if p < current_price else "Sell"
            mult = 1.0
            
            # Если поток токсичен, уменьшаем объемы на сторонах, где нас "разрывают"
            if self.is_toxic():
                # Например, если мы покупаем в падающем рынке (toxic), уменьшаем Buy объемы
                mult = 0.5
                
            skewed.append(GridLevel(price=p, side=side, qty_mult=mult))
            
        return skewed
