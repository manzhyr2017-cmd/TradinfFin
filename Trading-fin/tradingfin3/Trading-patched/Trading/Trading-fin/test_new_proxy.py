
import os
import time
import hmac
import hashlib
import json
import requests
from dotenv import load_dotenv
import urllib3

urllib3.disable_warnings()

# New Proxy Details
PROXY = "http://VSeMhdTD:iE7xTrsG@156.246.213.194:62956"
proxies = {"http": PROXY, "https": PROXY}

# Load API Keys
load_dotenv()
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")

print(f"Checking with NEW PROXY: {PROXY}")

def debug_request(url, name, auth=False):
    print(f"\n--- CHECKING {name} ---")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json"
    }
    
    params_str = "accountType=UNIFIED&coin=USDT" if auth else ""

    if auth:
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"
        sign_str = f"{timestamp}{API_KEY}{recv_window}{params_str}"
        signature = hmac.new(API_SECRET.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256).hexdigest()
        
        headers["X-BAPI-API-KEY"] = API_KEY
        headers["X-BAPI-TIMESTAMP"] = timestamp
        headers["X-BAPI-SIGN"] = signature
        headers["X-BAPI-RECV-WINDOW"] = recv_window
    
    final_url = f"{url}?{params_str}" if params_str else url
    
    try:
        resp = requests.get(final_url, headers=headers, proxies=proxies, timeout=10, verify=False)
        print(f"Status: {resp.status_code}")
        
        # Check Time Sync if possible
        if "timeSecond" in resp.text:
            try:
                server_time = int(resp.json()['result']['timeSecond'])
                local_time = int(time.time())
                diff = local_time - server_time
                print(f"⏱️ Time Sync: Local={local_time}, Server={server_time}, Diff={diff}s")
                if abs(diff) > 5:
                    print("⚠️ CRITICAL: SYSTEM TIME IS OUT OF SYNC! API WILL FAIL.")
            except: pass

        if resp.status_code == 200:
            print("✅ SUCCESS!")
            print(f"Response: {str(resp.json())[:100]}...")
            return True
        else:
            print("❌ FAILED:")
            print(f"Headers: {dict(resp.headers)}")
            print(f"Body: {resp.text[:500]}") # Print UP TO 500 chars
            return False
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return False

# 1. Public Time (No Auth) - Tests Connectivity/Proxy
debug_request("https://api.bybit.com/v5/market/time", "PUBLIC ENDPOINT (Time)")

# 2. Private (Auth) - Tests Keys
debug_request("https://api.bybit.com/v5/account/wallet-balance", "PRIVATE ENDPOINT (Auth)", auth=True)
