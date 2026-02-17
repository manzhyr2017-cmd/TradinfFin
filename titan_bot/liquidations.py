"""
TITAN BOT 2026 - Liquidation Levels
Где маркет-мейкер будет охотиться?
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Optional
import config

@dataclass
class LiquidationLevel:
    """Уровень ликвидации"""
    price: float
    estimated_volume: float  # Примерный объём ликвидаций
    type: str               # 'LONG' или 'SHORT'
    leverage: int           # Плечо (5x, 10x, 25x, etc.)
    distance_percent: float # Расстояние от текущей цены

@dataclass  
class LiquidationMap:
    """Карта ликвидаций"""
    current_price: float
    long_liquidations: List[LiquidationLevel]
    short_liquidations: List[LiquidationLevel]
    nearest_long_liq: Optional[LiquidationLevel]
    nearest_short_liq: Optional[LiquidationLevel]
    magnet_direction: str  # Куда "притягивается" цена


class LiquidationAnalyzer:
    """
    Анализатор уровней ликвидаций.
    
    ПОЧЕМУ ЭТО CRITICAL:
    
    Ликвидация = принудительное закрытие позиции биржей.
    
    Когда цена достигает уровня ликвидации:
    - Позиции закрываются РЫНОЧНЫМИ ордерами
    - Это создаёт каскадный эффект
    - Цена "пробивает" уровень с ускорением
    
    Маркет-мейкеры ЗНАЮТ где эти уровни и СПЕЦИАЛЬНО ведут туда цену!
    
    Формула ликвидации для лонга:
    Liq Price = Entry × (1 - 1/Leverage + Maintenance Margin)
    
    Для 10x лонга от 2000$:
    Liq ≈ 2000 × (1 - 0.1) = 1800$ (-10%)
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        
        # Стандартные плечи на Bybit
        self.leverage_levels = [5, 10, 25, 50, 100]
        
        # Maintenance margin (примерно)
        self.maintenance_margin = 0.005  # 0.5%
    
    def analyze(self, symbol: str = None) -> LiquidationMap:
        """
        Строит карту ликвидаций.
        
        Мы не знаем ТОЧНО где стоят позиции, но можем ОЦЕНИТЬ
        на основе недавних свингов и популярных плечей.
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем текущую цену
        ticker = self.data.get_funding_rate(symbol)
        if not ticker:
            return self._empty_map()
        
        current_price = ticker['last_price']
        
        # Получаем недавние свинги (там вероятно входили трейдеры)
        df = self.data.get_klines(symbol, limit=100)
        if df is None:
            return self._empty_map()
        
        entry_zones = self._find_likely_entry_zones(df)
        
        # Рассчитываем уровни ликвидаций для каждой зоны входа
        long_liqs = []
        short_liqs = []
        
        for zone in entry_zones:
            for leverage in self.leverage_levels:
                # Ликвидация лонгов (ниже цены входа)
                long_liq_price = self._calc_long_liquidation(zone['price'], leverage)
                
                if long_liq_price < current_price:
                    distance = (current_price - long_liq_price) / current_price * 100
                    
                    long_liqs.append(LiquidationLevel(
                        price=long_liq_price,
                        estimated_volume=zone['volume'] / leverage,
                        type='LONG',
                        leverage=leverage,
                        distance_percent=distance
                    ))
                
                # Ликвидация шортов (выше цены входа)
                short_liq_price = self._calc_short_liquidation(zone['price'], leverage)
                
                if short_liq_price > current_price:
                    distance = (short_liq_price - current_price) / current_price * 100
                    
                    short_liqs.append(LiquidationLevel(
                        price=short_liq_price,
                        estimated_volume=zone['volume'] / leverage,
                        type='SHORT',
                        leverage=leverage,
                        distance_percent=distance
                    ))
        
        # Группируем близкие уровни
        long_liqs = self._cluster_levels(long_liqs)
        short_liqs = self._cluster_levels(short_liqs)
        
        # Сортируем по близости к текущей цене
        long_liqs.sort(key=lambda x: x.distance_percent)
        short_liqs.sort(key=lambda x: x.distance_percent)
        
        # Определяем направление "магнита"
        magnet = self._determine_magnet(long_liqs, short_liqs, current_price)
        
        return LiquidationMap(
            current_price=current_price,
            long_liquidations=long_liqs[:10],
            short_liquidations=short_liqs[:10],
            nearest_long_liq=long_liqs[0] if long_liqs else None,
            nearest_short_liq=short_liqs[0] if short_liqs else None,
            magnet_direction=magnet
        )
    
    def _find_likely_entry_zones(self, df: pd.DataFrame) -> List[dict]:
        """
        Находит зоны, где вероятно входили трейдеры.
        
        Признаки:
        1. Высокий объём
        2. Swing points
        3. Круглые числа
        """
        zones = []
        
        # Зоны высокого объёма
        volume_mean = df['volume'].mean()
        high_volume_candles = df[df['volume'] > volume_mean * 1.5]
        
        for _, candle in high_volume_candles.iterrows():
            zones.append({
                'price': (candle['high'] + candle['low']) / 2,
                'volume': candle['volume'],
                'type': 'HIGH_VOLUME'
            })
        
        # Swing points
        for i in range(5, len(df) - 5):
            # Swing High
            if df['high'].iloc[i] == df['high'].iloc[i-5:i+6].max():
                zones.append({
                    'price': df['high'].iloc[i],
                    'volume': df['volume'].iloc[i],
                    'type': 'SWING_HIGH'
                })
            
            # Swing Low
            if df['low'].iloc[i] == df['low'].iloc[i-5:i+6].min():
                zones.append({
                    'price': df['low'].iloc[i],
                    'volume': df['volume'].iloc[i],
                    'type': 'SWING_LOW'
                })
        
        return zones
    
    def _calc_long_liquidation(self, entry_price: float, leverage: int) -> float:
        """
        Рассчитывает цену ликвидации для лонга.
        
        Liq = Entry × (1 - 1/Leverage + MM)
        """
        return entry_price * (1 - 1/leverage + self.maintenance_margin)
    
    def _calc_short_liquidation(self, entry_price: float, leverage: int) -> float:
        """
        Рассчитывает цену ликвидации для шорта.
        
        Liq = Entry × (1 + 1/Leverage - MM)
        """
        return entry_price * (1 + 1/leverage - self.maintenance_margin)
    
    def _cluster_levels(self, levels: List[LiquidationLevel], threshold: float = 0.5) -> List[LiquidationLevel]:
        """
        Группирует близкие уровни ликвидаций.
        
        Если уровни ближе чем threshold% — объединяем.
        """
        if not levels:
            return []
        
        levels.sort(key=lambda x: x.price)
        clustered = []
        
        current_cluster = [levels[0]]
        
        for level in levels[1:]:
            last_price = current_cluster[-1].price
            
            if abs(level.price - last_price) / last_price * 100 < threshold:
                current_cluster.append(level)
            else:
                # Завершаем кластер
                avg_price = sum(l.price for l in current_cluster) / len(current_cluster)
                total_volume = sum(l.estimated_volume for l in current_cluster)
                
                clustered.append(LiquidationLevel(
                    price=avg_price,
                    estimated_volume=total_volume,
                    type=current_cluster[0].type,
                    leverage=current_cluster[0].leverage,
                    distance_percent=current_cluster[0].distance_percent
                ))
                
                current_cluster = [level]
        
        # Последний кластер
        if current_cluster:
            avg_price = sum(l.price for l in current_cluster) / len(current_cluster)
            total_volume = sum(l.estimated_volume for l in current_cluster)
            
            clustered.append(LiquidationLevel(
                price=avg_price,
                estimated_volume=total_volume,
                type=current_cluster[0].type,
                leverage=current_cluster[0].leverage,
                distance_percent=current_cluster[0].distance_percent
            ))
        
        return clustered
    
    def _determine_magnet(
        self, 
        long_liqs: List[LiquidationLevel],
        short_liqs: List[LiquidationLevel],
        current_price: float
    ) -> str:
        """
        Определяет, куда "притягивается" цена.
        
        Цена идёт туда, где БОЛЬШЕ ликвидности (ликвидаций).
        Маркет-мейкер хочет собрать максимум.
        """
        long_volume = sum(l.estimated_volume for l in long_liqs[:3]) if long_liqs else 0
        short_volume = sum(l.estimated_volume for l in short_liqs[:3]) if short_liqs else 0
        
        # Учитываем близость
        if long_liqs and long_liqs[0].distance_percent < 2:
            long_volume *= 2  # Ближние уровни важнее
        if short_liqs and short_liqs[0].distance_percent < 2:
            short_volume *= 2
        
        if long_volume > short_volume * 1.5:
            return "DOWN"  # Много лонг-ликвидаций внизу — магнит вниз
        elif short_volume > long_volume * 1.5:
            return "UP"    # Много шорт-ликвидаций вверху — магнит вверх
        else:
            return "NEUTRAL"
    
    def _empty_map(self) -> LiquidationMap:
        """Пустая карта при ошибке."""
        return LiquidationMap(
            current_price=0,
            long_liquidations=[],
            short_liquidations=[],
            nearest_long_liq=None,
            nearest_short_liq=None,
            magnet_direction="NEUTRAL"
        )
    
    def get_liquidation_report(self, symbol: str = None) -> str:
        """Генерирует отчёт о ликвидациях."""
        liq_map = self.analyze(symbol)
        
        report = f"""
╔══════════════════════════════════════════════════════════╗
║             LIQUIDATION HEATMAP                          ║
╠══════════════════════════════════════════════════════════╣
║  Current Price: ${liq_map.current_price:.2f}                          
║  Magnet Direction: {liq_map.magnet_direction}                            
╠══════════════════════════════════════════════════════════╣
║  LONG LIQUIDATIONS (below price):                        ║"""
        
        for liq in liq_map.long_liquidations[:5]:
            report += f"\n║    ${liq.price:.2f} ({liq.distance_percent:.1f}% away) - {liq.leverage}x"
        
        report += """
╠══════════════════════════════════════════════════════════╣
║  SHORT LIQUIDATIONS (above price):                       ║"""
        
        for liq in liq_map.short_liquidations[:5]:
            report += f"\n║    ${liq.price:.2f} ({liq.distance_percent:.1f}% away) - {liq.leverage}x"
        
        report += """
╚══════════════════════════════════════════════════════════╝"""
        
        return report
