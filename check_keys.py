
import os
import logging
from pybit.unified_trading import HTTP
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)

load_dotenv()

api_key = os.getenv("BYBIT_API_KEY")
api_secret = os.getenv("BYBIT_API_SECRET")
# Explicitly use standard Unified Trading accountType
# Note: Demo Trading is a special mode on Mainnet, typically handling Unified automatically.

print(f"Checking Key: {api_key[:5]}... (from .env)")

# 1. TEST MAINNET
print("\n--- CHECKING MAINNET (api.bybit.com) ---")
try:
    session = HTTP(testnet=False, api_key=api_key, api_secret=api_secret)
    session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    print(">>> SUCCESS! This is a MAINNET key.")
except Exception as e:
    print(f"Mainnet Failed (Expected if keys are Testnet/Demo): {e}")

# 2. TEST TESTNET
print("\n--- CHECKING TESTNET (api-testnet.bybit.com) ---")
try:
    session = HTTP(testnet=True, api_key=api_key, api_secret=api_secret)
    session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    print(">>> SUCCESS! This is a TESTNET key.")
except Exception as e:
    print(f"Testnet Failed (Expected if keys are Mainnet/Demo): {e}")

# 3. TEST DEMO TRADING
print("\n--- CHECKING DEMO TRADING (api-demo.bybit.com) ---")
try:
    # Pybit 5.x: demo=True often maps to Demo Trading if testnet=False? 
    # Or we must manually set domain. Let's try forcing domain/url if possible or standard args.
    # Looking at pybit source, demo_trading arg usually sets the correct url.
    session = HTTP(testnet=False, demo_trading=True, api_key=api_key, api_secret=api_secret)
    # Double check URL if we can (internal prop)
    # print(f"URL: {session.endpoint}") 
    session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
    print(">>> SUCCESS! This is a DEMO TRADING key.")
except Exception as e:
    print(f"Demo Trading Failed: {e}")
