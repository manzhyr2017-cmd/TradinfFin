import json
import logging
from typing import Callable, Optional
from pybit.unified_trading import WebSocket
import config

log = logging.getLogger("GridBot")

class OrderWebSocket:
    """
    Subscribes to order updates via WebSocket for real-time notifications.
    """
    def __init__(self, on_order_filled: Callable[[dict], None], on_order_cancelled: Callable[[dict], None]):
        self.on_filled = on_order_filled
        self.on_cancelled = on_order_cancelled
        self.ws: Optional[WebSocket] = None
        self._running = False

    def start(self):
        self.ws = WebSocket(
            testnet=False,
            demo=config.BYBIT_DEMO,
            channel_type="private",
            api_key=config.BYBIT_API_KEY,
            api_secret=config.BYBIT_API_SECRET
        )
        self.ws.order_stream(callback=self._handle_order_update)
        self._running = True
        log.info("🔌 Order WebSocket connected")

    def _handle_order_update(self, message: dict):
        try:
            if "data" not in message:
                return
            for order in message["data"]:
                if order.get("symbol") != config.SYMBOL:
                    continue
                status = order.get("orderStatus")
                order_data = {
                    "orderId": order.get("orderId"),
                    "side": order.get("side"),
                    "avgPrice": order.get("avgPrice", order.get("price", "0")),
                    "qty": order.get("qty", "0"),
                    "orderStatus": status,
                }
                if status == "Filled":
                    self.on_filled(order_data)
                elif status in ("Cancelled", "Rejected", "Deactivated"):
                    self.on_cancelled(order_data)
        except Exception as e:
            log.error(f"Order WS Error: {e}")

    def stop(self):
        self._running = False
        if self.ws:
            self.ws.exit()

class TickerWebSocket:
    """
    Subscribes to real-time price updates.
    """
    def __init__(self, on_price_update: Callable[[str, str], None]):
        self.on_price = on_price_update
        self.ws: Optional[WebSocket] = None

    def start(self):
        self.ws = WebSocket(
            testnet=False,
            demo=False, # Публичные данные берем из реального рынка (они идентичны)
            channel_type=config.CATEGORY
        )
        self.ws.ticker_stream(symbol=config.SYMBOL, callback=self._handle_ticker)
        log.info(f"📡 Ticker WS connected: {config.SYMBOL}")

    def _handle_ticker(self, message: dict):
        try:
            if "data" in message:
                data = message["data"]
                ts = message.get("ts") # Bybit WS ticker usually has 'ts' field
                self.on_price(data.get("lastPrice", "0"), data.get("volume24h", "0"), timestamp=ts)
        except Exception as e:
            log.error(f"Ticker WS Error: {e}")

    def stop(self):
        if self.ws:
            self.ws.exit()
