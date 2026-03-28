
import sqlite3
from datetime import datetime, timedelta
import json

db_path = r"d:\Projects\Trading\titan_bot\data\titan_main.db"

def analyze_trades():
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Calculate three days ago
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        print(f"Analyzing trades since: {three_days_ago}")
        
        query = "SELECT * FROM trades WHERE entry_time >= ? ORDER BY entry_time DESC"
        cursor.execute(query, (three_days_ago,))
        columns = [column[0] for column in cursor.description]
        trades = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        if not trades:
            print("No trades found in the last 3 days.")
            return

        print(f"Found {len(trades)} trades.")
        
        total_pnl = 0
        wins = 0
        losses = 0
        
        print("\n--- Trade List ---")
        for t in trades:
            pnl = t['pnl'] if t['pnl'] is not None else 0
            total_pnl += pnl
            if pnl > 0: wins += 1
            elif pnl < 0: losses += 1
            
            status = t['status']
            symbol = t['symbol']
            side = t['side']
            entry_time = t['entry_time']
            pnl_pct = t['pnl_percent'] if t['pnl_percent'] is not None else 0
            score = t['score_total']
            
            print(f"[{entry_time}] {symbol} {side} | Status: {status} | PnL: {pnl:.2f} ({pnl_pct:.2f}%) | Score: {score}")

        print("\n--- Summary ---")
        print(f"Total PnL: {total_pnl:.2f}")
        print(f"Win Rate: {wins/(wins+losses)*100 if (wins+losses) > 0 else 0:.1f}% ({wins}W / {losses}L)")
        
        # Also check system logs for errors
        print("\n--- Recent System Logs (Errors/Warnings) ---")
        cursor.execute("SELECT * FROM logs WHERE timestamp >= ? AND level IN ('ERROR', 'WARNING') ORDER BY timestamp DESC LIMIT 10", (three_days_ago,))
        logs = cursor.fetchall()
        for log in logs:
            print(f"[{log[1]}] {log[2]} | {log[3]}: {log[4]}")

        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze_trades()
