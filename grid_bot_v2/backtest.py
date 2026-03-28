import pandas as pd
from indicators import calculate_ema, calculate_rsi

def run_backtest(csv_file):
    df = pd.read_csv(csv_file)
    df['ema'] = calculate_ema(df)
    df['rsi'] = calculate_rsi(df)
    
    balance = 1000.0  # Initial Balance USDT
    position = 0.0    # ETH Position
    trades = 0
    
    for i in range(200, len(df)):
        price = df['close'].iloc[i]
        ema = df['ema'].iloc[i]
        rsi = df['rsi'].iloc[i]
        
        # Buy Signal
        if price > ema and rsi < 30 and balance > 10:
            position = balance / price
            balance = 0
            trades += 1
            print(f"BUY at {price}")
            
        # Sell Signal (Profit Taking)
        elif position > 0 and rsi > 70:
            balance = position * price
            position = 0
            trades += 1
            print(f"SELL at {price} | Balance: {balance}")

    print(f"\n--- Backtest Result ---")
    print(f"Final Balance: {balance if balance > 0 else position * df['close'].iloc[-1]} USDT")
    print(f"Total Trades: {trades}")

if __name__ == "__main__":
    # run_backtest('historical_data.csv')
    pass
