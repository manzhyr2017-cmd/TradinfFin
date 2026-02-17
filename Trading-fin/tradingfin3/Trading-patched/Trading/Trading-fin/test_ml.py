
import pandas as pd
import numpy as np
from mean_reversion_bybit import AdvancedMeanReversionEngine, generate_test_data

def test_strategy():
    print("Testing ML Data Collection logic...")
    
    # 1. Generate Fake Data
    df_15m = generate_test_data(500)
    df_1h = df_15m.iloc[::4].reset_index(drop=True)
    df_4h = df_15m.iloc[::16].reset_index(drop=True)
    
    engine = AdvancedMeanReversionEngine(min_confluence=0)
    
    # 2. Run Analysis
    try:
        # Long Check
        signal = engine.analyze(
            df_15m, df_1h, df_4h, "BTCUSDT",
            funding_rate=0.0001,
            orderbook_imbalance=1.2
        )
        print("Analyze completed without crash.")
        
        if signal:
            print(f"Signal found: {signal.signal_type}")
            # Access indicators to ensure they exist
            print("ATR Pct:", signal.indicators.get('atr_pct'))
        else:
            print("No signal found (expected on random data).")
            
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_strategy()
