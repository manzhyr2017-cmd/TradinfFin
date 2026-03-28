import logging
from dataclasses import dataclass, field
from typing import List

log = logging.getLogger("OnChain")

@dataclass
class OnChainData:
    overall_signal: float # -1 (bearish) to 1 (bullish)
    alerts: List[str] = field(default_factory=list)
    exchange_inflow: float = 0.0

class OnChainAnalyzer:
    """
    Анализатор ончейн данных.
    Мониторит Whale Alerts и потоки на биржи (Inflow/Outflow).
    """
    
    def __init__(self):
        pass
        
    def get_onchain_data(self) -> OnChainData:
        """
        Получает сводку ончейн данных.
        В реальности требует CryptoQuant / Glassnode / WhaleAlert API.
        """
        # Эмуляция нейтрального сигнала
        return OnChainData(overall_signal=0.0)
