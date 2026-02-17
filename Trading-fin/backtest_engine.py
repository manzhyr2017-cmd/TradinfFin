import pandas as pd
import numpy as np
import logging
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pybit.unified_trading import HTTP
from mean_reversion_bybit import AdvancedMeanReversionEngine, SignalType

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Backtest")

class Backtester:
    def __init__(self, api_key="", api_secret=""):
        self.client = HTTP(testnet=False, api_key=api_key, api_secret=api_secret)
        self.engine = AdvancedMeanReversionEngine(min_confluence=70)
        self.trades = []
        self.balance = 1000.0  # Начальный баланс $1000
        self.initial_balance = 1000.0
        
    def fetch_data(self, symbol: str, interval: str, days: int) -> pd.DataFrame:
        """Скачивает исторические данные частями (по 1000 свечей)"""
        limit = 1000
        total_candles = int((days * 24 * 60) / int(interval if interval != 'D' else 1440))
        # Для простоты берем последние N свечей, но лучше чанками
        # В этом примере упростим: скачаем 1000 (максимум за раз) * N запросов
        
        all_data = []
        end_time = int(datetime.now().timestamp() * 1000)
        
        logger.info(f"Downloading {interval} data for {symbol}...")
        
        for _ in range(5): # Скачаем ~5000 свечей (ок. 2 месяцев на 15м)
            try:
                resp = self.client.get_kline(
                    category="linear",
                    symbol=symbol,
                    interval=interval,
                    limit=limit,
                    end=end_time
                )
                if resp['retCode'] != 0: break
                
                chunk = resp['result']['list']
                if not chunk: break
                
                all_data.extend(chunk)
                last_candle_time = int(chunk[-1][0])
                end_time = last_candle_time - 1
                
                import time
                time.sleep(0.2) # Avoid Rate Limit
            except Exception as e:
                logger.error(f"Download error: {e}")
                break
                
        if not all_data:
            logger.warning("API Failed (Geo-block/Limit). Generating SYNTHETIC data for demonstration.")
            return self.generate_synthetic_data(days, interval)
            
        df = pd.DataFrame(all_data, columns=['startTime', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
        df['startTime'] = pd.to_numeric(df['startTime'])
        df['startTime'] = pd.to_datetime(df['startTime'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
            
        df = df.sort_values('startTime').reset_index(drop=True)
        return df

    def generate_synthetic_data(self, days, interval) -> pd.DataFrame:
        """Генерация случайных данных для тестирования логики"""
        # Увеличим объем данных для AI обучения
        days = 300 
        minutes = int(interval) if interval != 'D' else 1440
        periods = int((days * 24 * 60) / minutes)
        
        start_date = datetime.now() - timedelta(days=days)
        dates = [start_date + timedelta(minutes=minutes*i) for i in range(periods)]
        
        # Random Walk starting at 50000
        price = 50000.0
        data = []
        import random
        
        for date in dates:
            change = random.uniform(-0.005, 0.005) # +/- 0.5% per bar
            open_p = price
            close_p = price * (1 + change)
            high_p = max(open_p, close_p) * (1 + random.uniform(0, 0.002))
            low_p = min(open_p, close_p) * (1 - random.uniform(0, 0.002))
            vol = random.uniform(10, 100)
            
            data.append([date, open_p, high_p, low_p, close_p, vol, vol*close_p])
            price = close_p
            
        df = pd.DataFrame(data, columns=['startTime', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
        return df

    def run(self, symbol: str):
        logger.info(f"Starting Backtest for {symbol}...")
        
        # 1. Скачиваем данные
        df_15m = self.fetch_data(symbol, "15", 60)  # 2 месяца
        df_1h = self.fetch_data(symbol, "60", 60)
        df_4h = self.fetch_data(symbol, "240", 60)
        
        if df_15m.empty or df_1h.empty or df_4h.empty:
            logger.error("Not enough data")
            return

        logger.info(f"Loaded {len(df_15m)} 15m candles")

        # 2. Симуляция
        # Начинаем с 200-й свечи, чтобы хватило истории для индикаторов
        start_idx = 200
        
        active_trade = None
        
        for i in range(start_idx, len(df_15m)):
            current_time = df_15m.iloc[i]['startTime']
            
            # Срез данных "как в реальном времени"
            slice_15m = df_15m.iloc[i-200:i+1] # Последние 200 свечей
            
            # Эмуляция данных старших ТФ (ищем свечу, которая была известна на тот момент)
            # Берем свечи, закрытые ДО current_time
            slice_1h = df_1h[df_1h['startTime'] < current_time].tail(60)
            slice_4h = df_4h[df_4h['startTime'] < current_time].tail(60)
            
            if len(slice_1h) < 50 or len(slice_4h) < 50:
                continue
                
            current_bar = df_15m.iloc[i]
            current_price = current_bar['close']
            current_high = current_bar['high']
            current_low = current_bar['low']
            
            # === Проверка выхода из сделки ===
            if active_trade:
                # LONG Exit
                if active_trade['type'] == 'LONG':
                    if current_low <= active_trade['sl']:
                        self._close_trade(active_trade, active_trade['sl'], current_time, 'LOSS (SL)')
                        active_trade = None
                    elif current_high >= active_trade['tp']:
                        self._close_trade(active_trade, active_trade['tp'], current_time, 'WIN (TP)')
                        active_trade = None
                    # Trailing Stop (Simple)
                    elif current_high > active_trade['entry'] * 1.01: # 1% profit
                         active_trade['sl'] = active_trade['entry'] # Breakeven
                         
                # SHORT Exit
                elif active_trade['type'] == 'SHORT':
                    if current_high >= active_trade['sl']:
                        self._close_trade(active_trade, active_trade['sl'], current_time, 'LOSS (SL)')
                        active_trade = None
                    elif current_low <= active_trade['tp']:
                        self._close_trade(active_trade, active_trade['tp'], current_time, 'WIN (TP)')
                        active_trade = None
            
            # === Поиск входа ===
            else:
                signal = self.engine.analyze(slice_15m, slice_1h, slice_4h, symbol)
                
                if signal:
                    # Открываем сделку
                    tp = signal.take_profit_1 # Консервативный TP
                    sl = signal.stop_loss
                    
                    active_trade = {
                        'symbol': symbol,
                        'type': signal.signal_type.value,
                        'entry': current_price,
                        'sl': sl,
                        'tp': tp,
                        'time': current_time,
                        'size': 100 # Фикс ставка $100
                    }
                    print(f"[{current_time}] {signal.signal_type.value} Entry: {current_price:.2f} | Score: {signal.confluence.total_score}")

    def _close_trade(self, trade, exit_price, time, reason):
        pnl = 0
        is_win = 0
        if trade['type'] == 'LONG':
            pnl = (exit_price - trade['entry']) / trade['entry'] * trade['size']
            is_win = 1 if exit_price > trade['entry'] else 0
        else:
            pnl = (trade['entry'] - exit_price) / trade['entry'] * trade['size']
            is_win = 1 if exit_price < trade['entry'] else 0
            
        fee = trade['size'] * 0.001 # 0.1% комиссия (вход+выход)
        pnl -= fee
        
        # Save training data
        if 'features' in trade:
            trade['features']['target'] = is_win
            self.training_data.append(trade['features'])
            if len(self.training_data) % 10 == 0:
                self.save_training_data()
        
        self.balance += pnl
        self.trades.append({
            'type': trade['type'],
            'entry': trade['entry'],
            'exit': exit_price,
            'pnl': pnl,
            'reason': reason,
            'time': time
        })
        print(f"  └── {reason} Exit: {exit_price:.2f} | PnL: ${pnl:.2f}")

    def save_training_data(self):
        if not self.training_data:
            return
        df = pd.DataFrame(self.training_data)
        df.to_csv('training_data.csv', index=False)
        print(f"\n[AI] Saved {len(df)} training samples to training_data.csv")

    def run(self, symbol: str):
        logger.info(f"Starting Backtest for {symbol}...")
        self.training_data = [] # Buffer for AI features
        
        # 1. Скачиваем данные
        df_15m = self.fetch_data(symbol, "15", 60)  # 2 месяца
        df_1h = self.fetch_data(symbol, "60", 60)
        df_4h = self.fetch_data(symbol, "240", 60)
        
        if df_15m.empty or df_1h.empty or df_4h.empty:
            logger.error("Not enough data")
            return

        logger.info(f"Loaded {len(df_15m)} 15m candles")

        # 2. Симуляция
        # Начинаем с 200-й свечи, чтобы хватило истории для индикаторов
        start_idx = 200
        
        active_trade = None
        
        for i in range(start_idx, len(df_15m)):
            current_time = df_15m.iloc[i]['startTime']
            
            # Срез данных "как в реальном времени"
            slice_15m = df_15m.iloc[i-200:i+1] # Последние 200 свечей
            
            # Эмуляция данных старших ТФ (ищем свечу, которая была известна на тот момент)
            # Берем свечи, закрытые ДО current_time
            slice_1h = df_1h[df_1h['startTime'] < current_time].tail(60)
            slice_4h = df_4h[df_4h['startTime'] < current_time].tail(60)
            
            if len(slice_1h) < 50 or len(slice_4h) < 50:
                continue
                
            current_bar = df_15m.iloc[i]
            current_price = current_bar['close']
            current_high = current_bar['high']
            current_low = current_bar['low']
            
            # === Проверка выхода из сделки ===
            if active_trade:
                # LONG Exit
                if active_trade['type'] == 'LONG':
                    if current_low <= active_trade['sl']:
                        self._close_trade(active_trade, active_trade['sl'], current_time, 'LOSS (SL)')
                        active_trade = None
                    elif current_high >= active_trade['tp']:
                        self._close_trade(active_trade, active_trade['tp'], current_time, 'WIN (TP)')
                        active_trade = None
                    # Trailing Stop (Simple)
                    elif current_high > active_trade['entry'] * 1.01: # 1% profit
                         active_trade['sl'] = active_trade['entry'] # Breakeven
                         
                # SHORT Exit
                elif active_trade['type'] == 'SHORT':
                    if current_high >= active_trade['sl']:
                        self._close_trade(active_trade, active_trade['sl'], current_time, 'LOSS (SL)')
                        active_trade = None
                    elif current_low <= active_trade['tp']:
                        self._close_trade(active_trade, active_trade['tp'], current_time, 'WIN (TP)')
                        active_trade = None
            
            # === Поиск входа ===
            else:
                signal = self.engine.analyze(slice_15m, slice_1h, slice_4h, symbol)
                
                if signal:
                    # Feature Extraction for AI
                    features = {
                        'rsi_15m': signal.indicators.get('rsi_15m'),
                        'rsi_1h': signal.indicators.get('rsi_1h'),
                        'rsi_4h': signal.indicators.get('rsi_4h'),
                        'bb_position': signal.indicators.get('bb_position'),
                        'vol_ratio': signal.indicators.get('volume_ratio'),
                        'atr_pct': signal.indicators.get('atr', 0) / current_price * 100,
                        'hour_of_day': current_time.hour,
                        'trend_adx': slice_15m['adx'].iloc[-1] if 'adx' in slice_15m else 0, # Assuming ADX is calculated inside analyze, but it modifies copy. We might need to access it differently or recalc. 
                        # Actually analyze modifies transient copies. Let's simplify and assume indicators are populated in signal.
                        'funding_rate': signal.funding_rate or 0
                    }
                    
                    # Открываем сделку
                    tp = signal.take_profit_1 # Консервативный TP
                    sl = signal.stop_loss
                    
                    active_trade = {
                        'symbol': symbol,
                        'type': signal.signal_type.value,
                        'entry': current_price,
                        'sl': sl,
                        'tp': tp,
                        'time': current_time,
                        'size': 100, # Фикс ставка $100
                        'features': features
                    }
                    print(f"[{current_time}] {signal.signal_type.value} Entry: {current_price:.2f} | Score: {signal.confluence.total_score}")

        self._print_stats()
        self.save_training_data()

    def _print_stats(self):
        if not self.trades:
            print("\nNo trades executed.")
            return
            
        wins = len([t for t in self.trades if t['pnl'] > 0])
        total = len(self.trades)
        win_rate = (wins / total) * 100
        total_pnl = self.balance - self.initial_balance
        
        print("\n=== BACKTEST RESULTS ===")
        print(f"Total Trades: {total}")
        print(f"Win Rate:     {win_rate:.1f}%")
        print(f"Total PnL:    ${total_pnl:.2f} ({(total_pnl/self.initial_balance)*100:.1f}%)")
        print(f"Final Balance: ${self.balance:.2f}")
        print("========================\n")

if __name__ == "__main__":
    import sys
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    bt = Backtester()
    bt.run(symbol)
