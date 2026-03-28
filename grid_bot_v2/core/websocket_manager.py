import time
import threading
import logging
from typing import Callable, Optional, Tuple, List, Dict
from datetime import datetime

from pybit.unified_trading import WebSocket

import config

log = logging.getLogger("GridBot")


class RobustWebSocket:
    """
    Обёртка над pybit WebSocket с автоматическим
    reconnect и защитой от крашей.
    
    Решает КОНКРЕТНО ту ошибку:
    WebSocketConnectionClosedException: Connection is already closed.
    """

    def __init__(
        self,
        channel_type: str = "private",
        max_reconnect_attempts: int = 50,
        reconnect_delay_sec: float = 3.0,
        heartbeat_timeout_sec: float = 30.0,
    ):
        self.channel_type = channel_type
        self.max_reconnects = max_reconnect_attempts
        self.reconnect_delay = reconnect_delay_sec
        self.heartbeat_timeout = heartbeat_timeout_sec

        self._ws: Optional[WebSocket] = None
        self._callbacks = {}          # stream_name → callback
        self._running = False
        self._lock = threading.Lock()
        self._reconnect_count = 0
        self._last_message_time = datetime.utcnow()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._connected = False

    def start(self, symbol: Optional[str] = None):
        """Запускаем WebSocket с защитой."""
        self._running = True
        self._connect()
        self._start_heartbeat()

    def _connect(self):
        """Создаём новое WebSocket соединение."""
        with self._lock:
            # ① Убиваем старое соединение
            self._safe_close()

            # ② Создаём новое
            try:
                is_testnet = getattr(config, "BYBIT_TESTNET", False)
                if self.channel_type == "private":
                    self._ws = WebSocket(
                        testnet=is_testnet,
                        channel_type="private",
                        api_key=config.BYBIT_API_KEY,
                        api_secret=config.BYBIT_API_SECRET,
                    )
                else:
                    self._ws = WebSocket(
                        testnet=is_testnet,
                        channel_type=self.channel_type,
                    )

                self._connected = True
                self._last_message_time = datetime.utcnow()
                self._reconnect_count = 0

                log.info(
                    f"🔌 WS [{self.channel_type}] подключён"
                )

                # ③ Переподписываемся на все стримы
                self._resubscribe()

            except Exception as e:
                self._connected = False
                log.error(f"🔌 WS connect error: {e}")
                self._schedule_reconnect()

    def _safe_close(self):
        """
        Безопасное закрытие старого соединения.
        """
        if self._ws is not None:
            try:
                if hasattr(self._ws, 'ws') and self._ws.ws:
                    try:
                        self._ws.ws.close()
                    except Exception:
                        pass
                try:
                    self._ws.exit()
                except Exception:
                    pass
            except Exception as e:
                log.debug(f"WS close cleanup: {e}")
            finally:
                self._ws = None
                self._connected = False
            time.sleep(0.5)

    def _resubscribe(self):
        """Переподписываемся после reconnect."""
        if not self._ws:
            return

        for stream_name, callback in self._callbacks.items():
            try:
                if stream_name == "order":
                    self._ws.order_stream(
                        callback=self._safe_callback(callback)
                    )
                elif stream_name == "ticker":
                    self._ws.ticker_stream(
                        symbol=config.SYMBOL,
                        callback=self._safe_callback(callback),
                    )
                elif stream_name == "trade":
                    self._ws.trade_stream(
                        symbol=config.SYMBOL,
                        callback=self._safe_callback(callback),
                    )
                elif stream_name == "orderbook":
                    self._ws.orderbook_stream(
                        depth=50,
                        symbol=config.SYMBOL,
                        callback=self._safe_callback(callback),
                    )

                log.info(f"📡 Переподписка: {stream_name}")

            except Exception as e:
                log.error(f"Resubscribe error [{stream_name}]: {e}")

    def _safe_callback(self, callback: Callable) -> Callable:
        """Оборачиваем в try/except."""
        def wrapper(message):
            try:
                self._last_message_time = datetime.utcnow()
                callback(message)
            except Exception as e:
                log.error(
                    f"WS callback error: {e}",
                    exc_info=True,
                )
        return wrapper

    def subscribe_orders(self, callback: Callable):
        self._callbacks["order"] = callback
        if self._ws and self._connected:
            try:
                self._ws.order_stream(
                    callback=self._safe_callback(callback)
                )
            except Exception as e:
                log.error(f"Order subscribe error: {e}")
                self._schedule_reconnect()

    def subscribe_ticker(self, callback: Callable, symbol: str = None):
        symbol = symbol or config.SYMBOL
        self._callbacks["ticker"] = callback
        if self._ws and self._connected:
            try:
                self._ws.ticker_stream(
                    symbol=symbol,
                    callback=self._safe_callback(callback),
                )
            except Exception as e:
                log.error(f"Ticker subscribe error: {e}")
                self._schedule_reconnect()

    def _start_heartbeat(self):
        """
        Мониторинг здоровья WS.
        
        ВАЖНО: private WS может молчать минутами (нет событий).
        Поэтому для private используем PING проверку,
        а не "время последнего сообщения".
        """
        def heartbeat_loop():
            while self._running:
                try:
                    time.sleep(10)

                    if not self._running:
                        break

                    # ─── Проверка для PUBLIC WS ──────────
                    # (тикер шлёт данные каждую секунду)
                    if self.channel_type in ("spot", "linear"):
                        since_last = (
                            datetime.utcnow() - self._last_message_time
                        ).total_seconds()

                        if since_last > self.heartbeat_timeout:
                            log.warning(
                                f"💓 [{self.channel_type}] "
                                f"нет данных {since_last:.0f}s → reconnect"
                            )
                            self._schedule_reconnect()

                    # ─── Проверка для PRIVATE WS ─────────
                    # (может молчать долго — это нормально)
                    elif self.channel_type == "private":
                        # Проверяем живость через ping
                        if not self._check_ws_alive():
                            log.warning(
                                f"💓 [private] WS не отвечает → reconnect"
                            )
                            self._schedule_reconnect()

                except Exception as e:
                    log.debug(f"Heartbeat error: {e}")

        self._heartbeat_thread = threading.Thread(
            target=heartbeat_loop,
            daemon=True,
            name=f"ws-heartbeat-{self.channel_type}",
        )
        self._heartbeat_thread.start()

    def _check_ws_alive(self) -> bool:
        """
        Проверяем жив ли WebSocket без ожидания данных.
        Для private WS — проверяем сам объект соединения.
        """
        try:
            if self._ws is None:
                return False

            # Проверяем внутренний websocket объект pybit
            if hasattr(self._ws, 'ws') and self._ws.ws:
                ws_inner = self._ws.ws
                if hasattr(ws_inner, 'sock') and ws_inner.sock:
                    return ws_inner.sock.connected
                # Если нет sock — проверяем по-другому
                return True

            return self._connected

        except Exception:
            return False

    def _schedule_reconnect(self):
        if not self._running: return
        self._reconnect_count += 1
        if self._reconnect_count > self.max_reconnects:
            log.critical(f"🔌 WS: достигнут лимит reconnect ({self.max_reconnects})")
            return
        delay = min(self.reconnect_delay * (2 ** (self._reconnect_count - 1)), 60.0)
        log.info(f"🔌 WS reconnect #{self._reconnect_count} через {delay:.1f}s...")
        def reconnect():
            time.sleep(delay)
            if self._running: self._connect()
        threading.Thread(target=reconnect, daemon=True).start()

    def stop(self):
        self._running = False
        with self._lock: self._safe_close()

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None


