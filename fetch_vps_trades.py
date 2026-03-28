
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
import time

# Add titan_bot to path
sys.path.append(str(Path(os.getcwd()) / "titan_bot"))

import config
from data_engine import DataEngine

def fetch_actual_trades():
    print("--- FETCHING ACTUAL TRADES FROM BYBIT API ---")
    data = DataEngine()
    
    # 3 days ago in milliseconds
    three_days_ago_ms = int((datetime.now() - timedelta(days=3)).timestamp() * 1000)
    
    try:
        # Fetching closed PNL for the account
        # Note: Category is required, usually 'linear' as per config
        response = data.session.get_closed_pnl(
            category=config.CATEGORY,
            limit=100,
            startTime=three_days_ago_ms
        )
        
        if response['retCode'] != 0:
            print(f"❌ Error fetching trades: {response['retMsg']}")
            return

        trades = response['result']['list']
        if not trades:
            print("No closed trades found in the last 3 days.")
            return

        print(f"Found {len(trades)} closed trades.\n")
        
        total_pnl = 0
        wins = 0
        losses = 0
        
        # Sort by fill time
        trades.sort(key=lambda x: int(x.get('updatedTime', 0)))
        
        print(f"{'Time':<20} | {'Symbol':<10} | {'Side':<5} | {'Qty':<10} | {'Entry':<10} | {'Exit':<10} | {'PnL':<10}")
        print("-" * 90)
        
        for t in trades:
            symbol = t.get('symbol', 'N/A')
            side = t.get('side', 'N/A')
            qty = t.get('qty', '0')
            entry_price = t.get('avgEntryPrice', '0')
            exit_price = t.get('avgExitPrice', '0')
            pnl = float(t.get('closedPnl', 0))
            updated_time = int(t.get('updatedTime', 0))
            dt = datetime.fromtimestamp(updated_time / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            total_pnl += pnl
            if pnl > 0: wins += 1
            elif pnl < 0: losses += 1
            
            print(f"{dt:<20} | {symbol:<10} | {side:<5} | {qty:<10} | {entry_price:<10} | {exit_price:<10} | ${pnl:+.2f}")

        print("-" * 90)
        print(f"Total PnL: ${total_pnl:.2f}")
        if (wins + losses) > 0:
            print(f"Win Rate: {(wins / (wins + losses)) * 100:.1f}% ({wins}W / {losses}L)")
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {str(e)}")

if __name__ == "__main__":
    fetch_actual_trades()
