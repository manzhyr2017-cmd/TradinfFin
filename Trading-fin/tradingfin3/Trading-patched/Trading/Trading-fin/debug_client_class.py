
import os
import asyncio
from dotenv import load_dotenv
from bybit_client import BybitClient, BybitCategory

# Load env same as server
load_dotenv(override=True)

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
PROXY = os.getenv("HTTP_PROXY")

print(f"KEY: {API_KEY[:5]}...")
print(f"PROXY: {PROXY}")

async def test():
    client = BybitClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        testnet=False,
        demo_trading=False,
        proxy=PROXY
    )
    
    print("\n--- Testing get_open_positions ---")
    try:
        # Call the synchronous method directly
        pos = client.get_open_positions()
        print(f"Positions Count: {len(pos)}")
        print(f"Positions Data: {pos}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
