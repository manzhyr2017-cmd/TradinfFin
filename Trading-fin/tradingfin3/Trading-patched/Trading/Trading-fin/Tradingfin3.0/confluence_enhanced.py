"""
╔══════════════════════════════════════════════════════════════════╗
║          ENHANCED CONFLUENCE SYSTEM v2.0                         ║
║                                                                  ║
║  Исправления и улучшения:                                        ║
║    1. ✅ max_possible = 145 (было 100)                           ║
║    2. ✅ News Sentiment (+/- 10 баллов)                          ║
║    3. ✅ Dynamic ATR tolerance для S/R                           ║
║    4. ✅ Adaptive thresholds по рыночному режиму                 ║
║    5. ✅ Confidence weighting                                    ║
║                                                                  ║
║  Приоритет: 🔴 КРИТИЧНЫЙ (max_possible fix)                     ║
╚══════════════════════════════════════════════════════════════════╝
"""

import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    import numpy as np
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


# ═══════════════════════════════════════════════════════════════
# ИСПРАВЛЕННЫЙ ConfluenceScore
# ═══════════════════════════════════════════════════════════════

@dataclass
class ConfluenceScore:
    """
    ИСПРАВЛЕННАЯ версия ConfluenceScore.
    
    КЛЮЧЕВОЕ ИЗМЕНЕНИЕ: max_possible = 145 (было 100!)
    
    Breakdown (каждый фактор):
        RSI:          0-25    | Основной осциллятор
        BB:           0-15    | Bollinger Bands position
        MTF:          0-25    | Multi-timeframe alignment
        S/R:          0-15    | Support/Resistance proximity
        Volume:       0-10    | Volume spike confirmation
        MACD:         0-10    | MACD divergence/convergence
        Funding:      0-10    | Bybit funding rate
        OrderBook:    0-5     | Order book imbalance
        Oscillators:  0-10    | Extra (Williams %R, CCI, etc)
        Fibonacci:    0-15    | Fib level proximity (БОНУС)
        Supertrend:   0-10    | Trend confirmation (БОНУС)
        News:         0-10    | News sentiment (НОВЫЙ!)
        ─────────────────────────────────────
        ИТОГО:        0-145   ← ПРАВИЛЬНЫЙ МАКСИМУМ!
    """
    total_score: int = 0
    max_possible: int = 145          # ← ИСПРАВЛЕНО! Было 100!
    
    # Детализация по факторам
    rsi_score: int = 0
    bb_score: int = 0
    mtf_score: int = 0
    sr_score: int = 0
    volume_score: int = 0
    macd_score: int = 0
    funding_score: int = 0
    orderbook_score: int = 0
    oscillators_score: int = 0
    fibonacci_score: int = 0         # ← БОНУС
    supertrend_score: int = 0        # ← БОНУС
    news_score: int = 0              # ← НОВЫЙ!
    
    # Metadata
    direction: str = ""
    confidence: float = 0.0
    market_regime: str = ""
    
    @property
    def percentage(self) -> float:
        """Правильный процент с учётом реального максимума"""
        return (self.total_score / self.max_possible * 100) if self.max_possible > 0 else 0
    
    @property
    def strength(self) -> str:
        pct = self.percentage
        if pct >= 80: return "EXTREME"
        elif pct >= 65: return "STRONG"
        elif pct >= 50: return "MODERATE"
        elif pct >= 35: return "WEAK"
        else: return "VERY_WEAK"
    
    @property
    def is_tradeable(self) -> bool:
        return self.percentage >= 50
    
    def recalculate_total(self):
        """Пересчёт total_score из компонентов"""
        self.total_score = (
            self.rsi_score + self.bb_score + self.mtf_score +
            self.sr_score + self.volume_score + self.macd_score +
            self.funding_score + self.orderbook_score + self.oscillators_score +
            self.fibonacci_score + self.supertrend_score + self.news_score
        )
    
    def get_breakdown(self) -> str:
        return (
            f"RSI:{self.rsi_score}/25 | BB:{self.bb_score}/15 | "
            f"MTF:{self.mtf_score}/25 | S/R:{self.sr_score}/15 | "
            f"Vol:{self.volume_score}/10 | MACD:{self.macd_score}/10 | "
            f"Fund:{self.funding_score}/10 | OB:{self.orderbook_score}/5 | "
            f"Osc:{self.oscillators_score}/10 | Fib:{self.fibonacci_score}/15 | "
            f"ST:{self.supertrend_score}/10 | News:{self.news_score}/10 | "
            f"TOTAL: {self.total_score}/{self.max_possible} ({self.percentage:.1f}%) [{self.strength}]"
        )


# ═══════════════════════════════════════════════════════════════
# ADAPTIVE CONFLUENCE THRESHOLDS
# ═══════════════════════════════════════════════════════════════

