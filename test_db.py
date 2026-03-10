import sqlite3
import json

conn = sqlite3.connect('titan_bot/data/titan_main.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT * FROM trades ORDER BY entry_time DESC LIMIT 10")
for r in c.fetchall():
    print(f"{r['entry_time']} | {r['symbol']} | {r['side']} | {r['score_total']} | PNL: {r['pnl']}")
    try:
        print(f"  Details: {r['score_details']}")
    except:
        pass
