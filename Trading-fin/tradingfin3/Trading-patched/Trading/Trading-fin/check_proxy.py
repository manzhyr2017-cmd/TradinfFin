import os
import sys
import logging
from dotenv import load_dotenv

import json

# Add project root to path
sys.path.append(os.getcwd())

# Load env
load_dotenv()

from bybit_client import BybitClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ProxyTest")

def load_proxy_from_config():
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, 'bot_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                return config.get('proxy')
    except Exception:
        pass
    return None

def test_connection():
    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or load_proxy_from_config()
    logger.info(f"Testing connectivity with Proxy: {proxy}")
    
    try:
        # Init client (it will auto-load proxy from init if passed, or we pass it explicit)
        client = BybitClient(proxy=proxy)
        
        # Use cloudscraper via client
        logger.info("Fetching Server Time...")
        time_data = client._request("/v5/market/time")
        logger.info(f"Server Time: {time_data}")
        
        logger.info("Fetching BTC Price...")
        ticker = client.get_ticker("BTCUSDT")
        logger.info(f"BTC Price: {ticker['price']}")
        
        print("\n✅ PROXY CONNECTION SUCCESSFUL")
        return True
    except Exception as e:
        logger.error(f"Connection Failed: {e}")
        print("\n❌ PROXY CONNECTION FAILED")
        return False

if __name__ == "__main__":
    test_connection()
