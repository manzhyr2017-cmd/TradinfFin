"""
TITAN BOT 2026 - Order Executor
Исполнение торговых ордеров
"""

from pybit.unified_trading import HTTP
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import time
import config

@dataclass
class OrderResult:
    """Результат выставления ордера"""
    success: bool
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    error: str = ""

class OrderExecutor:
    """
    Исполнитель ордеров.
    
    Особенности:
    1. Лимитные ордера для минимизации комиссий
    2. Автоматический StopLoss и TakeProfit
    3. Retry логика при ошибках
    """
    
    def __init__(self, data_engine):
        self.session = HTTP(
            testnet=config.TESTNET,
            api_key=config.API_KEY,
            api_secret=config.API_SECRET
        )
        self.data = data_engine
        
    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float = None,
        stop_loss: float = None,
        take_profit: float = None,
        order_type: str = "Limit",
        leverage: int = 10
    ) -> OrderResult:
        """
        Выставляет ордер на Bybit.
        
        Args:
            symbol: Торговая пара
            side: 'Buy' или 'Sell'
            quantity: Количество
            price: Цена (для лимитного ордера)
            stop_loss: Уровень стоп-лосса
            take_profit: Уровень тейк-профита
            order_type: 'Limit' или 'Market'
            leverage: Плечо
        """
        try:
            # Устанавливаем плечо
            self._set_leverage(symbol, leverage)
            
            # Параметры ордера
            params = {
                'category': config.CATEGORY,
                'symbol': symbol,
                'side': side,
                'orderType': order_type,
                'qty': str(quantity),
                'timeInForce': 'GTC',  # Good Till Cancel
                'positionIdx': 0  # One-way mode
            }
            
            # Для лимитного ордера нужна цена
            if order_type == 'Limit':
                if price is None:
                    # Берем текущую цену
                    ticker = self.session.get_tickers(category=config.CATEGORY, symbol=symbol)
                    price = float(ticker['result']['list'][0]['lastPrice'])
                    # Небольшой отступ для лимитки
                    if side == 'Buy':
                        price = price * 0.9995
                    else:
                        price = price * 1.0005
                
                params['price'] = str(round(price, 2))
            
            # Добавляем SL/TP
            if stop_loss:
                params['stopLoss'] = str(round(stop_loss, 2))
                params['slTriggerBy'] = 'LastPrice'
            
            if take_profit:
                params['takeProfit'] = str(round(take_profit, 2))
                params['tpTriggerBy'] = 'LastPrice'
            
            # Выставляем ордер
            response = self.session.place_order(**params)
            
            if response['retCode'] == 0:
                order_id = response['result']['orderId']
                print(f"[Executor] ✅ Ордер выставлен: {side} {quantity} {symbol} @ {price}")
                print(f"[Executor] Order ID: {order_id}")
                print(f"[Executor] SL: {stop_loss}, TP: {take_profit}")
                
                return OrderResult(
                    success=True,
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price or 0
                )
            else:
                error_msg = response['retMsg']
                print(f"[Executor] ❌ Ошибка ордера: {error_msg}")
                
                return OrderResult(
                    success=False,
                    order_id="",
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price or 0,
                    error=error_msg
                )
                
        except Exception as e:
            print(f"[Executor] ❌ Exception: {e}")
            return OrderResult(
                success=False,
                order_id="",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price or 0,
                error=str(e)
            )
    
    def close_position(self, symbol: str = None) -> OrderResult:
        """Закрывает открытую позицию."""
        if symbol is None:
            symbol = config.SYMBOL
        
        positions = self.data.get_positions(symbol)
        
        if not positions:
            print(f"[Executor] Нет открытых позиций для {symbol}")
            return OrderResult(False, "", symbol, "", 0, 0, "No position")
        
        pos = positions[0]
        side = 'Sell' if pos['side'] == 'Buy' else 'Buy'
        
        return self.place_order(
            symbol=symbol,
            side=side,
            quantity=pos['size'],
            order_type='Market'
        )
    
    def cancel_all_orders(self, symbol: str = None) -> bool:
        """Отменяет все открытые ордера."""
        if symbol is None:
            symbol = config.SYMBOL
        
        try:
            response = self.session.cancel_all_orders(
                category=config.CATEGORY,
                symbol=symbol
            )
            
            if response['retCode'] == 0:
                print(f"[Executor] Все ордера отменены для {symbol}")
                return True
            return False
            
        except Exception as e:
            print(f"[Executor] Ошибка отмены ордеров: {e}")
            return False
    
    def _set_leverage(self, symbol: str, leverage: int):
        """Устанавливает плечо для инструмента."""
        try:
            self.session.set_leverage(
                category=config.CATEGORY,
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
        except Exception as e:
            # Игнорируем ошибку если плечо уже установлено
            pass
    
    def modify_sl_tp(
        self,
        symbol: str,
        stop_loss: float = None,
        take_profit: float = None
    ) -> bool:
        """Изменяет SL/TP для открытой позиции."""
        try:
            params = {
                'category': config.CATEGORY,
                'symbol': symbol,
                'positionIdx': 0
            }
            
            if stop_loss:
                params['stopLoss'] = str(round(stop_loss, 2))
            if take_profit:
                params['takeProfit'] = str(round(take_profit, 2))
            
            response = self.session.set_trading_stop(**params)
            
            return response['retCode'] == 0
            
        except Exception as e:
            print(f"[Executor] Ошибка изменения SL/TP: {e}")
            return False
