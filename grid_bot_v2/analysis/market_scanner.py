import logging
import pandas as pd
import numpy as np
from decimal import Decimal
from typing import List, Dict, Any, Optional
from datetime import datetime

log = logging.getLogger("MarketScanner")

class ScannerResult:
    def __init__(self, symbol: str, score: float, regime: str, volatility: float):
        self.symbol = symbol
        self.score = score  # 0 to 100, higher is better for Grid
        self.regime = regime
        self.volatility = volatility

class MarketScanner:
    """
    Сканер рынка для поиска наиболее подходящей пары для сеточной торговли.
    Ищет "боковик" (mean-reversion) с умеренной волатильностью.
    """
    
    def __init__(self, client):
        self.client = client
        self.symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
        
    def scan(self) -> Optional[ScannerResult]:
        """Сканирует список пар и возвращает лучшую."""
        results = []
        for symbol in self.symbols:
            try:
                res = self.analyze_symbol(symbol)
                if res:
                    results.append(res)
                    log.info(f"🔍 Scanner: {symbol} | Score: {res.score:.1f} | Regime: {res.regime}")
            except Exception as e:
                log.error(f"❌ Scanner error for {symbol}: {e}")
        
        if not results:
            return None
            
        # Сортируем по скору
        results.sort(key=lambda x: x.score, reverse=True)
        return results[0]

    def analyze_symbol(self, symbol: str) -> Optional[ScannerResult]:
        """Анализирует конкретный символ на пригодность для Grid."""
        klines = self.client.get_klines(symbol=symbol, interval="15", limit=100)
        if not klines or len(klines) < 50:
            return None
            
        df = pd.DataFrame(klines, columns=['ts', 'open', 'high', 'low', 'close', 'vol', 'turnover'])
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        
        # 1. Считаем ADX (Trend Strength)
        adx = self._calculate_adx(df)
        
        # 2. Считаем Hurst Exponent (Mean Reversion)
        hurst = self._calculate_hurst(df['close'].values)
        
        # 3. Волатильность (ATR % от цены)
        returns = df['close'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(24 * 4) * 100 # Дневная волатильность
        
        # 4. Расчет итогового скора (чем меньше ADX и Hurst, тем лучше для Grid)
        # Идеальный ADX < 20
        # Идеальный Hurst < 0.45
        # Идеальная волатильность > 1% но < 5%
        
        adx_score = max(0, 100 - adx * 3) #ADX 20 -> 40, ADX 10 -> 70
        hurst_score = max(0, (0.7 - hurst) * 200) #Hurst 0.4 -> 60, Hurst 0.6 -> 20
        
        vol_score = 0
        if 1.0 < volatility < 5.0:
            vol_score = 50
        elif volatility >= 5.0:
            vol_score = 20 # Слишком опасно
        
        total_score = (adx_score * 0.4) + (hurst_score * 0.4) + (vol_score * 0.2)
        
        regime = "SIDEWAYS" if adx < 25 else "TRENDING"
        
        return ScannerResult(
            symbol=symbol,
            score=total_score,
            regime=regime,
            volatility=volatility
        )

    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Упрощенный расчет ADX."""
        plus_dm = df['high'].diff()
        minus_dm = df['low'].diff()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        minus_dm = abs(minus_dm)
        
        tr = pd.concat([df['high'] - df['low'], 
                        abs(df['high'] - df['close'].shift(1)), 
                        abs(df['low'] - df['close'].shift(1))], axis=1).max(axis=1)
        
        atr = tr.rolling(window=period).mean()
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()
        
        return float(adx.iloc[-1]) if not np.isnan(adx.iloc[-1]) else 50.0

    def _calculate_hurst(self, time_series, max_lag=20):
        """Расчет показателя Херста."""
        lags = range(2, max_lag)
        tau = [np.sqrt(np.std(np.subtract(time_series[lag:], time_series[:-lag]))) for lag in lags]
        poly = np.polyfit(np.log(lags), np.log(tau), 1)
        return poly[0] * 2.0
