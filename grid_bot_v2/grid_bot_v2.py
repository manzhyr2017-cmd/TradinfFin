import time
import pandas as pd
from pybit.unified_trading import HTTP
from config import *
from indicators import *
from notifier import send_telegram_message
from database import session, Trade, BotState

from ws_client import OrderWebSocket, TickerWebSocket
from analyzers import SpreadAnalyzer, MultiTimeframeAnalyzer, AnomalyDetector
from risk_manager import SmartSizer
from decimal import Decimal

class GridBot:
    def __init__(self):
        self.session = HTTP(
            testnet=False,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET,
        )
        self.grid_orders = []
        self._current_price = Decimal("0")
        
        # New Modules
        self.order_ws = OrderWebSocket(
            on_order_filled=self._ws_on_filled,
            on_order_cancelled=self._ws_on_cancelled
        )
        self.ticker_ws = TickerWebSocket(
            on_price_update=self._ws_on_price
        )
        self.spread_analyzer = SpreadAnalyzer(self)
        self.mtf_analyzer = MultiTimeframeAnalyzer(self.session)
        self.anomaly_detector = AnomalyDetector()

    def _ws_on_filled(self, order_data):
        print(f"⚡ Real-time Fill: {order_data['side']} at {order_data['avgPrice']}")
        # Logic to handle fill (e.g. place next grid level)
        
    def _ws_on_cancelled(self, order_data):
        print(f"❌ Order Cancelled: {order_data['orderId']}")

    def _ws_on_price(self, price, volume):
        self._current_price = Decimal(price)

    def get_market_data(self):
        # Fetch kline data for indicators
        kline = self.session.get_kline(
            category="spot",
            symbol=SYMBOL,
            interval="60",
            limit=250
        )
        # Convert to DataFrame
        columns = ["timestamp", "open", "high", "low", "close", "volume", "turnover"]
        df = pd.DataFrame(kline['result']['list'], columns=columns)
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        return df.iloc[::-1]  # Reverse for proper TA order

    def check_indicators(self, df):
        ema = calculate_ema(df, EMA_PERIOD).iloc[-1]
        rsi = calculate_rsi(df, RSI_PERIOD).iloc[-1]
        current_price = float(self._current_price) if self._current_price > 0 else df['close'].iloc[-1]
        
        # Trend Filter: Only Buy if Price > EMA 200
        is_uptrend = current_price > ema
        # Momentum Filter: Not Overbought
        is_safe_rsi = rsi < RSI_OVERBOUGHT
        
        # MTF check
        regime = self.mtf_analyzer.analyze_regime()
        
        return is_uptrend and is_safe_rsi and regime == "sideways"

    def place_order(self, side, price, qty):
        try:
            # Spread check before placing
            spread_info = self.spread_analyzer.get_current_spread()
            if spread_info['spread_pct'] > 0.1: # Threshold 0.1%
                print(f"⚠️ High Spread: {spread_info['spread_pct']}% - skipping order")
                return None

            order = self.session.place_order(
                category="spot",
                symbol=SYMBOL,
                side=side,
                orderType="Limit",
                price=str(price),
                qty=str(qty),
            )
            # Log to Database
            new_trade = Trade(
                symbol=SYMBOL,
                order_id=order['result']['orderId'],
                side=side,
                price=price,
                qty=qty,
                status="NEW"
            )
            session.add(new_trade)
            session.commit()
            
            send_telegram_message(f"🚀 <b>Order Placed:</b> {side} {SYMBOL} at {price}")
            return order
        except Exception as e:
            print(f"Order Error: {e}")
            return None

    def manage_grid(self, current_price):
        # Fetch current open orders from Bybit
        try:
            open_orders = self.session.get_open_orders(category="spot", symbol=SYMBOL)['result']['list']
            # Re-sync database statuses if needed
            for order in open_orders:
                db_trade = session.query(Trade).filter_by(order_id=order['orderId']).first()
                if db_trade and db_trade.status != order['status']:
                    db_trade.status = order['status']
            session.commit()
            
            # Simple Grid Logic: 
            # 1. If no open orders and indicators are green, start base grid
            if len(open_orders) == 0:
                # Anomaly check
                is_anomaly, reason = self.anomaly_detector.check(current_price)
                if is_anomaly:
                    print(f"🛑 Pausing: {reason}")
                    return

                print("No open orders. Initializing grid...")
                
                # Dynamic Qty using SmartSizer
                # Assuming simple balance for now, real implementation should fetch from session
                balance = Decimal("1000") # Placeholder
                qty = SmartSizer.calculate_qty(balance, current_price)
                
                # Place a Buy order below and a Sell order above
                buy_price = round(float(current_price) * (1 - GRID_STEP_PERCENT/100), 2)
                sell_price = round(float(current_price) * (1 + GRID_STEP_PERCENT/100), 2)
                
                self.place_order("Buy", buy_price, qty)
                self.place_order("Sell", sell_price, qty)
                
        except Exception as e:
            print(f"Grid Management Error: {e}")

    def run(self):
        print(f"Starting {SYMBOL} Grid Bot v2.1 (WS Enabled)...")
        send_telegram_message(f"🟢 Grid Bot v2.1 Started for {SYMBOL}")
        
        # Start WebSockets
        self.order_ws.start()
        self.ticker_ws.start()
        
        while True:
            try:
                df = self.get_market_data()
                current_price = self._current_price if self._current_price > 0 else Decimal(str(df['close'].iloc[-1]))
                
                if self.check_indicators(df):
                    self.manage_grid(current_price)
                else:
                    print("Indicators suggest staying flat.")
                
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                print(f"Runtime Error: {e}")
                time.sleep(10)

if __name__ == "__main__":
    bot = GridBot()
    bot.run()
