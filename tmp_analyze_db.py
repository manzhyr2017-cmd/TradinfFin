import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

db = sqlite3.connect(r'd:\Projects\Trading\titan_bot\data\titan_main.db')
c = db.cursor()

# Show all tables
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()
print('=== TABLES ===')
for t in tables:
    print(t[0])

for table in tables:
    tn = table[0]
    c.execute(f'SELECT COUNT(*) FROM {tn}')
    cnt = c.fetchone()[0]
    print(f'\n=== {tn}: {cnt} rows ===')
    if cnt > 0:
        c.execute(f'SELECT * FROM {tn} LIMIT 3')
        cols = [d[0] for d in c.description]
        print('Columns:', cols)
        for row in c.fetchall():
            print(row)

# Deep analysis of trades
print('\n\n========== DEEP TRADE ANALYSIS ==========')
c.execute("SELECT * FROM trades ORDER BY entry_time DESC")
cols = [d[0] for d in c.description]
trades = [dict(zip(cols, row)) for row in c.fetchall()]
print(f'Total trades: {len(trades)}')

if trades:
    total_pnl = 0
    wins = 0
    losses = 0
    pnl_by_symbol = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
    pnl_by_side = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
    pnl_by_day = defaultdict(lambda: {'pnl': 0, 'count': 0})
    pnl_by_hour = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
    scores = []
    win_scores = []
    loss_scores = []
    
    for t in trades:
        pnl = t['pnl'] if t['pnl'] is not None else 0
        total_pnl += pnl
        symbol = t['symbol']
        side = t['side']
        score = t['score_total'] if t['score_total'] is not None else 0
        status = t['status']
        
        if pnl > 0:
            wins += 1
            win_scores.append(score)
        elif pnl < 0:
            losses += 1
            loss_scores.append(score)
        
        pnl_by_symbol[symbol]['pnl'] += pnl
        pnl_by_symbol[symbol]['count'] += 1
        if pnl > 0: pnl_by_symbol[symbol]['wins'] += 1
        elif pnl < 0: pnl_by_symbol[symbol]['losses'] += 1
        
        pnl_by_side[side]['pnl'] += pnl
        pnl_by_side[side]['count'] += 1
        if pnl > 0: pnl_by_side[side]['wins'] += 1
        elif pnl < 0: pnl_by_side[side]['losses'] += 1
        
        if t['entry_time']:
            try:
                dt = datetime.fromisoformat(t['entry_time'].replace('Z', '+00:00'))
                day_name = dt.strftime('%A')
                hour = dt.hour
                pnl_by_day[day_name]['pnl'] += pnl
                pnl_by_day[day_name]['count'] += 1
                pnl_by_hour[hour]['pnl'] += pnl
                pnl_by_hour[hour]['count'] += 1
                if pnl > 0: pnl_by_hour[hour]['wins'] += 1
                elif pnl < 0: pnl_by_hour[hour]['losses'] += 1
            except:
                pass
        
        scores.append(score)
    
    print(f'\nTotal PnL: ${total_pnl:.2f}')
    wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
    print(f'Win Rate: {wr:.1f}% ({wins}W / {losses}L)')
    if win_scores:
        print(f'Avg Win Score: {sum(win_scores)/len(win_scores):.1f}')
    if loss_scores:
        print(f'Avg Loss Score: {sum(loss_scores)/len(loss_scores):.1f}')
    
    # By side
    print('\n--- BY SIDE ---')
    for side, data in sorted(pnl_by_side.items()):
        total = data['wins'] + data['losses']
        wr = data['wins'] / total * 100 if total > 0 else 0
        print(f'{side}: PnL=${data["pnl"]:.2f} | {data["count"]} trades | WR={wr:.1f}% ({data["wins"]}W/{data["losses"]}L)')
    
    # By symbol (top losers)
    print('\n--- TOP LOSERS BY SYMBOL ---')
    sorted_symbols = sorted(pnl_by_symbol.items(), key=lambda x: x[1]['pnl'])
    for sym, data in sorted_symbols[:15]:
        total = data['wins'] + data['losses']
        wr = data['wins'] / total * 100 if total > 0 else 0
        print(f'{sym:12} PnL=${data["pnl"]:+.2f} | {data["count"]} trades | WR={wr:.1f}%')
    
    # By symbol (top winners)
    print('\n--- TOP WINNERS BY SYMBOL ---')
    for sym, data in sorted_symbols[-10:]:
        total = data['wins'] + data['losses']
        wr = data['wins'] / total * 100 if total > 0 else 0
        print(f'{sym:12} PnL=${data["pnl"]:+.2f} | {data["count"]} trades | WR={wr:.1f}%')
    
    # By day
    print('\n--- BY DAY OF WEEK ---')
    for day, data in sorted(pnl_by_day.items()):
        print(f'{day:12} PnL=${data["pnl"]:+.2f} | {data["count"]} trades')
    
    # By hour
    print('\n--- BY HOUR (UTC) ---')
    for hour in sorted(pnl_by_hour.keys()):
        data = pnl_by_hour[hour]
        total = data['wins'] + data['losses']
        wr = data['wins'] / total * 100 if total > 0 else 0
        print(f'{hour:02d}:00 PnL=${data["pnl"]:+.2f} | {data["count"]} trades | WR={wr:.1f}%')
    
    # Date range
    dates = [t['entry_time'] for t in trades if t['entry_time']]
    if dates:
        print(f'\nDate range: {min(dates)} to {max(dates)}')
    
    # Consecutive losses analysis
    print('\n--- DRAWDOWN ANALYSIS ---')
    cumulative = 0
    max_dd = 0
    peak = 0
    for t in reversed(trades):  # chronological order
        pnl = t['pnl'] if t['pnl'] is not None else 0
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    print(f'Max Drawdown: ${max_dd:.2f}')
    print(f'Final Cumulative PnL: ${cumulative:.2f}')
    
    # Last 20 trades
    print('\n--- LAST 20 TRADES ---')
    for t in trades[:20]:
        pnl = t['pnl'] if t['pnl'] is not None else 0
        pnl_pct = t['pnl_percent'] if t['pnl_percent'] is not None else 0
        icon = '+' if pnl > 0 else '-' if pnl < 0 else '='
        print(f'[{t["entry_time"]}] {t["symbol"]:12} {t["side"]:4} | PnL=${pnl:+.2f} ({pnl_pct:+.2f}%) | Score={t["score_total"]} | {t["status"]}')

# Check for open trades
print('\n--- OPEN TRADES ---')
c.execute("SELECT * FROM trades WHERE status='open'")
open_cols = [d[0] for d in c.description]
open_trades = [dict(zip(open_cols, row)) for row in c.fetchall()]
print(f'Open trades: {len(open_trades)}')
for t in open_trades:
    print(f'  {t["symbol"]} {t["side"]} entry={t["entry_price"]} sl={t["stop_loss"]} tp={t["take_profit"]}')

# Check recent logs
print('\n--- RECENT LOGS (last 30) ---')
try:
    c.execute("SELECT * FROM logs ORDER BY timestamp DESC LIMIT 30")
    log_cols = [d[0] for d in c.description]
    for row in c.fetchall():
        log = dict(zip(log_cols, row))
        print(f'[{log.get("timestamp","")}] {log.get("level","")} | {log.get("module","")} | {log.get("message","")}')
except Exception as e:
    print(f'Logs error: {e}')

db.close()
