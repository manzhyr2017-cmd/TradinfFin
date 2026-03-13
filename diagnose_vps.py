import sqlite3
import os
from datetime import datetime

# Проверяем пути и в корне, и в подпапке
DB_PATHS = [
    "data/grid_state.db",
    "grid_bot/data/grid_state.db",
    "/opt/grid-bot/data/grid_state.db"
]

def get_db_path():
    for p in DB_PATHS:
        if os.path.exists(p):
            return p
    return None

def diagnose():
    db_path = get_db_path()
    if not db_path:
        print(f"❌ База данных не найдена! Проверены пути: {DB_PATHS}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=== GRID BOT DIAGNOSTICS ===")
    
    # 1. Summary of states
    cursor.execute("SELECT symbol, upper, lower, total_profit, total_trades, start_balance, updated_at FROM grid_state")
    rows = cursor.fetchall()
    
    total_db_profit = 0
    for row in rows:
        symbol, upper, lower, profit, trades, start_bal, updated = row
        total_db_profit += profit
        print(f"\nSymbol: {symbol}")
        print(f"  Range: {lower} - {upper}")
        print(f"  Trades: {trades}")
        print(f"  Closed Profit: ${profit:.2f}")
        print(f"  Last Update: {updated}")

    print(f"\nTOTAL CLOSED PROFIT (DB): ${total_db_profit:.2f}")

    # 2. Check levels per symbol
    for row in rows:
        symbol = row[0]
        cursor.execute("SELECT side, status, COUNT(*) FROM grid_levels WHERE symbol = ? GROUP BY side, status", (symbol,))
        level_stats = cursor.fetchall()
        print(f"\nLevels for {symbol}:")
        for stat in level_stats:
            print(f"  {stat[0]} {stat[1]}: {stat[2]}")

    conn.close()

if __name__ == "__main__":
    diagnose()
