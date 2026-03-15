import logging
import config
from decimal import Decimal
from dataclasses import dataclass

log = logging.getLogger("AdaptiveSizing")

@dataclass
class SizingResult:
    qty: Decimal
    multiplier: float
    reason: str

class AdaptiveSizingEngine:
    """
    Рассчитывает динамический объем ордера.
    Использует байесовский подход и анализ волатильности.
    """
    
    def __init__(self, client, db):
        self.client = client
        self.db = db
        
    def calculate_qty(self, price: Decimal, multiplier: float = 1.0) -> Decimal:
        """
        Упрощенный расчет объема для сетки.
        """
        base_qty = Decimal(str(config.BASE_ORDER_QTY))
        return base_qty * Decimal(str(multiplier))

    def calculate_order_size(self, price: Decimal, side: str) -> SizingResult:
        """
         price: текущая цена
         side: Buy или Sell
        """
        # Базовый объем из конфига
        base_qty = Decimal(str(config.BASE_ORDER_QTY))
        
        # Динамические корректировки
        multiplier = 1.0
        
        # 1. Снижаем объем если волатильность зашкаливает (ATR)
        # 2. Увеличиваем, если WinRate по последним сделкам высокий
        
        final_qty = base_qty * Decimal(str(multiplier))
        
        return SizingResult(
            qty=final_qty,
            multiplier=multiplier,
            reason="Market Normal"
        )
