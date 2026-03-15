import logging
from dataclasses import dataclass
from typing import List, Dict, Any

log = logging.getLogger("LiquidationHeatmap")

@dataclass
class LiquidationStatus:
    long_clusters: List[float]
    short_clusters: List[float]
    grid_adjustment: Dict[str, Any]

class LiquidationHeatmapAnalyzer:
    """
    Анализатор карты ликвидаций.
    Находит уровни, где скоплено больше всего ликвидаций лонгов/шортов.
    """
    
    def __init__(self, client):
        self.client = client
        
    def analyze(self, current_price: float) -> LiquidationStatus:
        """
        Основной метод анализа для MasterBrain.
        """
        clusters = self.find_liquidation_clusters()
        
        # Оценка риска
        risk_level = "normal"
        all_clusters = clusters["long_liq_levels"] + clusters["short_liq_levels"]
        for c in all_clusters:
            if abs(current_price - c) / current_price < 0.005: # Ближе 0.5%
                risk_level = "elevated"
                break
                
        return LiquidationStatus(
            long_clusters=clusters["long_liq_levels"],
            short_clusters=clusters["short_liq_levels"],
            grid_adjustment={"risk_level": risk_level}
        )

    def find_liquidation_clusters(self) -> Dict[str, List[float]]:
        """
        Ищет кластеры ликвидаций.
        """
        # Mock данных: в реальности тянем из API
        return {
            "long_liq_levels": [],
            "short_liq_levels": []
        }

    def filter_grid_levels(self, grid_levels: List[float], current_price: float) -> List[float]:
        """
        Убирает уровни сетки, которые находятся слишком близко к крупным кластерам ликвидаций.
        """
        status = self.analyze(current_price)
        all_clusters = status.long_clusters + status.short_clusters
        
        if not all_clusters:
            return grid_levels
            
        filtered = []
        for level in grid_levels:
            is_risky = False
            for cluster in all_clusters:
                if abs(level - cluster) / cluster < 0.001:
                    is_risky = True
                    break
            if not is_risky:
                filtered.append(level)
                
        return filtered
