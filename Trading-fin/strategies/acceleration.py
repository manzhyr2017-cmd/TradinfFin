import pandas as pd
from typing import Dict, Optional
import numpy as np

from mean_reversion_bybit import AdvancedSignal, SignalType, SignalStrength, ConfluenceScore, MarketRegime

class AccelerationStrategy:
    """
    Sniper Scalp Strategy for Small Deposit Acceleration ($50-$100).
    High Risk / High Reward.
    
    Logic:
    - Timeframe: 5m (preferred) or 15m
    - Trend: EMA 200
    - Trigger: RSI + Bollinger Bands
    """
    
    def __init__(self):
        self.name = "Acceleration (Scalp)"
        
    def _calculate_ema(self, series, span):
        return series.ewm(span=span, adjust=False).mean()
        
    def _calculate_rsi(self, series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        return 100 - (100 / (1 + rs))
        
    def _calculate_bb(self, series, period=20, std=2):
        sma = series.rolling(window=period).mean()
        rstd = series.rolling(window=period).std()
        return sma + (rstd * std), sma - (rstd * std)
        
    def _calculate_atr(self, df, period=14):
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        return true_range.rolling(window=period).mean()

    def analyze(self, df: pd.DataFrame, symbol: str, funding_rate: float = 0.0, orderbook_imbalance: float = None, **kwargs) -> Optional[AdvancedSignal]:
        # Need enough data
        if len(df) < 200:
            return None
            
        # --- Indicators ---
        # 1. Trend
        df['ema200'] = self._calculate_ema(df['close'], 200)
        
        # 2. Momentum
        df['rsi'] = self._calculate_rsi(df['close'], 14)
        
        # 3. Volatility
        df['bb_upper'], df['bb_lower'] = self._calculate_bb(df['close'], 20, 2)
        
        # Get last candle
        curr = df.iloc[-1]
        
        # DEBUG LOGGING
        if len(df) > 0:
            print(f"DEBUG ACCEL: Columns: {df.columns}")
            print(f"DEBUG ACCEL: Time Col Type: {df['time'].dtype if 'time' in df.columns else 'MISSING'}")
            if 'time' in curr:
                print(f"DEBUG ACCEL: curr['time'] Value: {curr['time']} Type: {type(curr['time'])}")
            else:
                 print(f"DEBUG ACCEL: curr has no 'time' index/column. Name: {curr.name} Type: {type(curr.name)}")
        
        # --- Logic ---
        signal_type = None
        reasoning = []
        
        # LONG Condition
        # 1. Above Trend (Bullish) or slightly below in strong pullback
        # 2. Deep Pullback: RSI < 35 (Oversold)
        # 3. Price touched Lower BB
        if curr['close'] > curr['ema200']:
            if curr['rsi'] < 40 and curr['low'] <= curr['bb_lower']:
                signal_type = SignalType.LONG
                reasoning.append("Uptrend Pullback (Price > EMA200)")
                reasoning.append(f"RSI Oversold ({curr['rsi']:.1f})")
                reasoning.append("Touched Lower Bollinger Band")
                
        # SHORT Condition
        elif curr['close'] < curr['ema200']:
            if curr['rsi'] > 60 and curr['high'] >= curr['bb_upper']:
                signal_type = SignalType.SHORT
                reasoning.append("Downtrend Pullback (Price < EMA200)")
                reasoning.append(f"RSI Overbought ({curr['rsi']:.1f})")
                reasoning.append("Touched Upper Bollinger Band")

        if not signal_type:
            return None
            
        # --- Signal Construction ---
        stop_loss = 0.0
        take_profit = 0.0
        entry_price = float(curr['close'])
        
        # Tight ATR Stop
        atr_series = self._calculate_atr(df)
        atr = atr_series.iloc[-1]
        
        if signal_type == SignalType.LONG:
            stop_loss = entry_price - (atr * 1.5) # Tight stop
            take_profit = entry_price + (atr * 3.0) # 1:2 RR
        else:
            stop_loss = entry_price + (atr * 1.5)
            take_profit = entry_price - (atr * 3.0)
            
        confluence = ConfluenceScore()
        confluence.score = 85 # Base high score for this aggressive strategy
        
        # Robust Timestamp Calculation
        ts = curr.get('time', curr.name)
        try:
             # Ensure it's a pandas Timestamp
             ts = pd.to_datetime(ts)
        except:
             ts = pd.Timestamp.now()
             
        # Calculate valid_until safely
        valid_until_val = ts + pd.Timedelta(minutes=30)
        
        return AdvancedSignal(
            symbol=symbol,
            signal_type=signal_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit_1=take_profit,
            take_profit_2=take_profit * 1.01,
            confluence=confluence,
            probability=85,
            strength=SignalStrength.STRONG,
            timeframes_aligned={},
            support_resistance_nearby=None,
            market_regime=MarketRegime.STRONG_TREND_UP if signal_type == SignalType.LONG else MarketRegime.STRONG_TREND_DOWN,
            risk_reward_ratio=2.0,
            position_size_percent=5.0, # Aggressive sizing for acceleration
            funding_rate=0,
            funding_interpretation="Neutral",
            orderbook_imbalance=0,
            timestamp=ts,
            valid_until=valid_until_val,
            indicators={'rsi': curr['rsi'], 'ema200': curr['ema200']},
            reasoning=reasoning, # Now it's a list
            warnings=["High Risk Strategy"]
        )
