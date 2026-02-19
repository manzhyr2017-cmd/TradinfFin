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

    # ==========================================
    # ИНФОРМАЦИЯ ОБ ИНСТРУМЕНТАХ
    # ==========================================
    def get_symbol_info(self, symbol: str) -> dict:
        """
        Получает правила торговли для символа (точность цены, шаги лота).
        """
        if symbol in self.symbol_info_cache:
            return self.symbol_info_cache[symbol]
            
        try:
            response = self.session.get_instruments_info(
                category=config.CATEGORY,
                symbol=symbol
            )
            
            if response['retCode'] == 0:
                info = response['result']['list'][0]
                
                # Извлекаем нужные параметры для удобства
                formatted_info = {
                    'price_precision': int(info.get('priceScale', 2)),
                    'qty_step': float(info.get('lotSizeFilter', {}).get('qtyStep', 0.001)),
                    'min_qty': float(info.get('lotSizeFilter', {}).get('minOrderQty', 0.001)),
                    'tick_size': float(info.get('priceFilter', {}).get('tickSize', 0.01)),
                    'raw': info
                }
                
                # Считаем количество знаков после запятой для кол-ва
                qty_step_str = str(formatted_info['qty_step']).rstrip('0')
                if '.' in qty_step_str:
                    formatted_info['qty_precision'] = len(qty_step_str.split('.')[1])
                else:
                    formatted_info['qty_precision'] = 0
                
                self.symbol_info_cache[symbol] = formatted_info
                return formatted_info
                
        except Exception as e:
            print(f"[DataEngine] Ошибка получения инфо о символе {symbol}: {e}")
            
        # Fallback на дефолты
        return {
            'price_precision': 2,
            'qty_precision': 3,
            'qty_step': 0.001,
            'min_qty': 0.001,
            'tick_size': 0.01
        }
    
    # ==========================================
    # СВЕЧИ (KLINES / OHLCV)
    # ==========================================
    def get_klines(self, symbol: str, interval: str = None, limit: int = 200) -> pd.DataFrame:
        """
        Получает свечи и возвращает DataFrame с техническими индикаторами.
        
        Args:
            symbol: Торговая пара (ETHUSDT)
            interval: Таймфрейм ('1', '5', '15', '60', '240', 'D')
            limit: Количество свечей (макс 1000)
        
        Returns:
            DataFrame с колонками: open, high, low, close, volume + индикаторы
        """
        if interval is None:
            interval = config.TIMEFRAME
            
        try:
            response = self.session.get_kline(
                category=config.CATEGORY,
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            if response['retCode'] != 0:
                print(f"[DataEngine] Ошибка API: {response['retMsg']}")
                return None
            
            # Парсим данные
            data = response['result']['list']
            df = pd.DataFrame(data, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'
            ])
            
            # Конвертация типов
            df['timestamp'] = pd.to_datetime(df['timestamp'].astype(int), unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume', 'turnover']:
                df[col] = df[col].astype(float)
            
            # Разворачиваем (API возвращает от новых к старым)
            df = df.iloc[::-1].reset_index(drop=True)
            
            # Добавляем базовые индикаторы
            df = self._add_indicators(df)
            
            # Кэшируем
            self.klines_cache[symbol] = df
            self.last_update[f'klines_{symbol}'] = datetime.now()
            
            return df
            
        except Exception as e:
            print(f"[DataEngine] Ошибка получения свечей: {e}")
            return None
    
    def _add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Добавляет технические индикаторы к DataFrame.
        Мы используем их НЕ для сигналов, а для контекста и ML.
        """
        # ATR (Average True Range) - мера волатильности
        df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=14)
        
        # EMA для определения тренда (не для входов!)
        df['ema_20'] = ta.ema(df['close'], length=20)
        df['ema_50'] = ta.ema(df['close'], length=50)
        
        # Волатильность (стандартное отклонение доходности)
        df['volatility'] = df['close'].pct_change().rolling(window=20).std()
        
        # Объемный профиль
        df['volume_sma'] = df['volume'].rolling(window=20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma']  # Относительный объем
        
        # Свечной анализ
        df['body_size'] = abs(df['close'] - df['open'])
        df['wick_upper'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['wick_lower'] = df[['open', 'close']].min(axis=1) - df['low']
        df['is_bullish'] = df['close'] > df['open']
        
        return df
    
    # ==========================================
    # СТАКАН (ORDER BOOK)
    # ==========================================
    def get_orderbook(self, symbol: str = None, depth: int = None) -> dict:
        """
        Получает стакан заявок.
        
        Returns:
            dict с ключами: bids, asks, bid_volume, ask_volume, imbalance
        """
        if symbol is None:
            symbol = config.SYMBOL
        if depth is None:
            depth = config.ORDERBOOK_DEPTH
            
        try:
            response = self.session.get_orderbook(
                category=config.CATEGORY,
                symbol=symbol,
                limit=depth
            )
            
            if response['retCode'] != 0:
                return None
            
            result = response['result']
            
            # Парсим биды (заявки на покупку)
            bids = pd.DataFrame(result['b'], columns=['price', 'size'])
            bids = bids.astype(float)
            
            # Парсим аски (заявки на продажу)
            asks = pd.DataFrame(result['a'], columns=['price', 'size'])
            asks = asks.astype(float)
            
            # Считаем объемы
            bid_volume = bids['size'].sum()
            ask_volume = asks['size'].sum()
            total_volume = bid_volume + ask_volume
            
            # Дисбаланс (0.5 = равновесие, >0.5 = давление покупателей)
            imbalance = bid_volume / total_volume if total_volume > 0 else 0.5
            
            # Находим крупные стенки
            bid_walls = bids[bids['size'] > bids['size'].mean() * 3]
            ask_walls = asks[asks['size'] > asks['size'].mean() * 3]
            
            # Проверка на пустой стакан
            if bids.empty or asks.empty or len(bids) == 0 or len(asks) == 0:
                return None

            try:
                best_ask = asks['price'].iloc[0]
                best_bid = bids['price'].iloc[0]
            except (IndexError, KeyError):
                return None

            orderbook_data = {
                'bids': bids,
                'asks': asks,
                'bid_volume': bid_volume,
                'ask_volume': ask_volume,
                'imbalance': imbalance,
                'bid_walls': bid_walls,
                'ask_walls': ask_walls,
                'spread': best_ask - best_bid,
                'mid_price': (best_ask + best_bid) / 2
            }
            
            self.orderbook_cache[symbol] = orderbook_data
            return orderbook_data
            
        except Exception as e:
            print(f"[DataEngine] Ошибка получения стакана: {e}")
            return None
    
    # ==========================================
    # ФАНДИНГ (FUNDING RATE)
    # ==========================================
    def get_funding_rate(self, symbol: str = None) -> dict:
        """
        Получает текущий funding rate.
        Положительный = лонгисты платят шортистам (толпа в лонгах).
        """
        if symbol is None:
            symbol = config.SYMBOL
            
        try:
            response = self.session.get_tickers(
                category=config.CATEGORY,
                symbol=symbol
            )
            
            if response['retCode'] != 0:
                return None
            
            ticker = response['result']['list'][0]
            
            funding_data = {
                'funding_rate': float(ticker['fundingRate']),
                'next_funding_time': ticker.get('nextFundingTime'),
                'mark_price': float(ticker['markPrice']),
                'index_price': float(ticker['indexPrice']),
                'open_interest': float(ticker.get('openInterest', 0)),
                'last_price': float(ticker['lastPrice']),
                'volume_24h': float(ticker['volume24h']),
                'price_change_24h': float(ticker['price24hPcnt'])
            }
            
            return funding_data
            
        except Exception as e:
            print(f"[DataEngine] Ошибка получения фандинга: {e}")
            return None
    
    # ==========================================
    # БАЛАНС И ПОЗИЦИИ
    # ==========================================
    def get_balance(self) -> float:
        """Получает баланс USDT (поддержка UTA и Contract аккаунтов)."""
        try:
            # 1. Пробуем Unified аккаунт (UTA), как на скрине юзера
            response = self.session.get_wallet_balance(
                accountType="UNIFIED",
                coin="USDT"
            )
            
            if response['retCode'] == 0 and response['result']['list']:
                # В UTA режиме часто смотрят totalEquity
                total_equity = response['result']['list'][0].get('totalEquity')
                if total_equity:
                    return float(total_equity)
                
                # Или ищем в списке монет
                coins = response['result']['list'][0].get('coin', [])
                for c in coins:
                    if c.get('coin') == 'USDT':
                        return float(c.get('walletBalance', 0.0))
            
            # 2. Если не UTA, пробуем Contract (классический деривативный)
            response = self.session.get_wallet_balance(
                accountType="CONTRACT",
                coin="USDT"
            )
            
            if response['retCode'] == 0 and response['result']['list']:
                coins = response['result']['list'][0].get('coin', [])
                for c in coins:
                    if c.get('coin') == 'USDT':
                        return float(c.get('walletBalance', 0.0))
            
            # Если всё равно 401 или ошибка, возвращаем дефолт из конфига
            return getattr(config, 'INITIAL_DEPOSIT', 300.0)
            
        except Exception as e:
            print(f"[DataEngine] Ошибка баланса: {e}")
            return getattr(config, 'INITIAL_DEPOSIT', 300.0)
    
    def get_positions(self, symbol: str = None) -> list:
        """Получает открытые позиции."""
        try:
            params = {'category': config.CATEGORY}
            if symbol:
                params['symbol'] = symbol
            elif config.CATEGORY == 'linear':
                params['settleCoin'] = 'USDT'
                
            response = self.session.get_positions(**params)
            
            if response['retCode'] != 0:
                return []
            
            positions = []
            for pos in response['result']['list']:
                if float(pos['size']) > 0:
                    positions.append({
                        'symbol': pos['symbol'],
                        'side': pos['side'],
                        'size': float(pos['size']),
                        'entry_price': float(pos['avgPrice']),
                        'unrealized_pnl': float(pos['unrealisedPnl']),
                        'leverage': float(pos['leverage'])
                    })
            
            return positions
            
        except Exception as e:
            print(f"[DataEngine] Ошибка получения позиций: {e}")
            return []


# ==========================================
# WEBSOCKET HANDLER (Реалтайм данные)
# ==========================================
class RealtimeDataStream:
    """
    WebSocket подключение для получения данных в реальном времени.
    Используется для ленты сделок и обновлений стакана.
    """
    
    def __init__(self, on_trade_callback=None, on_orderbook_callback=None):
        self.ws = None
        self.on_trade = on_trade_callback
        self.on_orderbook = on_orderbook_callback
        self.trades_buffer = []
        self.delta_volume = 0  # Разница между покупками и продажами
        
    def start(self, symbol):
        """Запуск прослушивания сделок с защитой от перегрузки."""
        if self.ws:
            return

        print(f"[RealtimeStream] Попытка подключения к WebSocket для {symbol}...")
        try:
            # Создаем WebSocket с отключенным автоматическим перезапуском при ошибке, 
            # чтобы не спамить сервер при блокировке
            self.ws = WebSocket(
                testnet=config.TESTNET,
                channel_type="linear",
                demo=getattr(config, 'BYBIT_DEMO', False),
                restart_on_error=False 
            )
            
            # Если пришел список - подписываемся на все
            if isinstance(symbol, list):
                for s in symbol:
                    self.ws.trade_stream(symbol=s, callback=self._handle_trade)
            else:
                self.ws.trade_stream(symbol=symbol, callback=self._handle_trade)
                
            print(f"[RealtimeStream] WebSocket успешно инициализирован.")
            
        except Exception as e:
            print(f"[RealtimeStream] Ошибка инициализации сокета: {e}")
            self.ws = None
            # Не бросаем исключение, чтобы бот мог работать через REST если сокет упал
    
    def switch_symbol(self, symbol: str):
        """Метод оставлен для совместимости, но теперь мы стараемся не перезапускать WS часто."""
        pass
    
    def _handle_trade(self, message):
        """
        Обработчик входящих сделок.
        Считает Delta Volume (разницу между покупками по рынку и продажами).
        """
        try:
            if 'data' not in message:
                return
                
            for trade in message['data']:
                side = trade['S']  # 'Buy' или 'Sell'
                size = float(trade['v'])
                price = float(trade['p'])
                
                # Delta: покупки +, продажи -
                if side == 'Buy':
                    self.delta_volume += size
                else:
                    self.delta_volume -= size
                
                # Сохраняем в буфер (последние 1000 сделок)
                self.trades_buffer.append({
                    'time': trade['T'],
                    'side': side,
                    'size': size,
                    'price': price
                })
                
                if len(self.trades_buffer) > 1000:
                    self.trades_buffer.pop(0)
                
                # Callback если есть
                if self.on_trade:
                    self.on_trade(trade)
                    
        except Exception as e:
            print(f"[RealtimeStream] Ошибка обработки сделки: {e}")
    
    def _handle_orderbook(self, message):
        """Обработчик обновлений стакана."""
        if self.on_orderbook:
            self.on_orderbook(message)
    
    def get_delta_volume(self, reset: bool = True) -> float:
        """
        Возвращает накопленную Delta Volume.
        Положительная = больше покупок по рынку.
        Отрицательная = больше продаж по рынку.
        """
        delta = self.delta_volume
        if reset:
            self.delta_volume = 0
        return delta
    
    def get_recent_trades(self, count: int = 100) -> list:
        """Возвращает последние N сделок."""
        return self.trades_buffer[-count:]
    
    def stop(self):
        """Останавливает WebSocket."""
        if self.ws:
            self.ws.exit()
            print("[RealtimeStream] WebSocket остановлен")
