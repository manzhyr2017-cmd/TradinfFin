import os
from dotenv import load_dotenv
from pybit.unified_trading import HTTP
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BybitCheck")

def test_connection():
    load_dotenv(override=True)
    
    api_key = os.getenv("BYBIT_API_KEY")
    api_secret = os.getenv("BYBIT_API_SECRET")
    
    if not api_key or not api_secret:
        logger.error("❌ API Keys not found in .env via os.getenv")
        return

    mask_key = f"{api_key[:5]}...{api_key[-5:]}" if api_key else "None"
    logger.info(f"🔑 Loaded Key: {mask_key}")
    
    # 1. Try Mainnet
    logger.info("------------- Testing MAINNET -------------")
    try:
        session = HTTP(
            testnet=False,
            api_key=api_key,
            api_secret=api_secret,
        )
        # Simple auth request
        resp = session.get_api_key_information()
        logger.info(f"✅ Mainnet Auth Success! Permissions: {resp.get('result', {}).get('permissions')}")
    except Exception as e:
        logger.error(f"❌ Mainnet Failed: {str(e)}")

    # 2. Try Testnet
    logger.info("------------- Testing TESTNET -------------")
    try:
        session_test = HTTP(
            testnet=True,
            api_key=api_key,
            api_secret=api_secret,
        )
        resp = session_test.get_api_key_information()
        logger.info(f"✅ Testnet Auth Success! Permissions: {resp.get('result', {}).get('permissions')}")
    except Exception as e:
        logger.error(f"❌ Testnet Failed: {str(e)}")

if __name__ == "__main__":
    test_connection()
