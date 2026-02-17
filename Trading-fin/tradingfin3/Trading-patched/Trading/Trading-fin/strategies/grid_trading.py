"""
Grid Trading Strategy
Passively profits from oscillating (sideways) markets by placing a grid of buy/sell orders.
Best used when Sentiment = RISK_ON (but not TREND_UP/DOWN).
"""

import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


@dataclass
class GridConfig:
    """Configuration for Grid Trading"""
    symbol: str
    upper_price: float  # Top of the grid
    lower_price: float  # Bottom of the grid
    num_grids: int = 10  # Number of grid levels
    total_investment: float = 50.0  # Total USDT to allocate
    
    def get_grid_levels(self) -> List[float]:
        """Calculate grid price levels"""
        step = (self.upper_price - self.lower_price) / self.num_grids
        return [self.lower_price + (step * i) for i in range(self.num_grids + 1)]
    
    def get_order_size(self) -> float:
        """USDT per grid level"""
        return self.total_investment / self.num_grids


class GridStatus(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class GridTrader:
    """
    Grid Trading Bot
    Places buy orders at lower grid levels, sell orders at upper levels.
    When price crosses a level, it triggers the opposite order.
    """
    
    def __init__(self, client, config: GridConfig):
        self.client = client
        self.config = config
        self.status = GridStatus.STOPPED
        self.active_orders: Dict[str, dict] = {}  # order_id -> order_info
        self.filled_buys: List[float] = []  # Levels where we bought
        self.pnl = 0.0
        
    def start(self) -> bool:
        """Initialize and place initial grid orders"""
        logger.info(f"🔲 Starting Grid for {self.config.symbol}")
        logger.info(f"   Range: ${self.config.lower_price:.2f} - ${self.config.upper_price:.2f}")
        logger.info(f"   Grids: {self.config.num_grids}, Investment: ${self.config.total_investment:.2f}")
        
        try:
            # Get current price
            ticker = self.client._request("/v5/market/tickers", {"category": self.client.category.value, "symbol": self.config.symbol})
            if not ticker or 'list' not in ticker:
                logger.error("Failed to get ticker")
                return False
            
            current_price = float(ticker['list'][0]['lastPrice'])
            levels = self.config.get_grid_levels()
            order_size_usd = self.config.get_order_size()
            
            # Place buy orders BELOW current price, sell orders ABOVE
            for level in levels:
                qty = order_size_usd / level
                
                if level < current_price:
                    # Place Buy Limit
                    self._place_limit_order(level, qty, "Buy")
                elif level > current_price:
                    # Place Sell Limit (only if we have inventory)
                    # Initially we only place buys, sells come after buys fill
                    pass
            
            self.status = GridStatus.RUNNING
            logger.info(f"✅ Grid started with {len(self.active_orders)} orders")
            return True
            
        except Exception as e:
            logger.error(f"Grid start failed: {e}")
            return False
    
    def _place_limit_order(self, price: float, qty: float, side: str) -> Optional[str]:
        """Place a limit order"""
        try:
            # Get instrument info for rounding
            instr = self.client.get_instrument_info(self.config.symbol)
            qty_step = float(instr.get('lotSizeFilter', {}).get('qtyStep', '0.001'))
            price_tick = float(instr.get('priceFilter', {}).get('tickSize', '0.01'))
            
            # Round
            import math
            qty_decimals = len(str(qty_step).split('.')[-1]) if '.' in str(qty_step) else 0
            price_decimals = len(str(price_tick).split('.')[-1]) if '.' in str(price_tick) else 0
            
            qty = math.floor(qty / qty_step) * qty_step
            qty = round(qty, qty_decimals)
            price = round(round(price / price_tick) * price_tick, price_decimals)
            
            if qty <= 0:
                return None
            
            result = self.client.place_order(
                symbol=self.config.symbol,
                side=side,
                order_type="Limit",
                qty=qty,
                price=price,
                reduce_only=False
            )
            
            if result and 'orderId' in result:
                order_id = result['orderId']
                self.active_orders[order_id] = {
                    'side': side,
                    'price': price,
                    'qty': qty,
                    'status': 'open'
                }
                logger.info(f"📝 Grid {side} order placed: {qty} @ ${price}")
                return order_id
                
        except Exception as e:
            logger.error(f"Grid order failed: {e}")
        return None
    
    def check_and_rebalance(self):
        """
        Check filled orders and place opposite orders.
        Called periodically from main loop.
        """
        if self.status != GridStatus.RUNNING:
            return
            
        try:
            # Check order statuses
            for order_id, order_info in list(self.active_orders.items()):
                # Query order status from exchange
                status = self.client._request("/v5/order/realtime", {"category": self.client.category.value, "orderId": order_id})
                
                if status and 'list' in status and status['list']:
                    order_status = status['list'][0].get('orderStatus', '')
                    
                    if order_status == 'Filled':
                        # Order filled! Place opposite order
                        fill_price = order_info['price']
                        fill_qty = order_info['qty']
                        
                        if order_info['side'] == 'Buy':
                            # Buy filled -> Place Sell above
                            self.filled_buys.append(fill_price)
                            sell_price = fill_price * 1.005  # +0.5% profit target
                            self._place_limit_order(sell_price, fill_qty, "Sell")
                            logger.info(f"🟢 Grid Buy filled @ {fill_price}, placing Sell @ {sell_price}")
                            
                        else:
                            # Sell filled -> Place Buy below + record profit
                            profit = (fill_price - self.filled_buys.pop(0)) * fill_qty if self.filled_buys else 0
                            self.pnl += profit
                            buy_price = fill_price * 0.995  # -0.5% rebuy
                            self._place_limit_order(buy_price, fill_qty, "Buy")
                            logger.info(f"🔴 Grid Sell filled @ {fill_price}, profit: ${profit:.2f}, total PnL: ${self.pnl:.2f}")
                        
                        # Remove from active
                        del self.active_orders[order_id]
                        
        except Exception as e:
            logger.error(f"Grid rebalance error: {e}")
    
    def stop(self) -> Dict:
        """Stop grid and cancel all orders"""
        logger.info("🛑 Stopping Grid...")
        
        cancelled = 0
        for order_id in list(self.active_orders.keys()):
            try:
                self.client._request('/v5/order/cancel', {
                    'category': 'linear',
                    'symbol': self.config.symbol,
                    'orderId': order_id
                }, method='POST', signed=True)
                cancelled += 1
            except:
                pass
        
        self.status = GridStatus.STOPPED
        self.active_orders.clear()
        
        return {
            'cancelled': cancelled,
            'total_pnl': self.pnl
        }
    
    def get_status(self) -> Dict:
        """Get current grid status"""
        return {
            'status': self.status.value,
            'symbol': self.config.symbol,
            'active_orders': len(self.active_orders),
            'filled_buys': len(self.filled_buys),
            'pnl': self.pnl,
            'range': f"${self.config.lower_price:.2f} - ${self.config.upper_price:.2f}"
        }


def create_auto_grid(client, symbol: str, investment: float = 50.0, num_grids: int = 10) -> Optional[GridTrader]:
    """
    Auto-creates a grid based on current price and ATR.
    Uses ±3% from current price as default range.
    """
    try:
        ticker = client._request("/v5/market/tickers", {"category": client.category.value, "symbol": symbol})
        if not ticker or 'list' not in ticker:
            return None
        
        current_price = float(ticker['list'][0]['lastPrice'])
        
        # Default: ±3% range
        upper = current_price * 1.03
        lower = current_price * 0.97
        
        config = GridConfig(
            symbol=symbol,
            upper_price=upper,
            lower_price=lower,
            num_grids=num_grids,
            total_investment=investment
        )
        
        return GridTrader(client, config)
        
    except Exception as e:
        logger.error(f"Auto-grid creation failed: {e}")
        return None
