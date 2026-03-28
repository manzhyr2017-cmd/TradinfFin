"""
Direct Bybit API trade fetcher - forces .env keys
"""
import sys
from datetime import datetime, timedelta
from collections import defaultdict
from pybit.unified_trading import HTTP

# Force these credentials from .env
API_KEY = "E79XlJz8KpQXDWPKw4"
API_SECRET = "WZVMqcFnPE4cHsbpylzF301vATXzKPZAooX7"

print(f"API Key: {API_KEY[:8]}****")

session = HTTP(
    api_key=API_KEY,
    api_secret=API_SECRET,
    demo=False
)

# Fetch balance
print("\n=== BALANCE ===")
try:
    wallet = session.get_wallet_balance(accountType="UNIFIED")
    if wallet['retCode'] == 0:
        for acc in wallet['result']['list']:
            print(f"Account equity: {acc.get('totalEquity', '?')}")
            print(f"Available balance: {acc.get('totalAvailableBalance', '?')}")
            for coin in acc['coin']:
                bal = float(coin.get('walletBalance', 0))
                if bal > 0.001:
                    print(f"  {coin['coin']}: balance={coin['walletBalance']} equity={coin.get('equity','?')} uPnL={coin.get('unrealisedPnl','?')}")
    else:
        print(f"Error: {wallet['retMsg']}")
except Exception as e:
    print(f"Balance error: {e}")

import time
time.sleep(0.5)

# Fetch closed PnL - paginated
print("\n=== FETCHING TRADES ===")
all_trades = []
cursor = ""
pages = 0
start_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

while pages < 30:
    try:
        params = {
            "category": "linear",
            "limit": 100,
            "startTime": start_ms,
        }
        if cursor:
            params["cursor"] = cursor
        
        response = session.get_closed_pnl(**params)
        
        if response['retCode'] != 0:
            print(f"API Error: {response['retMsg']}")
            break
        
        trades = response['result']['list']
        if not trades:
            break
        
        all_trades.extend(trades)
        cursor = response['result'].get('nextPageCursor', '')
        pages += 1
        
        if not cursor:
            break
        
        print(f"  Page {pages}: +{len(trades)} trades (total: {len(all_trades)})")
        time.sleep(0.3)
        
    except Exception as e:
        print(f"Fetch error: {e}")
        break

print(f"\nTOTAL TRADES: {len(all_trades)}")

if not all_trades:
    # Try without startTime
    print("\nRetrying without time filter...")
    try:
        response = session.get_closed_pnl(category="linear", limit=100)
        if response['retCode'] == 0:
            all_trades = response['result']['list']
            print(f"Got {len(all_trades)} trades")
        else:
            print(f"Error: {response['retMsg']}")
    except Exception as e:
        print(f"Error: {e}")

if not all_trades:
    print("\nNo trades at all. Trying execution list...")
    try:
        response = session.get_executions(category="linear", limit=100)
        if response['retCode'] == 0:
            execs = response['result']['list']
            print(f"Executions found: {len(execs)}")
            for ex in execs[:10]:
                print(f"  {ex.get('symbol')} {ex.get('side')} {ex.get('execType')} qty={ex.get('execQty')} price={ex.get('execPrice')} pnl={ex.get('closedPnl','?')}")
        else:
            print(f"Error: {response['retMsg']}")
    except Exception as e:
        print(f"Executions error: {e}")
    sys.exit(0)

# Sort oldest first
all_trades.sort(key=lambda x: int(x.get('updatedTime', 0)))

# ========== FULL ANALYSIS ==========
total_pnl = 0
wins = 0
losses = 0
pnl_by_symbol = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
pnl_by_side = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
pnl_by_day = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
pnl_by_hour = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
daily_pnl = defaultdict(float)

for t in all_trades:
    pnl = float(t.get('closedPnl', 0))
    symbol = t.get('symbol', '?')
    side = t.get('side', '?')
    updated = int(t.get('updatedTime', 0))
    
    total_pnl += pnl
    if pnl > 0: wins += 1
    elif pnl < 0: losses += 1
    
    pnl_by_symbol[symbol]['pnl'] += pnl
    pnl_by_symbol[symbol]['count'] += 1
    if pnl > 0: pnl_by_symbol[symbol]['wins'] += 1
    elif pnl < 0: pnl_by_symbol[symbol]['losses'] += 1
    
    pnl_by_side[side]['pnl'] += pnl
    pnl_by_side[side]['count'] += 1
    if pnl > 0: pnl_by_side[side]['wins'] += 1
    elif pnl < 0: pnl_by_side[side]['losses'] += 1
    
    if updated:
        dt = datetime.fromtimestamp(updated / 1000)
        day_name = dt.strftime('%A')
        hour = dt.hour
        date_str = dt.strftime('%Y-%m-%d')
        
        pnl_by_day[day_name]['pnl'] += pnl
        pnl_by_day[day_name]['count'] += 1
        if pnl > 0: pnl_by_day[day_name]['wins'] += 1
        elif pnl < 0: pnl_by_day[day_name]['losses'] += 1
        
        pnl_by_hour[hour]['pnl'] += pnl
        pnl_by_hour[hour]['count'] += 1
        if pnl > 0: pnl_by_hour[hour]['wins'] += 1
        elif pnl < 0: pnl_by_hour[hour]['losses'] += 1
        
        daily_pnl[date_str] += pnl

