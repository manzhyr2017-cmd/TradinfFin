from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import logging
import numpy as np

log = logging.getLogger("VolumeProfile")

@dataclass
class VPNode:
    price: float
    volume: float
    node_type: str # 'poc', 'hvn', 'lvn'

@dataclass
class VolumeProfile:
    nodes: List[VPNode]
    poc: float
    value_area_high: float
    value_area_low: float

class VolumeProfileAnalyzer:
    """
    Анализатор профиля объема (VPVR).
    Находит Point of Control (POC) и Value Area.
    """
    
    def __init__(self, client):
        self.client = client
        self.last_profile: Optional[VolumeProfile] = None
        
    def analyze(self, symbol: str) -> VolumeProfile:
        """
        Расчитывает профиль объема на основе последних данных.
        """
        klines = self.client.get_klines(symbol=symbol, interval="15", limit=200)
        if not klines:
            empty = VolumeProfile(nodes=[], poc=0.0, value_area_high=0.0, value_area_low=0.0)
            self.last_profile = empty
            return empty
            
        prices = np.array([float(k[4]) for k in klines])
        volumes = np.array([float(k[5]) for k in klines])
        
        # Гистограмма объемов
        bins_count = 50
        hist, bin_edges = np.histogram(prices, bins=bins_count, weights=volumes)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        
        max_idx = np.argmax(hist)
        poc = bin_centers[max_idx]
        
        avg_vol = np.mean(hist)
        
        nodes = []
        for i in range(len(bin_centers)):
            vol = hist[i]
            if i == max_idx:
                ntype = "poc"
            elif vol > avg_vol * 1.5:
                ntype = "hvn"
            elif vol < avg_vol * 0.5:
                ntype = "lvn"
            else:
                continue # Обычные узлы не интересны
                
            nodes.append(VPNode(price=float(bin_centers[i]), volume=float(vol), node_type=ntype))
            
        profile = VolumeProfile(
            nodes=nodes,
            poc=float(poc),
            value_area_high=float(max(prices)),
            value_area_low=float(min(prices))
        )
        self.last_profile = profile
        return profile

    def generate_weighted_grid(self, lower: float, upper: float, levels_count: int) -> List[float]:
        """
        Генерирует уровни сетки, смещая их в сторону узлов высокого объема.
        """
        uniform_grid = list(np.linspace(lower, upper, levels_count))
        
        try:
            profile = self.analyze(self.client.symbol) if not self.last_profile else self.last_profile
            
            # Находим наиболее загруженные зоны внутри нашего диапазона
            valid_nodes = [n for n in profile.nodes if lower <= n.price <= upper and n.node_type in ('poc', 'hvn')]
            
            if len(valid_nodes) < levels_count:
                # Если мало узлов, дополняем равномерными
                return uniform_grid
                
            # Выбираем топ N уровней по объему
            valid_nodes.sort(key=lambda x: x.volume, reverse=True)
            top_nodes = sorted(valid_nodes[:levels_count], key=lambda x: x.price)
            weighted_levels = [n.price for n in top_nodes]
            
            return weighted_levels
        except Exception as e:
            log.error(f"Error in generate_weighted_grid: {e}")
            return uniform_grid
