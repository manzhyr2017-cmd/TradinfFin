"""
Direct Bybit API trade fetcher - no VPS access needed
Uses the API keys from .env to pull closed PnL history
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.append(str(Path(__file__).parent / "titan_bot"))
os.chdir(str(Path(__file__).parent / "titan_bot"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / "titan_bot" / ".env")

from pybit.unified_trading import HTTP

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
DEMO = os.getenv("BYBIT_DEMO", "False").lower() == "true"

print(f"API Key: {API_KEY[:6]}****")
print(f"Demo mode: {DEMO}")

session = HTTP(
    api_key=API_KEY,
    api_secret=API_SECRET,
    demo=DEMO
)

# Fetch balance
try:
    wallet = session.get_wallet_balance(accountType="UNIFIED")
    if wallet['retCode'] == 0:
        coins = wallet['result']['list'][0]['coin']
        for coin in coins:
            if float(coin.get('walletBalance', 0)) > 0:
                print(f"Balance: {coin['coin']} = {coin['walletBalance']} (equity={coin.get('equity','?')})")
except Exception as e:
    print(f"Balance error: {e}")

# Fetch closed trades - paginated
all_trades = []
cursor = ""
pages = 0

# Go back 30 days
start_ms = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)

while pages < 20:  # max 20 pages
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
            print(f"Error: {response['retMsg']}")
            break
        
        trades = response['result']['list']
        if not trades:
            break
        
        all_trades.extend(trades)
        cursor = response['result'].get('nextPageCursor', '')
        pages += 1
        
        if not cursor:
            break
            
        print(f"Page {pages}: +{len(trades)} trades (total: {len(all_trades)})")
        
    except Exception as e:
        print(f"Fetch error: {e}")
        break

print(f"\n{'='*80}")
print(f"TOTAL CLOSED TRADES (last 30 days): {len(all_trades)}")
print(f"{'='*80}")

if not all_trades:
    print("No trades found!")
    sys.exit(0)

# Analysis
total_pnl = 0
wins = 0
losses = 0
pnl_by_symbol = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
pnl_by_side = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
pnl_by_day = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
pnl_by_hour = defaultdict(lambda: {'pnl': 0, 'wins': 0, 'losses': 0, 'count': 0})
daily_pnl = defaultdict(float)
trade_sizes = []
hold_times = []

for t in all_trades:
    pnl = float(t.get('closedPnl', 0))
    symbol = t.get('symbol', 'N/A')
    side = t.get('side', 'N/A')
    qty = float(t.get('qty', 0))
    entry_price = float(t.get('avgEntryPrice', 0))
    exit_price = float(t.get('avgExitPrice', 0))
    created = int(t.get('createdTime', 0))
    updated = int(t.get('updatedTime', 0))
    leverage = t.get('leverage', 'N/A')
    
    total_pnl += pnl
    
    if pnl > 0:
        wins += 1
    elif pnl < 0:
        losses += 1
    
    # By symbol
    pnl_by_symbol[symbol]['pnl'] += pnl
    pnl_by_symbol[symbol]['count'] += 1
    if pnl > 0: pnl_by_symbol[symbol]['wins'] += 1
    elif pnl < 0: pnl_by_symbol[symbol]['losses'] += 1
    
    # By side
    pnl_by_side[side]['pnl'] += pnl
    pnl_by_side[side]['count'] += 1
    if pnl > 0: pnl_by_side[side]['wins'] += 1
    elif pnl < 0: pnl_by_side[side]['losses'] += 1
    
    # By datetime
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
    
    # Trade size
    if entry_price > 0:
        trade_sizes.append(qty * entry_price)
    
    # Hold time
    if created and updated and updated > created:
        hold_times.append((updated - created) / 1000 / 60)  # minutes

# Summary
print(f"\nTotal PnL: ${total_pnl:.2f}")
wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
print(f"Win Rate: {wr:.1f}% ({wins}W / {losses}L / {len(all_trades) - wins - losses} BE)")
if trade_sizes:
    print(f"Avg Trade Size: ${sum(trade_sizes)/len(trade_sizes):.2f}")
if hold_times:
    print(f"Avg Hold Time: {sum(hold_times)/len(hold_times):.1f} min")
    print(f"Median Hold Time: {sorted(hold_times)[len(hold_times)//2]:.1f} min")

# By side
print(f"\n{'--- BY SIDE ---':^60}")
for side, data in sorted(pnl_by_side.items()):
    total = data['wins'] + data['losses']
    wr = data['wins'] / total * 100 if total > 0 else 0
    avg = data['pnl'] / data['count'] if data['count'] > 0 else 0
    print(f"  {side:5}: PnL=${data['pnl']:+.2f} | {data['count']} trades | WR={wr:.1f}% ({data['wins']}W/{data['losses']}L) | Avg=${avg:+.4f}")

# By symbol (top losers)
print(f"\n{'--- TOP LOSERS ---':^60}")
sorted_symbols = sorted(pnl_by_symbol.items(), key=lambda x: x[1]['pnl'])
for sym, data in sorted_symbols[:15]:
    total = data['wins'] + data['losses']
    wr = data['wins'] / total * 100 if total > 0 else 0
    print(f"  {sym:12} PnL=${data['pnl']:+.2f} | {data['count']} trades | WR={wr:.1f}%")

# By symbol (top winners)
print(f"\n{'--- TOP WINNERS ---':^60}")
for sym, data in sorted_symbols[-10:]:
    total = data['wins'] + data['losses']
    wr = data['wins'] / total * 100 if total > 0 else 0
    print(f"  {sym:12} PnL=${data['pnl']:+.2f} | {data['count']} trades | WR={wr:.1f}%")

# By day
print(f"\n{'--- BY DAY OF WEEK ---':^60}")
day_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
for day in day_order:
    if day in pnl_by_day:
        data = pnl_by_day[day]
        total = data['wins'] + data['losses']
        wr = data['wins'] / total * 100 if total > 0 else 0
        print(f"  {day:12} PnL=${data['pnl']:+.2f} | {data['count']} trades | WR={wr:.1f}%")

# By hour
print(f"\n{'--- BY HOUR (LOCAL TIME) ---':^60}")
for hour in sorted(pnl_by_hour.keys()):
    data = pnl_by_hour[hour]
    total = data['wins'] + data['losses']
    wr = data['wins'] / total * 100 if total > 0 else 0
    bar = '#' * max(0, int(abs(data['pnl']) * 2))
    sign = '+' if data['pnl'] >= 0 else '-'
    print(f"  {hour:02d}:00  PnL=${data['pnl']:+.2f} | {data['count']:3} trades | WR={wr:.1f}%")

# Daily PnL
print(f"\n{'--- DAILY PNL ---':^60}")
cumulative = 0
for date in sorted(daily_pnl.keys()):
    pnl = daily_pnl[date]
    cumulative += pnl
    bar = '*' * max(0, int(abs(pnl) * 5))
    icon = '+' if pnl >= 0 else '-'
    print(f"  {date} PnL=${pnl:+.2f} | Cumul=${cumulative:+.2f}")

# Drawdown
print(f"\n{'--- DRAWDOWN ANALYSIS ---':^60}")
cumulative = 0
peak = 0
max_dd = 0
for date in sorted(daily_pnl.keys()):
    cumulative += daily_pnl[date]
    if cumulative > peak:
        peak = cumulative
    dd = peak - cumulative
    if dd > max_dd:
        max_dd = dd
print(f"  Peak Equity: ${peak:+.2f}")
print(f"  Max Drawdown: ${max_dd:.2f}")
print(f"  Final Cumulative PnL: ${cumulative:+.2f}")

# Win/Loss distribution
print(f"\n{'--- PNL DISTRIBUTION ---':^60}")
win_pnls = [float(t['closedPnl']) for t in all_trades if float(t['closedPnl']) > 0]
loss_pnls = [float(t['closedPnl']) for t in all_trades if float(t['closedPnl']) < 0]
if win_pnls:
    print(f"  Avg Win: ${sum(win_pnls)/len(win_pnls):.4f}")
    print(f"  Max Win: ${max(win_pnls):.4f}")
if loss_pnls:
    print(f"  Avg Loss: ${sum(loss_pnls)/len(loss_pnls):.4f}")
    print(f"  Max Loss: ${min(loss_pnls):.4f}")
if win_pnls and loss_pnls:
    avg_win = sum(win_pnls)/len(win_pnls)
    avg_loss = abs(sum(loss_pnls)/len(loss_pnls))
    print(f"  Avg Win / Avg Loss Ratio: {avg_win/avg_loss:.2f}")
    expectancy = (wr/100 * avg_win) - ((100-wr)/100 * avg_loss)
    print(f"  Expectancy per trade: ${expectancy:.4f}")

# Last 30 trades
print(f"\n{'--- LAST 30 TRADES ---':^60}")
all_trades.sort(key=lambda x: int(x.get('updatedTime', 0)), reverse=True)
for t in all_trades[:30]:
    pnl = float(t.get('closedPnl', 0))
    dt = datetime.fromtimestamp(int(t.get('updatedTime', 0)) / 1000).strftime('%Y-%m-%d %H:%M')
    icon = '✅' if pnl > 0 else '❌'
    print(f"  {icon} [{dt}] {t['symbol']:12} {t['side']:4} | Entry={t['avgEntryPrice']:>10} Exit={t['avgExitPrice']:>10} | PnL=${pnl:+.4f}")

# Current open positions
print(f"\n{'--- CURRENT OPEN POSITIONS ---':^60}")
try:
    pos_resp = session.get_positions(category="linear", settleCoin="USDT")
    if pos_resp['retCode'] == 0:
        positions = [p for p in pos_resp['result']['list'] if float(p.get('size', 0)) > 0]
        if positions:
            for p in positions:
                pnl = float(p.get('unrealisedPnl', 0))
                icon = '📈' if pnl > 0 else '📉'
                print(f"  {icon} {p['symbol']:12} {p['side']:4} Size={p['size']:>8} Entry={p['avgPrice']:>10} | uPnL=${pnl:+.4f} | Lev={p.get('leverage','?')}x")
        else:
            print("  No open positions")
except Exception as e:
    print(f"  Position error: {e}")
