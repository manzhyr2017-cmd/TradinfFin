
import os
import time
from bybit_client import BybitClient, BybitCategory

client = BybitClient(
    api_key=os.getenv("BYBIT_API_KEY"),
    api_secret=os.getenv("BYBIT_API_SECRET"),
    demo_trading=True
)

symbols_to_check = ["BTCUSDT", "ETHUSDT", "SHIBUSDT", "PEPEUSDT", "1000PEPEUSDT", "SIRENUSDT", "BONKUSDT", "1000BONKUSDT"]

print(f"{'Symbol':<15} | {'QtyStep':<15} | {'MinQty':<15} | {'MaxQty':<15} | {'Price':<10}")
print("-" * 80)

for symbol in symbols_to_check:
    try:
        info = client.get_instrument_info(symbol)
        ticker = client.get_ticker(symbol)
        lsf = info.get('lotSizeFilter', {})
        print(f"{symbol:<15} | {lsf.get('qtyStep', 'N/A'):<15} | {lsf.get('minOrderQty', 'N/A'):<15} | {lsf.get('maxOrderQty', 'N/A'):<15} | {ticker.get('price', 0):<10}")
    except Exception as e:
        print(f"{symbol:<15} | Error: {e}")
