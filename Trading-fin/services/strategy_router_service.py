import pandas as pd
import logging
from typing import Dict
from enum import Enum

logger = logging.getLogger(__name__)

class MarketRegime(Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING_WIDE = "RANGING_WIDE"
    RANGING_NARROW = "RANGING_NARROW"
    VOLATILE_CHAOS = "VOLATILE_CHAOS"

class StrategyRouterService:
    """
    Selects the optimal strategy based on market conditions
    """
    def __init__(self, bot):
        self.bot = bot
        
    def detect_regime(self, df: pd.DataFrame) -> MarketRegime:
        """
        Detects market regime using ADX, ATR, and Bollinger Bands
        """
        # We assume indicators are already calculated or we calculate them here
        from mean_reversion_bybit import TechnicalIndicators
        ind = TechnicalIndicators()
        
        # 1. ADX for Trend Strength
        adx, plus_di, minus_di = ind.adx(df['high'], df['low'], df['close'])
        current_adx = adx.iloc[-1]
        
        # 2. ATR for Volatility
        atr = ind.atr(df['high'], df['low'], df['close'])
        current_atr = atr.iloc[-1]
        avg_atr = atr.tail(20).mean()
        
        # 3. Bollinger Band Width
        upper, middle, lower = ind.bollinger_bands(df['close'])
        bb_width = (upper.iloc[-1] - lower.iloc[-1]) / middle.iloc[-1]
        
        # Regime Detection Logic
        if current_atr > avg_atr * 2.5:
            return MarketRegime.VOLATILE_CHAOS
            
        if current_adx > 25:
            if plus_di.iloc[-1] > minus_di.iloc[-1]:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN
                
        if bb_width < 0.03:
            return MarketRegime.RANGING_NARROW
        else:
            return MarketRegime.RANGING_WIDE

    def select_strategy(self, regime: MarketRegime) -> str:
        """
        Returns strategy name based on regime
        """
        if regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            return "trend"
        elif regime == MarketRegime.RANGING_WIDE:
            return "mean_reversion"
        elif regime == MarketRegime.RANGING_NARROW:
            return "grid"
        elif regime == MarketRegime.VOLATILE_CHAOS:
            return "breakout"
        else:
            return "mean_reversion"
            
    def get_risk_params(self, regime: MarketRegime) -> Dict:
        """
        Adjust risk parameters based on regime
        """
        if regime == MarketRegime.VOLATILE_CHAOS:
            return {"risk_multiplier": 0.5, "stop_multiplier": 2.0} # Lower risk, wider stops
        elif regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            return {"risk_multiplier": 1.2, "stop_multiplier": 1.0} # Aggressive
        else:
            return {"risk_multiplier": 1.0, "stop_multiplier": 1.0} # Normal
