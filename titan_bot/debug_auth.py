import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

def test_bybit_auth():
    load_dotenv()
    
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    testnet = os.getenv("TESTNET", "True").lower() == "true"
    
    base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"
    endpoint = "/v5/account/wallet-balance"
    params = "accountType=UNIFIED&coin=USDT"
    
    timestamp = str(int(time.time() * 1000))
    recv_window = "20000"
    
    raw_data = timestamp + api_key + recv_window + params
    signature = hmac.new(
        bytes(api_secret, "utf-8"),
        bytes(raw_data, "utf-8"),
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "X-BAPI-API-KEY": api_key,
        "X-BAPI-SIGN": signature,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json"
    }
    
    url = f"{base_url}{endpoint}?{params}"
    
    print(f"--- TESTING BYBIT AUTH ---")
    print(f"URL: {url}")
    print(f"Timestamp: {timestamp}")
    print(f"Recv Window: {recv_window}")
    
    response = requests.get(url, headers=headers)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")

if __name__ == "__main__":
    test_bybit_auth()
