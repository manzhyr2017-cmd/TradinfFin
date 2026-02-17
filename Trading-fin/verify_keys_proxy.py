
import os
import time
import hmac
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("BYBIT_API_KEY", "IRt2XGOe8vJXIk0Tq9")
API_SECRET = os.getenv("BYBIT_API_SECRET", "l9dxUn9inkh3jEb9nlQyTXE56Nw4P7W25vpN")
# Proxy from bot_config.json
PROXY = "http://VSeMhdTD:iE7xTrsG@156.246.213.194:62956"
proxies = {"http": PROXY, "https": PROXY}

def check_bybit(name, base_url, is_demo=False):
    print(f"\n--- Checking {name} ({base_url}) ---")
    
    endpoint = "/v5/account/wallet-balance"
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    params = "accountType=UNIFIED"
    
    sign_str = f"{timestamp}{API_KEY}{recv_window}{params}"
    signature = hmac.new(
        API_SECRET.encode("utf-8"), 
        sign_str.encode("utf-8"), 
        hashlib.sha256
    ).hexdigest()
    
    headers = {
        "X-BAPI-API-KEY": API_KEY,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-SIGN": signature,
        "X-BAPI-RECV-WINDOW": recv_window,
    }
    
    url = f"{base_url}{endpoint}?{params}"
    
    try:
        # We try with proxy first
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=15)
        print(f"Status Code: {resp.status_code}")
        data = resp.json()
        
        if data.get("retCode") == 0:
            print(f"✅ SUCCESS! {name} keys are VALID.")
            balance = data.get("result", {}).get("list", [{}])[0].get("totalEquity", "0")
            print(f"💰 Balance/Equity: ${balance}")
            return True
        else:
            print(f"❌ API Error: {data.get('retMsg')} (Code: {data.get('retCode')})")
            return False
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False

print(f"Testing keys starting with: {API_KEY[:5]}...")

# 1. Mainnet
check_bybit("MAINNET", "https://api.bybit.com")

# 2. Testnet
check_bybit("TESTNET", "https://api-testnet.bybit.com")

# 3. Demo Trading (special subdomain)
check_bybit("DEMO TRADING", "https://api-demo.bybit.com")