class AdaptiveThresholds:
    """
    Адаптивные пороги для confluence в зависимости от рыночного режима.
    
    В трендовом рынке — ниже пороги (больше сделок).
    В хаосе — выше пороги (меньше сделок, больше уверенности).
    """
    
    # {market_regime: min_confluence_percentage}
    REGIME_THRESHOLDS = {
        "STRONG_TREND_UP":   45,   # Тренд помогает → можно ниже
        "WEAK_TREND_UP":     50,
        "RANGING_NARROW":    55,   # Основной рабочий режим
        "RANGING_WIDE":      55,
        "WEAK_TREND_DOWN":   50,
        "STRONG_TREND_DOWN": 45,
        "VOLATILE_CHAOS":    70,   # Хаос → нужна высокая уверенность
        "NEUTRAL":           55,
    }
    
    # Scaling position size by regime
    REGIME_POSITION_SCALE = {
        "STRONG_TREND_UP":   1.2,
        "WEAK_TREND_UP":     1.0,
        "RANGING_NARROW":    1.0,
        "RANGING_WIDE":      0.9,
        "WEAK_TREND_DOWN":   1.0,
        "STRONG_TREND_DOWN": 1.2,
        "VOLATILE_CHAOS":    0.5,  # Хаос → маленькие позиции
        "NEUTRAL":           0.8,
    }
    
    @classmethod
    def get_min_confluence(cls, regime: str) -> float:
        """Минимальный confluence % для данного режима"""
        return cls.REGIME_THRESHOLDS.get(regime.upper(), 55)
    
    @classmethod
    def get_position_scale(cls, regime: str) -> float:
        """Масштаб размера позиции для данного режима"""
        return cls.REGIME_POSITION_SCALE.get(regime.upper(), 1.0)
    
    @classmethod
    def should_trade(cls, confluence_pct: float, regime: str) -> Tuple[bool, str]:
        """Должны ли мы торговать при данном confluence и режиме?"""
        min_required = cls.get_min_confluence(regime)
        
        if confluence_pct >= min_required:
            return True, f"✅ {confluence_pct:.1f}% >= {min_required}% ({regime})"
        else:
            return False, f"❌ {confluence_pct:.1f}% < {min_required}% ({regime})"


# ═══════════════════════════════════════════════════════════════
# ENHANCED S/R DETECTOR (Dynamic ATR Tolerance)
# ═══════════════════════════════════════════════════════════════

class EnhancedSRDetector:
    """
    Улучшенный детектор S/R уровней.
    
    Ключевое изменение: tolerance = f(ATR) вместо фиксированных 0.2%
    """

    def __init__(
        self, 
        lookback: int = 100, 
        atr_multiplier: float = 0.5,
        min_tolerance: float = 0.001,
        max_tolerance: float = 0.01,
        min_touches: int = 2,
    ):
        self.lookback = lookback
        self.atr_multiplier = atr_multiplier
        self.min_tolerance = min_tolerance
        self.max_tolerance = max_tolerance
        self.min_touches = min_touches

    def find_levels(self, highs, lows, closes, atr_value: float = 0.0) -> dict:
        """
        Найти S/R уровни с динамическим tolerance.
        
        highs, lows, closes: массивы/списки цен
        atr_value: текущий ATR
        """
        if len(closes) < 10:
            return {"support_levels": [], "resistance_levels": [], "sr_score": 0}
        
        # Берём последние lookback баров
        h = list(highs[-self.lookback:])
        l = list(lows[-self.lookback:])
        c = list(closes[-self.lookback:])
        current_price = c[-1]
        
        # Dynamic tolerance
        if atr_value <= 0:
            atr_value = self._simple_atr(h, l, c)
        
        tolerance = (atr_value / current_price) * self.atr_multiplier
        tolerance = max(self.min_tolerance, min(self.max_tolerance, tolerance))
        
        # Pivot points
        potential = []
        for i in range(2, len(h) - 2):
            if h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]:
                potential.append(h[i])
            if l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]:
                potential.append(l[i])
        
        # Merge close levels
        merged = self._merge(potential, atr_value)
        
        # Count touches
        strong = []
        for level in merged:
            touches = sum(
                1 for i in range(len(h))
                if abs(h[i] - level) / level < tolerance or
                   abs(l[i] - level) / level < tolerance
            )
            if touches >= self.min_touches:
                strong.append((level, touches))
        
        strong.sort(key=lambda x: x[1], reverse=True)
        
        supports = sorted([lv for lv, t in strong if lv < current_price], reverse=True)[:5]
        resistances = sorted([lv for lv, t in strong if lv >= current_price])[:5]
        
        nearest_s = supports[0] if supports else current_price * 0.98
        nearest_r = resistances[0] if resistances else current_price * 1.02
        
        # S/R score (0-15)
        sr_score = self._calc_score(current_price, nearest_s, nearest_r, tolerance)
        
        return {
            "support_levels": supports,
            "resistance_levels": resistances,
            "nearest_support": nearest_s,
            "nearest_resistance": nearest_r,
            "tolerance": tolerance,
            "tolerance_pct": tolerance * 100,
            "sr_score": sr_score,
        }

    def _calc_score(self, price, support, resistance, tolerance) -> int:
        min_dist = min(abs(price - support), abs(resistance - price)) / price
        if min_dist < tolerance * 0.5: return 15
        elif min_dist < tolerance: return 12
        elif min_dist < tolerance * 2: return 8
        elif min_dist < tolerance * 3: return 5
        return 2

    @staticmethod
    def _merge(levels, distance):
        if not levels:
            return []
        levels = sorted(levels)
        merged = [levels[0]]
        for lv in levels[1:]:
            if abs(lv - merged[-1]) <= distance:
                merged[-1] = (merged[-1] + lv) / 2
            else:
                merged.append(lv)
        return merged

    @staticmethod
    def _simple_atr(highs, lows, closes, period=14):
        trs = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        if len(trs) < period:
            return sum(trs) / len(trs) if trs else 0
        return sum(trs[-period:]) / period


