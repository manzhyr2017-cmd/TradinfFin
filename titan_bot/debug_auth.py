import os
from pybit.unified_trading import HTTP
from dotenv import load_dotenv
import json

def test_bybit_auth_official():
    load_dotenv()
    
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    testnet = os.getenv("TESTNET", "True").lower() == "true"
    
    print(f"--- TESTING OFFICIAL BYBIT AUTH (pybit) ---")
    print(f"Key: {api_key[:4]}****")
    print(f"Testnet: {testnet}")
    
    session = HTTP(
        testnet=testnet,
        api_key=api_key,
        api_secret=api_secret,
        recv_window=20000
    )
    
    try:
        # Пробуем получить баланс самого простого типа
        response = session.get_wallet_balance(
            accountType="UNIFIED",
            coin="USDT"
        )
        print("✅ SUCCESS!")
        print(json.dumps(response, indent=2))
        
    except Exception as e:
        print("❌ FAILED!")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Detail: {str(e)}")
        
        # Если не UTA, пробуем обычный аккаунт
        print("\nTrying legacy CONTRACT account...")
        try:
            response = session.get_wallet_balance(
                accountType="CONTRACT",
                coin="USDT"
            )
            print("✅ SUCCESS (Legacy CONTRACT)!")
            print(json.dumps(response, indent=2))
        except Exception as e2:
            print(f"❌ Legacy also failed: {e2}")

if __name__ == "__main__":
    test_bybit_auth_official()
