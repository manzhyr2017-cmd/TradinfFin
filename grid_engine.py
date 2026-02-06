import logging
import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GridEngine")

@dataclass
class GridOrder:
    price: float
    side: str # 'BUY' or 'SELL'
    qty: float
    grid_id: int

class GridStrategy:
    """
    Арифметическая Grid Стратегия.
    Создает сетку ордеров вокруг текущей цены.
    """
    
    def __init__(self, symbol: str, balance: float, config: Dict = None):
        self.symbol = symbol
        self.balance = balance
        self.config = config or {}
        self.min_qty = 0.001 # Пример для BTC, нужно брать из инфо инструмента
        
    def calculate_grid(self, current_price: float, lower_price: float, upper_price: float, grids: int = 10) -> List[GridOrder]:
        """
        Рассчитывает уровни сетки.
        
        Args:
            current_price: Текущая цена
            lower_price: Нижняя граница диапазона
            upper_price: Верхняя граница диапазона
            grids: Количество уровней (ордеров)
            
        Returns:
            Список ордеров GridOrder
        """
        if lower_price >= current_price or upper_price <= current_price:
            logger.error("Current price must be within range [lower, upper]")
            return []
            
        # Арифметическая сетка: равное расстояние между уровнями
        # step = (upper_price - lower_price) / grids
        # Но мы хотим сетку вокруг цены, чтобы часть была BUY, часть SELL
        
        # Просто бьем диапазон на уровни
        levels = np.linspace(lower_price, upper_price, grids + 1)
        
        orders = []
        total_investment = self.balance * 0.95 # 95% баланса в работу
        order_amount_usdt = total_investment / grids
        
        for i, price in enumerate(levels):
            # Пропускаем уровни слишком близкие к текущей цене (чтобы не сработали мгновенно как Market)
            if abs(price - current_price) / current_price < 0.001:
                continue
                
            qty = order_amount_usdt / price
            
            # Округляем кол-во (упрощенно)
            qty = round(qty, 4) 
            if qty <= 0: continue

            if price < current_price:
                orders.append(GridOrder(price=price, side='BUY', qty=qty, grid_id=i))
            else:
                orders.append(GridOrder(price=price, side='SELL', qty=qty, grid_id=i))
                
        logger.info(f"Calculated {len(orders)} grid orders for {self.symbol}")
        return orders

    def get_grid_summary(self, orders: List[GridOrder]) -> str:
        buys = [o for o in orders if o.side == 'BUY']
        sells = [o for o in orders if o.side == 'SELL']
        
        return f"""
🕸️ <b>GRID Setup calculated</b>
Symbol: {self.symbol}
Range: {orders[0].price:.2f} - {orders[-1].price:.2f}
Grids: {len(orders)} ({len(buys)} BUY, {len(sells)} SELL)
Invest: ~{self.balance:.2f} USDT
"""
