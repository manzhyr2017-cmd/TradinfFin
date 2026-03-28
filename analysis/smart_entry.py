import numpy as np
import pandas as pd
import logging
from typing import List, Tuple, Dict, Optional
from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("GridBot")

@dataclass
class EntrySignal:
    score: float          # -1.0 to 1.0 (normalized for Brain)
    action: str           # "BUY", "SELL", "WAIT"
    should_enter: bool    # Quick verdict
    confidence: float     # 0.0 to 1.0
    indicators: Dict[str, float]
    levels: Dict[str, float]

class SmartEntryAnalyzer:
    """
    ═══════════════════════════════════════════
     АНАЛИЗАТОР УМНЫХ ТОЧЕК ВХОДА
    ═══════════════════════════════════════════
    
    Использует scoring-систему для оценки момента входа.
    Поддерживает анализ конкретной цены (для сеточных уровней).
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.last_signal: Optional[EntrySignal] = None

    def analyze_buy_entry(
        self, 
        closes: np.ndarray, 
        highs: np.ndarray, 
        lows: np.ndarray, 
        volumes: np.ndarray,
        target_price: float
    ) -> EntrySignal:
        """Анализ пригодности цены для открытия BUY ордера."""
        df = pd.DataFrame({
            'close': closes,
            'high': highs,
            'low': lows,
            'volume': volumes
        })
        # Используем существующий метод, но с учетом target_price
        signal = self.analyze(df, target_price=target_price)
        
        # Инвертируем логику если сигнал на продажу, а мы просили покупку
        if signal.action == "SELL":
            signal.should_enter = False
            signal.score = -abs(signal.score / 100.0)
        else:
            signal.should_enter = (signal.action == "BUY")
            signal.score = signal.score / 100.0 if signal.action == "BUY" else 0.0
            
        return signal

    def analyze_sell_entry(
        self, 
        closes: np.ndarray, 
        highs: np.ndarray, 
        lows: np.ndarray, 
        volumes: np.ndarray,
        target_price: float
    ) -> EntrySignal:
        """Анализ пригодности цены для открытия SELL ордера."""
        df = pd.DataFrame({
            'close': closes,
            'high': highs,
            'low': lows,
            'volume': volumes
        })
        signal = self.analyze(df, target_price=target_price)
        
        if signal.action == "BUY":
            signal.should_enter = False
            signal.score = -abs(signal.score / 100.0)
        else:
            signal.should_enter = (signal.action == "SELL")
            signal.score = signal.score / 100.0 if signal.action == "SELL" else 0.0
            
        return signal

    def analyze(self, df: pd.DataFrame, target_price: Optional[float] = None) -> EntrySignal:
        """
        Полный анализ текущего состояния или конкретной цены.
        """
        if len(df) < 20:
            return EntrySignal(0, "WAIT", False, 0, {}, {})

        # ─── 1. ВЫЧИСЛЕНИЯ ИНДИКАТОРОВ ───────────────
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        vol = df['volume'].values

        # Bollinger Bands (период 20, откл 2)
        ma20 = self._sma(close, 20)
        std20 = self._std(close, 20)
        upper_bb = ma20 + (std20 * 2)
        lower_bb = ma20 - (std20 * 2)
        # bb_width = (upper_bb - lower_bb) / ma20 # Not used in scoring

        # RSI (14)
        rsi = self._rsi(close, 14)

        # MACD (12, 26, 9)
        macd, signal_line, hist = self._macd(close) # Renamed signal to signal_line to avoid conflict

        # Stochastic (14, 3, 3)
        stoch_k, stoch_d = self._stochastic(high, low, close, 14, 3)

        # VWAP (упрощённый для intraday)
        vwap = self._calculate_vwap(df)

        # ─── 2. SCORING SYSTEM (0-100) ───────────────
        buy_score = 0
        sell_score = 0
        # details = {} # Removed as it's not used in the new EntrySignal

        # Тестируемая цена: либо текущая, либо заданный уровень
        eval_price = target_price if target_price is not None else close[-1]

        # ① Bollinger Bands Filter (25 pts)
        # Требуем, чтобы цена была у нижней границы для покупки
        bb_pos = (eval_price - lower_bb[-1]) / (upper_bb[-1] - lower_bb[-1]) if (upper_bb[-1] > lower_bb[-1]) else 0.5
        if bb_pos < 0.2: # Очень близко к нижней
            buy_score += 25
            # details["bb_buy"] = 25
        elif bb_pos > 0.8: # Близко к верхней
            sell_score += 25
            # details["bb_sell"] = 25

        # ② Volume Spike (15 pts) - только если анализируем текущее состояние
        # Аномальный объём часто подтверждает разворот
        vol_ratio = 1.0
        if target_price is None:
            avg_vol = np.mean(vol[-20:-1]) if len(vol) > 20 else np.mean(vol)
            vol_ratio = vol[-1] / avg_vol if avg_vol > 0 else 1.0
            if vol_ratio > 2.0:
                buy_score += 15
                sell_score += 15
                # details["vol_spike"] = 15

        # ③ MACD Divergence (20 pts)
        # Ищем классическую бычью/медвежью дивергенцию
        if self._is_bullish_divergence(close, hist):
            buy_score += 20
            # details["macd_div_buy"] = 20
        if self._is_bearish_divergence(close, hist):
            sell_score += 20
            # details["macd_div_sell"] = 20

        # ④ RSI & Stochastic (20 pts)
        # Перепроданность/Перекупленность
        if rsi[-1] < 35 or stoch_k[-1] < 20: # Changed AND to OR
            buy_score += 20
            # details["oversold"] = 20
        elif rsi[-1] > 65 or stoch_k[-1] > 80: # Changed AND to OR
            sell_score += 20
            # details["overbought"] = 20

        # ⑤ VWAP & Trend (20 pts)
        # Возврат к среднему (Mean Reversion)
        if eval_price < vwap[-1] * 0.995: # 0.5% ниже VWAP
            buy_score += 20
            # details["below_vwap"] = 20
        elif eval_price > vwap[-1] * 1.005: # 0.5% выше VWAP
            sell_score += 20
            # details["above_vwap"] = 20

        # ─── 3. ВЕРДИКТ ──────────────────────────────
        verdict = "WAIT"
        final_score = 0
        
        # Порог входа — 50 баллов
        THRESHOLD = 50 # Changed from 60 to 50
        
        if buy_score >= THRESHOLD and buy_score > sell_score:
            verdict = "BUY"
            final_score = buy_score
        elif sell_score >= THRESHOLD and sell_score > buy_score:
            verdict = "SELL"
            final_score = sell_score

        # Расчёт уровней для входа
        levels = {
            "entry": eval_price,
            "stop": lower_bb[-1] if verdict == "BUY" else upper_bb[-1],
            "target": vwap[-1], # Simplified target to always be VWAP
            "vwap": vwap[-1]
        }

        signal = EntrySignal(
            score=float(final_score),
            action=verdict,
            should_enter=(final_score >= THRESHOLD),
            confidence=final_score / 100,
            indicators={
                "rsi": float(rsi[-1]),
                "stoch": float(stoch_k[-1]),
                "bb_pos": float(bb_pos),
                "vol_ratio": float(vol_ratio)
            },
            levels=levels
        )
        
        self.last_signal = signal
        return signal

    # ─── ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ ──────────────────────
    
    def _sma(self, data, period):
        return pd.Series(data).rolling(window=period).mean().values

    def _std(self, data, period):
        return pd.Series(data).rolling(window=period).std().values

    def _rsi(self, prices, periods=14):
        deltas = np.diff(prices)
        seed = deltas[:periods+1]
        up = seed[seed >= 0].sum() / periods
        down = -seed[seed < 0].sum() / periods
        rs = up / down if down > 0 else 0
        rsi = np.zeros_like(prices)
        rsi[:periods] = 100. - 100. / (1. + rs)

        for i in range(periods, len(prices)):
            delta = deltas[i - 1]
            if delta > 0:
                upval = delta
                downval = 0.
            else:
                upval = 0.
                downval = -delta

            up = (up * (periods - 1) + upval) / periods
            down = (down * (periods - 1) + downval) / periods
            rs = up / down if down > 0 else 0
            rsi[i] = 100. - 100. / (1. + rs)
        return rsi

    def _macd(self, prices):
        exp1 = pd.Series(prices).ewm(span=12, adjust=False).mean()
        exp2 = pd.Series(prices).ewm(span=26, adjust=False).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=9, adjust=False).mean()
        return macd.values, signal.values, (macd - signal).values

    def _stochastic(self, high, low, close, k=14, d=3):
        low_min = pd.Series(low).rolling(window=k).min()
        high_max = pd.Series(high).rolling(window=k).max()
        stoch_k = 100 * (pd.Series(close) - low_min) / (high_max - low_min)
        stoch_d = stoch_k.rolling(window=d).mean()
        return stoch_k.values, stoch_d.values

    def _calculate_vwap(self, df):
        v = df['volume'].values
        p = (df['high'] + df['low'] + df['close']).values / 3
        return (p * v).cumsum() / v.cumsum()

    def _is_bullish_divergence(self, close, hist, window=10):
        """Ищем: Цена падает, а гистограмма MACD растёт."""
        c_win = close[-window:]
        h_win = hist[-window:]
        # Упрощённая проверка наклона
        c_slope = (c_win[-1] - c_win[0]) / window
        h_slope = (h_win[-1] - h_win[0]) / window
        return c_slope < 0 and h_slope > 0

    def _is_bearish_divergence(self, close, hist, window=10):
        """Ищем: Цена растёт, а гистограмма MACD падает."""
        c_win = close[-window:]
        h_win = hist[-window:]
        c_slope = (c_win[-1] - c_win[0]) / window
        h_slope = (h_win[-1] - h_win[0]) / window
        return c_slope > 0 and h_slope < 0
