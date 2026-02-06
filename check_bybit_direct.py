
import os
import time
import hmac
import hashlib
import json
import requests
from dotenv import load_dotenv
import urllib3

urllib3.disable_warnings()
load_dotenv()

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

# FORCE NO PROXY
proxies = {} 

print("--- TESTING DIRECT CONNECTION (NO PROXY) ---")

def check_endpoint(name, base_url):
    print(f"\n--- CHECKING {name} ({base_url}) ---")
    
    endpoint = "/v5/account/wallet-balance"
    timestamp = str(int(time.time() * 1000))
    recv_window = str(5000)
    params = "accountType=UNIFIED&coin=USDT"
    
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
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    url = f"{base_url}{endpoint}?{params}"
    
    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        print(f"Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("retCode") == 0:
                print("✅ SUCCESS! Direct connection works.")
                result = data.get("result", {}).get("list", [{}])[0]
                equity = result.get("totalEquity", "Unknown")
                print(f"💰 Equity: {equity}")
                return True
            else:
                print(f"❌ API Error: {data.get('retMsg')}")
        else:
            print(f"❌ Failed. Body preview: {resp.text[:200]}")

    except Exception as e:
        print(f"Connection Error: {e}")

check_endpoint("MAINNET", "https://api.bybit.com")
