import logging
import numpy as np
import config
from decimal import Decimal
from dataclasses import dataclass
from typing import Dict, Any

log = logging.getLogger("PrecisionTiming")

@dataclass
class TimingScore:
    score: int
    reasons: list = None

class PrecisionTimingEngine:
    """
    Оценивает ЛУЧШИЙ момент для входа/выхода (Тайминг).
    Анализирует микро-структуру рынка.
    """
    
    def __init__(self, client):
        self.client = client
        self.symbol = config.SYMBOL

    def calculate_timing_score(self) -> TimingScore:
        """Рассчитывает композитный скор от 0 до 100."""
        scores = []
        
        # 1. Order Book Imbalance
        obi_data = self._analyze_orderbook()
        scores.append(obi_data['obi'] * 100 * 0.4)
        
        # 2. Funding Rate Check
        funding = self._analyze_funding_rate()
        if funding['funding_rate'] > 0.0003: # Перекос в лонг
            scores.append(30 * 0.3)
        else:
            scores.append(80 * 0.3)
            
        # 3. Spread Stability
        # ... 
        
        total = int(sum(scores))
        return TimingScore(score=total)

    def _analyze_orderbook(self) -> Dict[str, Any]:
        """Анализ давления в стакане."""
        ob = self.client.get_orderbook(limit=20)
        if not ob: return {"obi": 0.5}
        
        bids_vol = sum([float(x[1]) for x in ob.get('b', [])])
        asks_vol = sum([float(x[1]) for x in ob.get('a', [])])
        
        if (bids_vol + asks_vol) == 0: return {"obi": 0.5}
        
        obi = bids_vol / (bids_vol + asks_vol)
        return {"obi": obi}

    def _analyze_funding_rate(self) -> Dict[str, Any]:
        """Анализ ставки финансирования."""
        # Для спота возвращаем 0, для фьючерсов - реальное значение
        return {"funding_rate": 0.0, "next_funding_time": 0}