class WebSocketManager:
    def __init__(self):
        # Private WS: НЕ проверяем по данным (ордера редкие)
        self.private_ws = RobustWebSocket(
            channel_type="private",
            heartbeat_timeout_sec=300.0,   # 5 минут (было 30)
        )
        # Public WS: проверяем часто (тикер шлёт постоянно)
        self.public_ws = RobustWebSocket(
            channel_type="spot",           # config.CATEGORY обычно spot
            heartbeat_timeout_sec=15.0,    # 15 сек — ок для тикера
        )

        self.last_price: Optional[float] = None
        self.last_bid: Optional[float] = None
        self.last_ask: Optional[float] = None
        self._price_lock = threading.Lock()
        self._order_callbacks = []

    def start(self):
        log.info("🔌 WebSocket Manager: запуск...")
        self.private_ws.start()
        self.private_ws.subscribe_orders(self._on_order_update)
        self.public_ws.start()
        self.public_ws.subscribe_ticker(self._on_ticker)

    def on_order_fill(self, callback: Callable):
        self._order_callbacks.append(callback)

    def _on_order_update(self, message: dict):
        try:
            if "data" not in message: return
            for order in message["data"]:
                symbol = order.get("symbol", "")
                if symbol != config.SYMBOL: continue
                status = order.get("orderStatus", "")
                oid = order.get("orderId", "")
                if status == "Filled":
                    log.info(f"⚡ WS Fill: {order.get('side')} @ {order.get('avgPrice', '?')} [{oid[:12]}]")
                    for cb in self._order_callbacks: cb(order)
                elif status in ("Cancelled", "Rejected", "Deactivated"):
                    log.warning(f"❌ WS Cancel: {oid}")
        except Exception as e:
            log.error(f"Order update error: {e}")

    def _on_ticker(self, message: dict):
        try:
            if "data" not in message: return
            data = message["data"]
            with self._price_lock:
                price = data.get("lastPrice")
                if price: self.last_price = float(price)
                bid1 = data.get("bid1Price")
                ask1 = data.get("ask1Price")
                if bid1: self.last_bid = float(bid1)
                if ask1: self.last_ask = float(ask1)
        except Exception as e:
            log.error(f"Ticker update error: {e}")

    def get_price(self) -> Optional[float]:
        with self._price_lock: return self.last_price

    def get_spread(self) -> Optional[Tuple[float, float]]:
        with self._price_lock:
            if self.last_bid and self.last_ask:
                return (self.last_bid, self.last_ask)
        return None

    def stop(self):
        self.private_ws.stop()
        self.public_ws.stop()

    @property
    def is_healthy(self) -> bool:
        return self.private_ws.is_connected and self.public_ws.is_connected
