import os
from pybit.unified_trading import HTTP
from dotenv import load_dotenv
import json
import time

def test_everything():
    load_dotenv()
    
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    testnet = os.getenv("TESTNET", "True").lower() == "true"
    
    print(f"--- HARDCORE AUTH TEST ---")
    print(f"Key: {api_key[:4]}****")
    
    # Список доменов для теста
    domains = [
        "https://api-testnet.bybit.com",
        "https://api-testnet.bybit.com" # Повтор для уверенности
    ]
    
    for domain in domains:
        print(f"\nTesting Domain: {domain}")
        session = HTTP(
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret,
            recv_window=60000 # Максимальное окно
        )
        
        # Тест 1: Баланс UTA
        print("Test 1: UNIFIED balance...")
        try:
            res = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            print(f"✅ SUCCESS UTA: {res['retCode']}")
            return
        except Exception as e:
            print(f"❌ UTA Failed: {e}")
            
        # Тест 2: Позиции (простейший запрос)
        print("Test 2: Positions list...")
        try:
            res = session.get_positions(category="linear", symbol="BTCUSDT")
            print(f"✅ SUCCESS POSITIONS: {res['retCode']}")
            return
        except Exception as e:
            print(f"❌ Positions Failed: {e}")

    print("\n--- CONCLUSION ---")
    print("If all failed with 401, check:")
    print("1. Are these keys EXACTLY from TESTNET (not mainnet)?")
    print("2. Is your server time correct? Current server time:", time.ctime())

if __name__ == "__main__":
    test_everything()
