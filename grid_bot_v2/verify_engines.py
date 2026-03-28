import sys
import os
# Add current dir to path
sys.path.append(os.getcwd())

import config
from database import session, Trade, BotState
from adaptive_sizing import AdaptiveSizingEngine
from smart_pause import SmartPauseEngine
from precision_timing import PrecisionTimingEngine
from pybit.unified_trading import HTTP

class MockBybitClient:
    def get_tickers(self, **kwargs):
        return {'result': {'list': [{'lastPrice': '2500.0', 'bid1Price': '2499.0', 'ask1Price': '2501.0', 'val24h': '2000000'}]}}
    
    def get_orderbook(self, **kwargs):
        return {'result': {'b': [['2499.0', '10.0']], 'a': [['2501.0', '10.0']]}}
    
    def get_kline(self, **kwargs):
        # Return descending list [curr, prev]
        return {'result': {'list': [
            ['1600000000000', '2500.0', '2510.0', '2490.0', '2500.0', '100', '250000'],
            ['1500000000000', '2500.0', '2510.0', '2490.0', '2500.0', '100', '250000']
        ]}}
    
    def get_server_time(self):
        return {'result': {'timeSecond': '1600000000'}}

    def get_public_trading_history(self, **kwargs):
        return {'result': {'list': [{'size': '1.0', 'side': 'Buy'}, {'size': '0.5', 'side': 'Sell'}]}}
    
    def get_wallet_balance(self, **kwargs):
        return {'result': {'list': [{'accountMaintenanceMarginRate': '0.1'}]}}

def verify_engines():
    print("--- Verifying Grid Bot v3.5 Engines (MOCKED) ---")
    
    mock_client = MockBybitClient()

    # 1. Adaptive Sizing
    print("\n1. Testing AdaptiveSizingEngine...")
    sizing = AdaptiveSizingEngine(mock_client)
    print(f"Current Priors: {sizing.priors}")
    size = sizing.calculate_size(1000, "Buy")
    print(f"Calculated Size for $1000 (Mock Price 2500): {size}")
    
    # Test Update
    sizing.update_priors(is_win=True)
    print(f"Updated alpha! New Priors: {sizing.priors}")

    # 2. Smart Pause
    print("\n2. Testing SmartPauseEngine...")
    pause = SmartPauseEngine(mock_client)
    safety = pause.check_safety()
    print(f"Safety Status: {safety}")

    # 3. Precision Timing
    print("\n3. Testing PrecisionTimingEngine...")
    timing = PrecisionTimingEngine(mock_client)
    score = timing.get_timing_score()
    print(f"Timing Score: {score}/100")

    print("\n--- Verification Complete ---")

if __name__ == "__main__":
    verify_engines()
