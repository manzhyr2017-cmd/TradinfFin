"""
Candlestick Pattern Recognition
Uses simple rule-based detection for common patterns.
Integrated with AI Agent for pattern description.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class PatternType(Enum):
    # Bullish patterns
    HAMMER = "hammer"
    BULLISH_ENGULFING = "bullish_engulfing"
    MORNING_STAR = "morning_star"
    PIERCING = "piercing"
    THREE_WHITE_SOLDIERS = "three_white_soldiers"
    
    # Bearish patterns
    SHOOTING_STAR = "shooting_star"
    BEARISH_ENGULFING = "bearish_engulfing"
    EVENING_STAR = "evening_star"
    DARK_CLOUD = "dark_cloud"
    THREE_BLACK_CROWS = "three_black_crows"
    
    # Neutral/Reversal patterns
    DOJI = "doji"
    SPINNING_TOP = "spinning_top"
    INSIDE_BAR = "inside_bar"


@dataclass
class CandlePattern:
    """Detected candlestick pattern"""
    pattern_type: PatternType
    direction: str  # bullish, bearish, neutral
    strength: int   # 1-10
    index: int      # candle index in dataframe
    description: str


class PatternRecognizer:
    """
    Detects candlestick patterns in OHLCV data.
    """
    
    def __init__(self, body_threshold: float = 0.3):
        """
        Args:
            body_threshold: Max body/range ratio for doji
        """
        self.body_threshold = body_threshold
    
    def analyze(self, df: pd.DataFrame, lookback: int = 5) -> List[CandlePattern]:
        """
        Analyze recent candles for patterns.
        
        Args:
            df: DataFrame with columns: open, high, low, close
            lookback: Number of recent candles to analyze
            
        Returns:
            List of detected patterns
        """
        patterns = []
        
        if len(df) < lookback + 3:
            return patterns
        
        # Analyze last N candles
        for i in range(len(df) - lookback, len(df)):
            detected = self._check_patterns(df, i)
            patterns.extend(detected)
        
        return patterns
    
    def _candle_features(self, row) -> Dict:
        """Extract candle features"""
        o, h, l, c = row['open'], row['high'], row['low'], row['close']
        
        body = abs(c - o)
        total_range = h - l if h != l else 0.0001
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        
        return {
            'open': o,
            'high': h,
            'low': l,
            'close': c,
            'body': body,
            'range': total_range,
            'upper_wick': upper_wick,
            'lower_wick': lower_wick,
            'body_ratio': body / total_range,
            'is_bullish': c > o,
            'is_bearish': c < o
        }
    
    def _check_patterns(self, df: pd.DataFrame, idx: int) -> List[CandlePattern]:
        """Check for patterns at given index"""
        patterns = []
        
        if idx < 2:
            return patterns
        
        curr = self._candle_features(df.iloc[idx])
        prev = self._candle_features(df.iloc[idx - 1])
        prev2 = self._candle_features(df.iloc[idx - 2]) if idx >= 2 else None
        
        # === DOJI ===
        if curr['body_ratio'] < self.body_threshold:
            patterns.append(CandlePattern(
                pattern_type=PatternType.DOJI,
                direction='neutral',
                strength=5,
                index=idx,
                description="Doji: Нерешительность рынка. Возможен разворот."
            ))
        
        # === HAMMER (Bullish Reversal) ===
        if (curr['is_bullish'] and 
            curr['lower_wick'] > 2 * curr['body'] and 
            curr['upper_wick'] < curr['body'] * 0.5):
            patterns.append(CandlePattern(
                pattern_type=PatternType.HAMMER,
                direction='bullish',
                strength=7,
                index=idx,
                description="🔨 Молот: Сильный сигнал разворота вверх."
            ))
        
        # === SHOOTING STAR (Bearish Reversal) ===
        if (curr['is_bearish'] and 
            curr['upper_wick'] > 2 * curr['body'] and 
            curr['lower_wick'] < curr['body'] * 0.5):
            patterns.append(CandlePattern(
                pattern_type=PatternType.SHOOTING_STAR,
                direction='bearish',
                strength=7,
                index=idx,
                description="⭐ Падающая звезда: Сигнал разворота вниз."
            ))
        
        # === BULLISH ENGULFING ===
        if (prev['is_bearish'] and curr['is_bullish'] and
            curr['open'] < prev['close'] and curr['close'] > prev['open']):
            patterns.append(CandlePattern(
                pattern_type=PatternType.BULLISH_ENGULFING,
                direction='bullish',
                strength=8,
                index=idx,
                description="🟢 Бычье поглощение: Сильный сигнал покупки!"
            ))
        
        # === BEARISH ENGULFING ===
        if (prev['is_bullish'] and curr['is_bearish'] and
            curr['open'] > prev['close'] and curr['close'] < prev['open']):
            patterns.append(CandlePattern(
                pattern_type=PatternType.BEARISH_ENGULFING,
                direction='bearish',
                strength=8,
                index=idx,
                description="🔴 Медвежье поглощение: Сильный сигнал продажи!"
            ))
        
        # === INSIDE BAR ===
        if (curr['high'] < prev['high'] and curr['low'] > prev['low']):
            patterns.append(CandlePattern(
                pattern_type=PatternType.INSIDE_BAR,
                direction='neutral',
                strength=5,
                index=idx,
                description="📦 Внутренний бар: Консолидация перед движением."
            ))
        
        # === MORNING STAR (3-candle bullish reversal) ===
        if prev2:
            if (prev2['is_bearish'] and 
                prev['body_ratio'] < 0.4 and  # Small body
                curr['is_bullish'] and
                curr['close'] > (prev2['open'] + prev2['close']) / 2):
                patterns.append(CandlePattern(
                    pattern_type=PatternType.MORNING_STAR,
                    direction='bullish',
                    strength=9,
                    index=idx,
                    description="🌟 Утренняя звезда: Очень сильный бычий разворот!"
                ))
            
            # === EVENING STAR (3-candle bearish reversal) ===
            if (prev2['is_bullish'] and 
                prev['body_ratio'] < 0.4 and
                curr['is_bearish'] and
                curr['close'] < (prev2['open'] + prev2['close']) / 2):
                patterns.append(CandlePattern(
                    pattern_type=PatternType.EVENING_STAR,
                    direction='bearish',
                    strength=9,
                    index=idx,
                    description="🌙 Вечерняя звезда: Очень сильный медвежий разворот!"
                ))
        
        return patterns
    
    def get_summary(self, patterns: List[CandlePattern]) -> Dict:
        """Get summary of detected patterns"""
        if not patterns:
            return {"detected": 0, "bias": "neutral", "patterns": []}
        
        bullish = sum(1 for p in patterns if p.direction == 'bullish')
        bearish = sum(1 for p in patterns if p.direction == 'bearish')
        
        if bullish > bearish:
            bias = 'bullish'
        elif bearish > bullish:
            bias = 'bearish'
        else:
            bias = 'neutral'
        
        strongest = max(patterns, key=lambda p: p.strength)
        
        return {
            "detected": len(patterns),
            "bullish": bullish,
            "bearish": bearish,
            "bias": bias,
            "strongest": strongest.pattern_type.value,
            "strongest_desc": strongest.description,
            "patterns": [p.pattern_type.value for p in patterns]
        }


def analyze_candles(df: pd.DataFrame) -> Dict:
    """Quick function for integration"""
    recognizer = PatternRecognizer()
    patterns = recognizer.analyze(df, lookback=5)
    return recognizer.get_summary(patterns)
