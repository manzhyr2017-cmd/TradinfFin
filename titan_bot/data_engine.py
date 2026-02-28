"""
TITAN BOT 2026 - Data Engine
Получение и обработка рыночных данных
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
from pybit.unified_trading import HTTP, WebSocket
from datetime import datetime, timedelta
import time
import config

class DataEngine:
    """
    Класс для получения всех рыночных данных с Bybit.
    Поддерживает REST API и WebSocket.
    """
    
    def __init__(self):
        # Инициализация HTTP клиента
        self.session = HTTP(
            testnet=config.TESTNET,
            api_key=config.API_KEY,
            api_secret=config.API_SECRET,
            recv_window=20000,
            demo=getattr(config, 'BYBIT_DEMO', False)
        )
        
        # Кэш для данных (чтобы не долбить API)
        self.klines_cache = {}
        self.orderbook_cache = {}
        self.trades_cache = []
        self.last_update = {}
        self.symbol_info_cache = {}
        
        mode = "DEMO" if getattr(config, 'BYBIT_DEMO', False) else ("TESTNET" if config.TESTNET else "MAINNET")
        print(f"[DataEngine] Инициализирован. Режим: {mode}")

    def get_symbol_info(self, symbol: str) -> dict:
        if symbol in self.symbol_info_cache:
            return self.symbol_info_cache[symbol]
        try:
            response = self.session.get_instruments_info(category=config.CATEGORY, symbol=symbol)
            if response['retCode'] == 0:
                info = response['result']['list'][0]
                formatted_info = {
                    'price_precision': int(info.get('priceScale', 2)),
                    'qty_step': float(info.get('lotSizeFilter', {}).get('qtyStep', 0.001)),
                    'min_qty': float(info.get('lotSizeFilter', {}).get('minOrderQty', 0.001)),
                    'tick_size': float(info.get('priceFilter', {}).get('tickSize', 0.01)),
                    'raw': info
                }
                qty_step_str = str(formatted_info['qty_step']).rstrip('0')
                formatted_info['qty_precision'] = len(qty_step_str.split('.')[1]) if '.' in qty_step_str else 0
                self.symbol_info_cache[symbol] = formatted_info
                return formatted_info
        except Exception as e:
            print(f"[DataEngine] Error symbol info {symbol}: {e}")
        return {'price_precision': 2, 'qty_precision': 3, 'qty_step': 0.001, 'min_qty': 0.001, 'tick_size': 0.01}
    
    def get_klines(self, symbol: str, interval: str = None, limit: int = 200) -> pd.DataFrame:
        if interval is None: interval = config.TIMEFRAME
        try:
            response = self.session.get_kline(category=config.CATEGORY, symbol=symbol, interval=interval, limit=limit)
            if response['retCode'] != 0: return None
            data = response['result']['list']
            df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume', 'turnover']: df[col] = df[col].astype(float)
            df = df.iloc[::-1].reset_index(drop=True)
            df = self._add_indicators(df)
            self.klines_cache[symbol] = df
            return df
        except Exception as e:
            print(f"[DataEngine] Error klines: {e}")
            return None
    
    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        df['ema_20'] = ta.ema(df['close'], length=20)
        df['ema_50'] = ta.ema(df['close'], length=50)
        df['volatility'] = df['close'].pct_change().rolling(window=20).std()
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['body_size'] = abs(df['close'] - df['open'])
        return df
    
    def get_orderbook(self, symbol: str = None, depth: int = None) -> dict:
        if symbol is None: symbol = config.SYMBOL
        if depth is None: depth = config.ORDERBOOK_DEPTH
        try:
            response = self.session.get_orderbook(category=config.CATEGORY, symbol=symbol, limit=depth)
            if response['retCode'] != 0: return None
            result = response['result']
            bids = pd.DataFrame(result['b'], columns=['price', 'size']).astype(float)
            asks = pd.DataFrame(result['a'], columns=['price', 'size']).astype(float)
            
            # Детекция "стенок" (Order Walls)
            avg_bid_size = bids['size'].mean()
            avg_ask_size = asks['size'].mean()
            bid_walls = bids[bids['size'] > avg_bid_size * 3]
            ask_walls = asks[asks['size'] > avg_ask_size * 3]
            
            bid_volume, ask_volume = bids['size'].sum(), asks['size'].sum()
            total_volume = bid_volume + ask_volume
            imbalance = bid_volume / total_volume if total_volume > 0 else 0.5
            
            return {
                'bids': bids, 
                'asks': asks, 
                'bid_walls': bid_walls,
                'ask_walls': ask_walls,
                'bid_volume': bid_volume, 
                'ask_volume': ask_volume,
                'imbalance': imbalance, 
                'spread': asks['price'].iloc[0] - bids['price'].iloc[0],
                'mid_price': (asks['price'].iloc[0] + bids['price'].iloc[0]) / 2
            }
        except Exception as e:
            print(f"[DataEngine] Error orderbook: {e}")
            return None

    def get_balance(self) -> float:
        """Получает доступный баланс (Available Margin) для торговли."""
        try:
            for acc in ["UNIFIED", "CONTRACT"]:
                response = self.session.get_wallet_balance(accountType=acc, coin="USDT")
                if response['retCode'] == 0 and response['result']['list']:
                    res = response['result']['list'][0]
                    # Для UNIFIED аккаунта берем доступную маржу (Available Margin)
                    if acc == "UNIFIED":
                        for c in res.get('coin', []):
                            if c.get('coin') == 'USDT':
                                # availableToWithdraw - это то, что реально свободно для новых ордеров
                                val = c.get('availableToWithdraw')
                                if not val: 
                                    val = c.get('walletBalance', '0')
                                return float(val) if val else 0.0
                    
                    # Для обычного CONTRACT аккаунта
                    for c in res.get('coin', []):
                        if c.get('coin') == 'USDT':
                            val = c.get('walletBalance', '0')
                            return float(val) if val else 0.0
            return float(config.INITIAL_DEPOSIT)
        except Exception as e:
            print(f"[DataEngine] Error balance: {e}")
            return 300.0

    def get_positions(self, symbol: str = None) -> list:
        try:
            params = {'category': config.CATEGORY}
            if symbol: params['symbol'] = symbol
            elif config.CATEGORY == 'linear': params['settleCoin'] = 'USDT'
            response = self.session.get_positions(**params)
            if response['retCode'] != 0: return []
            return [{'symbol': p['symbol'], 'side': p['side'], 'size': float(p['size']), 'unrealized_pnl': float(p['unrealisedPnl'])} 
                    for p in response['result']['list'] if float(p['size']) > 0]
        except Exception as e:
            print(f"[DataEngine] Error positions: {e}")
            return []

    def get_funding_rate(self, symbol: str) -> dict:
        """Получает текущую ставку финансирования."""
        try:
            response = self.session.get_tickers(category=config.CATEGORY, symbol=symbol)
            if response['retCode'] != 0: return {}
            ticker = response['result']['list'][0]
            return {
                'funding_rate': float(ticker.get('fundingRate', 0)),
                'next_funding_time': ticker.get('nextFundingTime', "")
            }
        except Exception as e:
            print(f"[DataEngine] Error funding: {e}")
            return {}

    def get_closed_pnl(self, symbol: str, limit: int = 1) -> list:
        """Получает результат последних закрытых сделок."""
        try:
            response = self.session.get_closed_pnl(category=config.CATEGORY, symbol=symbol, limit=limit)
            if response['retCode'] != 0: return []
            return response['result']['list']
        except Exception as e:
            print(f"[DataEngine] Error closed pnl: {e}")
            return []

class RealtimeDataStream:
    def __init__(self, on_trade_callback=None):
        self.ws = None
        self.on_trade = on_trade_callback
        self.trades_buffer = []
        self.delta_volume = 0
        
    def start(self, symbol):
        if self.ws: return
        is_testnet = config.TESTNET
        is_demo = getattr(config, 'BYBIT_DEMO', False)
        # Bybit Demo V5 WebSocket эндпоинт wss://stream-demo.bybit.com часто выдает 404.
        # В документации сказано: для Demo UTA использовать Mainnet сокеты или Testnet.
        # Мы отключаем параметр demo=True для публичных потоков, чтобы pybit не лез на битую ссылку.
        ws_demo_param = False # Всегда False для публичных котировок в режиме Demo
        print(f"[RealtimeStream] Connecting WS (Testnet={is_testnet}, Demo_Keys={is_demo})...")
        try:
            self.ws = WebSocket(
                testnet=is_testnet,
                channel_type="linear",
                demo=ws_demo_param,
                restart_on_error=True
            )
            symbols = symbol if isinstance(symbol, list) else [symbol]
            for s in symbols:
                self.ws.trade_stream(symbol=s, callback=self._handle_trade)
            print(f"[RealtimeStream] ✅ WebSocket ONLINE for {len(symbols)} coins")
        except Exception as e:
            print(f"[RealtimeStream] ⚠️ WS Error: {e}. Falling back to REST.")
            self.ws = None
    
    def _handle_trade(self, message):
        try:
            if 'data' not in message: return
            for trade in message['data']:
                side, size = trade['S'], float(trade['v'])
                self.delta_volume += size if side == 'Buy' else -size
                self.trades_buffer.append({'side': side, 'size': size, 'price': float(trade['p'])})
                if len(self.trades_buffer) > 1000: self.trades_buffer.pop(0)
                if self.on_trade: self.on_trade(trade)
        except Exception as e: print(f"[RealtimeStream] Error callback: {e}")
    
    def get_delta_volume(self, reset: bool = True) -> float:
        delta = self.delta_volume
        if reset: self.delta_volume = 0
        return delta
    
    def get_recent_trades(self, limit: int = 50) -> list:
        """Возвращает последние сделки из буфера."""
        return self.trades_buffer[-limit:]

    def stop(self):
        if self.ws: self.ws.exit()
