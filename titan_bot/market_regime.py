"""
TITAN BOT 2026 - Market Regime Detection
Разные режимы = разные стратегии
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
import config

class MarketRegime(Enum):
    TRENDING_UP = "TRENDING_UP"       # Сильный тренд вверх
    TRENDING_DOWN = "TRENDING_DOWN"   # Сильный тренд вниз
    RANGING = "RANGING"               # Боковик/флэт
    VOLATILE = "VOLATILE"             # Высокая волатильность, хаос
    QUIET = "QUIET"                   # Низкая волатильность, затишье

@dataclass
class RegimeAnalysis:
    """Результат анализа режима"""
    regime: MarketRegime
    volatility_percentile: float  # 0-100, где текущая волатильность
    adr_percent: float            # Average Daily Range в %
    recommended_strategy: str
    position_size_multiplier: float  # Корректировка размера позиции
    description: str


class MarketRegimeDetector:
    """
    Детектор режима рынка.
    
    ПОЧЕМУ ЭТО КРИТИЧНО:
    - В тренде работают пробои и откаты
    - В флэте работает Mean Reversion (от границ)
    - В хаосе лучше не торговать вообще
    
    Использование одной стратегии везде = слив.
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
    
    def analyze(self, symbol: str = None) -> RegimeAnalysis:
        """
        Определяет текущий режим рынка.
        
        Методы определения:
        1. ADX — сила тренда
        2. ATR Percentile — уровень волатильности
        3. Bollinger Band Width — сжатие/расширение
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        df = self.data.get_klines(symbol, limit=100)
        
        if df is None or len(df) < 50:
            return self._empty_analysis()
        
        # 1. Рассчитываем ADX (сила тренда)
        adx = self._calculate_adx(df)
        
        # 2. Волатильность (ATR percentile)
        atr_percentile = self._calculate_atr_percentile(df)
        
        # 3. Bollinger Band Width
        bb_width = self._calculate_bb_width(df)
        
        # 4. Average Daily Range
        adr = self._calculate_adr(df)
        
        # 5. Направление тренда
        trend_direction = self._get_trend_direction(df)
        
        # Определяем режим
        regime = self._classify_regime(adx, atr_percentile, bb_width, trend_direction)
        
        # Рекомендации
        strategy, size_mult, description = self._get_recommendations(regime, atr_percentile)
        
        return RegimeAnalysis(
            regime=regime,
            volatility_percentile=atr_percentile,
            adr_percent=adr,
            recommended_strategy=strategy,
            position_size_multiplier=size_mult,
            description=description
        )
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """
        Рассчитывает ADX (Average Directional Index).
        
        ADX > 25 = тренд
        ADX < 20 = флэт
        """
        high = df['high']
        low = df['low']
        close = df['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        # Smoothed
        atr = pd.Series(tr).rolling(period).mean()
        plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / atr
        minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / atr
        
        # ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(period).mean()
        
        return adx.iloc[-1] if not pd.isna(adx.iloc[-1]) else 0
    
    def _calculate_atr_percentile(self, df: pd.DataFrame) -> float:
        """
        Определяет, где текущая волатильность относительно истории.
        
        90+ percentile = экстремальная волатильность
        10- percentile = затишье перед бурей
        """
        atr = df['atr'].dropna()
        
        if len(atr) < 20:
            return 50
        
        current_atr = atr.iloc[-1]
        percentile = (atr < current_atr).sum() / len(atr) * 100
        
        return percentile
    
    def _calculate_bb_width(self, df: pd.DataFrame, period: int = 20) -> float:
        """
        Bollinger Band Width — мера волатильности.
        
        Сжатие (низкий width) = скоро будет движение
        Расширение = движение уже идёт
        """
        close = df['close']
        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        
        upper = sma + 2 * std
        lower = sma - 2 * std
        
        width = (upper - lower) / sma * 100  # В процентах
        
        return width.iloc[-1] if not pd.isna(width.iloc[-1]) else 0
    
    def _calculate_adr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Average Daily Range в процентах."""
        daily_range = (df['high'] - df['low']) / df['close'] * 100
        return daily_range.rolling(period).mean().iloc[-1]
    
    def _get_trend_direction(self, df: pd.DataFrame) -> str:
        """Направление тренда по EMA."""
        ema_20 = df['close'].ewm(span=20).mean().iloc[-1]
        ema_50 = df['close'].ewm(span=50).mean().iloc[-1]
        
        if ema_20 > ema_50 * 1.01:
            return "UP"
        elif ema_20 < ema_50 * 0.99:
            return "DOWN"
        else:
            return "FLAT"
    
    def _classify_regime(
        self, 
        adx: float, 
        atr_pct: float, 
        bb_width: float,
        trend: str
    ) -> MarketRegime:
        """Классификация режима рынка."""
        
        # Высокая волатильность + нет тренда = хаос
        if atr_pct > 80 and adx < 20:
            return MarketRegime.VOLATILE
        
        # Низкая волатильность = затишье
        if atr_pct < 20 and bb_width < 2:
            return MarketRegime.QUIET
        
        # Сильный тренд
        if adx > 30:
            if trend == "UP":
                return MarketRegime.TRENDING_UP
            elif trend == "DOWN":
                return MarketRegime.TRENDING_DOWN
        
        # Средний тренд
        if adx > 20:
            if trend == "UP":
                return MarketRegime.TRENDING_UP
            elif trend == "DOWN":
                return MarketRegime.TRENDING_DOWN
        
        # По умолчанию — боковик
        return MarketRegime.RANGING
    
    def _get_recommendations(
        self, 
        regime: MarketRegime, 
        vol_pct: float
    ) -> tuple:
        """Рекомендации по торговле для режима."""
        
        recommendations = {
            MarketRegime.TRENDING_UP: (
                "TREND_FOLLOWING",
                1.0,
                "🟢 Тренд вверх. Торгуй откаты, покупай SFP на поддержках."
            ),
            MarketRegime.TRENDING_DOWN: (
                "TREND_FOLLOWING",
                1.0,
                "🔴 Тренд вниз. Шортуй откаты, продавай SFP на сопротивлениях."
            ),
            MarketRegime.RANGING: (
                "MEAN_REVERSION",
                0.7,
                "🟡 Боковик. Торгуй от границ диапазона. Меньше размер позиции."
            ),
            MarketRegime.VOLATILE: (
                "AVOID",
                0.3,
                "🔥 Высокая волатильность. Очень маленькие позиции или пропуск."
            ),
            MarketRegime.QUIET: (
                "WAIT_BREAKOUT",
                0.5,
                "😴 Затишье. Жди пробой. Можно готовить отложки."
            )
        }
        
        return recommendations.get(regime, ("UNKNOWN", 1.0, ""))
    
    def _empty_analysis(self) -> RegimeAnalysis:
        """Пустой анализ при ошибке."""
        return RegimeAnalysis(
            regime=MarketRegime.VOLATILE,
            volatility_percentile=50,
            adr_percent=0,
            recommended_strategy="AVOID",
            position_size_multiplier=0.5,
            description="Ошибка получения данных"
        )
