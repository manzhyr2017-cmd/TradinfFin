import logging
import pandas as pd
import numpy as np
from decimal import Decimal
from dataclasses import dataclass
from typing import List

log = logging.getLogger("TechnicalAnalyzer")

@dataclass
class IndicatorResult:
    rsi: float
    ema_fast: float
    ema_slow: float
    atr: float
    volatility_pct: float

class TechnicalAnalyzer:
    """
    Класс для расчёта технических индикаторов.
    Использует pandas для эффективности.
    """
    
    def analyze(self, prices: List[Decimal], highs: List[Decimal], lows: List[Decimal]) -> IndicatorResult:
        if not prices:
            return IndicatorResult(50, 0, 0, 0, 0)
            
        df = pd.DataFrame({
            'close': [float(p) for p in prices],
            'high': [float(p) for p in highs],
            'low': [float(p) for p in lows]
        })
        
        rsi = self._calculate_rsi(df).iloc[-1]
        ema_fast = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema_slow = df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        atr = self._calculate_atr(df).iloc[-1]
        
        # Годовая волатильность (упрощенно)
        returns = df['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(365 * 24 * 4) * 100 # Для 15м свечей
        
        return IndicatorResult(
            rsi=float(rsi) if not np.isnan(rsi) else 50.0,
            ema_fast=float(ema_fast),
            ema_slow=float(ema_slow),
            atr=float(atr) if not np.isnan(atr) else 0.0,
            volatility_pct=float(volatility) if not np.isnan(volatility) else 0.0
        )

    def _calculate_rsi(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/period, adjust=False).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        high = df['high']
        low = df['low']
        close = df['close'].shift(1)
        tr = pd.concat([high - low, (high - close).abs(), (low - close).abs()], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()
