"""
TITAN BOT 2026 - Volume Profile (VPVR)
Где РЕАЛЬНО торговали, а не где рисовали свечи
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
import config

@dataclass
class VolumeLevel:
    """Уровень объёма"""
    price: float
    volume: float
    percent_of_total: float
    is_poc: bool          # Point of Control
    is_hva: bool          # High Volume Area
    is_lva: bool          # Low Volume Area

@dataclass
class VolumeProfileAnalysis:
    """Результат анализа Volume Profile"""
    poc: float                          # Point of Control (цена с макс объёмом)
    vah: float                          # Value Area High (верх зоны стоимости)
    val: float                          # Value Area Low (низ зоны стоимости)
    hva_zones: List[Tuple[float, float]]  # High Volume Areas (поддержки/сопротивления)
    lva_zones: List[Tuple[float, float]]  # Low Volume Areas (пробиваются легко)
    current_position: str               # 'ABOVE_POC', 'BELOW_POC', 'AT_POC'
    nearest_hva: Optional[float]        # Ближайшая зона высокого объёма
    trade_recommendation: str
    description: str


class VolumeProfileAnalyzer:
    """
    Анализатор Volume Profile.
    
    ПОЧЕМУ ЭТО КИЛЛЕР-ФИЧА:
    
    Обычные свечи показывают OHLC. Но они НЕ показывают,
    ГДЕ РЕАЛЬНО ПРОИСХОДИЛА ТОРГОВЛЯ.
    
    Volume Profile показывает:
    - POC (Point of Control) — цена, где прошёл МАКСИМУМ объёма
      Это "справедливая цена". Рынок к ней возвращается.
    
    - Value Area (70% объёма) — зона, где прошла основная торговля
      VAH (верх) и VAL (низ) — сильные уровни
    
    - HVA (High Volume Area) — много торговали = сильная поддержка/сопротивление
    - LVA (Low Volume Area) — мало торговали = цена ПРОЛЕТАЕТ через эти зоны
    
    СТРАТЕГИЯ:
    - Входи на отбой от POC или границ Value Area
    - Не лонгуй в LVA снизу — там нет поддержки
    - После пробоя LVA жди сильное движение
    """
    
    def __init__(self, data_engine, num_bins: int = 50):
        self.data = data_engine
        self.num_bins = num_bins
        self.value_area_percent = 0.70  # 70% объёма = Value Area
    
    def analyze(self, symbol: str = None, lookback: int = 200) -> VolumeProfileAnalysis:
        """
        Строит Volume Profile и анализирует текущую позицию цены.
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        df = self.data.get_klines(symbol, limit=lookback)
        
        if df is None or len(df) < 50:
            return self._empty_analysis()
        
        # Строим профиль
        profile = self._build_profile(df)
        
        # Находим POC
        poc = self._find_poc(profile)
        
        # Находим Value Area
        vah, val = self._find_value_area(profile, poc)
        
        # Находим HVA и LVA зоны
        hva_zones = self._find_hva_zones(profile)
        lva_zones = self._find_lva_zones(profile)
        
        # Определяем позицию текущей цены
        current_price = df['close'].iloc[-1]
        position = self._get_price_position(current_price, poc, vah, val)
        
        # Находим ближайшую HVA
        nearest_hva = self._find_nearest_hva(current_price, hva_zones)
        
        # Генерируем рекомендацию
        recommendation, description = self._generate_recommendation(
            current_price, poc, vah, val, hva_zones, lva_zones, position
        )
        
        return VolumeProfileAnalysis(
            poc=poc,
            vah=vah,
            val=val,
            hva_zones=hva_zones,
            lva_zones=lva_zones,
            current_position=position,
            nearest_hva=nearest_hva,
            trade_recommendation=recommendation,
            description=description
        )
    
    def _build_profile(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Строит Volume Profile.
        
        Разбиваем ценовой диапазон на бины и считаем объём в каждом.
        """
        price_min = df['low'].min()
        price_max = df['high'].max()
        
        # Создаём бины
        bins = np.linspace(price_min, price_max, self.num_bins + 1)
        bin_centers = (bins[:-1] + bins[1:]) / 2
        
        # Распределяем объём по бинам
        volumes = np.zeros(self.num_bins)
        
        for _, row in df.iterrows():
            # Упрощение: весь объём свечи распределяем равномерно между low и high
            candle_low = row['low']
            candle_high = row['high']
            candle_volume = row['volume']
            
            # Находим бины, которые покрывает свеча
            for i, (bin_low, bin_high) in enumerate(zip(bins[:-1], bins[1:])):
                # Пересечение свечи с бином
                overlap_low = max(candle_low, bin_low)
                overlap_high = min(candle_high, bin_high)
                
                if overlap_high > overlap_low:
                    # Пропорция объёма для этого бина
                    candle_range = candle_high - candle_low
                    if candle_range > 0:
                        overlap_ratio = (overlap_high - overlap_low) / candle_range
                        volumes[i] += candle_volume * overlap_ratio
        
        # Создаём DataFrame профиля
        profile = pd.DataFrame({
            'price': bin_centers,
            'volume': volumes
        })
        
        profile['volume_percent'] = profile['volume'] / profile['volume'].sum() * 100
        
        return profile
    
    def _find_poc(self, profile: pd.DataFrame) -> float:
        """Находит Point of Control — цену с максимальным объёмом."""
        idx = profile['volume'].idxmax()
        return profile.loc[idx, 'price']
    
    def _find_value_area(self, profile: pd.DataFrame, poc: float) -> Tuple[float, float]:
        """
        Находит Value Area — зону, содержащую 70% объёма.
        
        Начинаем с POC и расширяемся в обе стороны,
        пока не захватим 70% объёма.
        """
        total_volume = profile['volume'].sum()
        target_volume = total_volume * self.value_area_percent
        
        poc_idx = profile[profile['price'] == poc].index[0]
        
        # Начинаем с POC
        included = {poc_idx}
        current_volume = profile.loc[poc_idx, 'volume']
        
        low_idx = poc_idx
        high_idx = poc_idx
        
        while current_volume < target_volume:
            # Смотрим, какой сосед добавит больше объёма
            vol_above = profile.loc[high_idx + 1, 'volume'] if high_idx + 1 < len(profile) else 0
            vol_below = profile.loc[low_idx - 1, 'volume'] if low_idx - 1 >= 0 else 0
            
            if vol_above >= vol_below and high_idx + 1 < len(profile):
                high_idx += 1
                current_volume += vol_above
            elif low_idx - 1 >= 0:
                low_idx -= 1
                current_volume += vol_below
            else:
                break
        
        vah = profile.loc[high_idx, 'price']
        val = profile.loc[low_idx, 'price']
        
        return vah, val
    
    def _find_hva_zones(self, profile: pd.DataFrame, threshold: float = 1.5) -> List[Tuple[float, float]]:
        """
        Находит High Volume Areas — зоны с объёмом выше среднего.
        
        Эти зоны работают как поддержка/сопротивление.
        """
        mean_volume = profile['volume'].mean()
        hva_threshold = mean_volume * threshold
        
        # Находим бины с высоким объёмом
        hva_bins = profile[profile['volume'] >= hva_threshold]
        
        if hva_bins.empty:
            return []
        
        # Группируем смежные бины в зоны
        zones = []
        zone_start = None
        prev_idx = None
        
        for idx in hva_bins.index:
            if zone_start is None:
                zone_start = idx
            elif idx != prev_idx + 1:
                # Зона закончилась
                zones.append((
                    profile.loc[zone_start, 'price'],
                    profile.loc[prev_idx, 'price']
                ))
                zone_start = idx
            prev_idx = idx
        
        # Последняя зона
        if zone_start is not None:
            zones.append((
                profile.loc[zone_start, 'price'],
                profile.loc[prev_idx, 'price']
            ))
        
        return zones
    
    def _find_lva_zones(self, profile: pd.DataFrame, threshold: float = 0.5) -> List[Tuple[float, float]]:
        """
        Находит Low Volume Areas — зоны с низким объёмом.
        
        Цена БЫСТРО проходит через эти зоны — там нет сопротивления.
        """
        mean_volume = profile['volume'].mean()
        lva_threshold = mean_volume * threshold
        
        lva_bins = profile[profile['volume'] <= lva_threshold]
        
        if lva_bins.empty:
            return []
        
        zones = []
        zone_start = None
        prev_idx = None
        
        for idx in lva_bins.index:
            if zone_start is None:
                zone_start = idx
            elif idx != prev_idx + 1:
                zones.append((
                    profile.loc[zone_start, 'price'],
                    profile.loc[prev_idx, 'price']
                ))
                zone_start = idx
            prev_idx = idx
        
        if zone_start is not None:
            zones.append((
                profile.loc[zone_start, 'price'],
                profile.loc[prev_idx, 'price']
            ))
        
        return zones
    
    def _get_price_position(self, price: float, poc: float, vah: float, val: float) -> str:
        """Определяет позицию цены относительно Value Area."""
        if price > vah:
            return "ABOVE_VALUE_AREA"
        elif price < val:
            return "BELOW_VALUE_AREA"
        elif abs(price - poc) / poc < 0.005:  # В пределах 0.5% от POC
            return "AT_POC"
        elif price > poc:
            return "ABOVE_POC"
        else:
            return "BELOW_POC"
    
    def _find_nearest_hva(self, price: float, hva_zones: List[Tuple[float, float]]) -> Optional[float]:
        """Находит ближайшую HVA зону."""
        if not hva_zones:
            return None
        
        nearest = None
        min_distance = float('inf')
        
        for low, high in hva_zones:
            mid = (low + high) / 2
            distance = abs(price - mid)
            if distance < min_distance:
                min_distance = distance
                nearest = mid
        
        return nearest
    
    def _generate_recommendation(
        self, 
        price: float, 
        poc: float, 
        vah: float, 
        val: float,
        hva_zones: List,
        lva_zones: List,
        position: str
    ) -> Tuple[str, str]:
        """Генерирует торговую рекомендацию."""
        
        # Проверяем, в LVA ли мы
        in_lva = any(low <= price <= high for low, high in lva_zones)
        
        if position == "AT_POC":
            return "WAIT", f"Цена на POC ({poc:.2f}). Жди реакцию — может отбиться в любую сторону."
        
        if position == "BELOW_VALUE_AREA":
            if in_lva:
                return "RISKY_LONG", f"Цена в LVA под Value Area. Опасно для лонга — нет поддержки!"
            else:
                return "LONG_OPPORTUNITY", f"Цена под Value Area ({val:.2f}). Лонг на возврат к POC ({poc:.2f})."
        
        if position == "ABOVE_VALUE_AREA":
            if in_lva:
                return "RISKY_SHORT", f"Цена в LVA над Value Area. Опасно для шорта — нет сопротивления!"
            else:
                return "SHORT_OPPORTUNITY", f"Цена над Value Area ({vah:.2f}). Шорт на возврат к POC ({poc:.2f})."
        
        if position == "ABOVE_POC":
            return "NEUTRAL_BULLISH", f"Цена выше POC, но в Value Area. Бычий настрой, но близко к справедливой цене."
        
        if position == "BELOW_POC":
            return "NEUTRAL_BEARISH", f"Цена ниже POC, но в Value Area. Медвежий настрой, но близко к справедливой цене."
        
        return "NEUTRAL", "Нет явной рекомендации."
    
    def _empty_analysis(self) -> VolumeProfileAnalysis:
        """Пустой анализ при ошибке."""
        return VolumeProfileAnalysis(
            poc=0, vah=0, val=0,
            hva_zones=[], lva_zones=[],
            current_position="UNKNOWN",
            nearest_hva=None,
            trade_recommendation="ERROR",
            description="Ошибка получения данных"
        )
    
    def get_profile_report(self, symbol: str = None) -> str:
        """Генерирует визуальный отчёт."""
        analysis = self.analyze(symbol)
        
        current_price = self.data.get_funding_rate(symbol or config.SYMBOL)['last_price']
        
        report = f"""
╔══════════════════════════════════════════════════════════╗
║              VOLUME PROFILE ANALYSIS                     ║
╠══════════════════════════════════════════════════════════╣
║  Current Price:  ${current_price:>10.2f}                         ║
║  POC:            ${analysis.poc:>10.2f}  ← Справедливая цена     ║
║  VAH:            ${analysis.vah:>10.2f}  ← Верх Value Area       ║
║  VAL:            ${analysis.val:>10.2f}  ← Низ Value Area        ║
╠══════════════════════════════════════════════════════════╣
║  Position: {analysis.current_position:<20}                  ║
║  Recommendation: {analysis.trade_recommendation:<15}                 ║
╠══════════════════════════════════════════════════════════╣
║  {analysis.description:<56} ║
╚══════════════════════════════════════════════════════════╝"""
        
        return report
