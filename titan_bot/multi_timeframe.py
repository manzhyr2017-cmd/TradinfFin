"""
TITAN BOT 2026 - Multi-Timeframe Analysis
Не торгуй против старшего тренда!
"""

import pandas as pd
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import config

class Trend(Enum):
    STRONG_UP = "STRONG_UP"
    UP = "UP"
    NEUTRAL = "NEUTRAL"
    DOWN = "DOWN"
    STRONG_DOWN = "STRONG_DOWN"

@dataclass
class MTFAnalysis:
    """Результат мульти-таймфрейм анализа"""
    htf_trend: Trend          # Старший ТФ (H4)
    mtf_trend: Trend          # Средний ТФ (H1)
    ltf_trend: Trend          # Младший ТФ (M15)
    alignment: str            # 'BULLISH', 'BEARISH', 'MIXED'
    trade_allowed: str        # 'LONG', 'SHORT', 'BOTH', 'NONE'
    confidence: float
    description: str


class MultiTimeframeAnalyzer:
    """
    Анализатор нескольких таймфреймов.
    
    ЗОЛОТОЕ ПРАВИЛО:
    - Определяй тренд на СТАРШЕМ ТФ (H4/D1)
    - Ищи вход на МЛАДШЕМ ТФ (M15)
    - НИКОГДА не торгуй против старшего тренда
    
    Это правило одно может спасти 30% депозита.
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        
        # Таймфреймы для анализа
        self.htf = "240"   # H4 - определяем тренд
        self.mtf = "60"    # H1 - подтверждение
        self.ltf = "15"    # M15 - вход
    
    def analyze(self, symbol: str = None) -> MTFAnalysis:
        """
        Полный мульти-таймфрейм анализ.
        
        Returns:
            MTFAnalysis с рекомендацией что торговать
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем данные по всем ТФ
        htf_data = self.data.get_klines(symbol, interval=self.htf, limit=50)
        mtf_data = self.data.get_klines(symbol, interval=self.mtf, limit=50)
        ltf_data = self.data.get_klines(symbol, interval=self.ltf, limit=50)
        
        if htf_data is None or mtf_data is None or ltf_data is None:
            return self._empty_analysis()
        
        # Определяем тренд на каждом ТФ
        htf_trend = self._determine_trend(htf_data)
        mtf_trend = self._determine_trend(mtf_data)
        ltf_trend = self._determine_trend(ltf_data)
        
        # Определяем согласованность трендов
        alignment = self._check_alignment(htf_trend, mtf_trend, ltf_trend)
        
        # Определяем что можно торговать
        trade_allowed, confidence, description = self._get_trade_permission(
            htf_trend, mtf_trend, ltf_trend, alignment
        )
        
        return MTFAnalysis(
            htf_trend=htf_trend,
            mtf_trend=mtf_trend,
            ltf_trend=ltf_trend,
            alignment=alignment,
            trade_allowed=trade_allowed,
            confidence=confidence,
            description=description
        )
    
    def _determine_trend(self, df: pd.DataFrame) -> Trend:
        """
        Определяет тренд по структуре рынка.
        
        Логика:
        - Higher Highs + Higher Lows = Uptrend
        - Lower Highs + Lower Lows = Downtrend
        - Mixed = Neutral/Range
        """
        if len(df) < 20:
            return Trend.NEUTRAL
        
        # Берём последние 20 свечей
        recent = df.tail(20)
        
        # EMA тренд
        ema_fast = recent['close'].ewm(span=8).mean().iloc[-1]
        ema_slow = recent['close'].ewm(span=21).mean().iloc[-1]
        current_price = recent['close'].iloc[-1]
        
        # Структура: сравниваем текущие хай/лоу с предыдущими
        highs = recent['high'].values
        lows = recent['low'].values
        
        # Считаем Higher Highs и Lower Lows
        hh_count = sum(1 for i in range(1, len(highs)) if highs[i] > highs[i-1])
        ll_count = sum(1 for i in range(1, len(lows)) if lows[i] < lows[i-1])
        
        hh_ratio = hh_count / (len(highs) - 1)
        ll_ratio = ll_count / (len(lows) - 1)
        
        # Сила тренда
        ema_diff_pct = (ema_fast - ema_slow) / ema_slow * 100
        
        # Классификация
        if ema_diff_pct > 1.5 and hh_ratio > 0.6:
            return Trend.STRONG_UP
        elif ema_diff_pct > 0.5 and hh_ratio > 0.5:
            return Trend.UP
        elif ema_diff_pct < -1.5 and ll_ratio > 0.6:
            return Trend.STRONG_DOWN
        elif ema_diff_pct < -0.5 and ll_ratio > 0.5:
            return Trend.DOWN
        else:
            return Trend.NEUTRAL
    
    def _check_alignment(self, htf: Trend, mtf: Trend, ltf: Trend) -> str:
        """Проверяет согласованность трендов."""
        
        bullish_trends = [Trend.STRONG_UP, Trend.UP]
        bearish_trends = [Trend.STRONG_DOWN, Trend.DOWN]
        
        all_bullish = all(t in bullish_trends for t in [htf, mtf])
        all_bearish = all(t in bearish_trends for t in [htf, mtf])
        
        if all_bullish:
            return "BULLISH"
        elif all_bearish:
            return "BEARISH"
        else:
            return "MIXED"
    
    def _get_trade_permission(
        self, 
        htf: Trend, 
        mtf: Trend, 
        ltf: Trend,
        alignment: str
    ) -> tuple:
        """
        Определяет, какие сделки разрешены.
        
        ПРАВИЛА:
        1. Если HTF сильно бычий → только LONG
        2. Если HTF сильно медвежий → только SHORT  
        3. Если тренды согласованы → торгуем по тренду
        4. Если хаос → не торгуем или очень осторожно
        """
        
        # Сильный тренд на старшем ТФ — торгуем только по нему
        if htf == Trend.STRONG_UP:
            return "LONG", 0.9, "H4 в сильном аптренде — только LONG"
        
        if htf == Trend.STRONG_DOWN:
            return "SHORT", 0.9, "H4 в сильном даунтренде — только SHORT"
        
        # Согласованные тренды
        if alignment == "BULLISH":
            return "LONG", 0.8, "Все ТФ бычьи — приоритет LONG"
        
        if alignment == "BEARISH":
            return "SHORT", 0.8, "Все ТФ медвежьи — приоритет SHORT"
        
        # HTF нейтральный, но MTF имеет направление
        if htf == Trend.NEUTRAL:
            if mtf in [Trend.STRONG_UP, Trend.UP]:
                return "LONG", 0.6, "H4 нейтральный, H1 бычий — осторожный LONG"
            elif mtf in [Trend.STRONG_DOWN, Trend.DOWN]:
                return "SHORT", 0.6, "H4 нейтральный, H1 медвежий — осторожный SHORT"
        
        # Конфликт трендов — не торгуем
        if alignment == "MIXED":
            return "NONE", 0.3, "Конфликт таймфреймов — лучше подождать"
        
        return "BOTH", 0.5, "Нет явного направления"
    
    def _empty_analysis(self) -> MTFAnalysis:
        """Пустой анализ при ошибке."""
        return MTFAnalysis(
            htf_trend=Trend.NEUTRAL,
            mtf_trend=Trend.NEUTRAL,
            ltf_trend=Trend.NEUTRAL,
            alignment="MIXED",
            trade_allowed="NONE",
            confidence=0,
            description="Ошибка получения данных"
        )
    
    def get_key_levels(self, symbol: str = None) -> dict:
        """
        Находит ключевые уровни со старшего ТФ.
        Эти уровни важнее, чем уровни с M15!
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        htf_data = self.data.get_klines(symbol, interval=self.htf, limit=100)
        
        if htf_data is None:
            return {}
        
        # Находим значимые хай/лоу на H4
        recent = htf_data.tail(50)
        
        # Локальные экстремумы
        highs = []
        lows = []
        
        for i in range(2, len(recent) - 2):
            if recent['high'].iloc[i] > recent['high'].iloc[i-1] and \
               recent['high'].iloc[i] > recent['high'].iloc[i-2] and \
               recent['high'].iloc[i] > recent['high'].iloc[i+1] and \
               recent['high'].iloc[i] > recent['high'].iloc[i+2]:
                highs.append(recent['high'].iloc[i])
            
            if recent['low'].iloc[i] < recent['low'].iloc[i-1] and \
               recent['low'].iloc[i] < recent['low'].iloc[i-2] and \
               recent['low'].iloc[i] < recent['low'].iloc[i+1] and \
               recent['low'].iloc[i] < recent['low'].iloc[i+2]:
                lows.append(recent['low'].iloc[i])
        
        current_price = recent['close'].iloc[-1]
        
        # Ближайшие уровни
        resistance = [h for h in highs if h > current_price]
        support = [l for l in lows if l < current_price]
        
        return {
            'nearest_resistance': min(resistance) if resistance else None,
            'nearest_support': max(support) if support else None,
            'all_resistance': sorted(resistance)[:3],
            'all_support': sorted(support, reverse=True)[:3]
        }
