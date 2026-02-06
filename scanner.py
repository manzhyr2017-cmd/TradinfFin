import logging
import pandas as pd
from typing import List, Dict, Any, Optional
from datetime import datetime
from pybit.unified_trading import HTTP
from mean_reversion_bybit import AdvancedMeanReversionEngine, AdvancedSignal

logger = logging.getLogger("Scanner")

class MarketScanner:
    def __init__(self, api_key: str = "", api_secret: str = "", testnet: bool = False):
        self.client = HTTP(
            testnet=testnet,
            api_key=api_key,
            api_secret=api_secret
        )
        self.engine = AdvancedMeanReversionEngine(min_confluence=65) # Чуть ниже порог для сканера

    def get_top_pairs(self, limit: int = 30, min_volume: float = 5000000) -> List[str]:
        """Получает топ USDT пар по объему"""
        try:
            resp = self.client.get_tickers(category="linear")
            if resp['retCode'] != 0:
                logger.error(f"Bybit API Error: {resp}")
                return []
            
            tickers = resp['result']['list']
            # Фильтруем только USDT
            usdt_pairs = [t for t in tickers if t['symbol'].endswith('USDT')]
            
            # Сортируем по обороту (turnover24h = объем в $)
            sorted_pairs = sorted(usdt_pairs, key=lambda x: float(x.get('turnover24h', 0)), reverse=True)
            
            # Фильтр по мин объему
            top_pairs = [
                t['symbol'] for t in sorted_pairs 
                if float(t.get('turnover24h', 0)) >= min_volume
            ][:limit]
            
            return top_pairs
        except Exception as e:
            logger.error(f"Error fetching top pairs: {e}")
            return []

    def fetch_candles(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        try:
            response = self.client.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            
            if response['retCode'] != 0:
                return pd.DataFrame()
                
            data = response['result']['list']
            df = pd.DataFrame(data, columns=['startTime', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
            
            df['startTime'] = pd.to_numeric(df['startTime'])
            df['startTime'] = pd.to_datetime(df['startTime'], unit='ms')
            
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
                
            # Bybit отдает от нового к старому, нам нужно наоборот для pandas rolling
            df = df.sort_values(by='startTime', ascending=True).reset_index(drop=True)
            return df
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")
            return pd.DataFrame()

    def scan(self, limit: int = 20) -> List[Dict[str, Any]]:
        logger.info(f"Starting scan for top {limit} pairs...")
        pairs = self.get_top_pairs(limit=limit)
        results = []
        
        for symbol in pairs:
            #logger.info(f"Analyzing {symbol}...")
            try:
                # Получаем данные
                df_15m = self.fetch_candles(symbol, "15", 200)
                if df_15m.empty: continue
                
                df_1h = self.fetch_candles(symbol, "60", 60)
                df_4h = self.fetch_candles(symbol, "240", 50)
                
                # Получаем funding (опционально, можно пропустить для скорости)
                funding = None
                
                # Анализ
                signal = self.engine.analyze(
                    df_15m, df_1h, df_4h, symbol, funding_rate=funding
                )
                
                if signal:
                    results.append({
                        "symbol": signal.symbol,
                        "type": signal.signal_type.value,
                        "price": signal.entry_price,
                        "score": signal.confluence.total_score,
                        "strength": signal.strength.value,
                        "reason": ", ".join(signal.reasoning[:2]), # Берем первые 2 причины
                        "timestamp": signal.timestamp.isoformat()
                    })
            except Exception as e:
                logger.error(f"Failed to analyze {symbol}: {e}")
                continue
                
        return sorted(results, key=lambda x: x['score'], reverse=True)

if __name__ == "__main__":
    # Test run
    logging.basicConfig(level=logging.INFO)
    scanner = MarketScanner()
    opportunities = scanner.scan(limit=10)
    print(f"Found {len(opportunities)} opportunities:")
    for opp in opportunities:
        print(opp)
