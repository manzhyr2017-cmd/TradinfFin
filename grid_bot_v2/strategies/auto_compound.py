import logging
from decimal import Decimal
from typing import Optional
from datetime import datetime
import config

log = logging.getLogger("AutoCompounder")

from dataclasses import dataclass

@dataclass
class CompoundState:
    initial_capital: float = 1000.0
    total_compounded: float = 0.0
    compound_roi_pct: float = 0.0
    compound_count: int = 0

class AutoCompounder:
    """
    Автоматически реинвестирует прибыль.
    """
    def __init__(self, client, db):
        self.client = client
        self.db = db
        self.mode = config.COMPOUND_MODE
        self.accumulated_profit = Decimal("0")
        
        # Состояние для MasterBrain
        self.state = CompoundState(
            initial_capital=float(config.INITIAL_CAPITAL),
            total_compounded=0.0,
            compound_roi_pct=0.0
        )
        self.compound_threshold = float(config.MIN_COMPOUND_USDT)
        self.compound_enabled = True

    def add_profit(self, profit_usdt: Decimal):
        self.accumulated_profit += profit_usdt
        log.info(f"💰 Profit Added: +{float(profit_usdt):.4f} USDT")

    def compound(self, current_base_qty: Decimal, current_grid_levels: int) -> dict:
        if float(self.accumulated_profit) < self.compound_threshold:
            return {"compounded": False, "new_qty": current_base_qty, "new_levels": current_grid_levels}

        amount = float(self.accumulated_profit)
        log.info(f"🔄 AUTO-COMPOUND: Reinvesting {amount:.4f} USDT")
        
        # Logic to increase qty or levels
        new_qty = current_base_qty * (Decimal("1") + (self.accumulated_profit / Decimal(str(config.INITIAL_CAPITAL))))
        
        # Update state
        self.state.total_compounded += amount
        self.state.compound_roi_pct = (self.state.total_compounded / self.state.initial_capital) * 100
        self.state.compound_count += 1
        
        self.accumulated_profit = Decimal("0")
        
        return {
            "compounded": True,
            "new_qty": new_qty,
            "new_levels": current_grid_levels,
            "compound_count": self.state.compound_count,
            "profit_reinvested": amount
        }

    def get_projection(self, daily_rate_pct: float, months: int) -> dict:
        """
        Проекция сложного процента.
        """
        try:
            daily_rate = daily_rate_pct / 100.0
            days = months * 30
            balance = self.state.initial_capital + self.state.total_compounded

            if balance <= 0:
                balance = 1000.0

            projection = []
            current = balance

            for month in range(1, months + 1):
                current = current * ((1 + daily_rate) ** 30)
                projection.append({
                    'month': month,
                    'balance': round(current, 2),
                    'profit': round(current - balance, 2),
                    'roi_pct': round((current / balance - 1) * 100, 2)
                })

            return {
                'initial_balance': round(balance, 2),
                'final_balance': round(current, 2),
                'total_profit': round(current - balance, 2),
                'total_roi_pct': round((current / balance - 1) * 100, 2),
                'daily_rate_pct': daily_rate_pct,
                'months': months,
                'days': days,
                'monthly': projection
            }

        except Exception as e:
            log.error(f"Error in projection: {e}")
            return {
                'initial_balance': 0, 'final_balance': 0, 'total_profit': 0,
                'total_roi_pct': 0, 'daily_rate_pct': daily_rate_pct,
                'months': months, 'error': str(e)
            }

    @property
    def should_compound(self) -> bool:
        """
        Проверка: нужно ли реинвестировать прибыль.
        """
        try:
            return self.compound_enabled and float(self.accumulated_profit) >= self.compound_threshold
        except Exception:
            return False
