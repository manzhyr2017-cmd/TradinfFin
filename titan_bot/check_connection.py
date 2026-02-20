import sys
import os
from pathlib import Path

# Add current dir to path
sys.path.append(str(Path(__file__).parent))

try:
    print("--- TESTING TITAN BOT AUTONOMY ---")
    import config
    print(f"✅ Config loaded. Symbol: {config.SYMBOL}")
    print(f"✅ Mode: {'TESTNET' if config.TESTNET else 'MAINNET'}")
    
    from data_engine import DataEngine
    data = DataEngine()
    
    print("\nAttempting to fetch balance from Bybit...")
    balance = data.get_balance()
    print(f"💰 Current Balance: ${balance}")
    
    # Try to get top symbols to verify selector and API
    from selector import SymbolSelector
    selector = SymbolSelector()
    top_symbols = selector.get_top_symbols(3)
    print(f"📈 Top symbols: {top_symbols}")
    
    print("\n--- RESULTS ---")
    if balance is not None:
        print("✅ SUCCESS: Titan Bot is fully operational and autonomous!")
    else:
        print("❌ FAILURE: Could not connect to Bybit. Check your API keys in titan_bot/.env")

except Exception as e:
    print(f"\n❌ CRITICAL ERROR: {str(e)}")
    import traceback
    traceback.print_exc()