# Print summary
print(f"\n{'='*80}")
print(f"TITAN BOT PERFORMANCE REPORT")
print(f"{'='*80}")
print(f"Period: {len(daily_pnl)} trading days")
print(f"Total Trades: {len(all_trades)}")
print(f"Total PnL: ${total_pnl:.4f}")
wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
print(f"Win Rate: {wr:.1f}% ({wins}W / {losses}L)")

# PnL dist
win_pnls = [float(t['closedPnl']) for t in all_trades if float(t['closedPnl']) > 0]
loss_pnls = [float(t['closedPnl']) for t in all_trades if float(t['closedPnl']) < 0]
if win_pnls:
    avg_win = sum(win_pnls)/len(win_pnls)
    print(f"Avg Win: ${avg_win:.4f} | Max Win: ${max(win_pnls):.4f}")
if loss_pnls:
    avg_loss = abs(sum(loss_pnls)/len(loss_pnls))
    print(f"Avg Loss: -${avg_loss:.4f} | Max Loss: ${min(loss_pnls):.4f}")
if win_pnls and loss_pnls:
    ratio = avg_win / avg_loss
    print(f"Win/Loss Ratio: {ratio:.2f}")
    expectancy = (wr/100 * avg_win) - ((100-wr)/100 * avg_loss)
    print(f"Expectancy per trade: ${expectancy:.4f}")

# By side
print(f"\n--- BY SIDE ---")
for side, data in sorted(pnl_by_side.items()):
    total = data['wins'] + data['losses']
    side_wr = data['wins'] / total * 100 if total > 0 else 0
    print(f"  {side:5}: PnL=${data['pnl']:+.4f} | {data['count']} trades | WR={side_wr:.1f}%")

# Top losers
print(f"\n--- TOP 15 LOSING SYMBOLS ---")
sorted_syms = sorted(pnl_by_symbol.items(), key=lambda x: x[1]['pnl'])
for sym, data in sorted_syms[:15]:
    total = data['wins'] + data['losses']
    sym_wr = data['wins'] / total * 100 if total > 0 else 0
    print(f"  {sym:14} PnL=${data['pnl']:+.4f} | {data['count']} trades | WR={sym_wr:.1f}%")

# Top winners
print(f"\n--- TOP 10 WINNING SYMBOLS ---")
for sym, data in sorted_syms[-10:]:
    total = data['wins'] + data['losses']
    sym_wr = data['wins'] / total * 100 if total > 0 else 0
    print(f"  {sym:14} PnL=${data['pnl']:+.4f} | {data['count']} trades | WR={sym_wr:.1f}%")

# By day
print(f"\n--- BY DAY ---")
for day in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']:
    if day in pnl_by_day:
        data = pnl_by_day[day]
        total = data['wins'] + data['losses']
        day_wr = data['wins'] / total * 100 if total > 0 else 0
        print(f"  {day:12} PnL=${data['pnl']:+.4f} | {data['count']} trades | WR={day_wr:.1f}%")

# By hour
print(f"\n--- BY HOUR ---")
for hour in sorted(pnl_by_hour.keys()):
    data = pnl_by_hour[hour]
    total = data['wins'] + data['losses']
    hour_wr = data['wins'] / total * 100 if total > 0 else 0
    print(f"  {hour:02d}:00  PnL=${data['pnl']:+.4f} | {data['count']:3d} | WR={hour_wr:.1f}%")

# Daily equity curve
print(f"\n--- DAILY EQUITY ---")
cum = 0
peak = 0
max_dd = 0
for date in sorted(daily_pnl.keys()):
    p = daily_pnl[date]
    cum += p
    if cum > peak: peak = cum
    dd = peak - cum
    if dd > max_dd: max_dd = dd
    icon = '📈' if p > 0 else '📉'
    print(f"  {icon} {date}  PnL=${p:+.4f}  Cum=${cum:+.4f}")

print(f"\nMax Drawdown: ${max_dd:.4f}")

# Last 30 trades
print(f"\n--- LAST 30 TRADES ---")
for t in reversed(all_trades[-30:]):
    pnl = float(t.get('closedPnl', 0))
    dt = datetime.fromtimestamp(int(t.get('updatedTime', 0)) / 1000).strftime('%m-%d %H:%M')
    icon = '✅' if pnl > 0 else '❌'
    print(f"  {icon} [{dt}] {t['symbol']:14} {t['side']:4} PnL=${pnl:+.6f}")

# Open positions
print(f"\n--- OPEN POSITIONS ---")
try:
    time.sleep(0.3)
    pos = session.get_positions(category="linear", settleCoin="USDT")
    if pos['retCode'] == 0:
        active = [p for p in pos['result']['list'] if float(p.get('size',0)) > 0]
        if active:
            for p in active:
                upnl = float(p.get('unrealisedPnl', 0))
                icon = '📈' if upnl > 0 else '📉'
                print(f"  {icon} {p['symbol']:12} {p['side']:4} Size={p['size']:>8} Entry={p['avgPrice']:>12} uPnL=${upnl:+.4f} Lev={p.get('leverage','?')}x")
        else:
            print("  No open positions")
except Exception as e:
    print(f"  Error: {e}")
