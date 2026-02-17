import os
import json
import logging
from bybit_client import BybitClient, BybitCategory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Debug")

def test_connection():
    # Load keys
    with open('bot_config.json', 'r') as f:
        config = json.load(f)
        
    api_key = config['api_key']
    api_secret = config['api_secret']
    proxy = config.get('proxy')
    
    print(f"Testing Keys: {api_key[:5]}... / {api_secret[:5]}...")
    print(f"Proxy: {proxy}")
    
    # 0. Check Proxy Location
    import requests
    try:
        print("\n--- Checking Proxy Location ---")
        proxies = {"http": proxy, "https": proxy} if proxy else None
        resp = requests.get("http://ip-api.com/json", proxies=proxies, timeout=10)
        data = resp.json()
        print(f"IP: {data.get('query')} | Country: {data.get('country')} | Region: {data.get('regionName')}")
        
        print("\n--- Checking Generic HTTPS (Google) ---")
        requests.get("https://www.google.com", proxies=proxies, timeout=5)
        print("Google HTTPS: OK")
        
        print("\n--- Checking Binance API (Fallback Data) ---")
        bin_resp = requests.get("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", proxies=proxies, timeout=5)
        print(f"Binance: {bin_resp.json()}")
        
        print("\n--- Checking OKX API ---")
        # OKX Public Ticker
        okx_resp = requests.get("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT-SWAP", proxies=proxies, timeout=5)
        print(f"OKX Status: {okx_resp.status_code}")
        # print(f"OKX Body: {okx_resp.text[:100]}...")
        if okx_resp.status_code == 200:
            print("OKX API: ACCESSIBLE ✅")
        else:
            print(f"OKX API: BLOCKED ❌ ({okx_resp.status_code})")
        
    except Exception as e:
        print(f"Check Failed: {e}")
    
    # 1. Test Demo URL
    print("\n--- Testing api-demo.bybit.com ---")
    client = BybitClient(
        api_key=api_key, 
        api_secret=api_secret, 
        demo_trading=True,
        proxy=proxy,
        category=BybitCategory.LINEAR
    )
    
    try:
        # Public
        print("Requesting Ticker (Public)...")
        ticker = client.get_ticker("BTCUSDT")
        print(f"Ticker OK: {ticker['price']}")
        
        # Private
        print("Requesting Wallet (Private)...")
        balance = client.get_wallet_balance("USDT")
        print(f"Wallet OK: {balance}")
        
    except Exception as e:
        print(f"Demo Failed: {e}")


    # 2. Test Testnet URL
    # print("\n--- Testing api-testnet.bybit.com ---")
    # ...
    
    # 3. Test Mainnet URL (Maybe keys work there?)
    # print("\n--- Testing api.bybit.com (Mainnet) ---")
    # ...
    
    # 4. Test Bytick (Mainnet Mirror)
    # print("\n--- Testing api.bytick.com (Mirror) ---")
    # ...

if __name__ == "__main__":
    test_connection()
