import os
import requests
import time
from pybit.unified_trading import HTTP
from dotenv import load_dotenv

def test_time_and_auth():
    load_dotenv()
    
    testnet = os.getenv("TESTNET", "True").lower() == "true"
    base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
    
    print("--- 🕒 TIME SYNC CHECK ---")
    try:
        # Получаем время сервера Bybit
        server_time_res = requests.get(f"{base_url}/v5/market/time")
        resp_json = server_time_res.json()
        bybit_time = int(resp_json.get('time', resp_json.get('result', {}).get('timeNano', 0)[:13]))
        local_time = int(time.time() * 1000)
        
        drift_sec = (local_time - bybit_time) / 1000
        print(f"Bybit Server Time (UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(bybit_time/1000))}")
        print(f"Local Server Time (UTC): {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(local_time/1000))}")
        print(f"Time Drift: {drift_sec:.2f} seconds")
        
        if abs(drift_sec) > 10:
            print(f"❌ CRITICAL TIME DRIFT ({drift_sec:.2f}s)! Your server clock is out of sync.")
            print("Run: sudo systemctl restart systemd-timesyncd")
        else:
            print("✅ Time sync is acceptable.")
    except Exception as e:
        print(f"❌ Failed to get server time: {e}")

    print("\n--- 🔐 AUTH TEST ---")
    session = HTTP(
        testnet=testnet,
        api_key=os.getenv("BYBIT_API_KEY"),
        api_secret=os.getenv("BYBIT_API_SECRET"),
        recv_window=60000,
        demo=os.getenv("BYBIT_DEMO", "False").lower() == "true"
    )
    
    # Пытаемся сделать публичный запрос (не требует ключей)
    print("Testing PUBLIC request (Tickers)...")
    try:
        res = session.get_tickers(category="linear", symbol="BTCUSDT")
        print(f"✅ Public API: OK (Symbol: {res['result']['list'][0]['symbol']})")
    except Exception as e:
        print(f"❌ Public API Failed: {e}")

    # Пытаемся сделать приватный запрос
    print("\nTesting PRIVATE request (Balance)...")
    try:
        res = session.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        print(f"✅ Private API: SUCCESS! Code: {res['retCode']}")
    except Exception as e:
        print(f"❌ Private API Failed: {e}")

if __name__ == "__main__":
    test_time_and_auth()
