import logging
import numpy as np
from typing import Dict, Any, List

log = logging.getLogger("VolumeProfile")

class VolumeProfileAnalyzer:
    """
    Анализатор профиля объема (VPVR).
    Находит Point of Control (POC) и Value Area.
    """
    
    def __init__(self, client):
        self.client = client
        self.poc = None
        
    def analyze(self, symbol: str) -> Dict[str, Any]:
        """
        Расчитывает профиль объема на основе последних данных.
        """
        klines = self.client.get_klines(symbol=symbol, interval="15", limit=100)
        if not klines:
            return {"poc": 0.0, "value_area_high": 0.0, "value_area_low": 0.0}
            
        prices = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        
        # Простейший расчет POC
        hist, bin_edges = np.histogram(prices, bins=20, weights=volumes)
        max_bin = np.argmax(hist)
        self.poc = (bin_edges[max_bin] + bin_edges[max_bin+1]) / 2
        
        return {
            "poc": self.poc, 
            "value_area_high": max(prices), 
            "value_area_low": min(prices)
        }

    def generate_weighted_grid(self, lower: float, upper: float, levels_count: int) -> List[float]:
        """
        Генерирует уровни сетки, смещая их в сторону узлов высокого объема.
        """
        # Пока возвращаем равномерную сетку как fallback, если расчет не удался
        uniform_grid = list(np.linspace(lower, upper, levels_count))
        
        try:
            # Пытаемся получить данные для веса
            klines = self.client.get_klines(interval="15", limit=200)
            if not klines: return uniform_grid
            
            prices = np.array([float(k[4]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])
            
            # Гистограмма объемов
            hist, bin_edges = np.histogram(prices, bins=levels_count * 2, weights=volumes)
            bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
            
            # Находим наиболее загруженные зоны внутри нашего диапазона
            mask = (bin_centers >= lower) & (bin_centers <= upper)
            valid_centers = bin_centers[mask]
            valid_volumes = hist[mask]
            
            if len(valid_centers) < levels_count:
                return uniform_grid
                
            # Выбираем топ N уровней по объему
            indices = np.argsort(valid_volumes)[-levels_count:]
            weighted_levels = sorted(valid_centers[indices].tolist())
            
            return weighted_levels
        except Exception as e:
            log.error(f"Error in generate_weighted_grid: {e}")
            return uniform_grid
