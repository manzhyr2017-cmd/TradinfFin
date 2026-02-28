"""
TITAN BOT 2026 - DEEP WIN/LOSS Pattern Analysis
Запусти на VPS: python3 diagnose_deep.py
Скопируй ВЕСЬ вывод и отправь в чат.

Анализирует: ЧТО отличает прибыльные сделки от убыточных.
"""

import sqlite3
import json
from datetime import datetime
from collections import defaultdict

DB_PATH = "data/titan_main.db"

def run_deep():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    except Exception as e:
        print(f"❌ Не могу открыть БД: {e}")
        return

    print("=" * 65)
    print("  TITAN DEEP ANALYSIS: Winners vs Losers")
    print("=" * 65)

    # 1. SCORE COMPONENTS: Средние M, S, O для WIN vs LOSS
    print(f"\n{'='*65}")
    print("📐 1. КОМПОНЕНТЫ СКОРА: winners vs losers")
    print(f"{'='*65}")
    
    for label, condition in [("✅ WINNERS (pnl > 0)", "pnl > 0"), ("❌ LOSERS (pnl < 0)", "pnl < 0")]:
        c.execute(f"SELECT score_details, score_total FROM trades WHERE status='CLOSED' AND {condition}")
        rows = c.fetchall()
        
        mtf_scores = []
        smc_scores = []
        of_scores = []
        totals = []
        
        for row in rows:
            totals.append(row['score_total'] or 0)
            if row['score_details']:
                try:
                    d = json.loads(row['score_details'])
                    mtf_scores.append(d.get('mtf', 0))
                    smc_scores.append(d.get('smc', 0))
                    of_scores.append(d.get('orderflow', 0))
                except:
                    pass
        
        cnt = len(rows)
        avg_total = sum(totals) / cnt if cnt else 0
        avg_m = sum(mtf_scores) / len(mtf_scores) if mtf_scores else 0
        avg_s = sum(smc_scores) / len(smc_scores) if smc_scores else 0
        avg_o = sum(of_scores) / len(of_scores) if of_scores else 0
        
        print(f"\n  {label} ({cnt} trades):")
        print(f"    Avg Total Score: {avg_total:+.1f}")
        print(f"    Avg MTF comp:    {avg_m:+.1f}")
        print(f"    Avg SMC comp:    {avg_s:+.1f}")
        print(f"    Avg OF comp:     {avg_o:+.1f}")

    # 2. DIRECTION: LONG vs SHORT для WIN vs LOSS
    print(f"\n{'='*65}")
    print("📊 2. НАПРАВЛЕНИЕ: Win Rate по LONG vs SHORT")
    print(f"{'='*65}")
    
    for side, label in [("Buy", "LONG"), ("Sell", "SHORT")]:
        c.execute("SELECT COUNT(*) FROM trades WHERE side=? AND status='CLOSED'", (side,))
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM trades WHERE side=? AND pnl > 0 AND status='CLOSED'", (side,))
        wins = c.fetchone()[0]
        c.execute("SELECT AVG(pnl) FROM trades WHERE side=? AND pnl > 0 AND status='CLOSED'", (side,))
        avg_win = c.fetchone()[0] or 0
        c.execute("SELECT AVG(pnl) FROM trades WHERE side=? AND pnl < 0 AND status='CLOSED'", (side,))
        avg_loss = c.fetchone()[0] or 0
        wr = (wins / total * 100) if total else 0
        rr = abs(avg_win / avg_loss) if avg_loss else 0
        
        print(f"  {label:5}: {total:3} trades | WR: {wr:.1f}% | AvgWin: ${avg_win:+.2f} | AvgLoss: ${avg_loss:+.2f} | R:R 1:{rr:.2f}")

    # 3. TIME OF DAY: В какие часы профит, в какие убыток
    print(f"\n{'='*65}")
    print("🕐 3. ЧАСЫ ДНЯ: WR и PNL по часам (UTC)")
    print(f"{'='*65}")
    
    c.execute("SELECT entry_time, pnl FROM trades WHERE status='CLOSED' AND pnl IS NOT NULL")
    hour_data = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
    
    for row in c.fetchall():
        try:
            hour = int(row['entry_time'][11:13])
            pnl = row['pnl']
            hour_data[hour]['pnl'] += pnl
            if pnl > 0:
                hour_data[hour]['wins'] += 1
            else:
                hour_data[hour]['losses'] += 1
        except:
            pass
    
    for h in sorted(hour_data.keys()):
        d = hour_data[h]
        total = d['wins'] + d['losses']
        wr = (d['wins'] / total * 100) if total else 0
        bar = "█" * int(total / 2) if total > 0 else ""
        icon = "🟢" if d['pnl'] > 0 else "🔴"
        print(f"  {icon} {h:02d}:00 | {total:3} trades | WR: {wr:4.0f}% | PNL: ${d['pnl']:+7.2f} | {bar}")

    # 4. R:R ANALYSIS: Реальный RR у спецефицных скор-диапазонов
    print(f"\n{'='*65}")
    print("🎯 4. R:R ПО ДИАПАЗОНАМ СКОРА")
    print(f"{'='*65}")
    
    for low, high, label in [(30, 35, "30-35"), (35, 40, "35-40"), (40, 45, "40-45"), (45, 50, "45-50"), (50, 100, "50+")]:
        c.execute("""
            SELECT COUNT(*), 
                   SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                   AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
                   AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss,
                   SUM(pnl) as total_pnl
            FROM trades WHERE status='CLOSED' AND ABS(score_total) >= ? AND ABS(score_total) < ?
        """, (low, high))
        row = c.fetchone()
        cnt = row[0] or 0
        if cnt == 0:
            continue
        wins = row[1] or 0
        avg_w = row[2] or 0
        avg_l = row[3] or 0
        total_pnl = row[4] or 0
        wr = (wins / cnt * 100) if cnt else 0
        rr = abs(avg_w / avg_l) if avg_l else 0
        pf = abs(avg_w * wins / (avg_l * (cnt - wins))) if avg_l and (cnt - wins) else 0
        
        verdict = "✅ PROFIT" if total_pnl > 0 else "❌ LOSS"
        print(f"  Score {label:6}: {cnt:3} trades | WR: {wr:4.0f}% | R:R 1:{rr:.2f} | PF: {pf:.2f} | PNL: ${total_pnl:+.2f} {verdict}")

    # 5. COIN ANALYSIS: Какие монеты прибыльны, какие — слив
    print(f"\n{'='*65}")
    print("🪙 5. ВСЕ МОНЕТЫ: Win Rate и PNL")
    print(f"{'='*65}")
    
    c.execute("""
        SELECT symbol, 
               COUNT(*) as cnt,
               SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
               SUM(pnl) as total_pnl,
               AVG(pnl) as avg_pnl,
               AVG(CASE WHEN pnl > 0 THEN pnl END) as avg_win,
               AVG(CASE WHEN pnl < 0 THEN pnl END) as avg_loss
        FROM trades WHERE status='CLOSED'
        GROUP BY symbol
        HAVING cnt >= 3
        ORDER BY total_pnl DESC
    """)
    for row in c.fetchall():
        wr = (row['wins'] / row['cnt'] * 100) if row['cnt'] else 0
        icon = "🟢" if row['total_pnl'] > 0 else "🔴"
        avg_w = row['avg_win'] or 0
        avg_l = row['avg_loss'] or 0
        rr = abs(avg_w / avg_l) if avg_l else 0
        print(f"  {icon} {row['symbol']:14} | {row['cnt']:3} trades | WR: {wr:4.0f}% | PNL: ${row['total_pnl']:+8.2f} | R:R 1:{rr:.2f}")

    # 6. SL/TP DISTANCE: Как далеко ставились SL и TP у WIN vs LOSS
    print(f"\n{'='*65}")
    print("📏 6. SL/TP РАССТОЯНИЯ: Winners vs Losers")
    print(f"{'='*65}")
    
    for label, condition in [("✅ WINNERS", "pnl > 0"), ("❌ LOSERS", "pnl < 0")]:
        c.execute(f"""
            SELECT entry_price, sl, tp, side
            FROM trades WHERE status='CLOSED' AND {condition} AND entry_price > 0 AND sl > 0 AND tp > 0
        """)
        sl_pcts = []
        tp_pcts = []
        rr_ratios = []
        for row in c.fetchall():
            entry = row['entry_price']
            sl_dist = abs(entry - row['sl']) / entry * 100
            tp_dist = abs(entry - row['tp']) / entry * 100
            sl_pcts.append(sl_dist)
            tp_pcts.append(tp_dist)
            if sl_dist > 0:
                rr_ratios.append(tp_dist / sl_dist)
        
        if sl_pcts:
            print(f"\n  {label}:")
            print(f"    Avg SL distance: {sum(sl_pcts)/len(sl_pcts):.2f}%")
            print(f"    Avg TP distance: {sum(tp_pcts)/len(tp_pcts):.2f}%")
            print(f"    Avg planned R:R: 1:{sum(rr_ratios)/len(rr_ratios):.2f}")

    # 7. CONSECUTIVE PATTERNS: Что происходит после убытка
    print(f"\n{'='*65}")
    print("🔗 7. ЧТО ПОСЛЕ УБЫТКА: WR следующей сделки")
    print(f"{'='*65}")
    
    c.execute("SELECT pnl, symbol FROM trades WHERE status='CLOSED' ORDER BY entry_time ASC")
    all_trades = c.fetchall()
    
    after_win = {"wins": 0, "losses": 0}
    after_loss = {"wins": 0, "losses": 0}
    after_2loss = {"wins": 0, "losses": 0}
    
    prev = None
    prev2 = None
    for trade in all_trades:
        pnl = trade['pnl']
        if prev is not None:
            bucket = after_win if prev > 0 else after_loss
            if pnl > 0:
                bucket['wins'] += 1
            else:
                bucket['losses'] += 1
            
            if prev2 is not None and prev2 < 0 and prev < 0:
                if pnl > 0:
                    after_2loss['wins'] += 1
                else:
                    after_2loss['losses'] += 1
        
        prev2 = prev
        prev = pnl
    
    for label, data in [("После победы", after_win), ("После убытка", after_loss), ("После 2х убытков", after_2loss)]:
        total = data['wins'] + data['losses']
        wr = (data['wins'] / total * 100) if total else 0
        print(f"  {label:20}: {total:3} trades | WR: {wr:.1f}%")

    # 8. SAME COIN REPEAT: Повторные входы на одну монету
    print(f"\n{'='*65}")
    print("🔁 8. ПОВТОРНЫЕ ВХОДЫ: WR 1-й vs 2-й+ сделки на монете")
    print(f"{'='*65}")
    
    c.execute("SELECT symbol, pnl FROM trades WHERE status='CLOSED' ORDER BY entry_time ASC")
    coin_trade_num = defaultdict(int)
    first_entry = {"wins": 0, "losses": 0}
    repeat_entry = {"wins": 0, "losses": 0}
    
    for row in c.fetchall():
        coin_trade_num[row['symbol']] += 1
        bucket = first_entry if coin_trade_num[row['symbol']] == 1 else repeat_entry
        if row['pnl'] > 0:
            bucket['wins'] += 1
        else:
            bucket['losses'] += 1
    
    for label, data in [("1-я сделка на монете", first_entry), ("2-я+ сделка (повтор)", repeat_entry)]:
        total = data['wins'] + data['losses']
        wr = (data['wins'] / total * 100) if total else 0
        print(f"  {label:25}: {total:3} trades | WR: {wr:.1f}%")

    # 9. RECENT TRADES (Last 48 hours)
    print(f"\n{'='*65}")
    print("📈 9. ПОСЛЕДНИЕ 48 ЧАСОВ: Новейшие сделки (v8/v9)")
    print(f"{'='*65}")
    
    from datetime import timedelta
    cutoff_48h = (datetime.now() - timedelta(hours=48)).isoformat()
    
    c.execute("SELECT symbol, side, score_total, pnl, entry_time FROM trades WHERE status='CLOSED' AND entry_time > ? ORDER BY entry_time ASC", (cutoff_48h,))
    recent_trades = c.fetchall()
    
    if not recent_trades:
        print("  📭 Нет сделок за последние 48 часов!")
    else:
        wins_48h = sum(1 for t in recent_trades if (t['pnl'] or 0) > 0)
        losses_48h = sum(1 for t in recent_trades if (t['pnl'] or 0) < 0)
        total_pnl_48h = sum((t['pnl'] or 0) for t in recent_trades)
        wr_48h = (wins_48h / len(recent_trades)) * 100 if len(recent_trades) > 0 else 0
        
        print(f"  Всего сделок за 48ч: {len(recent_trades)} | WR: {wr_48h:.1f}% | PNL: ${total_pnl_48h:+.2f}\n")
        
        for t in recent_trades:
            pnl = t['pnl'] or 0
            icon = "🟢" if pnl > 0 else "🔴"
            score = t['score_total'] or 0
            print(f"  {t['entry_time'][5:16]} | {icon} {t['symbol']:10} | {t['side']:5} | Score: {score:4.1f} | PNL: ${pnl:+6.2f}")

    print(f"\n{'='*65}")
    print("  КОНЕЦ ГЛУБОКОГО АНАЛИЗА")
    print(f"{'='*65}")
    conn.close()

if __name__ == "__main__":
    run_deep()
