from decimal import Decimal
import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bybit_optimizer import BybitOptimizer
import config

class MockBybit:
    def get_fee_rate(self, **kwargs):
        return {"retCode": 0, "result": {"list": [{"makerFeeRate": "0.0001", "takerFeeRate": "0.0005"}]}}
    
    def get_account_info(self, **kwargs):
        return {"retCode": 0, "result": {"vipLevel": "VIP-3"}}
    
    def place_order(self, **kwargs):
        print(f"Mock Order: {kwargs.get('side')} at {kwargs.get('price')} (TIF: {kwargs.get('timeInForce')})")
        return {"retCode": 0, "result": {"orderId": "mock_id_123"}}

    def place_batch_order(self, **kwargs):
        reqs = kwargs.get("request", [])
        print(f"Mock Batch: Placing {len(reqs)} orders")
        return {
            "retCode": 0, 
            "result": {
                "list": [{"code": 0, "orderId": f"batch_{i}"} for i in range(len(reqs))]
            }
        }

def test_optimization():
    print("--- Verifying Bybit Optimization & Performance ---")
    mock_bybit = MockBybit()
    optimizer = BybitOptimizer(mock_bybit)
    
    # 1. Test Fee Update
    maker, taker = optimizer.get_effective_fees()
    print(f"Fee Check: Maker={maker}, Taker={taker}")
    
    # 2. Test PostOnly
    oid = optimizer.place_post_only("Buy", 0.1, 2600)
    print(f"PostOnly Result: {oid}")
    
    # 3. Test Batch Grid
    orders = [{"side": "Sell", "price": 2700 + i, "qty": 0.05} for i in range(5)]
    oids = optimizer.place_batch_grid(orders)
    print(f"Batch Grid Result: {len(oids)} orders placed")
    
    # 4. Final Stats
    report = optimizer.get_status_report()
    print(f"Stats Report: {report}")
    print("--- Done ---")

if __name__ == "__main__":
    test_optimization()
