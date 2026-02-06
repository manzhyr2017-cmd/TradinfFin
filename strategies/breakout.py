import sys
import os
# Add parent directory to path to import mean_reversion_bybit
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from typing import Optional
from datetime import datetime, timedelta
import logging

from mean_reversion_bybit import TechnicalIndicators, AdvancedSignal, SignalType, SignalStrength, ConfluenceScore, MarketRegime

logger = logging.getLogger(__name__)

class BreakoutStrategy:
    """
    Volatility Breakout Strategy (Keltner Channels)
    """
    def __init__(self):
        self.ind = TechnicalIndicators()

    def analyze(self, df_15m: pd.DataFrame, symbol: str) -> Optional[AdvancedSignal]:
        if len(df_15m) < 50:
            return None

        df = df_15m.copy()
        
        # Indicators
        df['ema_20'] = self.ind.ema(df['close'], 20)
        df['atr'] = self.ind.atr(df['high'], df['low'], df['close'], 10)
        
        # Keltner Channels
        # Middle = EMA 20
        # Upper = EMA 20 + 2*ATR
        # Lower = EMA 20 - 2*ATR
        df['kc_upper'] = df['ema_20'] + (2.0 * df['atr'])
        df['kc_lower'] = df['ema_20'] - (2.0 * df['atr'])
        
        df['adx'], _, _ = self.ind.adx(df['high'], df['low'], df['close'], 14)
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # Filter: ADX usually indicates strong trend if > 25
        if current['adx'] < 25:
             return None
             
        # Trigger: Close breaks Upper Channel
        if current['close'] > current['kc_upper'] and prev['close'] <= prev['kc_upper']:
             # Breakout UP
             signal_type = SignalType.LONG
             stop_loss = current['ema_20'] # Stop at EMA 20
             take_profit = current['close'] + (3 * current['atr'])
        elif current['close'] < current['kc_lower'] and prev['close'] >= prev['kc_lower']:
             # Breakout DOWN
             signal_type = SignalType.SHORT
             stop_loss = current['ema_20'] # Stop at EMA 20
             take_profit = current['close'] - (3 * current['atr'])
        else:
            return None
            
        confluence = ConfluenceScore()
        confluence.add_factor('Keltner Breakout', 60, 60)
        confluence.add_factor('High ADX', 20, 20)
        
        return AdvancedSignal(
            signal_type=signal_type,
            symbol=symbol,
            entry_price=current['close'],
            stop_loss=stop_loss,
            take_profit_1=take_profit,
            take_profit_2=take_profit, 
            confluence=confluence,
            probability=75,
            strength=SignalStrength.MODERATE,
            timeframes_aligned={'15m': True},
            support_resistance_nearby=None,
            market_regime=MarketRegime.VOLATILE_CHAOS,
            risk_reward_ratio=1.5,
            position_size_percent=1.0,
            funding_rate=None,
            funding_interpretation=None,
            orderbook_imbalance=None,
            timestamp=datetime.now(),
            valid_until=datetime.now() + timedelta(minutes=30),
            indicators={
                'rsi_15m': 50, # Placeholder
                'rsi_1h': 50,
                'rsi_4h': 50,
                'bb_position': 0.5,
                'vol_ratio': 1.0,
                'atr_pct': (current['atr'] / current['close']) * 100 if current['close'] > 0 else 0,
                'hour_of_day': datetime.now().hour,
                'trend_adx': current['adx'],
                'funding_rate': 0,
                'rsi_slope': 0,
                'ema_dist': 0,
                'bb_width': 0,
                'vol_zscore': 0
            },
            reasoning=[f"Breakout {signal_type.value}", "ADX > 25"],
            warnings=[]
        )
