
import os
import time
import hmac
import hashlib
import json
import requests
from dotenv import load_dotenv
import urllib3

urllib3.disable_warnings()

# New Proxy Details (Confirmed Working for Public)
PROXY = "http://VSeMhdTD:iE7xTrsG@156.246.213.194:62956"
proxies = {"http": PROXY, "https": PROXY}

load_dotenv(override=True)
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

def check_env(name, base_url):
    print(f"\n--- CHECKING {name} ({base_url}) ---")
    
    # 1. Check Public Time (Connectivity)
    try:
        resp = requests.get(f"{base_url}/v5/market/time", proxies=proxies, timeout=10, verify=False)
        if resp.status_code == 200:
            print(f"✅ Connectivity: OK (Time: {resp.json()['result']['timeSecond']})")
        else:
            print(f"❌ Connectivity: FAILED ({resp.status_code})")
            return
    except Exception as e:
        print(f"❌ Connectivity: Error {e}")
        return

    # 2. Check Private Auth (Key Validity)
    endpoint = "/v5/account/wallet-balance"
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    params = "accountType=UNIFIED&coin=USDT"
    
    sign_str = f"{timestamp}{API_KEY}{recv_window}{params}"
    signature = hmac.new(API_SECRET.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256).hexdigest()
    
    headers = {
        "X-BAPI-API-KEY": API_KEY,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-SIGN": signature,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    
    try:
        resp = requests.get(f"{base_url}{endpoint}?{params}", headers=headers, proxies=proxies, timeout=10, verify=False)
        print(f"Auth Status: {resp.status_code}")
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get('retCode') == 0:
                print("🎉 KEY VALID! This is the correct environment.")
                print(f"Balance: {data.get('result')}")
            else:
                print(f"⚠️ Key Invalid for this env: {data.get('retMsg')}")
        elif resp.status_code == 401:
             print("❌ 401 Unauthorized (Likely wrong environment or keys blocked)")
        else:
             print(f"❌ Error: {resp.text[:200]}")
             
    except Exception as e:
        print(f"Error: {e}")

print(f"Checking Key: {API_KEY}...")
check_env("MAINNET", "https://api.bybit.com")
check_env("TESTNET", "https://api-testnet.bybit.com")
check_env("DEMO TRADING", "https://api-demo.bybit.com")
