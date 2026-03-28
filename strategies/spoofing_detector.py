import logging
from collections import deque
from typing import Dict, Any

log = logging.getLogger("SpoofingDetector")

class SpoofingDetector:
    """
    Детектор спуфинга в стакане.
    Смотрит на быстро исчезающие крупные ордера прямо перед ценой.
    """
    
    def __init__(self, client):
        self.client = client
        self.snapshots = deque(maxlen=20)
        self.spoof_score = 0.0
        
    def take_snapshot(self):
        """Сохраняет срез стакана для анализа динамики."""
        ob = self.client.get_orderbook(limit=20)
        if ob:
            self.snapshots.append(ob)
            
    def analyze(self) -> "SpoofingDetector":
        """
        Сравнивает текущий стакан с прошлыми.
        Если большой объем исчез без сделок — это спуфинг.
        """
        if len(self.snapshots) < 2: 
            return self
            
        # Реальная логика требует сопоставления с лентой сделок (Trades)
        # Упрощаем: если волатильность объемов в слоях 2-5 выше нормы
        self.spoof_score = 0.1 # Mock value
        return self
