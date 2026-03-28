import logging
from grid_bot_v2 import GridBot
from decimal import Decimal
import pandas as pd

# Setup logging to see what's happening
logging.basicConfig(level=logging.INFO)

def test_bot_init():
    try:
        print("🤖 Initializing GridBot...")
        bot = GridBot()
        print("✅ GridBot initialized.")
        
        print("📈 Fetching market data...")
        df = bot.get_market_data()
        print(f"✅ Fetched {len(df)} candles.")
        print(df.tail(3))
        
        print("🔍 Testing market analysis...")
        analysis = bot._analyze_market(df)
        print(f"✅ Analysis complete: {analysis['regime']} (Confidence: {analysis['confidence']:.2f})")
        
        return True
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    test_bot_init()
