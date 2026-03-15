import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime
import config

log = logging.getLogger("AutoCompounder")

class AutoCompounder:
    """
    Автоматически реинвестирует прибыль.
    """
    def __init__(self, client, db):
        self.client = client
        self.db = db
        self.mode = config.COMPOUND_MODE
        self.accumulated_profit = Decimal("0")

    def add_profit(self, profit_usdt: Decimal):
        self.accumulated_profit += profit_usdt
        log.info(f"💰 Profit Added: +{float(profit_usdt):.4f} USDT")

    def compound(self, current_base_qty: Decimal, current_grid_levels: int) -> dict:
        if float(self.accumulated_profit) < config.MIN_COMPOUND_USDT:
            return {"compounded": False, "new_qty": current_base_qty, "new_levels": current_grid_levels}

        log.info(f"🔄 AUTO-COMPOUND: Reinvesting {float(self.accumulated_profit):.4f} USDT")
        # Logic to increase qty or levels
        new_qty = current_base_qty * (Decimal("1") + (self.accumulated_profit / Decimal(str(config.INITIAL_CAPITAL))))
        self.accumulated_profit = Decimal("0")
        
        return {
            "compounded": True,
            "new_qty": new_qty,
            "new_levels": current_grid_levels
        }
