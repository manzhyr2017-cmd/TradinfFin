import pandas as pd
import numpy as np
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import os
import sys
import logging
import time

# Импорт твоих компонентов
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
from brain.master_brain import MasterBrain
import config

# Настройка логирования для бэктеста
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
log = logging.getLogger("Backtest")

class MockBybitClient:
    def __init__(self, df, initial_balance=1000.0):
        self.df = df
        self.balance = Decimal(str(initial_balance))
        self.price = Decimal("0")
        self.open_orders = [] 
        self.fills = []
        self.symbol = config.SYMBOL
        self.leverage = 1
        self.current_idx = 0
        
    def __getattr__(self, name):
        """Ловим все недостающие методы биржи, чтобы бэктест не падал."""
        def wrapper(*args, **kwargs):
            return None
        return wrapper

    def get_price(self, symbol=None): return self.price
    def get_balance(self, coin="USDT"): return self.balance
    
    def get_instrument_info(self, symbol=None):
        return {
            "min_qty": Decimal("1"), # Для бэктеста упростим
            "qty_step": Decimal("1"), 
            "tick_size": Decimal("0.01"),
            "max_leverage": 100
        }
    
    def get_klines(self, symbol=None, interval="15", limit=200):
        """Возвращает исторические свечи из нашего DF на момент симуляции."""
        start = max(0, self.current_idx - limit)
        sub = self.df.iloc[start:self.current_idx]
        klines = []
        for _, r in sub.iterrows():
            # Формат Bybit: [ts, open, high, low, close, vol, turnover]
            klines.append([str(r['timestamp']), str(r['open']), str(r['high']), str(r['low']), str(r['close']), str(r['volume']), "0"])
        return klines

    def place_order(self, side, qty, price, order_link_id=None, **kwargs):
        oid = f"mock_{len(self.fills) + len(self.open_orders)}_{int(time.time()*1000)}"
        order = {
            "orderId": oid,
            "orderLinkId": order_link_id,
            "side": side,
            "price": Decimal(str(price)),
            "qty": Decimal(str(qty)),
            "status": "New"
        }
        self.open_orders.append(order)
        return oid

    def cancel_all(self, symbol=None):
        self.open_orders = []
        return True
    
    def cancel_all_orders(self, symbol=None): return self.cancel_all()

    def set_leverage(self, symbol, leverage):
        self.leverage = leverage
        return True

    def check_fills(self, high, low, sim_time):
        executed = []
        remaining = []
        for order in self.open_orders:
            price = order['price']
            is_filled = False
            if order['side'] == "Buy" and low <= price: is_filled = True
            elif order['side'] == "Sell" and high >= price: is_filled = True
            
            if is_filled:
                order['status'] = 'Filled'
                order['fill_price'] = float(price)
                executed.append(order)
            else:
                remaining.append(order)
        self.open_orders = remaining
        return executed

# --- MOCK DATABASE ---
class MockDatabase:
    def __init__(self):
        self.state = {}
        self.trades = []
        self.sim_time = datetime.now()
    def save_state(self, k, v): self.state[k] = v
    def load_state(self, k, default=None): return self.state.get(k, default)
    def save_trade(self, trade_data):
        trade_data['timestamp'] = self.sim_time.isoformat()
        self.trades.append(trade_data)
    def save_trade_reason(self, order_id, reason):
        for t in self.trades:
            if t.get('order_id') == order_id: t['reason'] = reason; break
    def update_trade_profit(self, order_id, profit, reason=None):
        for t in self.trades:
            if t.get('order_id') == order_id:
                t['profit_usdt'] = float(profit); t['status'] = 'FILLED'
                if reason: t['reason'] = reason
                break
    def update_level_order(self, idx, side, oid): pass
    def get_trades_today(self):
        window = self.sim_time - timedelta(days=1)
        return [t for t in self.trades if datetime.fromisoformat(t['timestamp']) > window]
    def get_total_profit(self):
        return Decimal(str(sum(float(t.get('profit_usdt', 0) or 0) for t in self.trades)))
    def clear_active_orders(self):
        self.trades = [t for t in self.trades if t.get('status') != 'NEW']

class SimulationAdapter:
    def __init__(self, data_path='historical_data.csv'):
        self.df = pd.read_csv(data_path)
        self.client = MockBybitClient(self.df, initial_balance=config.INITIAL_CAPITAL)
        self.db = MockDatabase()
        self.brain = MasterBrain()
        self.brain.client = self.client
        self.brain.db = self.db
        # Mocks
        self.brain.notifier = type('MockNotifier', (), {'send_alert': lambda *a, **k: None, 'send_message': lambda *a, **k: None, 'send': lambda *a, **k: None})()
        self.brain.reporter = type('MockReporter', (), {'log_full_report': lambda *a, **k: None})()
        
    def run(self):
        print(f"🕵️ Backtest started: {len(self.df)} candles...")
        for idx, row in self.df.iterrows():
            self.client.current_idx = idx
            ts = row['timestamp']
            sim_time = datetime.fromtimestamp(int(ts)/1000, tz=timezone.utc) if isinstance(ts, (int, float)) or str(ts).isdigit() else datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
            self.db.sim_time = sim_time
            price, high, low = Decimal(str(row['close'])), Decimal(str(row['high'])), Decimal(str(row['low']))
            self.client.price = price

            # 1. Fills
            fills = self.client.check_fills(high, low, sim_time)
            for fill in fills:
                lv_idx = 0
                if fill['orderLinkId'] and 'LVL-' in fill['orderLinkId']:
                    lv_idx = int(fill['orderLinkId'].split('-LVL-')[1].split('-')[0])
                self.brain.decide_and_act(
                    filled_order_id=fill['orderId'], filled_side=fill['side'],
                    filled_price=fill['fill_price'], filled_qty=float(fill['qty']),
                    filled_profit=0, filled_level_index=lv_idx
                )

            # 2. Decide
            self.brain.decide_and_act()

            if idx % 1440 == 0:
                print(f"Day {idx//1440} | Equity: {float(self.client.get_balance()) + float(self.db.get_total_profit()):.2f}")

        self.report()

    def report(self):
        profit = float(self.db.get_total_profit())
        print("\n" + "="*50 + "\n🏁 BACKTEST REPORT\n" + "="*50)
        print(f"Profit: {profit:+.2f} USDT | Balance: {float(self.client.get_balance()):.2f}")
        print(f"Trades: {len(self.db.trades)} | Protection Locks: {self.brain.stats.get('protections_triggered', 0)}")
        print("="*50)

if __name__ == "__main__":
    SimulationAdapter().run()
