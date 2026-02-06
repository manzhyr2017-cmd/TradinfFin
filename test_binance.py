import requests
import json

def test_binance():
    proxy = "http://VSeMhdTD:iE7xTrsG@45.199.213.45:64480"
    proxies = {"http": proxy, "https": proxy}
    
    print("Testing Binance API via Proxy...")
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
        resp = requests.get(url, proxies=proxies, timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_binance()
