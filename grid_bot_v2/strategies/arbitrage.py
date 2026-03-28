import logging
from typing import List, Optional
from dataclasses import dataclass

log = logging.getLogger("Arbitrage")

@dataclass
class ArbOpportunity:
    pair: str
    buy_exchange: str
    sell_exchange: str
    spread: float
    is_actionable: bool

class CrossExchangeArbitrage:
    """
    Модуль поиска арбитражных возможностей.
    Сравнивает цены Bybit с другими биржами (через CCXT или API).
    """
    
    def __init__(self, primary_client):
        self.primary_client = primary_client
        
    def is_available(self) -> bool:
        """Проверка доступности доп. бирж."""
        return False # По дефолту выключено

    def find_opportunities(self) -> List[ArbOpportunity]:
        """Ищет спреды между биржами."""
        return []
