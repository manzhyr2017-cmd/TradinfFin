import sqlite3
import pandas as pd
import os

# Set database path
DB_PATH = 'trading_bot.db'

def analyze_performance():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    
    try:
        # Load trades into a DataFrame
        query = "SELECT * FROM trades"
        df = pd.read_sql_query(query, conn)
        
        if df.empty:
            print("No trades found in the database.")
            return

        # Ensure numeric columns are actually numeric
        numeric_cols = ['pnl', 'price', 'exit_price', 'qty', 'stop_loss', 'take_profit', 'confluence_score', 'risk_reward']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Basic Stats
        total_trades = len(df)
        
        # Filter for closed trades (where pnl is not 0 or status is closed/win/loss)
        # Note: 'status' might be 'OPEN' for open trades. Pnl might be 0 for open trades.
        # Let's count trades that have a result.
        closed_trades = df[df['status'].isin(['WIN', 'LOSS'])]
        if closed_trades.empty:
             # Fallback: maybe they are marked differently or PnL is non-zero
             closed_trades = df[df['pnl'] != 0]

        if closed_trades.empty:
            print(f"Total Trades Logged: {total_trades}")
            print("No closed trades to analyze yet.")
            return

        wins = closed_trades[closed_trades['pnl'] > 0]
        losses = closed_trades[closed_trades['pnl'] <= 0]
        
        num_wins = len(wins)
        num_losses = len(losses)
        win_rate = (num_wins / len(closed_trades)) * 100 if len(closed_trades) > 0 else 0
        
        total_pnl = closed_trades['pnl'].sum()
        avg_pnl = closed_trades['pnl'].mean()
        
        avg_win = wins['pnl'].mean() if not wins.empty else 0
        avg_loss = losses['pnl'].mean() if not losses.empty else 0
        
        gross_profit = wins['pnl'].sum() if not wins.empty else 0
        gross_loss = abs(losses['pnl'].sum()) if not losses.empty else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

        print("="*40)
        print("🤖 BOT PERFORMANCE ANALYSIS")
        print("="*40)
        print(f"Total Closed Trades: {len(closed_trades)}")
        print(f"Win Rate:           {win_rate:.2f}%")
        print(f"Total PnL:          ${total_pnl:.2f}")
        print(f"Average PnL:        ${avg_pnl:.2f}")
        print(f"Profit Factor:      {profit_factor:.2f}")
        print(f"Avg Win:            ${avg_win:.2f}")
        print(f"Avg Loss:           ${avg_loss:.2f}")
        print("-" * 40)
        
        # Best and Worst
        best_trade = closed_trades.loc[closed_trades['pnl'].idxmax()]
        worst_trade = closed_trades.loc[closed_trades['pnl'].idxmin()]
        
        print(f"🏆 Best Trade:  {best_trade['symbol']} (${best_trade['pnl']:.2f})")
        print(f"💀 Worst Trade: {worst_trade['symbol']} (${worst_trade['pnl']:.2f})")
        print("-" * 40)

        # Analysis by Symbol (Top 5 by volume or impact)
        print("\n📊 Performance by Symbol (Top 5 by Trades):")
        symbol_stats = closed_trades.groupby('symbol').agg({
            'pnl': ['count', 'sum', 'mean'],
            'is_win': 'mean' # Win rate
        })
        symbol_stats.columns = ['Trades', 'Total PnL', 'Avg PnL', 'Win Rate']
        symbol_stats['Win Rate'] *= 100
        print(symbol_stats.sort_values(by='Trades', ascending=False).head(5).to_string())

        # Analysis by Side
        print("\nSIDE ANALYSIS:")
        side_stats = closed_trades.groupby('side').agg({
             'pnl': ['count', 'sum', 'mean'],
             'is_win': 'mean'
        })
        side_stats.columns = ['Trades', 'Total PnL', 'Avg PnL', 'Win Rate']
        side_stats['Win Rate'] *= 100
        print(side_stats.to_string())

        # Analysis by Confluence Score
        if 'confluence_score' in df.columns and df['confluence_score'].notna().any():
            print("\n🎯 Performance by Confluence Score:")
            # Group by score, handling potential float/int mismatch
            closed_trades['confluence_rounded'] = closed_trades['confluence_score'].fillna(0).round()
            score_stats = closed_trades.groupby('confluence_rounded').agg({
                'pnl': ['count', 'sum', 'mean'],
                'is_win': 'mean'
            })
            score_stats.columns = ['Trades', 'Total PnL', 'Avg PnL', 'Win Rate']
            score_stats['Win Rate'] *= 100
            print(score_stats.sort_index(ascending=False).to_string())

    except Exception as e:
        print(f"Error analyzing database: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    analyze_performance()
