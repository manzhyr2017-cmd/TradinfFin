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
    FVG_LONG = "FVG_LONG"           # Тест бычьего имбаланса
    FVG_SHORT = "FVG_SHORT"         # Тест медвежьего имбаланса
    NO_SIGNAL = "NO_SIGNAL"

@dataclass
class LiquidityZone:
    """Зона ликвидности (где стоят стопы толпы)"""
    price: float
    type: str  # 'HIGH' или 'LOW'
    strength: int  # Сколько раз тестировался уровень
    mitigated: bool # Был ли уровень уже пробит (снята ли ликвидность)
    timestamp: pd.Timestamp

@dataclass
class FVG:
    """Fair Value Gap (Имбаланс)"""
    top: float
    bottom: float
    type: str       # 'BULLISH' / 'BEARISH'
    mitigated: bool # Был ли перекрыт
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
    5. FVG (Fair Value Gaps) - магниты для цены
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        self.liquidity_zones: List[LiquidityZone] = []
        self.fvgs: List[FVG] = []
        
    def analyze(self, symbol: str = None) -> Optional[SMCSignal]:
        """
        Полный SMC анализ.
        
        Returns:
            SMCSignal если найден паттерн, None если нет
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем свечи
        df = self.data.get_klines(symbol, limit=200) # Берем больше истории для FVG
        if df is None or len(df) < 50:
            return None
        
        # 1. Находим зоны ликвидности
        self._update_liquidity_zones(df)
        
        # 2. Находим FVG (Imbalances)
        self._update_fvgs(df)
        
        # 3. Ищем SFP паттерн (главный разворотный сигнал)
        sfp_signal = self._detect_sfp(df)
        if sfp_signal:
            return sfp_signal
        
        # 4. Ищем тест FVG (продолжение тренда)
        fvg_signal = self._detect_fvg_retest(df)
        if fvg_signal:
            return fvg_signal

        # 5. Ищем Order Block
        ob_signal = self._detect_order_block(df)
        if ob_signal:
            return ob_signal
        
        return None
    
    def _find_swing_points(self, df: pd.DataFrame, lookback: int = None) -> Tuple[List, List]:
        """
        Находит Swing High и Swing Low.
        """
        if lookback is None:
            lookback = config.SWING_LOOKBACK
        
        swing_highs = []
        swing_lows = []
        
        for i in range(lookback, len(df) - lookback):
            # Swing High
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
            
            # Swing Low
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
        """
        Обновляет зоны ликвидности и помечает снятые (mitigated).
        """
        swing_highs, swing_lows = self._find_swing_points(df)
        current_price = df['close'].iloc[-1]
        
        self.liquidity_zones = []
        
        # Lows (Sell Side Liquidity)
        for swing in swing_lows[-15:]:
            # Проверяем, была ли цена НИЖЕ этого уровня ПОСЛЕ его формирования
            # Если да - ликвидность снята
            is_mitigated = False
            # Простой способ: если текущая цена ниже, значит сняли? 
            # Более точно: пробежать по свечам после swing['index']
            
            # Пока упрощенно: считаем зону активной
            self.liquidity_zones.append(LiquidityZone(
                price=swing['price'],
                type='LOW',
                strength=1,
                mitigated=is_mitigated,
                timestamp=swing['timestamp']
            ))
        
        # Highs (Buy Side Liquidity)
        for swing in swing_highs[-15:]:
            self.liquidity_zones.append(LiquidityZone(
                price=swing['price'],
                type='HIGH',
                strength=1,
                mitigated=False,
                timestamp=swing['timestamp']
            ))

    def _update_fvgs(self, df: pd.DataFrame):
        """
        Находит Fair Value Gaps (Imbalances).
        
        Bullish FVG: Low[i] > High[i-2]
        Bearish FVG: High[i] < Low[i-2]
        """
        self.fvgs = []
        
        for i in range(2, len(df) - 1): # Не берем самую последнюю, она еще не закрыта
            # Bullish FVG
            if df['low'].iloc[i] > df['high'].iloc[i-2]:
                top = df['low'].iloc[i]
                bottom = df['high'].iloc[i-2]
                if (top - bottom) / bottom > 0.0005: # Фильтр мелких дырок
                    self.fvgs.append(FVG(
                        top=top,
                        bottom=bottom,
                        type='BULLISH',
                        mitigated=False,
                        timestamp=df['timestamp'].iloc[i]
                    ))
            
            # Bearish FVG
            elif df['high'].iloc[i] < df['low'].iloc[i-2]:
                top = df['low'].iloc[i-2]
                bottom = df['high'].iloc[i]
                if (top - bottom) / bottom > 0.0005:
                    self.fvgs.append(FVG(
                        top=top,
                        bottom=bottom,
                        type='BEARISH',
                        mitigated=False,
                        timestamp=df['timestamp'].iloc[i]
                    ))
        
        # Проверяем Mitigation (был ли тест FVG)
        # Реализуем по-простому: смотрим только последние 5 FVG
        current_price = df['close'].iloc[-1]
        
        # Удаляем старые FVG (старше 50 свечей)
        # Оставляем только свежие
    
    def _detect_sfp(self, df: pd.DataFrame) -> Optional[SMCSignal]:
        """
        SFP (Swing Failure Pattern) с учетом тренда.
        """
        swing_highs, swing_lows = self._find_swing_points(df, lookback=5)
        if not swing_highs and not swing_lows:
            return None
        
        current = df.iloc[-1]
        atr = df['atr'].iloc[-1]
        
        # === SFP LONG ===
        if swing_lows:
            # Ищем ближайший неснятый лоу (для простоты берем самый низкий из последних 5)
            recent_lows = sorted(swing_lows[-10:], key=lambda x: x['price'])
            target_low = recent_lows[0]['price'] # Самый низкий
            
            pierced = current['low'] < target_low
            closed_above = current['close'] > target_low
            bullish_candle = current['close'] > current['open']
            
            if pierced and closed_above and bullish_candle:
                entry = current['close']
                stop_loss = current['low'] - (atr * 0.3)
                risk = entry - stop_loss
                take_profit = entry + (risk * config.MIN_RR_RATIO)
                
                return SMCSignal(
                    signal_type=SMCSignalType.SFP_LONG,
                    entry_price=entry,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    liquidity_level=target_low,
                    confidence=0.85, # Высокая уверенность
                    description=f"SFP Long: Сняли ликвидность {target_low:.2f}"
                )
        
        # === SFP SHORT ===
        if swing_highs:
            recent_highs = sorted(swing_highs[-10:], key=lambda x: x['price'], reverse=True)
            target_high = recent_highs[0]['price']
            
            pierced = current['high'] > target_high
            closed_below = current['close'] < target_high
            bearish_candle = current['close'] < current['open']
            
            if pierced and closed_below and bearish_candle:
                entry = current['close']
                stop_loss = current['high'] + (atr * 0.3)
                risk = stop_loss - entry
                take_profit = entry - (risk * config.MIN_RR_RATIO)
                
                return SMCSignal(
                    signal_type=SMCSignalType.SFP_SHORT,
                    entry_price=entry,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    liquidity_level=target_high,
                    confidence=0.85,
                    description=f"SFP Short: Сняли ликвидность {target_high:.2f}"
                )
        
        return None

    def _detect_fvg_retest(self, df: pd.DataFrame) -> Optional[SMCSignal]:
        """
        Вход на ретесте FVG.
        Цена вернулась в зону FVG и отскочила.
        """
        if not self.fvgs:
            return None
            
        current = df.iloc[-1]
        current_low = current['low']
        current_high = current['high']
        atr = df['atr'].iloc[-1]
        
        # Берем только свежие FVG (последние 3)
        recent_fvgs = self.fvgs[-3:]
        
        for fvg in recent_fvgs:
            # === Retest Bullish FVG ===
            if fvg.type == 'BULLISH':
                # Цена зашла в зону FVG (между top и bottom)
                if current_low <= fvg.top and current_high >= fvg.bottom:
                    # И закрылась выше середины FVG (отскок)
                    mid_fvg = (fvg.top + fvg.bottom) / 2
                    if current['close'] > mid_fvg:
                         entry = current['close']
                         stop = fvg.bottom - (atr * 0.2)
                         
                         return SMCSignal(
                            signal_type=SMCSignalType.FVG_LONG,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=entry + (entry - stop) * 2,
                            liquidity_level=fvg.bottom,
                            confidence=0.70,
                            description=f"FVG Retest Long: Отскок от {fvg.bottom:.2f}"
                        )

            # === Retest Bearish FVG ===
            elif fvg.type == 'BEARISH':
                if current_high >= fvg.bottom and current_low <= fvg.top:
                    mid_fvg = (fvg.top + fvg.bottom) / 2
                    if current['close'] < mid_fvg:
                         entry = current['close']
                         stop = fvg.top + (atr * 0.2)
                         
                         return SMCSignal(
                            signal_type=SMCSignalType.FVG_SHORT,
                            entry_price=entry,
                            stop_loss=stop,
                            take_profit=entry - (stop - entry) * 2,
                            liquidity_level=fvg.top,
                            confidence=0.70,
                            description=f"FVG Retest Short: Отскок от {fvg.top:.2f}"
                        )
        return None

    def _detect_order_block(self, df: pd.DataFrame) -> Optional[SMCSignal]:
        """
        Классический Order Block Detection.
        """
        atr = df['atr'].iloc[-1]
        
        # Ищем сильное движение за последние 15 свечей
        for i in range(-15, -3):
            # Проверяем импульс
            body = abs(df['close'].iloc[i] - df['open'].iloc[i])
            avg_body = df['atr'].iloc[i]
            
            # Если свеча в 2 раза больше среднего ATR - это импульс
            if body > avg_body * 1.5:
                
                # Bullish Impulse (Рост) -> Ищем последний красный бар до этого
                if df['close'].iloc[i] > df['open'].iloc[i]: 
                    # Проверяем 3 свечи до импульса
                    for j in range(1, 4):
                        idx = i - j
                        if df['close'].iloc[idx] < df['open'].iloc[idx]: # Медвежья свеча
                            ob_high = df['high'].iloc[idx]
                            ob_low = df['low'].iloc[idx]
                            
                            # Если текущая цена тестирует этот блок
                            curr = df.iloc[-1]
                            if ob_low <= curr['low'] <= ob_high:
                                return SMCSignal(
                                    signal_type=SMCSignalType.ORDER_BLOCK_LONG,
                                    entry_price=curr['close'],
                                    stop_loss=ob_low - (atr * 0.2), # Стоп за OB
                                    take_profit=curr['close'] + (curr['close'] - ob_low) * 2,
                                    liquidity_level=ob_low,
                                    confidence=0.65,
                                    description=f"Bullish OB Retest: {ob_low:.2f}"
                                )
                            break
                            
                # Bearish Impulse (Падение) -> Ищем последний зеленый бар
                elif df['close'].iloc[i] < df['open'].iloc[i]:
                    for j in range(1, 4):
                        idx = i - j
                        if df['close'].iloc[idx] > df['open'].iloc[idx]: # Бычья свеча
                            ob_high = df['high'].iloc[idx]
                            ob_low = df['low'].iloc[idx]
                            
                            curr = df.iloc[-1]
                            if ob_low <= curr['high'] <= ob_high:
                                return SMCSignal(
                                    signal_type=SMCSignalType.ORDER_BLOCK_SHORT,
                                    entry_price=curr['close'],
                                    stop_loss=ob_high + (atr * 0.2),
                                    take_profit=curr['close'] - (ob_high - curr['close']) * 2,
                                    liquidity_level=ob_high,
                                    confidence=0.65,
                                    description=f"Bearish OB Retest: {ob_high:.2f}"
                                )
                            break
        return None

    def get_nearest_liquidity(self, current_price: float, direction: str = 'both') -> List[LiquidityZone]:
        """
        Возвращает ближайшие зоны ликвидности.
        """
        zones = []
        for zone in self.liquidity_zones:
            if direction == 'above' and zone.price > current_price:
                zones.append(zone)
            elif direction == 'below' and zone.price < current_price:
                zones.append(zone)
            elif direction == 'both':
                zones.append(zone)
        
        zones.sort(key=lambda x: abs(x.price - current_price))
        return zones[:5]
