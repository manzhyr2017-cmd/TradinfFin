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
        
    def record_fill(self, order_id: str, side: str, fill_price: float, price_after_1min: float):
        """Регистрация исполнения и цены через 1 минуту для анализа токсичности."""
        self.executions.append({
            "time": time.time(),
            "side": side,
            "price": fill_price,
            "next_price": price_after_1min
        })
        if len(self.executions) > 50:
            self.executions.pop(0)

    def analyze(self) -> "AdverseSelectionDetector":
        """
        Рассчитывает текущий скор токсичности.
        Если цена идет ПРОТИВ нас сразу после исполнения -> поток токсичен.
        """
        if not self.executions:
            self.toxicity_score = 0.0
            return self

        diffs = []
        for ex in self.executions:
            # Если мы BUY, а цена упала -> не токсично (мы купили дешевле чем сейчас)
            # Если мы BUY, а цена пошла ВЫШЕ -> токсично (мы купили, и цена улетела вверх без нас или нас "обогнали")
            # На самом деле токсичность - это когда цена идет В СТОРОНУ нашего ордера и ПРОБИВАЕТ его.
            # Если мы купили, а цена продолжает падать -> Adverse Selection (мы купили падающий нож)
            
            change = (ex["next_price"] - ex["price"]) / ex["price"]
            if ex["side"] == "Buy":
                if change < -0.001: # Упала более чем на 0.1%
                    diffs.append(1.0)
                else:
                    diffs.append(0.0)
            else: # Sell
                if change > 0.001: # Выросла более чем на 0.1%
                    diffs.append(1.0)
                else:
                    diffs.append(0.0)
        
        if diffs:
            self.toxicity_score = sum(diffs) / len(diffs)
        
        return self

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
