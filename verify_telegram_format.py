
import sys
import os
from datetime import datetime, timedelta

# Add path
sys.path.append(os.getcwd())

from telegram_bot import SignalFormatter
from mean_reversion_bybit import AdvancedSignal, SignalType, SignalStrength, ConfluenceScore, MarketRegime

def create_trend_signal():
    confluence = ConfluenceScore()
    return AdvancedSignal(
        signal_type=SignalType.LONG,
        symbol='ETHUSDT',
        entry_price=3000.0,
        stop_loss=2900.0,
        take_profit_1=3100.0,
        take_profit_2=3200.0,
        confluence=confluence,
        probability=82,
        strength=SignalStrength.STRONG,
        timeframes_aligned={'1h': True},
        support_resistance_nearby=None,
        market_regime=MarketRegime.STRONG_TREND_UP,
        risk_reward_ratio=2.0,
        position_size_percent=1.0,
        funding_rate=0.0001,
        funding_interpretation=None,
        orderbook_imbalance=None,
        timestamp=datetime.now(),
        valid_until=datetime.now(),
        indicators={'ema_200': 2950.0, 'macd': 15.5},
        reasoning=['Price > EMA', 'MACD Cross'],
        warnings=[]
    )

def create_breakout_signal():
    confluence = ConfluenceScore()
    return AdvancedSignal(
        signal_type=SignalType.SHORT,
        symbol='SOLUSDT',
        entry_price=100.0,
        stop_loss=102.0,
        take_profit_1=95.0,
        take_profit_2=90.0,
        confluence=confluence,
        probability=75,
        strength=SignalStrength.MODERATE,
        timeframes_aligned={'15m': True},
        support_resistance_nearby=None,
        market_regime=MarketRegime.VOLATILE_CHAOS,
        risk_reward_ratio=2.5,
        position_size_percent=1.0,
        funding_rate=None,
        funding_interpretation=None,
        orderbook_imbalance=None,
        timestamp=datetime.now(),
        valid_until=datetime.now(),
        indicators={'adx': 35.2, 'kc_lower': 101.5}, 
        reasoning=['Breakout KC Lower', 'ADX > 25'],
        warnings=['Choppy market']
    )

print("--- TREND SIGNAL ---")
print(SignalFormatter.format_signal(create_trend_signal(), include_position_calc=False))
print("\n" + "="*30 + "\n")
print("--- BREAKOUT SIGNAL ---")
print(SignalFormatter.format_signal(create_breakout_signal(), include_position_calc=False))
