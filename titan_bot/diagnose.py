"""
TITAN BOT 2026 - Trade History Diagnostic
Запусти на VPS: python3 diagnose.py
Скопируй вывод и отправь в чат.
"""

import sqlite3
import json
from datetime import datetime

DB_PATH = "data/titan_main.db"

def run_diagnosis():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    except Exception as e:
        print(f"❌ Не могу открыть БД: {e}")
        return

    print("=" * 60)
    print("  TITAN TRADE HISTORY DIAGNOSTIC")
    print("=" * 60)

    # 1. Общая статистика
    c.execute("SELECT COUNT(*) FROM trades")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'")
    open_t = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE status='CLOSED'")
    closed = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl > 0 AND status='CLOSED'")
    wins = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl < 0 AND status='CLOSED'")
    losses = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM trades WHERE pnl = 0 AND status='CLOSED'")
    breakeven = c.fetchone()[0]

    print(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
    print(f"  Всего сделок: {total}")
    print(f"  Открытых: {open_t}")
    print(f"  Закрытых: {closed}")
    print(f"  Прибыльных: {wins}")
    print(f"  Убыточных: {losses}")
    print(f"  Безубыток: {breakeven}")
    if closed > 0:
        wr = (wins / closed) * 100
        print(f"  Win Rate: {wr:.1f}%")

    # 2. PNL анализ
    c.execute("SELECT SUM(pnl) FROM trades WHERE status='CLOSED'")
    total_pnl = c.fetchone()[0] or 0
    c.execute("SELECT SUM(pnl) FROM trades WHERE pnl > 0 AND status='CLOSED'")
    total_profit = c.fetchone()[0] or 0
    c.execute("SELECT SUM(pnl) FROM trades WHERE pnl < 0 AND status='CLOSED'")
    total_loss = c.fetchone()[0] or 0
    c.execute("SELECT AVG(pnl) FROM trades WHERE pnl > 0 AND status='CLOSED'")
    avg_win = c.fetchone()[0] or 0
    c.execute("SELECT AVG(pnl) FROM trades WHERE pnl < 0 AND status='CLOSED'")
    avg_loss = c.fetchone()[0] or 0
    c.execute("SELECT MIN(pnl) FROM trades WHERE status='CLOSED'")
    worst = c.fetchone()[0] or 0
    c.execute("SELECT MAX(pnl) FROM trades WHERE status='CLOSED'")
    best = c.fetchone()[0] or 0

    print(f"\n💰 PNL АНАЛИЗ:")
    print(f"  Общий PNL: ${total_pnl:.2f}")
    print(f"  Общая прибыль: ${total_profit:.2f}")
    print(f"  Общий убыток: ${total_loss:.2f}")
    print(f"  Ср. прибыль: ${avg_win:.2f}")
    print(f"  Ср. убыток: ${avg_loss:.2f}")
    print(f"  Лучшая сделка: ${best:.2f}")
    print(f"  Худшая сделка: ${worst:.2f}")
    if avg_loss != 0:
        rr = abs(avg_win / avg_loss)
        print(f"  Фактический R:R: 1:{rr:.2f}")
    if total_loss != 0:
        pf = abs(total_profit / total_loss)
        print(f"  Profit Factor: {pf:.2f}")

    # 3. По направлениям
    print(f"\n📈 ПО НАПРАВЛЕНИЯМ:")
    for side in ["Buy", "Sell"]:
        c.execute("SELECT COUNT(*), SUM(pnl), AVG(pnl) FROM trades WHERE side=? AND status='CLOSED'", (side,))
        row = c.fetchone()
        cnt, s_pnl, a_pnl = row[0] or 0, row[1] or 0, row[2] or 0
        c.execute("SELECT COUNT(*) FROM trades WHERE side=? AND pnl > 0 AND status='CLOSED'", (side,))
        s_wins = c.fetchone()[0]
        s_wr = (s_wins / cnt * 100) if cnt > 0 else 0
        label = "LONG" if side == "Buy" else "SHORT"
        print(f"  {label}: {cnt} trades | PNL: ${s_pnl:.2f} | AvgPNL: ${a_pnl:.2f} | WR: {s_wr:.1f}%")

    # 4. По монетам (Топ убыточных и Топ прибыльных)
    print(f"\n🏆 ТОП-5 ПРИБЫЛЬНЫХ МОНЕТ:")
    c.execute("""
        SELECT symbol, COUNT(*) as cnt, SUM(pnl) as total_pnl, AVG(pnl) as avg_pnl
        FROM trades WHERE status='CLOSED'
        GROUP BY symbol ORDER BY total_pnl DESC LIMIT 5
    """)
    for row in c.fetchall():
        print(f"  {row['symbol']:12} | {row['cnt']:3} trades | PNL: ${row['total_pnl']:.2f} | Avg: ${row['avg_pnl']:.2f}")

    print(f"\n💀 ТОП-5 УБЫТОЧНЫХ МОНЕТ:")
    c.execute("""
        SELECT symbol, COUNT(*) as cnt, SUM(pnl) as total_pnl, AVG(pnl) as avg_pnl
        FROM trades WHERE status='CLOSED'
        GROUP BY symbol ORDER BY total_pnl ASC LIMIT 5
    """)
    for row in c.fetchall():
        print(f"  {row['symbol']:12} | {row['cnt']:3} trades | PNL: ${row['total_pnl']:.2f} | Avg: ${row['avg_pnl']:.2f}")

    # 5. Анализ по скору (при каком скоре чаще всего профит / убыток)
    print(f"\n🎯 АНАЛИЗ ПО SCORE:")
    for low, high, label in [(0, 30, "0-30"), (30, 40, "30-40"), (40, 50, "40-50"), (50, 60, "50-60"), (60, 100, "60+")]:
        c.execute("""
            SELECT COUNT(*), SUM(pnl), AVG(pnl) 
            FROM trades WHERE status='CLOSED' AND ABS(score_total) >= ? AND ABS(score_total) < ?
        """, (low, high))
        row = c.fetchone()
        cnt, s_pnl, a_pnl = row[0] or 0, row[1] or 0, row[2] or 0
        c.execute("""
            SELECT COUNT(*) FROM trades 
            WHERE status='CLOSED' AND pnl > 0 AND ABS(score_total) >= ? AND ABS(score_total) < ?
        """, (low, high))
        s_wins = c.fetchone()[0]
        s_wr = (s_wins / cnt * 100) if cnt > 0 else 0
        if cnt > 0:
            print(f"  Score {label:6}: {cnt:3} trades | PNL: ${s_pnl:+.2f} | WR: {s_wr:.0f}% | Avg: ${a_pnl:+.2f}")

    # 6. Последние 20 сделок
    print(f"\n📋 ПОСЛЕДНИЕ 20 СДЕЛОК:")
    c.execute("""
        SELECT symbol, side, entry_time, entry_price, exit_price, pnl, score_total, status
        FROM trades ORDER BY entry_time DESC LIMIT 20
    """)
    for row in c.fetchall():
        t = row['entry_time'][:16] if row['entry_time'] else "????"
        pnl_str = f"${row['pnl']:+.2f}" if row['pnl'] else "OPEN"
        icon = "✅" if row['pnl'] and row['pnl'] > 0 else ("❌" if row['pnl'] and row['pnl'] < 0 else "⏳")
        sc = row['score_total'] or 0
        print(f"  {icon} {t} | {row['symbol']:10} {row['side']:4} | SC:{sc:+.0f} | {pnl_str}")

    # 7. Серии (стрики)
    print(f"\n🔥 СЕРИИ:")
    c.execute("SELECT pnl FROM trades WHERE status='CLOSED' ORDER BY entry_time ASC")
    pnls = [r['pnl'] for r in c.fetchall()]
    
    max_win_streak = 0
    max_loss_streak = 0
    cur_win = 0
    cur_loss = 0
    for p in pnls:
        if p and p > 0:
            cur_win += 1
            cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        elif p and p < 0:
            cur_loss += 1
            cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
        else:
            cur_win = 0
            cur_loss = 0
    
    print(f"  Макс. серия побед: {max_win_streak}")
    print(f"  Макс. серия убытков: {max_loss_streak}")

    # 8. Открытые позиции
    print(f"\n⏳ ОТКРЫТЫЕ ПОЗИЦИИ:")
    c.execute("SELECT symbol, side, entry_price, qty, score_total, entry_time FROM trades WHERE status='OPEN'")
    opens = c.fetchall()
    if not opens:
        print("  Нет открытых позиций в БД.")
    for row in opens:
        t = row['entry_time'][:16] if row['entry_time'] else "????"
        sc = row['score_total'] or 0
        print(f"  ⏳ {t} | {row['symbol']:10} {row['side']:4} @ {row['entry_price']} | qty: {row['qty']} | SC:{sc:+.0f}")

    print(f"\n{'=' * 60}")
    print(f"  КОНЕЦ ДИАГНОСТИКИ")
    print(f"{'=' * 60}")
    conn.close()

if __name__ == "__main__":
    run_diagnosis()
