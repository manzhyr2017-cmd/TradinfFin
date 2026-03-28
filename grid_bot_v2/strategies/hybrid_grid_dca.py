import logging
from decimal import Decimal
from typing import Optional, List
from datetime import datetime
from enum import Enum
import config

log = logging.getLogger("HybridGridDCA")

class BotMode(Enum):
    GRID = "grid"
    DCA = "dca"
    SELL_ONLY = "sell"
    PAUSED = "paused"

class HybridGridDCA:
    """
    Hybrid Engine: Switches between Grid and DCA based on market regime.
    """
    def __init__(self, client, db):
        self.client = client
        self.db = db
        self.current_mode = BotMode.GRID
        self.dca_accumulated_qty = Decimal("0")
        self.dca_avg_price = Decimal("0")

    def determine_mode(self, regime: str, rsi: float, trend_strength: float) -> BotMode:
        if regime == "high_volatility" or rsi < 20 or rsi > 80:
            return BotMode.PAUSED
        if regime == "trending_down" and trend_strength < -0.4:
            return BotMode.DCA
        if regime == "trending_up" and trend_strength > 0.4:
            return BotMode.SELL_ONLY
        return BotMode.GRID

    def manage_mode_switch(self, new_mode: BotMode):
        if new_mode == self.current_mode:
            return
        log.info(f"🔄 HYBRID SWITCH: {self.current_mode.value} -> {new_mode.value}")
        self.current_mode = new_mode

    def get_dca_levels(self, center_price: Decimal) -> List[dict]:
        levels = []
        base_qty = Decimal(str(config.BASE_ORDER_QTY))
        for i in range(1, 6):
            price = center_price * (Decimal("1") - (Decimal("0.02") * i))
            qty = base_qty * (Decimal("1") + (Decimal("0.5") * i))
            levels.append({"side": "Buy", "price": round(float(price), 2), "qty": qty})
        return levels
