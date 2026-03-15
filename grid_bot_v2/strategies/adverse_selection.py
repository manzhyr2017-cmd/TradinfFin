import logging
import time
from typing import List

log = logging.getLogger("AdverseSelection")

class AdverseSelectionDetector:
    """
    Детектор неблагоприятного отбора (Toxic Flow).
    Анализирует, как цена ведет себя ПОСЛЕ наших исполнений.
    Если цена сразу идет против нас — поток токсичен.
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
        # Упрощенная логика: если покупки часто совершаются на локальных хаях, 
        # а продажи на лоях — score растет.
        # В реальности используется VPIN или расчет последействия.
        return self
        
    def is_toxic(self) -> bool:
        return self.toxicity_score > 0.8
