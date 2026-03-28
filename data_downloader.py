import time
import pandas as pd
import json
import os
from datetime import datetime, timedelta, timezone
from pybit.unified_trading import HTTP
import sys

# Добавляем путь к корню проекта
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
import config

def download_bybit_data_pybit(symbol=None, interval="1", days=7):
    symbol = symbol or config.SYMBOL
    
    if getattr(config, 'API_PROXY', None):
        os.environ['HTTP_PROXY'] = config.API_PROXY
        os.environ['HTTPS_PROXY'] = config.API_PROXY

    # Важно: используем API ключи и флаг Demo
    session = HTTP(
        testnet=getattr(config, 'BYBIT_TESTNET', False),
        demo=getattr(config, 'BYBIT_DEMO', False),
        api_key=getattr(config, 'BYBIT_API_KEY', None),
        api_secret=getattr(config, 'BYBIT_API_SECRET', None)
    )
    
    now = datetime.now(timezone.utc)
    end_time = int(now.timestamp() * 1000)
    start_time = int((now - timedelta(days=days)).timestamp() * 1000)
    
    print(f"🚀 Начинаю загрузку {symbol} ({interval}m) за {days} дней...")
    
    all_klines = []
    current_start = start_time
    limit = 1000
    
    while current_start < end_time:
        try:
            response = session.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                start=current_start,
                limit=limit
            )
            
            if response.get('retCode') != 0:
                print(f"⚠️ Ошибка API: {response.get('retMsg')}")
                break

            klines = response.get('result', {}).get('list', [])
            if not klines: break
                
            klines.sort(key=lambda x: int(x[0]))
            all_klines += klines
            
            last_ts = int(klines[-1][0])
            if last_ts <= current_start: break
            current_start = last_ts + 60000 
            
            print(f"✅ Загружено {len(all_klines)} свечей... ({datetime.fromtimestamp(last_ts/1000, timezone.utc).strftime('%Y-%m-%d %H:%M')})")
            time.sleep(0.1)
            
        except Exception as e:
            print(f"⚠️ Ошибка: {e}")
            break
            
    if not all_klines:
        print("❌ Данные не были загружены. Пробуем альтернативный метод...")
        try:
             response = session.get_kline(category="linear", symbol=symbol, interval=interval, limit=1000)
             klines = response.get('result', {}).get('list', [])
             if klines:
                 print(f"✅ Удалось скачать последние {len(klines)} свечей.")
                 all_klines = klines
        except: pass

    if all_klines:
        df = pd.DataFrame(all_klines, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
        df.to_csv('historical_data.csv', index=False)
        print(f"🏁 Успех! Сохранено {len(all_klines)} свечей.")
    else:
        print("❌ Все попытки провалены. Bybit блокирует доступ.")

if __name__ == "__main__":
    download_bybit_data_pybit(days=7)
