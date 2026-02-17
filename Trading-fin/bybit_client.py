"""
Bybit Client v2.0
=================
Полная интеграция с Bybit API
- Spot и Derivatives (USDT Perpetual)
- Автоматическое получение ВСЕХ торговых пар
- Multi-Timeframe данные
- Funding Rate, Open Interest, Order Book

Bybit API Docs: https://bybit-exchange.github.io/docs/v5/intro
"""

import pandas as pd
import requests
import json
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import time
import logging
import hmac
import hashlib
import cloudscraper
import asyncio
from functools import partial

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class BybitCategory(Enum):
    """Категории торговых инструментов Bybit"""
    SPOT = "spot"
    LINEAR = "linear"      # USDT Perpetual
    INVERSE = "inverse"    # Inverse Perpetual


@dataclass
class MarketData:
    """Структура для хранения данных по нескольким таймфреймам"""
    symbol: str
    category: BybitCategory
    df_1m: pd.DataFrame
    df_5m: pd.DataFrame
    df_15m: pd.DataFrame
    df_1h: pd.DataFrame
    df_4h: pd.DataFrame
    current_price: float
    stats_24h: Dict[str, Any]
    funding_rate: Optional[float]
    open_interest: Optional[float]
    timestamp: datetime


class BybitClient:
    """
    Универсальный клиент Bybit API v5
    
    Поддержка:
    - Spot торговля
    - USDT Perpetual (Linear)
    - Все торговые пары автоматически
    - Multi-Timeframe данные
    - Market data (funding, OI, orderbook)
    """
    
    BASE_URL = "https://api.bybit.com"
    TESTNET_URL = "https://api-testnet.bybit.com"
    DEMO_URL = "https://api-demo.bybit.com"
    
    # Маппинг таймфреймов Bybit
    TIMEFRAMES = {
        '1m': '1', '3m': '3', '5m': '5', '15m': '15', '30m': '30',
        '1h': '60', '2h': '120', '4h': '240', '6h': '360', '12h': '720',
        '1d': 'D', '1w': 'W', '1M': 'M'
    }
    
    def __init__(
        self, 
        api_key: Optional[str] = None, 
        api_secret: Optional[str] = None,
        testnet: bool = False,
        demo_trading: bool = False,
        demo_mode: bool = False,
        proxy: Optional[str] = None,
        use_binance_data: bool = False,
        category: BybitCategory = BybitCategory.LINEAR
    ):
        """
        Args:
            api_key: API ключ
            api_secret: API секрет
            testnet: Использовать testnet
            demo_trading: Использовать Demo Trading (api-demo.bybit.com)
            demo_mode: Режим демо-торговли (использует fallback баланс)
            proxy: Прокси строка (http://user:pass@ip:port)
            use_binance_data: Использовать данные Binance (для симуляции при блоке Bybit)
            category: Категория
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.use_binance_data = use_binance_data
        self.demo_mode = demo_mode
        
        # Check for fake keys (demo mode without real API)
        self.has_valid_api = False
        if api_key and api_key != "fake_demo_key" and api_secret and api_secret != "fake_demo_secret":
            if len(api_key) > 5 and len(api_secret) > 5:
                self.has_valid_api = True
        
        logger.info(f"BybitClient API Config: has_valid_api={self.has_valid_api}, api_key={api_key[:8] if api_key else 'None'}..., demo_mode={demo_mode}")
        
        if demo_trading:
            self.base_url = self.DEMO_URL
        elif testnet:
            self.base_url = self.TESTNET_URL
        else:
            self.base_url = self.BASE_URL
            
        self.category = category
        self.testnet = testnet
        self.demo_trading = demo_trading
        
        self.proxies = None
        if proxy:
            # Basic validation
            if not proxy.startswith("http"):
                proxy = f"http://{proxy}"
                
            self.proxies = {
                "http": proxy,
                "https": proxy
            }
        
        # Cache
        self._symbols_cache: Optional[List[str]] = None
        self._symbols_cache_time: Optional[datetime] = None
        
        logger.info(f"BybitClient Initialized")
        logger.info(f"  URL: {self.base_url}")
        if proxy:
            logger.info(f"  Proxy: Configured")
        if use_binance_data:
            logger.warning(f"  ⚠️ USING BINANCE DATA FALLBACK (Simulation Only)")
        logger.info(f"  Category: {category.value}")
        
        # Cloudscraper initialization -> REPLACED WITH REQUESTS (Matching test_all_envs.py)
        # self.scraper = cloudscraper.create_scraper()
        self.session = requests.Session()
        
        # Increase connection pool size
        adapter = requests.adapters.HTTPAdapter(pool_connections=100, pool_maxsize=100)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        if self.proxies:
            self.session.proxies = self.proxies
            
        # Disable SSL Warnings
        import urllib3
        urllib3.disable_warnings()
    
    def _request(self, endpoint: str, params: Optional[Dict] = None, method: str = 'GET', signed: bool = False) -> Dict[str, Any]:
        """Универсальный метод для запросов к API Bybit V5"""
        if self.use_binance_data:
            return {'list': []}

        url = f"{self.base_url}{endpoint}"
        if params is None:
            params = {}
            
        # Timing & Headers
        timestamp = str(int(time.time() * 1000))
        recv_window = "30000"
        
        headers = {
            'X-BAPI-API-KEY': self.api_key or "",
            'X-BAPI-TIMESTAMP': timestamp,
            'X-BAPI-RECV-WINDOW': recv_window,
            'User-Agent': 'TradingAI/2.0 (Requests)'
        }
        
        if params is None:
            params = {}
            
        # Auto-inject category if missing for common v5 endpoints
        if 'category' not in params:
            if any(x in endpoint for x in ['/v5/market/', '/v5/order/', '/v5/position/']):
                # Some public endpoints don't strictly require category if symbol is enough, but v5 generally does.
                # Account/Asset/User endpoints do NOT need category.
                params['category'] = self.category.value if hasattr(self.category, 'value') else self.category

        # Prepare Parameters
        if method == 'GET':
            param_str = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
        else:
            param_str = json.dumps(params) if params else ""

        if signed:
            sign_str = f"{timestamp}{self.api_key}{recv_window}{param_str}"
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                sign_str.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            headers['X-BAPI-SIGN'] = signature

        # Request headers for POST
        if method == 'POST':
            headers['Content-Type'] = 'application/json'

        # Retry Logic
        for attempt in range(3):
            try:
                if method == 'GET':
                    if param_str:
                        full_url = f"{url}&{param_str}" if "?" in url else f"{url}?{param_str}"
                    else:
                        full_url = url
                    response = self.session.get(full_url, headers=headers, timeout=25, verify=False)
                else:
                    response = self.session.post(url, data=param_str, headers=headers, timeout=25, verify=False)
                
                response.raise_for_status()
                data = response.json()
                
                ret_code = data.get('retCode')
                if ret_code != 0:
                    err_msg = data.get('retMsg', 'Unknown error')
                    
                    # LOGGING: Detailed Context (Reduced noise for common handling codes)
                    ignored_codes = [110043, 100028, 10032]
                    if ret_code in ignored_codes:
                        logger.debug(f"ℹ️ Bybit Soft Error: {err_msg} (Code: {ret_code}) | Endpoint: {endpoint}")
                    else:
                        logger.error(f"❌ Bybit API Error: {err_msg} (Code: {ret_code})")
                        logger.error(f"   Endpoint: {endpoint} | Method: {method}")
                        logger.error(f"   Params Sent: {params}")
                    
                    # AUTO-SWITCH: Invalid Key (10003) on Live -> Try Demo
                    if ret_code == 10003 and self.base_url != self.DEMO_URL:
                        logger.warning(f"⚠️ Bybit error 10003 on Live. Switching to Demo Trading URL and retrying...")
                        self.base_url = self.DEMO_URL
                        self.demo_trading = True
                        url = f"{self.base_url}{endpoint}"
                        return self._request(endpoint, params, method, signed)
                    
                    # Time sync error
                    if ret_code == 10002 and attempt < 2:
                        time.sleep(1)
                        continue

                    raise Exception(f"Bybit API Error: {err_msg} (Code: {ret_code})")
                
                return data.get('result', {})
                
            except (requests.exceptions.ProxyError, requests.exceptions.Timeout) as e:
                if attempt == 2: raise e
                time.sleep(2 * (attempt + 1))
            except Exception as e:
                if "10003" in str(e) or "Illegal category" in str(e): # Ensure we re-raise these specifically if caught
                     raise e
                if attempt == 2: raise e
                time.sleep(1)

        return {}
            
    async def _request_async(
        self, 
        endpoint: str, 
        params: Optional[Dict] = None, 
        method: str = 'GET',
        signed: bool = False
    ) -> Any:
        """
        Асинхронная обёртка над _request (запускает в ThreadPoolExecutor)
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, 
            lambda: self._request(endpoint, params, method, signed)
        )

    # ============================================================
    # MARKET DATA - Рыночные данные
    # ============================================================

    def get_instrument_info(self, symbol: str) -> Dict:
        """Получает информацию об инструменте (шаг цены, мин. лот)"""
        if self.use_binance_data:
             return {"qtyStep": "0.001", "priceTick": "0.01", "minQty": "0.001"}
             
        # Кэширование можно добавить позже, пока прямой запрос
        params = {'category': self.category.value, 'symbol': symbol}
        data = self._request('/v5/market/instruments-info', params)
        
        if data.get('list'):
            return data['list'][0]
        return {}

    # ============================================================
    # TRADING & ACCOUNT - Торговля и Управление аккаунтом
    # ============================================================

    def get_wallet_balance(self, coin: str = 'USDT', available_only: bool = False) -> float:
        """Получает баланс кошелька (Проверяет UNIFIED -> CONTRACT -> SPOT)"""
        # Если нет валидных API ключей, используем fallback баланс
        if not self.has_valid_api:
            logger.warning(f"💰 No valid API keys, using fallback balance: $10000.00")
            return 10000.0
        
        def safe_float(val, default=0.0):
            if val is None or str(val).strip() == "": return default
            try: return float(val)
            except: return default

        # 1. Try UNIFIED (UTA) - WITHOUT coin parameter for account-level totals
        try:
            # IMPORTANT: Do not filter by coin to get account-level totals (totalAvailableMargin)
            data = self._request('/v5/account/wallet-balance', {
                'accountType': 'UNIFIED'
            }, signed=True)
            
            if data and data.get('list'):
                account = data['list'][0]
                
                # UTA: Priority is global available margin
                if available_only:
                    # totalAvailableMargin - how much we can use for new trades
                    total_avail = account.get('totalAvailableMargin')
                    bal = safe_float(total_avail)
                    if bal > 0:
                        logger.info(f"💰 Balance (UNIFIED totalAvailableMargin): ${bal:.2f}")
                        return bal
                else:
                    total_equity = safe_float(account.get('totalEquity'))
                    if total_equity > 0:
                        logger.info(f"💰 Balance (UNIFIED totalEquity): ${total_equity:.2f}")
                        return total_equity
                
                # Final fallback: find the specific coin in the list
                for asset in account.get('coin', []):
                    if asset['coin'] == coin:
                        bal = safe_float(asset.get('walletBalance'))
                        if bal > 0:
                            logger.info(f"💰 Balance (UNIFIED {coin} walletBalance): ${bal:.2f}")
                            return bal
            else:
                logger.warning(f"💰 UNIFIED response has no list: {data}")
        except Exception as e:
            logger.error(f"💰 UTA balance check failed: {e}")
            pass

        # 2. Try CONTRACT (Derivatives - Classic Account)
        try:
            data = self._request('/v5/account/wallet-balance', {
                'accountType': 'CONTRACT',
                'coin': coin
            }, signed=True)
            
            if data and data.get('list'):
                for account in data['list']:
                    for asset in account.get('coin', []):
                        if asset['coin'] == coin:
                            bal = float(asset.get('walletBalance', 0))
                            if bal > 0:
                                logger.info(f"💰 Balance (CONTRACT): ${bal:.2f}")
                                return bal
        except Exception as e:
            if "10001" in str(e):
                logger.debug("Skipping CONTRACT balance check: account is UNIFIED")
            pass
            
        # 3. Try SPOT (Just in case, though we trade Linear)
        try:
            data = self._request('/v5/account/wallet-balance', {
                'accountType': 'SPOT',
                'coin': coin
            }, signed=True)
            
            if data and data.get('list'):
                for account in data['list']:
                    for asset in account.get('coin', []):
                        if asset['coin'] == coin:
                            bal = float(asset.get('walletBalance', 0))
                            if bal > 0:
                                logger.warning(f"⚠️ Balance found on SPOT (${bal:.2f}), but trading Futures! Please transfer to Derivatives.")
                                return bal
        except Exception as e:
            if "10001" in str(e):
                logger.debug("Skipping SPOT balance check: account is UNIFIED")
            pass

        logger.warning(f"⚠️ Balance check failed. Found $0.00 for {coin}.")
        
        # Absolute fallback for demo/unauthenticated modes
        if self.demo_trading or self.demo_mode or not self.has_valid_api:
            logger.warning(f"💰 Returning fallback balance: $10000.00")
            return 10000.0
            
        return 0.0

    def get_total_equity(self) -> float:
        """Получает полную стоимость аккаунта (Total Equity) для UTA"""
        # Если нет валидных API ключей, используем fallback баланс
        if not self.has_valid_api:
            return 10000.0
        
        def safe_float(val, default=0.0):
            if val is None or str(val).strip() == "": return default
            try: return float(val)
            except: return default

        try:
            data = self._request('/v5/account/wallet-balance', {
                'accountType': 'UNIFIED'
            }, signed=True)
            
            if data and data.get('list'):
                val = data['list'][0].get('totalEquity')
                equity = safe_float(val)
                if equity > 0:
                    return equity
        except Exception as e:
            logger.error(f"💰 Failed to fetch total equity: {e}")
        
        # Fallback to wallet balance
        wallet_bal = self.get_wallet_balance('USDT')
        if wallet_bal > 0:
            return wallet_bal
        
        # Absolute fallback for demo/unauthenticated modes
        if self.demo_trading or self.demo_mode or not self.has_valid_api:
            return 10000.0
            
        return 0.0

        

    def set_leverage(self, symbol: str, leverage: float):
        """Устанавливает кредитное плечо"""
        try:
            self._request('/v5/position/set-leverage', {
                'category': self.category.value,
                'symbol': symbol,
                'buyLeverage': str(leverage),
                'sellLeverage': str(leverage)
            }, method='POST', signed=True)
            logger.info(f"Леверидж {leverage}x установлен для {symbol}")
        except Exception as e:
            # Игнорируем ошибку, если леверидж уже установлен
            if "not modified" not in str(e).lower():
                logger.warning(f"Ошибка установки левериджа для {symbol}: {e}")

    def switch_margin_mode(self, symbol: str, is_isolated: bool = True, leverage: float = 1.0):
        """Переключает режим маржи (Isolated/Cross)"""
        try:
            mode = 1 if is_isolated else 0
            self._request('/v5/position/switch-isolated', {
                'category': self.category.value,
                'symbol': symbol,
                'tradeMode': mode,
                'buyLeverage': str(leverage),
                'sellLeverage': str(leverage)
            }, method='POST', signed=True)
            logger.info(f"Режим маржи {'ISOLATED' if is_isolated else 'CROSS'} установлен для {symbol}")
        except Exception as e:
            err_msg = str(e).lower()
            if "110043" in err_msg or "not modified" in err_msg:
                return True
            if "100028" in err_msg or "unified account is forbidden" in err_msg or "10032" in err_msg:
                logger.debug(f"ℹ️ Margin mode switch skipped for {symbol} (UTA/Demo manages modes automatically)")
                return True
            logger.warning(f"Ошибка смены режима маржи для {symbol}: {e}")

    def set_trading_stop(self, symbol: str, take_profit: Optional[float] = None, stop_loss: Optional[float] = None, trailing_stop: Optional[float] = None, position_idx: int = 0):
        """Устанавливает TP/SL и Trailing Stop для открытой позиции (Bybit V5)"""
        try:
            params = {
                'category': 'linear',
                'symbol': symbol,
                'positionIdx': position_idx,
            }
            
            # 1. Получаем точность цены (tickSize)
            tick_size = 0.00001
            try:
                info = self.get_instrument_info(symbol)
                tick_str = info.get('priceFilter', {}).get('tickSize', '0.00001')
                tick_size = float(tick_str)
            except: pass
            
            def round_price(p):
                from decimal import Decimal, ROUND_HALF_UP
                d_p = Decimal(str(p))
                d_tick = Decimal(str(tick_size))
                return str(d_p.quantize(d_tick, rounding=ROUND_HALF_UP))

            if take_profit:
                params['takeProfit'] = round_price(take_profit)
            if stop_loss:
                params['stopLoss'] = round_price(stop_loss)
            if trailing_stop and trailing_stop > 0:
                 params['trailingStop'] = round_price(trailing_stop)
                
            if 'takeProfit' not in params and 'stopLoss' not in params and 'trailingStop' not in params:
                return False

            logger.info(f"🛡️ Enforcing TP/SL/Trailing for {symbol}: TP={params.get('takeProfit')}, SL={params.get('stopLoss')}, TS={params.get('trailingStop')}")
            return self._request('/v5/position/trading-stop', params, method='POST', signed=True)
            
        except Exception as e:
            logger.error(f"❌ Failed to set trading stop for {symbol}: {e}")
            return None

    def cancel_all_orders(self, symbol: str = "") -> bool:
        """Отменяет все ордера. Если symbol пуст, отменяет по settleCoin=USDT"""
        if self.use_binance_data:
            return True
            
        try:
            params = {
                'category': self.category.value,
            }
            if symbol:
                params['symbol'] = symbol
            else:
                params['settleCoin'] = 'USDT' # Cancel globally for USDT pairs

            self._request('/v5/order/cancel-all', params, method='POST', signed=True)
            logger.info(f"Отменены все ордера {'для ' + symbol if symbol else 'GLOBAL (USDT)'}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel all orders: {e}")
            return False

    def place_order(
        self,
        symbol: str,
        side: str,  # Buy / Sell
        qty: float,
        price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_type: str = None, # Changed default to None to allow auto-detect
        reduce_only: bool = False
    ) -> Dict[str, Any]:
        """
        Размещает ордер.
        Если price не указана -> Market.
        Если qty <= 0 -> Считаем риск от депозита (5% от баланса с плечом 10x по умолчанию).
        """
        # 1. Auto-detect Order Type
        if not order_type:
            order_type = 'Limit' if price else 'Market'
            
        # 2. Auto-calculate Qty if missing
        if qty <= 0:
            try:
                # Получаем цену (нужна для расчета)
                current_price = price if price else self.get_kline(symbol, '1m', 1).iloc[-1]['close']
                balance = self.get_wallet_balance('USDT')
                
                # Риск менеджмент: 5% от депозита в маржу. 
                # Пример: Депо $100. Риск $5. Плечо 10x -> Позиция $50.
                risk_amount = balance * 0.05 
                leverage = 10 # Hardcoded safe leverage assumption
                position_value = risk_amount * leverage
                
                # Qty = Value / Price
                qty = position_value / current_price
                
                # Rounding based on instrument precision
                qty_step = 0.001
                min_qty = 0.001
                try:
                    info = self.get_instrument_info(symbol)
                    qty_step = float(info.get('lotSizeFilter', {}).get('qtyStep', '0.001'))
                    min_qty = float(info.get('lotSizeFilter', {}).get('minOrderQty', '0.001'))
                except:
                    pass
                
                # Round to qty_step
                from decimal import Decimal, ROUND_FLOOR
                qty_dec = Decimal(str(qty)).quantize(Decimal(str(qty_step)), rounding=ROUND_FLOOR)
                qty = float(qty_dec)
                
                # Enforce minimum
                if qty < min_qty:
                    logger.warning(f"⚠️ Adjusted qty {qty} to min allowed {min_qty} for {symbol}")
                    qty = min_qty
                
                logger.info(f"⚖️ Auto-calculated Qty: {qty} ({symbol} @ {current_price})")
            except Exception as e:
                logger.error(f"Failed to auto-calc qty: {e}")
                raise ValueError("Qty is 0 and auto-calc failed")

        params = {
            'category': self.category.value,
            'symbol': symbol,
            'side': side.capitalize(),
            'orderType': order_type.capitalize(),
            'qty': str(qty),
        }
        
        if price and order_type.lower() == 'limit':
            params['price'] = str(price)
            
        # --- NEW: TP/SL ROUNDING ---
        if stop_loss or take_profit:
            try:
                info = self.get_instrument_info(symbol)
                tick_str = info.get('priceFilter', {}).get('tickSize', '0.00001')
                tick_size = float(tick_str)
                
                from decimal import Decimal, ROUND_HALF_UP
                def round_p(p):
                    d_p = Decimal(str(p))
                    d_tick = Decimal(str(tick_size))
                    return str(d_p.quantize(d_tick, rounding=ROUND_HALF_UP))
                
                if stop_loss:
                    params['stopLoss'] = round_p(stop_loss)
                if take_profit:
                    params['takeProfit'] = round_p(take_profit)
            except:
                if stop_loss: params['stopLoss'] = str(stop_loss)
                if take_profit: params['takeProfit'] = str(take_profit)
            
        if reduce_only:
            params['reduceOnly'] = True
            
        logger.info(f"Отправка ордера: {side} {qty} {symbol} @ {price or 'Market'}")
        
        return self._request('/v5/order/create', params, method='POST', signed=True)

    def get_open_positions(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получает открытые позиции (Оптимизировано для Unified Trading Account)"""
        if self.use_binance_data:
             return []
             
        try:
            # Для UTA/Linear обязательно категория и расчетная монета
            params = {
                'category': self.category.value,
            }
            if symbol:
                params['symbol'] = symbol
            else:
                params['settleCoin'] = 'USDT'
                params['limit'] = 200  # Fetch more positions at once
            
            data = self._request('/v5/position/list', params, signed=True)
            
            positions = []
            if data and data.get('list'):
                def safe_float(val, default=0.0):
                    if val is None or val == "": return default
                    try: return float(val)
                    except: return default

                for item in data.get('list', []):
                    size = safe_float(item.get('size'))
                    if size != 0: 
                        positions.append({
                            'symbol': item['symbol'],
                            'side': item['side'],
                            'size': abs(size),
                            'entry_price': safe_float(item.get('avgPrice')),
                            'mark_price': safe_float(item.get('markPrice')),
                            'unrealised_pnl': safe_float(item.get('unrealisedPnl')),
                            'leverage': safe_float(item.get('leverage', 1)),
                            'stop_loss': safe_float(item.get('stopLoss')),
                            'take_profit': safe_float(item.get('takeProfit')),
                            'trailing_stop': safe_float(item.get('trailingStop', 0)),
                            'position_idx': int(item.get('positionIdx', 0)),
                            'created_time': int(item.get('createdTime', 0))
                        })
            
            if not symbol:
                logger.info(f"📊 Найдено активных позиций (UTA): {len(positions)}")
            return positions
            
        except Exception as e:
            logger.error(f"Error fetching open positions (UTA): {e}")
            return []

    
    # ============================================================
    # SYMBOLS - Получение всех торговых пар
    # ============================================================
    
    def get_all_symbols(
        self, 
        quote_coin: str = 'USDT',
        min_volume_24h: float = 0,
        status: str = 'Trading'
    ) -> List[Dict[str, Any]]:
        """
        Получает ВСЕ доступные торговые пары
        
        Args:
            quote_coin: Котировочная валюта (USDT, USDC, BTC)
            min_volume_24h: Минимальный объём за 24h в USD
            status: Статус инструмента (Trading, Settling, etc)
        
        Returns:
            Список словарей с информацией о каждом символе
        """
        data = self._request('/v5/market/instruments-info', {
            'category': self.category.value
        })
        
        symbols = []
        
        for item in data.get('list', []):
            # Фильтруем по котировочной валюте
            if quote_coin and item.get('quoteCoin') != quote_coin:
                continue
            
            # Фильтруем по статусу
            if status and item.get('status') != status:
                continue
            
            symbols.append({
                'symbol': item['symbol'],
                'base_coin': item.get('baseCoin'),
                'quote_coin': item.get('quoteCoin'),
                'status': item.get('status'),
                'launch_time': item.get('launchTime'),
                'min_order_qty': float(item.get('lotSizeFilter', {}).get('minOrderQty', 0)),
                'tick_size': float(item.get('priceFilter', {}).get('tickSize', 0))
            })
        
        logger.info(f"Найдено {len(symbols)} торговых пар ({quote_coin})")
        return symbols
    
    def get_symbol_list(self, quote_coin: str = 'USDT') -> List[str]:
        """
        Получает список символов (только названия)
        С кэшированием на 1 час
        """
        now = datetime.now()
        
        # Проверяем кэш
        if (self._symbols_cache and self._symbols_cache_time and 
            (now - self._symbols_cache_time).seconds < 3600):
            return self._symbols_cache
        
        symbols_data = self.get_all_symbols(quote_coin=quote_coin)
        self._symbols_cache = [s['symbol'] for s in symbols_data]
        self._symbols_cache_time = now
        
        return self._symbols_cache
    
    def get_top_symbols_by_volume(
        self, 
        quote_coin: str = 'USDT',
        top_n: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Получает топ символов по объёму за 24h
        """
        if self.use_binance_data:
            return self._get_binance_top_symbols(quote_coin, top_n)

        # Получаем тикеры с объёмами
        data = self._request('/v5/market/tickers', {
            'category': self.category.value
        })
        
        tickers = []
        for item in data.get('list', []):
            symbol = item['symbol']
            
            # Фильтруем по котировочной валюте
            if quote_coin and not symbol.endswith(quote_coin):
                continue
            
            try:
                volume_24h = float(item.get('turnover24h', 0))  # В USD
                tickers.append({
                    'symbol': symbol,
                    'price': float(item.get('lastPrice', 0)),
                    'change_24h': float(item.get('price24hPcnt', 0)) * 100,
                    'volume_24h': volume_24h,
                    'high_24h': float(item.get('highPrice24h', 0)),
                    'low_24h': float(item.get('lowPrice24h', 0))
                })
            except (ValueError, TypeError):
                continue
        
        # Сортируем по объёму
        tickers.sort(key=lambda x: x['volume_24h'], reverse=True)
        
        return tickers[:top_n]

    def get_top_volatile_coins(
        self,
        quote_coin: str = 'USDT',
        top_n: int = 15,
        min_volume: float = 10_000_000  # Min $10M volume to avoid shitcoins
    ) -> List[Dict[str, Any]]:
        """
        Получает топ монет по волатильности (изменению цены).
        """
        # 1. Get Tickers
        if self.use_binance_data:
            return self._get_binance_top_symbols(quote_coin, top_n) # Fallback

        try:
            data = self._request('/v5/market/tickers', {
                'category': self.category.value
            })
            if not data or not data.get('list'):
                logger.warning("⚠️ Bybit tickers empty or failed, trying Binance fallback...")
                return self._get_binance_top_symbols(quote_coin, top_n)
        except Exception as e:
            logger.error(f"⚠️ Bybit tickers request failed ({e}), trying Binance fallback...")
            return self._get_binance_top_symbols(quote_coin, top_n)
        
        candidates = []
        for item in data.get('list', []):
            symbol = item['symbol']
            if quote_coin and not symbol.endswith(quote_coin):
                continue
                
            try:
                vol_usd = float(item.get('turnover24h', 0))
                if vol_usd < min_volume:
                    continue
                    
                price_change_pct = abs(float(item.get('price24hPcnt', 0))) # Absolute change
                
                candidates.append({
                    'symbol': symbol,
                    'price': float(item.get('lastPrice', 0)),
                    'change_24h': float(item.get('price24hPcnt', 0)) * 100,
                    'abs_change': price_change_pct,
                    'volume_24h': vol_usd
                })
            except:
                continue
                
        # Sort by absolute volatility (biggest movers, up or down)
        candidates.sort(key=lambda x: x['abs_change'], reverse=True)
        
        logger.info(f"🌪️ Top {top_n} Volatile Coins fetched (Max: {candidates[0]['change_24h']:.2f}%)")
        return candidates[:top_n]

    def _get_binance_top_symbols(self, quote_coin: str, top_n: int) -> List[Dict[str, Any]]:
        """Fallback to Binance Tickers list"""
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            resp = requests.get(url, timeout=15, proxies=self.proxies)
            data = resp.json()
            
            if not isinstance(data, list):
                logger.error("Binance all tickers error")
                return []
                
            tickers = []
            for item in data:
                symbol = item['symbol']
                # Binance symbols are like BTCUSDT. Bybit too.
                # Filter by quote coin
                if quote_coin and not symbol.endswith(quote_coin):
                    continue
                    
                # Exclude leveraged tokens or weird pairs if needed (UP/DOWN/BEAR/BULL)
                # But for now simple filter
                
                try:
                    # In Binance: volume=base, quoteVolume=quote (USD)
                    volume_usd = float(item.get('quoteVolume', 0))
                    
                    tickers.append({
                        'symbol': symbol,
                        'price': float(item.get('lastPrice', 0)),
                        'change_24h': float(item.get('priceChangePercent', 0)),
                        'high_24h': float(item.get('highPrice', 0)),
                        'low_24h': float(item.get('lowPrice', 0)),
                        'volume_24h': volume_usd, # Use Quote Usage as Volume 24h USD
                        'turnover_24h': volume_usd
                    })
                except:
                    continue
                    
            # Sort
            tickers.sort(key=lambda x: x['volume_24h'], reverse=True)
            return tickers[:top_n]
            
        except Exception as e:
            logger.error(f"Binance Top Symbols Fallback Error: {e}")
            logger.error(f"Binance Top Symbols Fallback Error: {e}")
            return []

    def get_closed_pnl(self, symbol: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch Closed PnL history.
        """
        params = {
            'category': self.category.value,
            'limit': limit
        }
        if symbol:
            params['symbol'] = symbol
            
        data = self._request('/v5/position/closed-pnl', params, signed=True)
        return data.get('list', [])
    
    # ============================================================
    # KLINES - Исторические данные
    # ============================================================
    
    def get_kline(self, *args, **kwargs) -> pd.DataFrame:
        """Alias for get_klines (Legacy support)"""
        return self.get_klines(*args, **kwargs)
    
    def get_klines(
        self,
        symbol: str,
        interval: str = '15m',
        limit: int = 200,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Получает исторические свечи (OHLCV)
        
        Args:
            symbol: Торговая пара (например 'BTCUSDT')
            interval: Таймфрейм ('1m', '5m', '15m', '1h', '4h', '1d')
            limit: Количество свечей (макс 1000)
            start_time: Начало периода
            end_time: Конец периода
        
        Returns:
            DataFrame с колонками [time, open, high, low, close, volume]
        """
        if interval not in self.TIMEFRAMES:
            raise ValueError(f"Неподдерживаемый таймфрейм: {interval}")
        
        if self.use_binance_data:
            return self._get_binance_klines(symbol, interval, limit)

        params = {
            'category': self.category.value,
            'symbol': symbol,
            'interval': self.TIMEFRAMES[interval],
            'limit': min(limit, 1000)
        }
        
        if start_time:
            params['start'] = int(start_time.timestamp() * 1000)
        if end_time:
            params['end'] = int(end_time.timestamp() * 1000)
        
        data = self._request('/v5/market/kline', params)
        
        if not data.get('list'):
            return pd.DataFrame()
        
        # Bybit возвращает данные в обратном порядке (новые сверху)
        rows = []
        for item in reversed(data['list']):
            rows.append({
                'time': pd.to_datetime(int(item[0]), unit='ms'),
                'open': float(item[1]),
                'high': float(item[2]),
                'low': float(item[3]),
                'close': float(item[4]),
                'volume': float(item[5])
            })
        
        df = pd.DataFrame(rows)
        df.attrs['symbol'] = symbol
        df.attrs['timeframe'] = interval
        
        return df

    def _get_binance_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Fallback to Binance Data"""
        try:
            # Map timeframe
            # Binance uses same strings mostly: 1m, 3m, 5m, 15m, 1h, 4h, 1d
            # But Bybit uses 'M' for month, Binance '1M'
            tf = interval
            if interval == '1M' and '1M' not in self.TIMEFRAMES: tf = '1M' 
            
            url = "https://api.binance.com/api/v3/klines"
            params = {
                'symbol': symbol.upper(),
                'interval': tf,
                'limit': limit
            }
            
            # Simple request without cloudscraper if possible, or use it
            resp = requests.get(url, params=params, timeout=10, proxies=self.proxies)
            data = resp.json()
            
            if not isinstance(data, list):
                logger.error(f"Binance error for {symbol}: {data}")
                return pd.DataFrame()
                
            rows = []
            for item in data:
                # Binance: [Open Time, Open, High, Low, Close, Volume, ...]
                rows.append({
                    'time': pd.to_datetime(int(item[0]), unit='ms'),
                    'open': float(item[1]),
                    'high': float(item[2]),
                    'low': float(item[3]),
                    'close': float(item[4]),
                    'volume': float(item[5])
                })
            
            df = pd.DataFrame(rows)
            df.attrs['symbol'] = symbol
            df.attrs['timeframe'] = interval
            return df
            
        except Exception as e:
            logger.error(f"Binance Fallback Error: {e}")
            return pd.DataFrame()
    
    def get_multi_timeframe_data(
        self,
        symbol: str,
        timeframes: Dict[str, int] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Получает данные для нескольких таймфреймов
        
        Args:
            symbol: Торговая пара
            timeframes: Dict {таймфрейм: количество_свечей}
        
        Returns:
            Dict с DataFrame для каждого таймфрейма
        """
        if timeframes is None:
            timeframes = {
                '1m': 100,
                '5m': 100,
                '15m': 100,
                '1h': 100,
                '4h': 50
            }
        
        data = {}
        
        for tf, limit in timeframes.items():
            try:
                df = self.get_klines(symbol, tf, limit)
                data[tf] = df
                logger.debug(f"  {symbol} {tf}: {len(df)} свечей")
                time.sleep(0.1)  # Rate limiting
            except Exception as e:
                logger.error(f"  {symbol} {tf}: ошибка - {e}")
                data[tf] = pd.DataFrame()
        
        return data
    
    # ============================================================
    # MARKET DATA - Текущие данные рынка
    # ============================================================
    
    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """Получает текущий тикер"""
        if self.use_binance_data:
            return self._get_binance_ticker(symbol)

        data = self._request('/v5/market/tickers', {
            'category': self.category.value,
            'symbol': symbol
        })
        
        if not data.get('list'):
            raise ValueError(f"Символ не найден: {symbol}")
        
        item = data['list'][0]
        
        return {
            'symbol': item['symbol'],
            'price': float(item['lastPrice']),
            'bid': float(item.get('bid1Price', 0)),
            'ask': float(item.get('ask1Price', 0)),
            'change_24h': float(item.get('price24hPcnt', 0)) * 100,
            'high_24h': float(item.get('highPrice24h', 0)),
            'low_24h': float(item.get('lowPrice24h', 0)),
            'volume_24h': float(item.get('volume24h', 0)),
            'turnover_24h': float(item.get('turnover24h', 0))
        }

    def _get_binance_ticker(self, symbol: str) -> Dict[str, Any]:
        """Fallback to Binance Ticker"""
        try:
            url = "https://api.binance.com/api/v3/ticker/24hr"
            params = {'symbol': symbol.upper()}
            
            # Fallback to Binance Ticker
            # Use proxies if available
            resp = requests.get(url, params=params, timeout=10, proxies=self.proxies)
            item = resp.json()
            
            if 'lastPrice' not in item:
                logger.error(f"Binance ticker error for {symbol}: {item}")
                raise ValueError(f"Ticker not found for {symbol}")
                
            return {
                'symbol': symbol,
                'price': float(item['lastPrice']),
                'bid': float(item.get('bidPrice', 0)),
                'ask': float(item.get('askPrice', 0)),
                'change_24h': float(item.get('priceChangePercent', 0)),
                'high_24h': float(item.get('highPrice', 0)),
                'low_24h': float(item.get('lowPrice', 0)),
                'volume_24h': float(item.get('volume', 0)), # Base volume
                'turnover_24h': float(item.get('quoteVolume', 0)) # Quote volume (USD)
            }
        except Exception as e:
            logger.error(f"Binance Ticker Fallback Error: {e}")
            raise
    
    def get_funding_rate(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получает текущий Funding Rate (только для perpetual)
        
        Funding Rate показывает баланс лонгов/шортов:
        - Положительный (>0): лонги платят шортам → перекупленность
        - Отрицательный (<0): шорты платят лонгам → перепроданность
        - Экстремальные значения (|FR| > 0.05%) часто = разворот
        """
        if self.category == BybitCategory.SPOT:
            return None
        
        try:
            data = self._request('/v5/market/tickers', {
                'category': self.category.value,
                'symbol': symbol
            })
            
            if data.get('list'):
                item = data['list'][0]
                funding_rate = float(item.get('fundingRate', 0))
                
                return {
                    'symbol': symbol,
                    'funding_rate': funding_rate,
                    'funding_rate_pct': funding_rate * 100,
                    'next_funding_time': item.get('nextFundingTime'),
                    'interpretation': self._interpret_funding(funding_rate)
                }
        except Exception as e:
            logger.debug(f"Funding rate error for {symbol}: {e}")
        
        return None
    
    def _interpret_funding(self, rate: float) -> str:
        """Интерпретация funding rate"""
        if rate > 0.001:  # > 0.1%
            return "EXTREME_LONG_BIAS"  # Много лонгов, возможен разворот вниз
        elif rate > 0.0005:
            return "HIGH_LONG_BIAS"
        elif rate > 0.0001:
            return "SLIGHT_LONG_BIAS"
        elif rate < -0.001:
            return "EXTREME_SHORT_BIAS"  # Много шортов, возможен разворот вверх
        elif rate < -0.0005:
            return "HIGH_SHORT_BIAS"
        elif rate < -0.0001:
            return "SLIGHT_SHORT_BIAS"
        else:
            return "NEUTRAL"
    
    def get_open_interest(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Получает Open Interest (только для perpetual)
        
        OI показывает общее количество открытых позиций.
        В сочетании с ценой:
        - Цена ↑ + OI ↑ = сильный бычий тренд
        - Цена ↓ + OI ↑ = накопление шортов, возможен squeeze вверх
        - Цена ↓ + OI ↓ = закрытие лонгов, продолжение падения
        """
        if self.category == BybitCategory.SPOT:
            return None
        
        try:
            data = self._request('/v5/market/open-interest', {
                'category': self.category.value,
                'symbol': symbol,
                'intervalTime': '5min',
                'limit': 1
            })
            
            if data.get('list'):
                item = data['list'][0]
                return {
                    'symbol': symbol,
                    'open_interest': float(item.get('openInterest', 0)),
                    'timestamp': pd.to_datetime(int(item.get('timestamp', 0)), unit='ms')
                }
        except Exception as e:
            logger.debug(f"Open interest error for {symbol}: {e}")
        
        return None
    
    def get_orderbook(self, symbol: str, depth: int = 25) -> Dict[str, Any]:
        """
        Получает стакан заявок и анализирует дисбаланс
        
        Imbalance > 1.5: давление покупателей (bullish)
        Imbalance < 0.67: давление продавцов (bearish)
        """
        data = self._request('/v5/market/orderbook', {
            'category': self.category.value,
            'symbol': symbol,
            'limit': depth
        })
        
        bids = data.get('b', [])
        asks = data.get('a', [])
        
        bid_volume = sum(float(b[1]) for b in bids)
        ask_volume = sum(float(a[1]) for a in asks)
        
        imbalance = bid_volume / ask_volume if ask_volume > 0 else 1
        
        best_bid = float(bids[0][0]) if bids else 0
        best_ask = float(asks[0][0]) if asks else 0
        spread = (best_ask - best_bid) / best_bid * 100 if best_bid > 0 else 0
        
        return {
            'symbol': symbol,
            'bid_volume': bid_volume,
            'ask_volume': ask_volume,
            'imbalance': imbalance,
            'imbalance_interpretation': self._interpret_imbalance(imbalance),
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread_pct': spread,
            'depth': depth
        }
    
    def _interpret_imbalance(self, imbalance: float) -> str:
        if imbalance > 2.0:
            return "STRONG_BUY_PRESSURE"
        elif imbalance > 1.5:
            return "MODERATE_BUY_PRESSURE"
        elif imbalance > 1.2:
            return "SLIGHT_BUY_PRESSURE"
        elif imbalance < 0.5:
            return "STRONG_SELL_PRESSURE"
        elif imbalance < 0.67:
            return "MODERATE_SELL_PRESSURE"
        elif imbalance < 0.83:
            return "SLIGHT_SELL_PRESSURE"
        else:
            return "BALANCED"
    
    # ============================================================
    # COMPLETE MARKET DATA
    # ============================================================
    
    def get_complete_market_data(self, symbol: str) -> MarketData:
        """
        Получает полные данные по символу для анализа
        """
        logger.info(f"Загрузка данных: {symbol}")
        
        # MTF данные
        mtf = self.get_multi_timeframe_data(symbol)
        
        # Тикер
        ticker = self.get_ticker(symbol)
        
        # Funding Rate (для perpetual)
        funding = self.get_funding_rate(symbol)
        
        # Open Interest (для perpetual)
        oi = self.get_open_interest(symbol)
        
        return MarketData(
            symbol=symbol,
            category=self.category,
            df_1m=mtf.get('1m', pd.DataFrame()),
            df_5m=mtf.get('5m', pd.DataFrame()),
            df_15m=mtf.get('15m', pd.DataFrame()),
            df_1h=mtf.get('1h', pd.DataFrame()),
            df_4h=mtf.get('4h', pd.DataFrame()),
            current_price=ticker['price'],
            stats_24h={
                'change_24h': ticker['change_24h'],
                'high_24h': ticker['high_24h'],
                'low_24h': ticker['low_24h'],
                'volume_24h': ticker['volume_24h'],
                'turnover_24h': ticker.get('turnover_24h', 0)
            },
            funding_rate=funding['funding_rate'] if funding else None,
            open_interest=oi['open_interest'] if oi else None,
            timestamp=datetime.now()
        )

    # ============================================================
    # ASYNC WRAPPERS
    # ============================================================

    async def get_ticker_async(self, symbol: str) -> Dict[str, Any]:
        return await self._request_async('/v5/market/tickers', {'category': self.category.value, 'symbol': symbol})

    async def get_klines_async(self, symbol: str, interval: str = '15m', limit: int = 200) -> pd.DataFrame:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.get_klines(symbol, interval, limit))

    async def get_multi_timeframe_data_async(self, symbol: str) -> Dict[str, pd.DataFrame]:
        """Последовательное получение данных (Zero-RAM пики)"""
        tfs = {'1m': 200, '5m': 200, '15m': 200, '1h': 200, '4h': 200}
        data = {}
        
        for tf, limit in tfs.items():
            try:
                # Sequential fetch
                df = await self.get_klines_async(symbol, tf, limit)
                data[tf] = df
            except Exception as e:
                logger.error(f"Error fetching {symbol} {tf}: {e}")
                data[tf] = pd.DataFrame()
                
        return data

    async def get_complete_market_data_async(self, symbol: str) -> Optional[MarketData]:
        """
        Асинхронное получение всех данных для символа
        """
        try:
            # Parallel fetch: MTF Data, Ticker, Funding, OI
            task_mtf = self.get_multi_timeframe_data_async(symbol)
            
            # For ticker/funding/oi we use run_in_executor wrappers or direct _request_async
            # But get_ticker parses result, so better wrap the method
            loop = asyncio.get_running_loop()
            task_ticker = loop.run_in_executor(None, lambda: self.get_ticker(symbol))
            
            # Funding/OI only for linear
            if self.category != BybitCategory.SPOT:
                task_funding = loop.run_in_executor(None, lambda: self.get_funding_rate(symbol))
                task_oi = loop.run_in_executor(None, lambda: self.get_open_interest(symbol))
            else:
                task_funding = asyncio.sleep(0) # dummy
                task_oi = asyncio.sleep(0) # dummy
            
            # AWAIT ALL
            results = await asyncio.gather(task_mtf, task_ticker, task_funding, task_oi, return_exceptions=True)
            
            mtf, ticker, funding, oi = results
            
            if isinstance(ticker, Exception):
                logger.error(f"Failed to fetch ticker for {symbol}: {ticker}")
                return None
            
            # Handle optionals
            funding_val = funding['funding_rate'] if isinstance(funding, dict) else None
            oi_val = oi['open_interest'] if isinstance(oi, dict) else None

            return MarketData(
                symbol=symbol,
                category=self.category,
                df_1m=mtf.get('1m', pd.DataFrame()),
                df_5m=mtf.get('5m', pd.DataFrame()),
                df_15m=mtf.get('15m', pd.DataFrame()),
                df_1h=mtf.get('1h', pd.DataFrame()),
                df_4h=mtf.get('4h', pd.DataFrame()),
                current_price=ticker['price'],
                stats_24h={
                    'change_24h': ticker['change_24h'],
                    'high_24h': ticker['high_24h'],
                    'low_24h': ticker['low_24h'],
                    'volume_24h': ticker['volume_24h'],
                    'turnover_24h': ticker['turnover_24h']
                },
                funding_rate=funding_val,
                open_interest=oi_val,
                timestamp=datetime.now()
            )
        except Exception as e:
            logger.error(f"Error in complete data async {symbol}: {e}")
            return None


# ============================================================
# SYMBOL SCANNER
# ============================================================

class BybitScanner:
    """
    Сканер рынка Bybit
    Автоматически работает со ВСЕМИ доступными парами
    """
    
    def __init__(
        self,
        client: BybitClient,
        symbols: Optional[List[str]] = None,
        min_volume_24h: float = 1_000_000,  # Минимум $1M объёма
        max_symbols: Optional[int] = None
    ):
        """
        Args:
            client: Клиент Bybit
            symbols: Конкретный список символов (если None - все доступные)
            min_volume_24h: Минимальный объём для фильтрации
            max_symbols: Максимальное количество символов (None = без ограничений)
        """
        self.client = client
        self.min_volume_24h = min_volume_24h
        self.max_symbols = max_symbols
        
        if symbols:
            self.symbols = symbols
        else:
            self.symbols = self._get_filtered_symbols()
    
    def _get_filtered_symbols(self) -> List[str]:
        """Получает отфильтрованный список символов"""
        
        tickers = self.client.get_top_symbols_by_volume(top_n=500)
        
        # Filter by min volume
        filtered = [
            t['symbol'] for t in tickers 
            if float(t.get('volume_24h', 0)) >= self.min_volume_24h
        ]
        
        # STRICT LIMIT ENFORCEMENT
        limit = self.max_symbols or 100 # Default to 100 if not set to prevent overloading
        if limit:
            filtered = filtered[:limit]
        
        logger.info(f"📋 Scanner Filtered Symbols: {len(filtered)} (Max: {limit}, Min Vol: ${self.min_volume_24h:,.0f})")
        
        return filtered
    
    def refresh_symbols(self):
        """Обновляет список символов"""
        self.symbols = self._get_filtered_symbols()
    
    def scan_all(self, delay: float = 0.2) -> List[MarketData]:
        """
        Сканирует все символы
        
        Args:
            delay: Задержка между запросами (rate limiting)
        
        Returns:
            Список MarketData для каждого символа
        """
        results = []
        total = len(self.symbols)
        
        logger.info(f"Сканирование {total} символов...")
        
        for i, symbol in enumerate(self.symbols, 1):
            try:
                logger.info(f"[{i}/{total}] {symbol}")
                data = self.client.get_complete_market_data(symbol)
                results.append(data)
                time.sleep(delay)
            except Exception as e:
                logger.error(f"  Ошибка {symbol}: {e}")
        
        logger.info(f"Загружено: {len(results)}/{total}")
        return results

    async def scan_all_async(self, batch_size: int = 1) -> List[MarketData]:
        """
        Асинхронное последовательное сканирование (Zero-RAM Mode)
        batch_size = 1 для исключения пиков потребления ОЗУ на слабом железе.
        """
        results = []
        total = len(self.symbols)
        logger.info(f"🚀 [ZERO-RAM] Последовательное сканирование {total} символов...")
        
        import gc
        for i, symbol in enumerate(self.symbols):
            try:
                # Process ONE by ONE
                logger.debug(f"  Scanning {i+1}/{total}: {symbol}...")
                data = await self.client.get_complete_market_data_async(symbol)
                if data:
                    results.append(data)
                
                # Forced cleanup every symbol to save every MB
                if i % 1 == 0:
                    gc.collect()
            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
            
        logger.info(f"✅ Сканирование завершено: {len(results)}/{total}")
        return results
    
    def get_market_overview(self) -> pd.DataFrame:
        """Возвращает обзор рынка в виде DataFrame"""
        
        tickers = self.client.get_top_symbols_by_volume(top_n=100)
        
        df = pd.DataFrame(tickers)
        df = df.sort_values('volume_24h', ascending=False)
        
        return df


# ============================================================
# DEMO
# ============================================================

def main():
    """Демонстрация работы клиента Bybit"""
    
    print("""
╔══════════════════════════════════════════════════════════════════╗
║                    BYBIT CLIENT v2.0                             ║
║                                                                  ║
║   • Все торговые пары автоматически                              ║
║   • Multi-Timeframe данные                                       ║
║   • Funding Rate & Open Interest                                 ║
║   • Order Book Analysis                                          ║
╚══════════════════════════════════════════════════════════════════╝
    """)
    
    # Инициализация клиента
    client = BybitClient(
        category=BybitCategory.LINEAR,  # USDT Perpetual
        testnet=False
    )
    
    print("Клиент инициализирован.")
    print("\nПример использования:\n")
    print("""
    # Получить ВСЕ торговые пары
    symbols = client.get_symbol_list()
    print(f"Доступно пар: {len(symbols)}")
    
    # Топ по объёму
    top = client.get_top_symbols_by_volume(top_n=20)
    
    # Полные данные по символу
    data = client.get_complete_market_data('BTCUSDT')
    
    # Сканер с автоматическим выбором пар
    scanner = BybitScanner(client, min_volume_24h=5_000_000)
    results = scanner.scan_all()
    """)


if __name__ == "__main__":
    main()
