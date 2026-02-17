"""
TITAN BOT 2026 - Smart Money Concepts (SMC)
Поиск ликвидности и паттернов институционалов
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum
import config

class SMCSignalType(Enum):
    """Типы SMC сигналов"""
    SFP_LONG = "SFP_LONG"           # Swing Failure Pattern - вход в лонг
    SFP_SHORT = "SFP_SHORT"         # Swing Failure Pattern - вход в шорт
    LIQUIDITY_GRAB_LONG = "LIQ_GRAB_LONG"   # Сбор ликвидности снизу
    LIQUIDITY_GRAB_SHORT = "LIQ_GRAB_SHORT" # Сбор ликвидности сверху
    ORDER_BLOCK_LONG = "OB_LONG"    # Бычий Order Block
    ORDER_BLOCK_SHORT = "OB_SHORT"  # Медвежий Order Block
    NO_SIGNAL = "NO_SIGNAL"

@dataclass
class LiquidityZone:
    """Зона ликвидности (где стоят стопы толпы)"""
    price: float
    type: str  # 'HIGH' или 'LOW'
    strength: int  # Сколько раз тестировался уровень
    timestamp: pd.Timestamp

@dataclass
class SMCSignal:
    """Сигнал Smart Money"""
    signal_type: SMCSignalType
    entry_price: float
    stop_loss: float
    take_profit: float
    liquidity_level: float
    confidence: float
    description: str


class SmartMoneyAnalyzer:
    """
    Анализатор Smart Money Concepts.
    
    Основная идея: Рынок движется от ликвидности к ликвидности.
    Крупные игроки (Smart Money) охотятся за стопами толпы.
    
    Что ищем:
    1. Swing High/Low - локальные экстремумы (там стопы)
    2. SFP (Swing Failure Pattern) - ложный пробой
    3. Liquidity Zones - зоны скопления стопов
    4. Order Blocks - зоны входа институционалов
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        self.liquidity_zones: List[LiquidityZone] = []
        
    def analyze(self, symbol: str = None) -> Optional[SMCSignal]:
        """
        Полный SMC анализ.
        
        Returns:
            SMCSignal если найден паттерн, None если нет
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем свечи
        df = self.data.get_klines(symbol, limit=100)
        if df is None or len(df) < 50:
            return None
        
        # 1. Находим зоны ликвидности
        self._update_liquidity_zones(df)
        
        # 2. Ищем SFP паттерн (главный сигнал)
        sfp_signal = self._detect_sfp(df)
        if sfp_signal:
            return sfp_signal
        
        # 3. Ищем Order Block
        ob_signal = self._detect_order_block(df)
        if ob_signal:
            return ob_signal
        
        return None
    
    def _find_swing_points(self, df: pd.DataFrame, lookback: int = None) -> Tuple[List, List]:
        """
        Находит Swing High и Swing Low.
        
        Swing High = свеча, у которой high выше, чем у N свечей слева И справа.
        Swing Low = свеча, у которой low ниже, чем у N свечей слева И справа.
        
        Это классические точки, где толпа ставит стопы.
        """
        if lookback is None:
            lookback = config.SWING_LOOKBACK
        
        swing_highs = []
        swing_lows = []
        
        # Нам нужны свечи и слева, и справа, поэтому не проверяем края
        for i in range(lookback, len(df) - lookback):
            # Проверяем Swing High
            current_high = df['high'].iloc[i]
            is_swing_high = True
            
            for j in range(1, lookback + 1):
                if df['high'].iloc[i - j] >= current_high or df['high'].iloc[i + j] >= current_high:
                    is_swing_high = False
                    break
            
            if is_swing_high:
                swing_highs.append({
                    'index': i,
                    'price': current_high,
                    'timestamp': df['timestamp'].iloc[i]
                })
            
            # Проверяем Swing Low
            current_low = df['low'].iloc[i]
            is_swing_low = True
            
            for j in range(1, lookback + 1):
                if df['low'].iloc[i - j] <= current_low or df['low'].iloc[i + j] <= current_low:
                    is_swing_low = False
                    break
            
            if is_swing_low:
                swing_lows.append({
                    'index': i,
                    'price': current_low,
                    'timestamp': df['timestamp'].iloc[i]
                })
        
        return swing_highs, swing_lows
    
    def _update_liquidity_zones(self, df: pd.DataFrame):
        """Обновляет зоны ликвидности на основе swing points."""
        swing_highs, swing_lows = self._find_swing_points(df)
        
        self.liquidity_zones = []
        
        # Добавляем зоны из swing lows (там стопы лонгистов)
        for swing in swing_lows[-10:]:  # Последние 10
            self.liquidity_zones.append(LiquidityZone(
                price=swing['price'],
                type='LOW',
                strength=1,
                timestamp=swing['timestamp']
            ))
        
        # Добавляем зоны из swing highs (там стопы шортистов)
        for swing in swing_highs[-10:]:
            self.liquidity_zones.append(LiquidityZone(
                price=swing['price'],
                type='HIGH',
                strength=1,
                timestamp=swing['timestamp']
            ))
    
    def _detect_sfp(self, df: pd.DataFrame) -> Optional[SMCSignal]:
        """
        Детекция Swing Failure Pattern (SFP).
        
        SFP LONG (Бычий):
        - Цена пробивает предыдущий Swing Low (собирает стопы лонгистов)
        - Но закрывается ВЫШЕ этого уровня
        - Это значит: крупный игрок загрузился на стопах толпы
        
        SFP SHORT (Медвежий):
        - Цена пробивает предыдущий Swing High (собирает стопы шортистов)
        - Но закрывается НИЖЕ этого уровня
        """
        swing_highs, swing_lows = self._find_swing_points(df, lookback=5)
        
        if not swing_highs and not swing_lows:
            return None
        
        # Текущая свеча
        current = df.iloc[-1]
        prev = df.iloc[-2]
        atr = df['atr'].iloc[-1]
        
        # === SFP LONG ===
        if swing_lows:
            # Берем ближайший swing low
            recent_low = min(swing_lows[-5:], key=lambda x: x['price']) if len(swing_lows) >= 5 else swing_lows[-1]
            swing_low_price = recent_low['price']
            
            # Условия SFP Long:
            # 1. Текущий low пробил swing low
            # 2. Текущий close ВЫШЕ swing low
            # 3. Свеча бычья или имеет длинную нижнюю тень
            
            pierced = current['low'] < swing_low_price
            closed_above = current['close'] > swing_low_price
            bullish_reaction = current['close'] > current['open'] or current['wick_lower'] > current['body_size']
            
            if pierced and closed_above and bullish_reaction:
                # Нашли SFP Long!
                entry = current['close']
                stop_loss = current['low'] - (atr * 0.5)  # Стоп за хвост + буфер
                risk = entry - stop_loss
                take_profit = entry + (risk * config.MIN_RR_RATIO)
                
                return SMCSignal(
                    signal_type=SMCSignalType.SFP_LONG,
                    entry_price=entry,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    liquidity_level=swing_low_price,
                    confidence=0.75,
                    description=f"SFP Long: Пробили {swing_low_price:.2f}, откупили. Вход: {entry:.2f}"
                )
        
        # === SFP SHORT ===
        if swing_highs:
            recent_high = max(swing_highs[-5:], key=lambda x: x['price']) if len(swing_highs) >= 5 else swing_highs[-1]
            swing_high_price = recent_high['price']
            
            pierced = current['high'] > swing_high_price
            closed_below = current['close'] < swing_high_price
            bearish_reaction = current['close'] < current['open'] or current['wick_upper'] > current['body_size']
            
            if pierced and closed_below and bearish_reaction:
                entry = current['close']
                stop_loss = current['high'] + (atr * 0.5)
                risk = stop_loss - entry
                take_profit = entry - (risk * config.MIN_RR_RATIO)
                
                return SMCSignal(
                    signal_type=SMCSignalType.SFP_SHORT,
                    entry_price=entry,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    liquidity_level=swing_high_price,
                    confidence=0.75,
                    description=f"SFP Short: Пробили {swing_high_price:.2f}, продали. Вход: {entry:.2f}"
                )
        
        return None
    
    def _detect_order_block(self, df: pd.DataFrame) -> Optional[SMCSignal]:
        """
        Детекция Order Block.
        
        Order Block - это последняя противоположная свеча перед сильным движением.
        Логика: Институционал не может загрузить всю позицию сразу.
        Он оставляет "незаполненные ордера" в зоне Order Block.
        Когда цена возвращается - он доливает позицию.
        
        Bullish OB: Последняя медвежья свеча перед сильным ростом
        Bearish OB: Последняя бычья свеча перед сильным падением
        """
        atr = df['atr'].iloc[-1]
        
        # Ищем сильное движение за последние 20 свечей
        for i in range(-20, -5):
            # Проверяем, было ли сильное движение вверх
            move_up = (df['close'].iloc[i+3] - df['low'].iloc[i]) / df['low'].iloc[i]
            
            if move_up > 0.02:  # Движение больше 2%
                # Ищем последнюю медвежью свечу перед движением
                for j in range(i, i-5, -1):
                    if j < -len(df):
                        break
                    if not df['is_bullish'].iloc[j]:  # Медвежья свеча
                        ob_high = df['high'].iloc[j]
                        ob_low = df['low'].iloc[j]
                        current_price = df['close'].iloc[-1]
                        
                        # Цена вернулась в зону OB?
                        if ob_low <= current_price <= ob_high:
                            entry = current_price
                            stop_loss = ob_low - (atr * 0.3)
                            risk = entry - stop_loss
                            take_profit = entry + (risk * config.MIN_RR_RATIO)
                            
                            return SMCSignal(
                                signal_type=SMCSignalType.ORDER_BLOCK_LONG,
                                entry_price=entry,
                                stop_loss=stop_loss,
                                take_profit=take_profit,
                                liquidity_level=ob_low,
                                confidence=0.65,
                                description=f"Bullish OB: Цена в зоне {ob_low:.2f}-{ob_high:.2f}"
                            )
                        break
        
        return None
    
    def get_nearest_liquidity(self, current_price: float, direction: str = 'both') -> List[LiquidityZone]:
        """
        Возвращает ближайшие зоны ликвидности.
        
        Args:
            current_price: Текущая цена
            direction: 'above', 'below', или 'both'
        """
        zones = []
        
        for zone in self.liquidity_zones:
            if direction == 'above' and zone.price > current_price:
                zones.append(zone)
            elif direction == 'below' and zone.price < current_price:
                zones.append(zone)
            elif direction == 'both':
                zones.append(zone)
        
        # Сортируем по близости к текущей цене
        zones.sort(key=lambda x: abs(x.price - current_price))
        
        return zones[:5]  # Топ 5 ближайших
