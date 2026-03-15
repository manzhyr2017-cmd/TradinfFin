import logging
from typing import List, Dict, Any

log = logging.getLogger("LiquidationHeatmap")

class LiquidationHeatmapAnalyzer:
    """
    Анализатор карты ликвидаций.
    Находит уровни, где скоплено больше всего ликвидаций лонгов/шортов.
    """
    
    def __init__(self, client):
        self.client = client
        
    def find_liquidation_clusters(self) -> Dict[str, List[float]]:
        """
        Ищет кластеры ликвидаций.
        """
        # Mock данных: в реальности тянем из API (Coinglass, Kingfisher и т.д.)
        return {
            "long_liq_levels": [],
            "short_liq_levels": []
        }

    def filter_grid_levels(self, grid_levels: List[float], current_price: float) -> List[float]:
        """
        Убирает уровни сетки, которые находятся слишком близко к крупным кластерам ликвидаций,
        так как там высокая вероятность проскальзывания и "выноса".
        """
        clusters = self.find_liquidation_clusters()
        all_clusters = clusters["long_liq_levels"] + clusters["short_liq_levels"]
        
        if not all_clusters:
            return grid_levels
            
        filtered = []
        for level in grid_levels:
            is_risky = False
            for cluster in all_clusters:
                # Если уровень ближе 0.1% к кластеру — считаем его рискованным
                if abs(level - cluster) / cluster < 0.001:
                    is_risky = True
                    break
            if not is_risky:
                filtered.append(level)
                
        return filtered
