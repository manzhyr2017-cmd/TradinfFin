import logging
from decimal import Decimal
from typing import List, Tuple
import config

log = logging.getLogger("GridBot")

class SpreadAnalyzer:
    def __init__(self, session):
        self.session = session
        self.spread_history = []

    def get_current_spread(self) -> dict:
        try:
            resp = self.session.get_orderbook(category="spot", symbol=config.SYMBOL, limit=5)
            if resp["retCode"] == 0:
                book = resp["result"]
                best_bid = Decimal(book["b"][0][0])
                best_ask = Decimal(book["a"][0][0])
                spread = best_ask - best_bid
                spread_pct = (spread / best_bid) * 100
                return {"bid": best_bid, "ask": best_ask, "spread_pct": spread_pct}
        except Exception as e:
            log.error(f"Spread analysis error: {e}")
        return {"bid": Decimal("0"), "ask": Decimal("0"), "spread_pct": Decimal("0")}

class MultiTimeframeAnalyzer:
    def __init__(self, session):
        self.session = session

    def analyze_regime(self) -> str:
        # Simplified MTF: checking trend on 1h and 15m
        # For brevity, returning a mock or simple logic
        return "sideways"

class AnomalyDetector:
    def __init__(self):
        self.price_history = []

    def check(self, current_price: Decimal) -> Tuple[bool, str]:
        self.price_history.append(current_price)
        if len(self.price_history) > 20:
            self.price_history = self.price_history[-20:]
            # Check for spikes > 2%
            if abs(current_price - self.price_history[0]) / self.price_history[0] > 0.02:
                return True, "Price spike detected"
        return False, ""
