"""
GRID BOT 2026 — Grid Executor
Взаимодействие с Bybit API: ордера, позиции, баланс
"""

import time
from pybit.unified_trading import HTTP
import grid_config as cfg
from logger import logger


class GridExecutor:
    """
    Обёртка над Bybit API для Grid Bot.
    Выставляет/отменяет ордера, получает баланс и позиции.
    """

    def __init__(self):
        self.session = HTTP(
            testnet=cfg.TESTNET,
            api_key=cfg.API_KEY if "dummy" not in cfg.API_KEY else None,
            api_secret=cfg.API_SECRET if "dummy" not in cfg.API_SECRET else None,
            demo=cfg.BYBIT_DEMO,
            recv_window=20000
        )
        self.public_session = HTTP(
            testnet=cfg.TESTNET,
            demo=cfg.BYBIT_DEMO,
            recv_window=20000
        )
        self._symbol_cache = {}
        mode = "DEMO" if cfg.BYBIT_DEMO else ("TESTNET" if cfg.TESTNET else "MAINNET")
        logger.info(f"[GridExecutor] Connected to Bybit ({mode})")

    # === Market Data ===

    def get_price(self, symbol: str = None) -> float:
        """Текущая цена символа"""
        symbol = symbol or cfg.SYMBOL
        if cfg.BYBIT_DEMO:
            return 95000.0  # Dummy price
        try:
            resp = self.public_session.get_tickers(category=cfg.CATEGORY, symbol=symbol)
            if resp['retCode'] == 0:
                return float(resp['result']['list'][0]['lastPrice'])
        except Exception as e:
            logger.error(f"[GridExecutor] Error getting price: {e}")
        return 0.0

    def get_symbol_info(self, symbol: str = None) -> dict:
        """Получает параметры символа: precision, min qty, tick size"""
        symbol = symbol or cfg.SYMBOL
        if symbol in self._symbol_cache:
            return self._symbol_cache[symbol]
        if cfg.BYBIT_DEMO:
             return {
                 'price_precision': 2,
                 'tick_size': 0.1,
                 'qty_step': 0.001,
                 'min_qty': 0.001,
                 'min_notional': 5.0,
             }
        try:
            resp = self.public_session.get_instruments_info(category=cfg.CATEGORY, symbol=symbol)
            if resp['retCode'] == 0:
                info = resp['result']['list'][0]
                result = {
                    'price_precision': int(info.get('priceScale', 2)),
                    'tick_size': float(info.get('priceFilter', {}).get('tickSize', 0.01)),
                    'qty_step': float(info.get('lotSizeFilter', {}).get('qtyStep', 0.001)),
                    'min_qty': float(info.get('lotSizeFilter', {}).get('minOrderQty', 0.001)),
                    'min_notional': float(info.get('lotSizeFilter', {}).get('minNotionalValue', 5)),
                }
                # Вычисляем precision из qty_step
                qs = str(result['qty_step']).rstrip('0')
                result['qty_precision'] = len(qs.split('.')[1]) if '.' in qs else 0
                self._symbol_cache[symbol] = result
                return result
        except Exception as e:
            logger.error(f"[GridExecutor] Error symbol info: {e}")
        return {
            'price_precision': 2, 'tick_size': 0.01,
            'qty_step': 0.001, 'min_qty': 0.001,
            'qty_precision': 3, 'min_notional': 5
        }

    def get_kline(self, symbol: str = None, interval: str = "15", limit: int = 14) -> list:
        """Fetches recent klines for indicator calculations."""
        symbol = symbol or cfg.SYMBOL
        try:
            resp = self.public_session.get_kline(
                category=cfg.CATEGORY,
                symbol=symbol,
                interval=interval,
                limit=limit + 1  # Need previous close for ATR
            )
            if resp['retCode'] == 0:
                # pybit returns latest first, reverse to chronological
                return resp['result']['list'][::-1]
        except Exception as e:
            logger.error(f"[GridExecutor] Kline error: {e}")
        return []

    def get_atr(self, symbol: str = None, period: int = 14) -> float:
        """Calculates Average True Range"""
        symbol = symbol or cfg.SYMBOL
        klines = self.get_kline(symbol, interval="15", limit=period)
        if len(klines) < period + 1:
            return 0.0
            
        true_ranges = []
        for i in range(1, len(klines)):
            high = float(klines[i][2])
            low = float(klines[i][3])
            prev_close = float(klines[i-1][4])
            
            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)
            
        return sum(true_ranges) / len(true_ranges)

    def get_rsi(self, symbol: str = None, period: int = 14) -> float:
        """Calculates Relative Strength Index (RSI)"""
        symbol = symbol or cfg.SYMBOL
        klines = self.get_kline(symbol, interval="15", limit=period) 
        if len(klines) < period + 1:
            return 50.0  # Default neutral
            
        gains = []
        losses = []
        for i in range(1, len(klines)):
            close_curr = float(klines[i][4])
            close_prev = float(klines[i-1][4])
            diff = close_curr - close_prev
            if diff >= 0:
                gains.append(diff)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(diff))
                
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            return 100.0
            
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))

    def get_funding_rate(self, symbol: str = None) -> float:
        """Fetches the current funding rate for the symbol."""
        symbol = symbol or cfg.SYMBOL
        if cfg.BYBIT_DEMO:
            return 0.0001
        try:
            resp = self.session.get_tickers(category=cfg.CATEGORY, symbol=symbol)
            if resp['retCode'] == 0:
                list_data = resp['result'].get('list', [])
                if list_data:
                    return float(list_data[0].get('fundingRate', 0.0))
        except Exception as e:
            logger.error(f"[GridExecutor] Funding rate error: {e}")
        return 0.0

    # === Account ===

    def get_balance(self) -> float:
        """Доступный баланс USDT"""
        try:
            for acc_type in ["UNIFIED", "CONTRACT"]:
                resp = self.session.get_wallet_balance(accountType=acc_type, coin="USDT")
                if resp['retCode'] == 0 and resp['result']['list']:
                    try:
                        coin_list = resp['result']['list'][0]['coin']
                    except (KeyError, IndexError):
                        logger.error("[GridExecutor] Balance data structure error!")
                        return 0.0

                    for coin_data in coin_list:
                        if coin_data['coin'] == "USDT":
                            return float(coin_data['availableToWithdraw'])
        except Exception as e:
            logger.error(f"[GridExecutor] Ошибка получения баланса: {e}")
        return 0.0

    def get_equity(self) -> float:
        """Полный equity аккаунта (баланс + нереализованный PnL)"""
        try:
            for acc_type in ["UNIFIED", "CONTRACT"]:
                resp = self.session.get_wallet_balance(accountType=acc_type, coin="USDT")
                if resp['retCode'] == 0 and resp['result']['list']:
                    res = resp['result']['list'][0]
                    eq = res.get('totalEquity') or res.get('totalWalletBalance')
                    if eq:
                        return float(eq)
                    for c in res.get('coin', []):
                        if c.get('coin') == 'USDT':
                            return float(c.get('equity', c.get('walletBalance', '0')))
        except Exception as e:
            logger.error(f"[GridExecutor] Ошибка получения equity: {e}")
        return 0.0

    # === Leverage ===

    def set_leverage(self, symbol: str = None, leverage: int = None):
        """Устанавливает плечо"""
        symbol = symbol or cfg.SYMBOL
        leverage = leverage or cfg.LEVERAGE
        try:
            resp = self.session.set_leverage(
                category=cfg.CATEGORY,
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            if resp['retCode'] == 0:
                logger.info(f"[GridExecutor] Leverage set to {leverage}x for {symbol}")
            else:
                logger.warning(f"[GridExecutor] Failed to set leverage: {resp['retMsg']}")
        except Exception as e:
            if "not modified" in str(e).lower() or "110043" in str(e):
                logger.debug(f"[GridExecutor] Leverage {leverage}x already set.")
            else:
                logger.error(f"[GridExecutor] Ошибка установки плеча: {e}")

    # === Order Management ===

    def place_limit_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        price: float,
        reduce_only: bool = False
    ) -> str:
        """
        Выставляет лимитный ордер.
        Возвращает order_id или пустую строку при ошибке.
        """
        info = self.get_symbol_info(symbol)
        p_prec = info['price_precision']
        q_prec = info['qty_precision']

        params = {
            'category': cfg.CATEGORY,
            'symbol': symbol,
            'side': side,
            'orderType': 'Limit',
            'qty': f"{qty:.{q_prec}f}",
            'price': f"{price:.{p_prec}f}",
            'timeInForce': 'GTC',
            'positionIdx': 0,
        }
        if reduce_only:
            params['reduceOnly'] = True

        try:
            resp = self.session.place_order(**params)
            if resp['retCode'] == 0:
                oid = resp['result']['orderId']
                logger.info(f"[GridExecutor] ✅ {side} {qty} {symbol} @ {price} → {oid[:8]}...")
                return oid
            else:
                logger.error(f"[GridExecutor] ❌ Order failed: {resp['retMsg']}")
                return ""
        except Exception as e:
            logger.error(f"[GridExecutor] ❌ Order exception: {e}")
            return ""

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Отменяет конкретный ордер"""
        try:
            resp = self.session.cancel_order(
                category=cfg.CATEGORY,
                symbol=symbol,
                orderId=order_id
            )
            if resp['retCode'] == 0:
                logger.info(f"[GridExecutor] 🗑️ Order {order_id[:8]}... cancelled for {symbol}")
                return True
            else:
                logger.warning(f"[GridExecutor] Failed to cancel order {order_id[:8]}...: {resp['retMsg']}")
                return False
        except Exception as e:
            logger.error(f"[GridExecutor] Cancel error: {e}")
            return False

    def cancel_all_orders(self, symbol: str = None) -> bool:
        """Отменяет ВСЕ ордера по символу"""
        symbol = symbol or cfg.SYMBOL
        try:
            resp = self.session.cancel_all_orders(
                category=cfg.CATEGORY,
                symbol=symbol
            )
            if resp['retCode'] == 0:
                logger.info(f"[GridExecutor] 🗑️ All orders cancelled for {symbol}")
                return True
            else:
                logger.warning(f"[GridExecutor] Cancel all error: {resp['retMsg']}")
                return False
        except Exception as e:
            logger.error(f"[GridExecutor] Cancel all exception: {e}")
            return False

    def get_open_orders(self, symbol: str = None) -> list:
        """Список активных ордеров"""
        symbol = symbol or cfg.SYMBOL
        try:
            resp = self.session.get_open_orders(
                category=cfg.CATEGORY,
                symbol=symbol,
                limit=50
            )
            if resp['retCode'] == 0:
                return [
                    {
                        'order_id': o['orderId'],
                        'side': o['side'],
                        'price': float(o['price']),
                        'qty': float(o['qty']),
                        'status': o['orderStatus'],
                    }
                    for o in resp['result']['list']
                ]
        except Exception as e:
            print(f"[GridExecutor] Open orders error: {e}")
        return []

    # === Position Management ===

    def get_positions(self, symbol: str = None) -> list:
        """Текущие открытые позиции"""
        symbol = symbol or cfg.SYMBOL
        try:
            resp = self.session.get_positions(
                category=cfg.CATEGORY,
                symbol=symbol
            )
            if resp['retCode'] == 0:
                return [
                    {
                        'symbol': p['symbol'],
                        'side': p['side'],
                        'size': float(p['size']),
                        'entry_price': float(p['avgPrice']),
                        'unrealized_pnl': float(p['unrealisedPnl']),
                        'leverage': p['leverage'],
                    }
                    for p in resp['result']['list']
                    if float(p['size']) > 0
                ]
        except Exception as e:
            print(f"[GridExecutor] Positions error: {e}")
        return []

    def close_all_positions(self, symbol: str = None) -> bool:
        """Закрывает все позиции маркет-ордером"""
        symbol = symbol or cfg.SYMBOL
        positions = self.get_positions(symbol)
        if not positions:
            return True

        success = True
        for pos in positions:
            close_side = "Sell" if pos['side'] == "Buy" else "Buy"
            info = self.get_symbol_info(symbol)
            q_prec = info['qty_precision']
            try:
                resp = self.session.place_order(
                    category=cfg.CATEGORY,
                    symbol=symbol,
                    side=close_side,
                    orderType='Market',
                    qty=f"{pos['size']:.{q_prec}f}",
                    positionIdx=0,
                    reduceOnly=True
                )
                if resp['retCode'] == 0:
                    print(f"[GridExecutor] 🔒 Closed {pos['side']} {pos['size']} {symbol}")
                else:
                    print(f"[GridExecutor] Close error: {resp['retMsg']}")
                    success = False
            except Exception as e:
                print(f"[GridExecutor] Close exception: {e}")
                success = False
        return success

    # === Closed PnL ===

    def get_recent_closed_pnl(self, symbol: str = None, limit: int = 10) -> list:
        """Последние закрытые сделки с PnL"""
        symbol = symbol or cfg.SYMBOL
        try:
            resp = self.session.get_closed_pnl(
                category=cfg.CATEGORY,
                symbol=symbol,
                limit=limit
            )
            if resp['retCode'] == 0:
                return [
                    {
                        'symbol': r['symbol'],
                        'side': r['side'],
                        'qty': float(r['qty']),
                        'pnl': float(r['closedPnl']),
                        'entry': float(r['avgEntryPrice']),
                        'exit': float(r['avgExitPrice']),
                        'time': r['updatedTime'],
                    }
                    for r in resp['result']['list']
                ]
        except Exception as e:
            print(f"[GridExecutor] Closed PnL error: {e}")
        return []
