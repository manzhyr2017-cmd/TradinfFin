import logging
import os
import time
from decimal import Decimal
from typing import List, Dict, Optional, Any
from pybit.unified_trading import HTTP
import config

log = logging.getLogger("BybitClient")

class BybitClient:
    """
    Улучшенный клиент Bybit для работы с Unified Trading Account.
    Поддерживает Spot и Linear (преймущественно Spot для сетки).
    """
    
    def __init__(self):
        if config.API_PROXY:
            os.environ['HTTP_PROXY'] = config.API_PROXY
            os.environ['HTTPS_PROXY'] = config.API_PROXY
            log.info(f"🌐 Proxy set to {config.API_PROXY}")

        self.session = HTTP(
            testnet=False, # Используем Mainnet или Demo Mainnet
            demo=config.BYBIT_DEMO, # Специальный флаг для UTA Demo
            api_key=config.BYBIT_API_KEY,
            api_secret=config.BYBIT_API_SECRET
        )
        self.symbol = config.SYMBOL
        self.category = config.CATEGORY
        self._instr_cache = {}
        self._position_mode = None # 0 = One-Way, 3 = Hedge
        
    def get_position_mode(self) -> int:
        """Определить текущий режим позиции (One-Way=0 или Hedge=3)."""
        if self._position_mode is not None:
            return self._position_mode
        try:
            # Пытаемся получить информацию о позиции для символа
            res = self.get_position()
            # Если позиций больше одной на символ (или есть поле positionIdx > 0)
            if any(p.get('positionIdx', 0) > 0 for p in res):
                self._position_mode = 3 # Hedge Mode
            else:
                self._position_mode = 0 # One-Way Mode
            log.info(f"🎯 Position Mode detected: {'Hedge' if self._position_mode == 3 else 'One-Way'}")
            return self._position_mode
        except:
            return 0
        
    def get_position(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить текущие позиции."""
        try:
            response = self.session.get_positions(
                category=self.category,
                symbol=symbol or self.symbol
            )
            return response['result']['list']
        except Exception as e:
            log.error(f"Error fetching position: {e}")
            return []

    def get_price(self, symbol: Optional[str] = None) -> Decimal:
        """Получить текущую рыночную цену (last price)."""
        try:
            response = self.session.get_tickers(
                category=self.category,
                symbol=symbol or self.symbol
            )
            if not response.get('result', {}).get('list'):
                raise ValueError(f"Empty ticker list for {symbol or self.symbol}")
            price = response['result']['list'][0]['lastPrice']
            return Decimal(str(price))
        except Exception as e:
            log.error(f"Error fetching price: {e}")
            raise

    def get_instrument_info(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Получить правила торговли (min_qty, tick_size)."""
        symbol = symbol or self.symbol
        # Кэшируем на время сессии
        if hasattr(self, '_instr_cache') and symbol in self._instr_cache:
            return self._instr_cache[symbol]
            
        try:
            response = self.session.get_instruments_info(
                category=self.category,
                symbol=symbol
            )
            if not response.get('result', {}).get('list'):
                raise ValueError(f"Empty instrument info for {symbol}")
            item = response['result']['list'][0]
            
            # Разные поля для разных категорий
            lot_size = item.get('lotSizeFilter', {})
            price_filter = item.get('priceFilter', {})
            
            info = {
                "min_qty": Decimal(str(lot_size.get('minOrderQty', '0'))),
                "qty_step": Decimal(str(lot_size.get('qtyStep', '0'))),
                "tick_size": Decimal(str(price_filter.get('tickSize', '0.01'))),
                "raw": item
            }
            if not hasattr(self, '_instr_cache'): self._instr_cache = {}
            self._instr_cache[symbol] = info
            return info
        except Exception as e:
            log.error(f"Error fetching instrument info for {symbol}: {e}")
            
            # Хардкод-фоллбэки для популярных монет (последний рубеж)
            hardcoded = {
                "BTCUSDT": {"min_qty": Decimal("0.001"), "qty_step": Decimal("0.001"), "tick_size": Decimal("0.1")},
                "ETHUSDT": {"min_qty": Decimal("0.01"), "qty_step": Decimal("0.01"), "tick_size": Decimal("0.01")},
                "BNBUSDT": {"min_qty": Decimal("0.01"), "qty_step": Decimal("0.01"), "tick_size": Decimal("0.01")},
                "SOLUSDT": {"min_qty": Decimal("0.1"), "qty_step": Decimal("0.1"), "tick_size": Decimal("0.01")},
            }
            if symbol in hardcoded:
                return hardcoded[symbol]
                
            return {
                "min_qty": Decimal("0.01"), 
                "qty_step": Decimal("0.01"),
                "tick_size": Decimal("0.01")
            }

    def get_orderbook(self, limit: int = 50, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Получить стакан ордеров."""
        try:
            response = self.session.get_orderbook(
                category=self.category,
                symbol=symbol or self.symbol,
                limit=limit
            )
            return response['result']
        except Exception as e:
            log.error(f"Error fetching orderbook: {e}")
            return {}

    def get_klines(self, interval: str = "15", limit: int = 200, symbol: Optional[str] = None) -> List[List[Any]]:
        """
        Получить исторические свечи.
        Интервалы: 1, 3, 5, 15, 30, 60, 120, 240, D, W, M
        """
        try:
            response = self.session.get_kline(
                category=self.category,
                symbol=symbol or self.symbol,
                interval=interval,
                limit=limit
            )
            # Список [start_time, open, high, low, close, volume, turnover]
            return response['result']['list']
        except Exception as e:
            log.error(f"Error fetching klines: {e}")
            return []

    def get_balance(self, coin: str = "USDT") -> Decimal:
        """Получить доступный баланс монеты."""
        try:
            response = self.session.get_wallet_balance(
                accountType="UNIFIED",
                coin=coin
            )
            # Для UTA баланс находится в списке монет
            if not response.get('result', {}).get('list'):
                return Decimal("0")
            coins = response['result']['list'][0].get('coin', [])
            for c in coins:
                if c['coin'] == coin:
                    return Decimal(str(c['walletBalance']))
            return Decimal("0")
        except Exception as e:
            log.error(f"Error fetching balance: {e}")
            return Decimal("0")

    def place_order(
        self, 
        side: str, 
        qty: str, 
        price: str, 
        order_type: str = "Limit",
        post_only: bool = False,
        symbol: Optional[str] = None,
        position_idx: Optional[int] = None
    ) -> Optional[str]:
        """Разместить ордер."""
        try:
            # Авто-детект positionIdx если не указан
            if position_idx is None:
                mode = self.get_position_mode()
                if mode == 3: # Hedge
                    position_idx = 1 if side == "Buy" else 2
                else:
                    position_idx = 0
                    
            params = {
                "category": self.category,
                "symbol": symbol or self.symbol,
                "side": side,
                "orderType": order_type,
                "qty": qty,
                "price": price,
                "timeInForce": "PostOnly" if post_only else "GTC",
                "positionIdx": position_idx
            }
            response = self.session.place_order(**params)
            return response['result']['orderId']
        except Exception as e:
            log.error(f"Error placing order: {e}")
            return None

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> bool:
        """Отменить конкретный ордер."""
        try:
            self.session.cancel_order(
                category=self.category,
                symbol=symbol or self.symbol,
                orderId=order_id
            )
            return True
        except Exception as e:
            log.error(f"Error cancelling order {order_id}: {e}")
            return False

    def cancel_all(self, symbol: Optional[str] = None) -> bool:
        """Отменить все активные ордера по инструменту."""
        try:
            self.session.cancel_all_orders(
                category=self.category,
                symbol=symbol or self.symbol
            )
            return True
        except Exception as e:
            log.error(f"Error cancelling all orders: {e}")
            return False

    def get_active_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получить список всех активных ордеров."""
        try:
            response = self.session.get_open_orders(
                category=self.category,
                symbol=symbol or self.symbol
            )
            return response['result']['list']
        except Exception as e:
            log.error(f"Error fetching open orders: {e}")
            return []
