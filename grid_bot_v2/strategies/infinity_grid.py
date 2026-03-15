import logging
from decimal import Decimal
from typing import List, Optional
import config

log = logging.getLogger("InfinityGrid")

class InfinityGridEngine:
    """
    Сетка без верхней границы.
    """
    def __init__(self, client):
        self.client = client
        self.floor_price = Decimal("0")
        
    def initialize(self, current_price: Decimal):
        self.floor_price = current_price * (Decimal("1") - Decimal(str(config.INFINITY_TRAILING_PCT / 100)))
        log.info(f"♾️ Infinity Initialized. Floor: {self.floor_price}")

    def update_floor(self, current_price: Decimal):
        new_floor = current_price * (Decimal("1") - Decimal(str(config.INFINITY_TRAILING_PCT / 100)))
        if new_floor > self.floor_price:
            self.floor_price = new_floor
            log.info(f"♾️ Infinity Trailing Floor: {self.floor_price}")