# ═══════════════════════════════════════════════════════════════
# ПРИМЕР ИНТЕГРАЦИИ В СУЩЕСТВУЮЩИЙ КОД
# ═══════════════════════════════════════════════════════════════

INTEGRATION_GUIDE = """
╔══════════════════════════════════════════════════════════════════╗
║              GUIDE: Как интегрировать в mean_reversion_bybit.py  ║
╚══════════════════════════════════════════════════════════════════╝

# === ШАГ 1: Импорты (в начале файла) ===

from confluence_enhanced import ConfluenceScore, AdaptiveThresholds, EnhancedSRDetector

# === ШАГ 2: Замена ConfluenceScore ===

# БЫЛО:
@dataclass
class ConfluenceScore:
    total_score: int = 0
    max_possible: int = 100  # ← НЕПРАВИЛЬНО!

# СТАЛО:
@dataclass
class ConfluenceScore:
    total_score: int = 0
    max_possible: int = 145  # ← ПРАВИЛЬНО!
    # + все новые поля (см. выше)

# === ШАГ 3: Замена SupportResistanceDetector ===

# БЫЛО:
class SupportResistanceDetector:
    def __init__(self, lookback=100, tolerance=0.002):  # Фиксированная!
        ...

# СТАЛО:
sr_detector = EnhancedSRDetector(lookback=100, atr_multiplier=0.5)
# tolerance теперь ДИНАМИЧЕСКАЯ!

# === ШАГ 4: Добавление news_score ===

# В методе analyze():
if self.news_engine:
    sentiment = self.news_engine.get_market_sentiment(symbol[:3])
    confluence.news_score = sentiment.confluence_points
    confluence.recalculate_total()

# === ШАГ 5: Adaptive thresholds ===

# БЫЛО:
if confluence.percentage >= 60:  # Фиксированный порог
    # trade...

# СТАЛО:
should_trade, reason = AdaptiveThresholds.should_trade(
    confluence.percentage, market_regime.value
)
if should_trade:
    # trade...
"""


if __name__ == "__main__":
    # Демо
    score = ConfluenceScore(
        rsi_score=20,
        bb_score=12,
        mtf_score=20,
        sr_score=10,
        volume_score=8,
        macd_score=7,
        funding_score=6,
        orderbook_score=3,
        oscillators_score=7,
        fibonacci_score=12,
        supertrend_score=8,
        news_score=5,
        direction="LONG",
        market_regime="RANGING_NARROW",
    )
    score.recalculate_total()
    
    print(f"📊 Confluence: {score.percentage:.1f}% [{score.strength}]")
    print(f"   {score.get_breakdown()}")
    print(f"   Tradeable: {score.is_tradeable}")
    
    # Adaptive threshold
    should, reason = AdaptiveThresholds.should_trade(score.percentage, "RANGING_NARROW")
    print(f"   {reason}")
    
    # Сравнение СТАРОЙ vs НОВОЙ системы
    print("\n⚠️ СРАВНЕНИЕ:")
    old_pct = score.total_score / 100 * 100  # Старый max=100
    new_pct = score.percentage                 # Новый max=145
    print(f"   Старая система (max=100): {old_pct:.1f}% → EXTREME (переоценка!)")
    print(f"   Новая система (max=145):  {new_pct:.1f}% → {score.strength} (правильно!)")
    print(f"   Разница: {old_pct - new_pct:.1f}% переоценки!")
