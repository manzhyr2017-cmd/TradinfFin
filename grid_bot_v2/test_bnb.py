
from core.bybit_client import BybitClient
import config
from decimal import Decimal

client = BybitClient()
info = client.get_instrument_info("BNBUSDT")
print(f"Info for BNBUSDT: {info}")

price = Decimal("661.80")
tick_size = info["tick_size"]
adj_price = (price / tick_size).quantize(Decimal('1')) * tick_size
print(f"Adj Price: {adj_price}")

qty = Decimal("0.02")
qty_step = info["qty_step"]
adj_qty = (qty / qty_step).quantize(Decimal('1')) * qty_step
print(f"Adj Qty (before min): {adj_qty}")
if adj_qty < info["min_qty"]:
    adj_qty = info["min_qty"]
print(f"Adj Qty (after min): {adj_qty}")
