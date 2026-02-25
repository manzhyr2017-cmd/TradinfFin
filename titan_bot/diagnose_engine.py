"""
TITAN BOT 2026 - SCORING ENGINE + ML FEATURES ANALYSIS
Запусти на VPS: python3 diagnose_engine.py
Скопируй ВЕСЬ вывод.

Анализирует: как работает движок скоринга, ML-фичи, длительность сделок.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from collections import defaultdict

DB_PATH = "data/titan_main.db"

def run_engine_analysis():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
    except Exception as e:
        print(f"❌ Не могу открыть БД: {e}")
        return

    print("=" * 65)
    print("  TITAN ENGINE & FEATURES DEEP ANALYSIS")
    print("=" * 65)

    # 1. Все компоненты скора подробно
    print(f"\n{'='*65}")
    print("🔬 1. SCORE_DETAILS: Полная разбивка компонентов")
    print(f"{'='*65}")
    
    c.execute("SELECT score_details FROM trades WHERE status='CLOSED' LIMIT 5")
    print("\n  Примеры score_details JSON:")
    for i, row in enumerate(c.fetchall()):
        print(f"  [{i}] {row['score_details']}")
    
    # Полная статистика по каждому компоненту
    c.execute("SELECT score_details, pnl FROM trades WHERE status='CLOSED' AND score_details IS NOT NULL")
    comp_wins = defaultdict(list)
    comp_losses = defaultdict(list)
    
    for row in c.fetchall():
        try:
            d = json.loads(row['score_details'])
            target = comp_wins if row['pnl'] > 0 else comp_losses
            for key, val in d.items():
                if isinstance(val, (int, float)):
                    target[key].append(val)
        except:
            pass
    
    all_keys = set(list(comp_wins.keys()) + list(comp_losses.keys()))
    print(f"\n  {'Component':<20} | {'WIN avg':>10} | {'LOSS avg':>10} | {'DIFF':>10} | Verdict")
    print(f"  {'-'*20}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+--------")
    for key in sorted(all_keys):
        w_avg = sum(comp_wins[key]) / len(comp_wins[key]) if comp_wins[key] else 0
        l_avg = sum(comp_losses[key]) / len(comp_losses[key]) if comp_losses[key] else 0
        diff = w_avg - l_avg
        verdict = "✅ USEFUL" if abs(diff) > 0.5 else ("⚠️ WEAK" if abs(diff) > 0.1 else "❌ NOISE")
        print(f"  {key:<20} | {w_avg:>+10.2f} | {l_avg:>+10.2f} | {diff:>+10.2f} | {verdict}")

    # 2. ML FEATURES analysis
    print(f"\n{'='*65}")
    print("🧠 2. ML FEATURES: Корреляция с прибылью")
    print(f"{'='*65}")
    
    c.execute("SELECT features, pnl FROM trades WHERE status='CLOSED' AND features IS NOT NULL")
    feat_wins = defaultdict(list)
    feat_losses = defaultdict(list)
    features_found = 0
    
    for row in c.fetchall():
        try:
            f = json.loads(row['features'])
            if not f:
                continue
            features_found += 1
            target = feat_wins if row['pnl'] > 0 else feat_losses
            for key, val in f.items():
                if isinstance(val, (int, float)) and val is not None:
                    target[key].append(val)
        except:
            pass
    
    print(f"\n  Сделок с ML features: {features_found}")
    
    if features_found > 0:
        all_feat_keys = set(list(feat_wins.keys()) + list(feat_losses.keys()))
        print(f"\n  {'Feature':<25} | {'WIN avg':>10} | {'LOSS avg':>10} | {'DIFF':>10} | Verdict")
        print(f"  {'-'*25}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+--------")
        
        # Сортируем по абсолютной разнице
        feature_diffs = []
        for key in all_feat_keys:
            w_avg = sum(feat_wins[key]) / len(feat_wins[key]) if feat_wins[key] else 0
            l_avg = sum(feat_losses[key]) / len(feat_losses[key]) if feat_losses[key] else 0
            diff = w_avg - l_avg
            feature_diffs.append((key, w_avg, l_avg, diff))
        
        feature_diffs.sort(key=lambda x: abs(x[3]), reverse=True)
        
        for key, w_avg, l_avg, diff in feature_diffs[:20]:  # Топ 20
            verdict = "✅ STRONG" if abs(diff) > 1.0 else ("⚠️ WEAK" if abs(diff) > 0.3 else "❌ NOISE")
            print(f"  {key:<25} | {w_avg:>+10.3f} | {l_avg:>+10.3f} | {diff:>+10.3f} | {verdict}")
    else:
        print("  ⚠️ ML Features пустые — модель не записывала данные")

    # 3. TRADE DURATION: Как долго живут WIN vs LOSS
    print(f"\n{'='*65}")
    print("⏱️ 3. ДЛИТЕЛЬНОСТЬ СДЕЛОК: Winners vs Losers")
    print(f"{'='*65}")
    
    c.execute("SELECT entry_time, exit_time, pnl FROM trades WHERE status='CLOSED' AND exit_time IS NOT NULL")
    win_durations = []
    loss_durations = []
    
    for row in c.fetchall():
        try:
            entry = datetime.fromisoformat(row['entry_time'])
            exit_t = datetime.fromisoformat(row['exit_time'])
            dur_min = (exit_t - entry).total_seconds() / 60
            if dur_min < 0 or dur_min > 10000:
                continue
            if row['pnl'] > 0:
                win_durations.append(dur_min)
            else:
                loss_durations.append(dur_min)
        except:
            pass
    
    if win_durations:
        print(f"\n  ✅ WINNERS ({len(win_durations)} trades):")
        print(f"    Средняя длительность: {sum(win_durations)/len(win_durations):.1f} мин")
        print(f"    Медиана: {sorted(win_durations)[len(win_durations)//2]:.1f} мин")
        print(f"    Мин: {min(win_durations):.1f} мин | Макс: {max(win_durations):.1f} мин")
    
    if loss_durations:
        print(f"\n  ❌ LOSERS ({len(loss_durations)} trades):")
        print(f"    Средняя длительность: {sum(loss_durations)/len(loss_durations):.1f} мин")
        print(f"    Медиана: {sorted(loss_durations)[len(loss_durations)//2]:.1f} мин")
        print(f"    Мин: {min(loss_durations):.1f} мин | Макс: {max(loss_durations):.1f} мин")

    # 4. DAY OF WEEK
    print(f"\n{'='*65}")
    print("📅 4. ДЕНЬ НЕДЕЛИ: WR и PNL")
    print(f"{'='*65}")
    
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    c.execute("SELECT entry_time, pnl FROM trades WHERE status='CLOSED'")
    day_data = defaultdict(lambda: {"wins": 0, "losses": 0, "pnl": 0.0})
    
    for row in c.fetchall():
        try:
            dt = datetime.fromisoformat(row['entry_time'])
            day = dt.weekday()
            day_data[day]['pnl'] += row['pnl']
            if row['pnl'] > 0:
                day_data[day]['wins'] += 1
            else:
                day_data[day]['losses'] += 1
        except:
            pass
    
    for d in range(7):
        if d in day_data:
            data = day_data[d]
            total = data['wins'] + data['losses']
            wr = (data['wins'] / total * 100) if total else 0
            icon = "🟢" if data['pnl'] > 0 else "🔴"
            print(f"  {icon} {days[d]:3} | {total:3} trades | WR: {wr:4.0f}% | PNL: ${data['pnl']:+8.2f}")

    # 5. COMBO ANALYSIS: Direction + Hour = WR
    print(f"\n{'='*65}")
    print("🎰 5. COMBO: Direction + Hour → Best combinations")
    print(f"{'='*65}")
    
    c.execute("SELECT side, entry_time, pnl FROM trades WHERE status='CLOSED'")
    combo_data = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
    
    for row in c.fetchall():
        try:
            hour = int(row['entry_time'][11:13])
            direction = "LONG" if row['side'] == "Buy" else "SHORT"
            key = f"{direction} @ {hour:02d}:00"
            combo_data[key]['total'] += 1
            combo_data[key]['pnl'] += row['pnl']
            if row['pnl'] > 0:
                combo_data[key]['wins'] += 1
        except:
            pass
    
    # Сортируем по PNL
    sorted_combos = sorted(combo_data.items(), key=lambda x: x[1]['pnl'], reverse=True)
    
    print(f"\n  🏆 ТОП-10 ЛУЧШИХ КОМБО:")
    for key, data in sorted_combos[:10]:
        wr = (data['wins'] / data['total'] * 100) if data['total'] else 0
        if data['total'] >= 2:
            print(f"  🟢 {key:18} | {data['total']:3} trades | WR: {wr:4.0f}% | PNL: ${data['pnl']:+8.2f}")
    
    print(f"\n  💀 ТОП-10 ХУДШИХ КОМБО:")
    for key, data in sorted_combos[-10:]:
        wr = (data['wins'] / data['total'] * 100) if data['total'] else 0
        if data['total'] >= 2:
            print(f"  🔴 {key:18} | {data['total']:3} trades | WR: {wr:4.0f}% | PNL: ${data['pnl']:+8.2f}")

    # 6. SCORING ENGINE THEORETICAL MAX
    print(f"\n{'='*65}")
    print("⚙️ 6. SCORING ENGINE: Теоретический потолок")
    print(f"{'='*65}")
    
    print(f"""
  Текущие веса:
    MTF:            20% (подаётся ✅)
    SMC:            20% (подаётся ✅)
    OrderFlow:      15% (подаётся ✅)
    Volume Profile: 10% (НЕ подаётся ❌ = 0)
    Open Interest:  10% (НЕ подаётся ❌ = 0)
    Regime:         10% (НЕ подаётся ❌ = 0)
    Whale:           5% (НЕ подаётся ❌ = 0)
    Fear & Greed:    5% (НЕ подаётся ❌ = 0)
    Correlation:     5% (НЕ подаётся ❌ = 0)
    
  Итого рабочий вес: 55% из 100%
  Макс теоретический скор: 55 × confidence
  При confidence 0.8: макс ~44
  При confidence 0.7: макс ~38
  
  ⚠️ ПРОБЛЕМА: 45% веса уходит в неработающие компоненты.
  Остальные 55% дают потолок ~43 при идеальных условиях.
  РЕШЕНИЕ: Перераспределить веса на рабочие компоненты.
    """)

    print(f"{'='*65}")
    print("  КОНЕЦ АНАЛИЗА ДВИЖКА")
    print(f"{'='*65}")
    conn.close()

if __name__ == "__main__":
    run_engine_analysis()
