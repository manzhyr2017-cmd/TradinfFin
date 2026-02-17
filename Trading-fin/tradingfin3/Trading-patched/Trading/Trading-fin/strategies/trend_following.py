import sys
import os
# Add parent directory to path to import mean_reversion_bybit
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

from mean_reversion_bybit import TechnicalIndicators, AdvancedSignal, SignalType, SignalStrength, ConfluenceScore, MarketRegime

logger = logging.getLogger(__name__)

class TrendFollowingStrategy:
    """
    SuperTrend + EMA Strategy
    """
    def __init__(self):
        self.ind = TechnicalIndicators()

    def analyze(self, df_1h: pd.DataFrame, symbol: str) -> Optional[AdvancedSignal]:
        if len(df_1h) < 200:
            return None

        df = df_1h.copy()
        
        # Indicators
        df['ema_200'] = self.ind.ema(df['close'], 200)
        df['atr'] = self.ind.atr(df['high'], df['low'], df['close'], 14)
        
        # SuperTrend (Simplified)
        # Basic calculation: HL2 +/- Multiplier * ATR
        multiplier = 3.0
        hl2 = (df['high'] + df['low']) / 2
        
        # Simplified vectorized SuperTrend calculation
        # Note: Proper SuperTrend is recursive. This is a basic approximation for the example.
        # Ideally, we should implement the full recursive logic.
        
        # For this iteration, we will use a simpler Trend Following trigger:
        # Price > EMA 200 AND MACD Bullish Cross
        
        # EMA Filter
        # Calculate MACD before taking snapshots
        df['macd'], df['macd_signal'], _ = self.ind.macd(df['close'])

        current = df.iloc[-1]
        prev = df.iloc[-2]

        if current['close'] < current['ema_200']:
            return None # Only Longs in Uptrend
            
        # Trigger: MACD Cross Up while above EMA 200
        is_bullish_cross = current['macd'] > current['macd_signal'] and prev['macd'] <= prev['macd_signal']
        
        if not is_bullish_cross:
            return None
            
        confluence = ConfluenceScore()
        confluence.add_factor('Trend (EMA 200)', 50, 50)
        confluence.add_factor('MACD Crossover', 30, 30)
        
        # Basic Risk Mgmt
        entry = current['close']
        stop_loss = entry - (2 * current['atr'])
        take_profit = entry + (4 * current['atr'])
        
        return AdvancedSignal(
            signal_type=SignalType.LONG,
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit,
            take_profit_2=take_profit * 1.05,
            confluence=confluence,
            probability=80,
            strength=SignalStrength.STRONG,
            timeframes_aligned={'1h': True},
            support_resistance_nearby=None,
            market_regime=MarketRegime.STRONG_TREND_UP,
            risk_reward_ratio=2.0,
            position_size_percent=1.0,
            funding_rate=None,
            funding_interpretation=None,
            orderbook_imbalance=None,
            timestamp=datetime.now(),
            valid_until=datetime.now() + timedelta(hours=1),
            indicators={
                'rsi_15m': 50, # Placeholder
                'rsi_1h': 50,
                'rsi_4h': 50,
                'bb_position': 0.5,
                'vol_ratio': 1.0,
                'atr_pct': (current['atr'] / entry) * 100 if entry > 0 else 0,
                'hour_of_day': datetime.now().hour,
                'trend_adx': 0,
                'funding_rate': 0,
                'rsi_slope': 0,
                'ema_dist': (current['close'] - current['ema_200']) / current['ema_200'] * 100 if 'ema_200' in current else 0,
                'bb_width': 0,
                'vol_zscore': 0
            },
            reasoning=["Price > EMA 200", "MACD Bullish Cross"],
            warnings=[]
        )
