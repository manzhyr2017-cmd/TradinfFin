
from core.bybit_client import BybitClient
import json

client = BybitClient()
try:
    # Проверка режима позиции (One-Way или Hedge)
    res = client.session.get_positions(
        category=client.category,
        symbol="BNBUSDT"
    )
    print("Position Info:")
    print(json.dumps(res, indent=2))
    
    # Проверка типа аккаунта (UTA или нет)
    acc = client.session.get_account_info()
    print("\nAccount Info:")
    print(json.dumps(acc, indent=2))
    
    # Проверка баланса
    bal = client.session.get_wallet_balance(
        accountType="UNIFIED",
        coin="USDT"
    )
    print("\nBalance (UTA):")
    print(json.dumps(bal, indent=2))
except Exception as e:
    print(f"Error: {e}")
