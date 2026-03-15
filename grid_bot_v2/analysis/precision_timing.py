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
        reasons = []
        
        # 1. Order Book Imbalance (40%)
        obi_data = self._analyze_orderbook()
        obi_score = obi_data['obi'] * 100
        scores.append(obi_score * 0.4)
        if obi_score > 70: reasons.append("Strong BID pressure")
        
        # 2. Funding Rate Check (20%)
        funding = self._analyze_funding_rate()
        fr = funding['funding_rate']
        if fr > 0.0003: # High funding (longs paying)
            scores.append(20 * 0.2)
            reasons.append(f"High funding: {fr:.4%}")
        elif fr < -0.0003: # Low funding (shorts paying)
            scores.append(80 * 0.2)
            reasons.append(f"Low funding: {fr:.4%}")
        else:
            scores.append(50 * 0.2)
            
        # 3. Volatility Check (20%)
        # Placeholder for real volatility check
        scores.append(50 * 0.2)
        
        # 4. Momentum (20%)
        # Placeholder for RSI/MACD timing
        scores.append(50 * 0.2)
        
        total = int(sum(scores))
        return TimingScore(score=total, reasons=reasons)

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
