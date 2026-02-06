"""
Advanced Mean Reversion Engine v2.0 - Bybit Edition
====================================================
Цель: 85%+ Win Rate через Multi-Factor Confluence

ИНТЕГРАЦИЯ С BYBIT:
+ Funding Rate анализ (экстремумы = разворот)
+ Open Interest анализ
+ Order Book Imbalance

CONFLUENCE FACTORS (100 баллов максимум):
1. RSI экстремумы (0-25)
2. Bollinger Bands position (0-15)
3. Multi-Timeframe alignment (0-25)
4. Support/Resistance proximity (0-15)
5. Volume spike (0-10)
6. MACD divergence (0-10)
7. Funding Rate (0-10) - НОВОЕ
8. Order Book Imbalance (0-5) - НОВОЕ
9. Additional oscillators (0-10)

Минимальный score для входа: 70/100
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from datetime import datetime, timedelta
import logging
import requests
import json
import os
from collections import deque

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# ENUMS & DATA CLASSES
# ============================================================

class SignalType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_SIGNAL = "NO_SIGNAL"


class SignalStrength(Enum):
    WEAK = "WEAK"           # 60-70% probability
    MODERATE = "MODERATE"   # 70-80% probability  
    STRONG = "STRONG"       # 80-85% probability
    EXTREME = "EXTREME"     # 85%+ probability


class MarketRegime(Enum):
    STRONG_TREND_UP = "STRONG_TREND_UP"
    WEAK_TREND_UP = "WEAK_TREND_UP"
    RANGING_NARROW = "RANGING_NARROW"
    RANGING_WIDE = "RANGING_WIDE"
    WEAK_TREND_DOWN = "WEAK_TREND_DOWN"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    VOLATILE_CHAOS = "VOLATILE_CHAOS"
    NEUTRAL = "NEUTRAL"


@dataclass
class SupportResistanceLevel:
    price: float
    strength: int
    level_type: str  # 'support' или 'resistance'
    timeframe: str
    last_touch: datetime


class StrategyType(Enum):
    MEAN_REVERSION = "MEAN_REVERSION"
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    GRID = "GRID"
    SCALPING = "SCALPING"


@dataclass
class Trade:
    """Trade record для Performance Tracker"""
    entry_time: datetime
    exit_time: Optional[datetime] = None
    symbol: str = ""
    strategy: StrategyType = StrategyType.MEAN_REVERSION
    signal_type: SignalType = SignalType.LONG
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    confluence_score: float = 0.0
    is_winner: bool = False
    exit_reason: str = ""


@dataclass
class ConfluenceScore:
    total_score: int = 0
    max_possible: int = 135  # Повышено до 135 (Ultimate v3)
    factors: Dict[str, Tuple[int, int]] = field(default_factory=dict)  # name: (score, max)
    
    def add_factor(self, name: str, score: int, max_score: int):
        self.factors[name] = (score, max_score)
        self.total_score += score
    
    @property
    def percentage(self) -> float:
        return (self.total_score / self.max_possible) * 100
    
    def get_strength(self) -> SignalStrength:
        pct = self.percentage
        if pct >= 85:
            return SignalStrength.EXTREME
        elif pct >= 75:
            return SignalStrength.STRONG
        elif pct >= 65:
            return SignalStrength.MODERATE
        else:
            return SignalStrength.WEAK
    
    def get_breakdown(self) -> str:
        """Возвращает детальную разбивку по факторам"""
        lines = []
        for name, (score, max_score) in self.factors.items():
            bar = '█' * int(score / max_score * 10) + '░' * (10 - int(score / max_score * 10))
            lines.append(f"  {name:25} [{bar}] {score}/{max_score}")
        return '\n'.join(lines)


# ============================================================
# ULTIMATE MODULES
# ============================================================

class NewsEngine:
    """Новостной движок с Sentiment Analysis и Детектором Критических Событий"""
    def __init__(self, api_key: str, use_finbert: bool = False):
        self.api_key = api_key
        self.base_url = "https://cryptopanic.com/api/v1"
        self.cache = {}
        self.cache_ttl = 300
        self.use_finbert = use_finbert
        self.sentiment_model = None
        
        if use_finbert:
            try:
                from transformers import pipeline
                self.sentiment_model = pipeline("sentiment-analysis", model="ProsusAI/finbert")
                logger.info("✅ NewsEngine: FinBERT loaded successfully")
            except Exception as e:
                logger.warning(f"⚠️ NewsEngine: FinBERT not available: {e}. Using simple sentiment.")
                self.use_finbert = False

    def _is_critical_event(self, text: str) -> bool:
        """Детектор критических событий (Hack, Delist, Scam и т.д.)"""
        text_lower = text.lower()
        critical_keywords = [
            'hack', 'hacked', 'exploit', 'vulnerability',
            'delist', 'delisting', 'suspend', 'halt',
            'regulation', 'sec', 'lawsuit', 'fraud',
            'bankruptcy', 'insolvent', 'collapse',
            'emergency', 'critical', 'urgent', 'alert'
        ]
        return any(keyword in text_lower for keyword in critical_keywords)

    def get_market_sentiment(self, currency: str) -> Dict[str, Any]:
        """Полный анализ market sentiment через CryptoPanic"""
        if not self.api_key:
            return {'score': 0.0, 'news_count': 0, 'critical_events': []}
            
        try:
            url = f"{self.base_url}/posts/"
            # Remove trailing slash and use more standard params
            params = {'auth_token': self.api_key, 'currencies': currency}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code != 200:
                logger.warning(f"⚠️ NewsEngine: CryptoPanic returned status {response.status_code}")
                return {'score': 0.0, 'news_count': 0, 'critical_events': []}

            if not response.text or response.text.strip() == "":
                logger.warning("⚠️ NewsEngine: CryptoPanic returned empty response")
                return {'score': 0.0, 'news_count': 0, 'critical_events': []}

            data = response.json()
            news = data.get('results', [])[:15]
            
            sentiments = []
            critical_events = []
            
            for item in news:
                title = item.get('title', '')
                if self._is_critical_event(title):
                    critical_events.append(title)
                
                score = self._analyze_text(title)
                sentiments.append(score)
            
            avg_score = sum(sentiments) / len(sentiments) if sentiments else 0.0
            logger.info(f"📰 NewsEngine: {currency} analysis complete. Items: {len(news)}, Score: {avg_score:.2f}")
            return {
                'score': float(avg_score),
                'news_count': len(news),
                'critical_events': critical_events,
                'sentiment_label': "Bullish" if avg_score > 0.2 else ("Bearish" if avg_score < -0.2 else "Neutral")
            }
        except Exception as e:
            logger.error(f"NewsEngine error: {e}")
            return {'score': 0.0, 'news_count': 0, 'critical_events': []}

    def _analyze_text(self, text: str) -> float:
        if self.use_finbert and self.sentiment_model:
            try:
                res = self.sentiment_model(text[:512])[0]
                label = res['label'].lower()
                score = res['score']
                return score if label == 'positive' else (-score if label == 'negative' else 0.0)
            except: pass
        
        # Simple keywords
        text = text.lower()
        pos_words = ['bull', 'pump', 'surge', 'rally', 'profit', 'up', 'buy', 'growth', 'listing']
        neg_words = ['bear', 'dump', 'crash', 'fall', 'loss', 'down', 'sell', 'scam', 'drop']
        
        pos = sum(1 for w in pos_words if w in text)
        neg = sum(1 for w in neg_words if w in text)
        
        if (pos + neg) == 0: return 0.0
        return (pos - neg) / (pos + neg)


class RiskManager:
    """Продвинутое управление рисками и Circuit Breaker (ULTIMA Grade)"""
    def __init__(self, total_capital: float = 10000, daily_loss_limit: float = 0.05, max_positions: int = 3):
        self.total_capital = total_capital
        self.starting_capital = total_capital
        self.daily_loss_limit = daily_loss_limit # 0.05 = 5%
        self.max_positions = max_positions
        
        self.daily_pnl = 0.0
        self.current_positions = 0
        self.last_reset = datetime.now().date()
        self.circuit_breaker_active = False

    def reset_daily_stats(self):
        today = datetime.now().date()
        if today > self.last_reset:
            self.daily_pnl = 0.0
            self.last_reset = today
            self.circuit_breaker_active = False
            logger.info("📊 RiskManager: Daily stats reset")

    def check_circuit_breaker(self) -> bool:
        self.reset_daily_stats()
        
        loss_pct = (self.daily_pnl / self.starting_capital)
        if loss_pct <= -self.daily_loss_limit:
            if not self.circuit_breaker_active:
                logger.critical(f"🚨 CIRCUIT BREAKER TRIGGERED! Daily loss: {loss_pct*100:.2f}%")
                self.circuit_breaker_active = True
            return True
        return False

    def can_open_position(self) -> bool:
        if self.circuit_breaker_active: return False
        if self.current_positions >= self.max_positions:
            return False
        return True

    def calculate_kelly_size_usd(self, win_rate: float, avg_win: float, avg_loss: float, stop_loss_pct: float) -> float:
        """
        Calculates position size in USD using Kelly Criterion (Conservative 1/4 Kelly)
        """
        if win_rate <= 0 or avg_win <= 0 or avg_loss <= 0:
            return self.total_capital * 0.01 / stop_loss_pct if stop_loss_pct > 0 else 0
            
        loss_rate = 1 - win_rate
        # Kelly % = (Win% * AvgWin - Loss% * AvgLoss) / AvgWin
        kelly_pct = (win_rate * avg_win - loss_rate * avg_loss) / avg_win
        
        # Quarter Kelly for safety
        kelly_pct = max(0, min(kelly_pct * 0.25, 0.05)) # Max 5% risk per trade
        
        risk_amount = self.total_capital * kelly_pct
        position_usd = risk_amount / stop_loss_pct if stop_loss_pct > 0 else 0
        
        return float(position_usd)


class PerformanceTracker:
    """Отслеживание результатов торгов"""
    def __init__(self, max_history: int = 1000):
        self.trades = deque(maxlen=max_history)
        self.equity_curve = [10000.0]

    def add_trade(self, trade: Trade):
        self.trades.append(trade)
        self.equity_curve.append(self.equity_curve[-1] + trade.pnl)

    def get_stats(self) -> Dict:
        if not self.trades: return {'win_rate': 0.5, 'profit_factor': 1.0, 'avg_win': 100, 'avg_loss': 100}
        wins = [t for t in self.trades if t.is_winner]
        losses = [t for t in self.trades if not t.is_winner]
        wr = len(wins) / len(self.trades)
        total_win = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        pf = total_win / total_loss if total_loss > 0 else 2.0
        return {'win_rate': wr, 'profit_factor': pf, 'avg_win': total_win/max(1, len(wins)), 'avg_loss': total_loss/max(1, len(losses))}


@dataclass
class AdvancedSignal:
    signal_type: SignalType
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    
    confluence: ConfluenceScore = field(default_factory=lambda: ConfluenceScore())
    probability: int = 50
    strength: SignalStrength = SignalStrength.MODERATE
    
    timeframes_aligned: Dict[str, bool] = field(default_factory=dict)
    support_resistance_nearby: Optional[SupportResistanceLevel] = None
    market_regime: MarketRegime = MarketRegime.NEUTRAL
    
    risk_reward_ratio: float = 2.0
    position_size_percent: float = 1.0
    
    # Bybit специфичные данные
    funding_rate: Optional[float] = 0.0
    funding_interpretation: Optional[str] = "Neutral"
    orderbook_imbalance: Optional[float] = 0.0
    
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    valid_until: datetime = field(default_factory=lambda: datetime.now() + timedelta(hours=4))
    
    indicators: Dict[str, Any] = field(default_factory=dict)
    reasoning: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Тюнинг стратегии (Фаза 5)
    time_exit_bars: int = 24  # Максимальное удержание (например, 24 свечи по 15м = 6 часов)


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

class TechnicalIndicators:
    """Набор технических индикаторов"""
    
    @staticmethod
    def sma(data: pd.Series, period: int) -> pd.Series:
        return data.rolling(window=period).mean()
    
    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        return data.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        delta = data.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def stochastic_rsi(data: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> Tuple[pd.Series, pd.Series]:
        rsi = TechnicalIndicators.rsi(data, rsi_period)
        stoch_rsi = (rsi - rsi.rolling(stoch_period).min()) / \
                    (rsi.rolling(stoch_period).max() - rsi.rolling(stoch_period).min())
        k = stoch_rsi * 100
        d = k.rolling(3).mean()
        return k, d
    
    @staticmethod
    def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        middle = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower
    
    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.rolling(window=period).mean()
    
    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        
        atr_val = TechnicalIndicators.atr(high, low, close, period)
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr_val)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr_val)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx_val = dx.rolling(window=period).mean()
        
        return adx_val, plus_di, minus_di
    
    @staticmethod
    def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = data.ewm(span=fast, adjust=False).mean()
        ema_slow = data.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()
        return -100 * (highest_high - close) / (highest_high - lowest_low)
    
    @staticmethod
    def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
        tp = (high + low + close) / 3
        sma = tp.rolling(window=period).mean()
        mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean())
        return (tp - sma) / (0.015 * mad)
    
        mfr = positive_mf / negative_mf
        return 100 - (100 / (1 + mfr))

    @staticmethod
    def fibonacci_levels(high: pd.Series, low: pd.Series, lookback: int = 50) -> Dict[str, float]:
        """
        Calculate Fibonacci Retracement levels from recent swing high/low.
        Returns dict with levels: 0.236, 0.382, 0.5, 0.618, 0.786
        """
        recent_high = high.tail(lookback).max()
        recent_low = low.tail(lookback).min()
        diff = recent_high - recent_low
        
        return {
            'high': recent_high,
            'low': recent_low,
            '0.236': recent_high - (diff * 0.236),
            '0.382': recent_high - (diff * 0.382),
            '0.5': recent_high - (diff * 0.5),
            '0.618': recent_high - (diff * 0.618),
            '0.786': recent_high - (diff * 0.786),
        }
    
    @staticmethod
    def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, 
                   period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
        """
        Supertrend indicator.
        Returns (supertrend_line, direction) where direction is 1 for bullish, -1 for bearish.
        """
        atr = TechnicalIndicators.atr(high, low, close, period)
        
        hl2 = (high + low) / 2
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        supertrend = pd.Series(index=close.index, dtype=float)
        direction = pd.Series(index=close.index, dtype=float)
        
        # Initialize
        supertrend.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = 1
        
        for i in range(1, len(close)):
            if close.iloc[i] > upper_band.iloc[i-1]:
                supertrend.iloc[i] = lower_band.iloc[i]
                direction.iloc[i] = 1  # Bullish
            elif close.iloc[i] < lower_band.iloc[i-1]:
                supertrend.iloc[i] = upper_band.iloc[i]
                direction.iloc[i] = -1  # Bearish
            else:
                supertrend.iloc[i] = supertrend.iloc[i-1]
                direction.iloc[i] = direction.iloc[i-1]
                
                # Adjust bands
                if direction.iloc[i] == 1 and lower_band.iloc[i] < supertrend.iloc[i-1]:
                    supertrend.iloc[i] = supertrend.iloc[i-1]
                elif direction.iloc[i] == -1 and upper_band.iloc[i] > supertrend.iloc[i-1]:
                    supertrend.iloc[i] = supertrend.iloc[i-1]
        
        return supertrend, direction

    @staticmethod
    def zscore(data: pd.Series, period: int = 20) -> pd.Series:
        mean = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        return (data - mean) / std


# ============================================================
# SUPPORT/RESISTANCE DETECTOR
# ============================================================

class SupportResistanceDetector:
    
    def __init__(self, lookback: int = 100, tolerance: float = 0.002):
        self.lookback = lookback
        self.tolerance = tolerance
    
    def find_levels(self, df: pd.DataFrame) -> List[SupportResistanceLevel]:
        levels = []
        data = df.tail(self.lookback).copy()
        
        highs = data['high'].values
        lows = data['low'].values
        closes = data['close'].values
        
        # Локальные максимумы
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                price = highs[i]
                strength = self._count_touches(closes, price)
                if strength >= 2:
                    levels.append(SupportResistanceLevel(
                        price=price,
                        strength=strength,
                        level_type='resistance',
                        timeframe=df.attrs.get('timeframe', '15m'),
                        last_touch=datetime.now()
                    ))
        
        # Локальные минимумы
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                price = lows[i]
                strength = self._count_touches(closes, price)
                if strength >= 2:
                    levels.append(SupportResistanceLevel(
                        price=price,
                        strength=strength,
                        level_type='support',
                        timeframe=df.attrs.get('timeframe', '15m'),
                        last_touch=datetime.now()
                    ))
        
        levels.sort(key=lambda x: x.strength, reverse=True)
        return self._merge_close_levels(levels)
    
    def _count_touches(self, prices: np.ndarray, level: float) -> int:
        tolerance_abs = level * self.tolerance
        return sum(1 for price in prices if abs(price - level) <= tolerance_abs)
    
    def _merge_close_levels(self, levels: List[SupportResistanceLevel], threshold: float = 0.005) -> List[SupportResistanceLevel]:
        if not levels:
            return []
        
        merged = [levels[0]]
        for level in levels[1:]:
            is_close = False
            for existing in merged:
                if abs(level.price - existing.price) / existing.price < threshold:
                    existing.strength += level.strength
                    is_close = True
                    break
            if not is_close:
                merged.append(level)
        return merged
    
    def find_nearest(self, levels: List[SupportResistanceLevel], price: float, direction: str) -> Optional[SupportResistanceLevel]:
        if direction == 'below':
            candidates = [l for l in levels if l.price < price and l.level_type == 'support']
            return max(candidates, key=lambda x: x.price) if candidates else None
        else:
            candidates = [l for l in levels if l.price > price and l.level_type == 'resistance']
            return min(candidates, key=lambda x: x.price) if candidates else None


# ============================================================
# MULTI-TIMEFRAME ANALYZER
# ============================================================

class MultiTimeframeAnalyzer:
    
    def __init__(self):
        self.ind = TechnicalIndicators()
    
    def analyze_timeframe(self, df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 50:
            return {'valid': False}
        
        df = df.copy()
        df['rsi'] = self.ind.rsi(df['close'])
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = self.ind.bollinger_bands(df['close'])
        df['adx'], df['plus_di'], df['minus_di'] = self.ind.adx(df['high'], df['low'], df['close'])
        df['macd'], df['macd_signal'], df['macd_hist'] = self.ind.macd(df['close'])
        df['ema_200'] = self.ind.ema(df['close'], 200)
        df['vol_zscore'] = self.ind.zscore(df['volume'], 20)
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        return {
            'valid': True,
            'rsi': current['rsi'],
            'rsi_oversold': current['rsi'] < 30,
            'rsi_overbought': current['rsi'] > 70,
            'rsi_extreme_oversold': current['rsi'] < 20,
            'rsi_extreme_overbought': current['rsi'] > 80,
            'below_bb_lower': current['close'] < current['bb_lower'],
            'above_bb_upper': current['close'] > current['bb_upper'],
            'bb_position': (current['close'] - current['bb_lower']) / (current['bb_upper'] - current['bb_lower']),
            'adx': current['adx'],
            'trend_strength': 'strong' if current['adx'] > 25 else 'weak',
            'trend_direction': 'up' if current['plus_di'] > current['minus_di'] else 'down',
            'macd_bearish': current['macd_hist'] < prev['macd_hist'],
            'macd_bullish': current['macd_hist'] > prev['macd_hist'],
            'price': current['close'],
            'rsi_slope': current['rsi'] - prev['rsi'],
            'ema_dist': (current['close'] - current['ema_200']) / current['ema_200'] * 100 if 'ema_200' in current else 0,
            'bb_width': (current['bb_upper'] - current['bb_lower']) / current['bb_middle'] if 'bb_middle' in current else 0,
            'vol_zscore': current['vol_zscore'] if 'vol_zscore' in current else 0
        }
    
    def check_alignment(self, tf_15m: Dict, tf_1h: Dict, tf_4h: Dict, direction: str) -> Dict[str, Any]:
        if not all([tf_15m.get('valid'), tf_1h.get('valid'), tf_4h.get('valid')]):
            return {'aligned': False, 'score': 0, 'details': {}}
        
        score = 0
        details = {}
        
        if direction == 'LONG':
            if tf_15m['rsi_oversold']:
                score += 20
                details['15m_rsi'] = f"✅ RSI={tf_15m['rsi']:.1f} < 30"
            if tf_15m['rsi_extreme_oversold']:
                score += 10
                details['15m_extreme'] = f"✅ RSI < 20 (экстремум)"
            if tf_15m['below_bb_lower']:
                score += 10
                details['15m_bb'] = "✅ Ниже BB Lower"
            
            if tf_1h['rsi'] < 40:
                score += 15
                details['1h_rsi'] = f"✅ 1H RSI={tf_1h['rsi']:.1f} < 40"
            if tf_1h['rsi'] < 30:
                score += 10
                details['1h_oversold'] = f"✅ 1H перепродан"
            if tf_1h['trend_strength'] == 'weak':
                score += 10
                details['1h_trend'] = f"✅ 1H тренд слабый"
            
            if tf_4h['rsi'] < 50:
                score += 10
                details['4h_rsi'] = f"✅ 4H RSI < 50"
            if tf_4h['adx'] < 30:
                score += 10
                details['4h_adx'] = f"✅ 4H нет сильного тренда"
            if tf_4h['macd_bullish']:
                score += 5
                details['4h_macd'] = "✅ 4H MACD вверх"
        
        else:  # SHORT
            if tf_15m['rsi_overbought']:
                score += 20
                details['15m_rsi'] = f"✅ RSI={tf_15m['rsi']:.1f} > 70"
            if tf_15m['rsi_extreme_overbought']:
                score += 10
                details['15m_extreme'] = f"✅ RSI > 80 (экстремум)"
            if tf_15m['above_bb_upper']:
                score += 10
                details['15m_bb'] = "✅ Выше BB Upper"
            
            if tf_1h['rsi'] > 60:
                score += 15
                details['1h_rsi'] = f"✅ 1H RSI={tf_1h['rsi']:.1f} > 60"
            if tf_1h['rsi'] > 70:
                score += 10
                details['1h_overbought'] = f"✅ 1H перекуплен"
            if tf_1h['trend_strength'] == 'weak':
                score += 10
                details['1h_trend'] = f"✅ 1H тренд слабый"
            
            if tf_4h['rsi'] > 50:
                score += 10
                details['4h_rsi'] = f"✅ 4H RSI > 50"
            if tf_4h['adx'] < 30:
                score += 10
                details['4h_adx'] = f"✅ 4H нет сильного тренда"
            if tf_4h['macd_bearish']:
                score += 5
                details['4h_macd'] = "✅ 4H MACD вниз"
        
        return {'aligned': score >= 50, 'score': score, 'details': details}


# ============================================================
# MAIN ENGINE
# ============================================================

class AdvancedMeanReversionEngine:
    """
    Продвинутый Mean Reversion движок для Bybit
    
    Дополнительные факторы:
    - Funding Rate (для perpetual)
    - Order Book Imbalance
    """
    
    def __init__(self, min_confluence: int = 85, min_rr: float = 4.5):
        """
        Sniper Mode: min_confluence=85 (Extreme only), min_rr=4.0 (1:4 minimum)
        """
        self.ind = TechnicalIndicators()
        self.sr_detector = SupportResistanceDetector()
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.min_confluence = min_confluence
        self.min_rr = min_rr
        
        # AI Integration
        try:
            from ai_engine import AIEngine
            self.ai = AIEngine()
        except ImportError:
            self.ai = None
    
    def analyze(
        self,
        df_15m: pd.DataFrame,
        df_1h: pd.DataFrame,
        df_4h: pd.DataFrame,
        symbol: str,
        funding_rate: Optional[float] = None,
        orderbook_imbalance: Optional[float] = None,
        is_scalping: bool = False
    ) -> Optional[AdvancedSignal]:
        """
        Главный метод анализа
        
        Args:
            df_15m, df_1h, df_4h: Данные по таймфреймам (В режиме Scalping df_15m = df_1m)
            symbol: Торговая пара
            funding_rate: Funding rate с Bybit (для perpetual)
            orderbook_imbalance: Дисбаланс стакана
            is_scalping: Режим скальпинга
        """
        
        # В режиме скальпинга нам нужно меньше истории
        min_len = 50 if is_scalping else 100
        if len(df_15m) < min_len:
            return None
        
        if not is_scalping and (len(df_1h) < 50 or len(df_4h) < 50):
            return None
            
        # 0. Фильтр волатильности (ATR Filter)
        # Не торгуем если цена "стоит" (ATR < 0.2% от цены)
        current_price = df_15m['close'].iloc[-1]
        atr = self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1]
        atr_pct = (atr / current_price) * 100
        
        if atr_pct < 0.2:
            logger.debug(f"{symbol}: Low Volatility (ATR {atr_pct:.2f}%) - SKIP")
            return None
        
        # Режим рынка
        if is_scalping:
            regime = MarketRegime.RANGING_WIDE # Default for scalping
        else:
            regime = self.detect_regime(df_4h)
            if regime in [MarketRegime.STRONG_TREND_UP, MarketRegime.STRONG_TREND_DOWN, MarketRegime.VOLATILE_CHAOS]:
                logger.debug(f"{symbol}: {regime.value} - пропуск")
                return None
        
        # Анализ таймфреймов
        tf_15m = self.mtf_analyzer.analyze_timeframe(df_15m)
        
        if is_scalping:
            # В скальпинге мы смотрим только на 1м (который передан в df_15m)
            # Заглушки для старших ТФ
            tf_1h = tf_15m.copy() 
            tf_4h = tf_15m.copy()
        else:
            tf_1h = self.mtf_analyzer.analyze_timeframe(df_1h)
            tf_4h = self.mtf_analyzer.analyze_timeframe(df_4h)
        
        # Проверка LONG
        long_signal = self._check_long(
            df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
            funding_rate, orderbook_imbalance
        )
        if long_signal and long_signal.confluence.percentage >= self.min_confluence:
            # AI Check
            if self.ai:
                try:
                    ai_prob = self.ai.predict_success_probability(long_signal.indicators)
                    long_signal.indicators['ai_score'] = ai_prob
                    long_signal.reasoning.append(f"🤖 AI Score: {ai_prob*100:.1f}%")
                    # Filter weak AI signals
                    if ai_prob < 0.6:
                         logger.info(f"AI rejected LONG {symbol} (prob {ai_prob:.2f})")
                         return None
                except Exception as e:
                    logger.warning(f"⚠️ AI Check Failed (Rate Limit?): {e}. Proceeding with technical signal.")
                    long_signal.reasoning.append("⚠️ AI недоступен (Tech Only)")

            return long_signal
        
        # Проверка SHORT
        short_signal = self._check_short(
            df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
            funding_rate, orderbook_imbalance
        )
        if short_signal and short_signal.confluence.percentage >= self.min_confluence:
             # AI Check
            if self.ai:
                try:
                    ai_prob = self.ai.predict_success_probability(short_signal.indicators)
                    short_signal.indicators['ai_score'] = ai_prob
                    short_signal.reasoning.append(f"🤖 AI Score: {ai_prob*100:.1f}%")
                    if ai_prob < 0.6:
                         logger.info(f"AI rejected SHORT {symbol} (prob {ai_prob:.2f})")
                         return None
                except Exception as e:
                    logger.warning(f"⚠️ AI Check Failed (Rate Limit?): {e}. Proceeding with technical signal.")
                    short_signal.reasoning.append("⚠️ AI недоступен (Tech Only)")

            return short_signal
        
        return None
    
    def detect_regime(self, df: pd.DataFrame) -> MarketRegime:
        df = df.copy()
        df['adx'], df['plus_di'], df['minus_di'] = self.ind.adx(df['high'], df['low'], df['close'])
        df['atr'] = self.ind.atr(df['high'], df['low'], df['close'])
        
        current = df.iloc[-1]
        avg_atr = df['atr'].tail(20).mean()
        volatility_ratio = current['atr'] / avg_atr if avg_atr > 0 else 1
        
        if volatility_ratio > 2.0:
            return MarketRegime.VOLATILE_CHAOS
        
        adx = current['adx']
        trend_up = current['plus_di'] > current['minus_di']
        
        if adx > 40:
            return MarketRegime.STRONG_TREND_UP if trend_up else MarketRegime.STRONG_TREND_DOWN
        elif adx > 25:
            return MarketRegime.WEAK_TREND_UP if trend_up else MarketRegime.WEAK_TREND_DOWN
        else:
            try:
                bb_upper, bb_middle, bb_lower = self.ind.bollinger_bands(df['close'])
                bb_width = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1]
                return MarketRegime.RANGING_NARROW if bb_width < 0.04 else MarketRegime.RANGING_WIDE
            except Exception:
                 return MarketRegime.RANGING_WIDE
    
    def _check_long(
        self, df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
        funding_rate, orderbook_imbalance
    ) -> Optional[AdvancedSignal]:
        
        # Dynamic RSI Thresholds
        adx = tf_15m.get('adx', 0)
        rsi_limit = 25 if adx > 30 else 30

        # === TREND GUARDIAN (Block counter-trend entries) ===
        price = tf_15m['price']
        
        # Long Safeguard
        if tf_1h.get('valid'):
            # If price is below 1H EMA 200 AND trend is strong down, BLOCK LONG
            # (ema_dist is (price - ema200) / ema200 * 100)
            is_bearish_macro = tf_1h.get('ema_dist', 0) < -0.5 and tf_1h.get('trend_direction') == 'down'
            
            if is_bearish_macro:
                # Allow only if EXTREME exhaustion (RSI < 15)
                if tf_15m['rsi'] > 15:
                    logger.debug(f"{symbol}: Blocked LONG by Trend Guardian (Bearish Macro)")
                    return None

        # Обязательные условия
        if tf_15m['rsi'] > rsi_limit or not tf_15m.get('below_bb_lower'):
            return None
        
        confluence = ConfluenceScore()
        reasoning = []
        warnings = []
        
        current = df_15m.iloc[-1]
        
        # === RSI (0-25) ===
        rsi = tf_15m['rsi']
        if rsi < 15:
            confluence.add_factor('RSI', 25, 25)
            reasoning.append(f"🔥 RSI={rsi:.1f} ЭКСТРЕМУМ")
        # === RSI (0-20) ===
        rsi = tf_15m['rsi']
        if rsi < 15:
            confluence.add_factor('RSI', 20, 20)
            reasoning.append(f"🔥 RSI={rsi:.1f} ЭКСТРЕМУМ")
        elif rsi < 25:
            confluence.add_factor('RSI', 15, 20)
            reasoning.append(f"RSI={rsi:.1f} перепродан")
        else:
            confluence.add_factor('RSI', 5, 20)
        
        # === Bollinger Bands (0-15) ===
        bb_pos = tf_15m['bb_position']
        if bb_pos < -0.1:
            confluence.add_factor('Bollinger Bands', 15, 15)
            reasoning.append("📉 Цена ниже BB Lower")
        elif bb_pos < 0:
            confluence.add_factor('Bollinger Bands', 10, 15)
        
        # === MTF Alignment (0-20) ===
        mtf = self.mtf_analyzer.check_alignment(tf_15m, tf_1h, tf_4h, 'LONG')
        mtf_score = min(mtf['score'] // 5, 20)
        confluence.add_factor('Multi-Timeframe', mtf_score, 20)
        for detail in mtf['details'].values():
            reasoning.append(detail)
        
        # === Support/Resistance (0-15) ===
        sr_levels = self.sr_detector.find_levels(df_15m)
        nearest_support = self.sr_detector.find_nearest(sr_levels, current['close'], 'below')
        
        # Dynamic ATR Tolerance for Levels
        atr_val = float(self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1])
        level_tolerance = atr_val * 0.3
        
        if nearest_support:
            dist = abs(current['close'] - nearest_support.price)
            if dist < level_tolerance:
                confluence.add_factor('Support/Resistance', 15, 15)
                reasoning.append(f"🎯 У сильной поддержки ${nearest_support.price:,.2f}")
            elif dist < level_tolerance * 2:
                confluence.add_factor('Support/Resistance', 10, 15)
                reasoning.append(f"Близко к поддержке ${nearest_support.price:,.2f}")
        
        # === Volume (0-10) ===
        df_15m_copy = df_15m.copy()
        df_15m_copy['vol_ma'] = df_15m_copy['volume'].rolling(20).mean()
        vol_ratio = current['volume'] / df_15m_copy['vol_ma'].iloc[-1] if df_15m_copy['vol_ma'].iloc[-1] > 0 else 1
        
        if vol_ratio > 2.0:
            confluence.add_factor('Volume', 10, 10)
            reasoning.append(f"📊 Всплеск объёма ({vol_ratio:.1f}x)")
        elif vol_ratio > 1.5:
            confluence.add_factor('Volume', 7, 10)
        
        # === MACD (0-10) ===
        df_15m_copy['macd'], df_15m_copy['macd_signal'], df_15m_copy['macd_hist'] = self.ind.macd(df_15m_copy['close'])
        macd_turning = df_15m_copy['macd_hist'].iloc[-1] > df_15m_copy['macd_hist'].iloc[-2]
        
        if macd_turning:
            confluence.add_factor('MACD', 10, 10)
            reasoning.append("📈 MACD разворачивается вверх")
        
        # === Funding Rate (0-10) ===
        funding_interpretation = None
        if funding_rate is not None:
            if funding_rate < -0.001:
                confluence.add_factor('Funding Rate', 10, 10)
                reasoning.append(f"🔥 Экстремальный SHORT BIAS ({funding_rate*100:.3f}%)")
                funding_interpretation = "EXTREME_SHORT_BIAS"
            elif funding_rate < -0.0005:
                confluence.add_factor('Funding Rate', 7, 10)
                funding_interpretation = "HIGH_SHORT_BIAS"
        
        # === Order Book (0-5) ===
        if orderbook_imbalance is not None:
            if orderbook_imbalance > 1.5:
                confluence.add_factor('Order Book', 5, 5)
                reasoning.append(f"📗 Перевес покупателей {orderbook_imbalance:.2f}x")
            elif orderbook_imbalance > 1.2:
                confluence.add_factor('Order Book', 3, 5)
        
        # === Extra Oscillators (0-10) ===
        stoch_k, _ = self.ind.stochastic_rsi(df_15m['close'])
        williams = self.ind.williams_r(df_15m['high'], df_15m['low'], df_15m['close'])
        extra_score = 0
        if stoch_k.iloc[-1] < 20: extra_score += 5
        if williams.iloc[-1] < -80: extra_score += 5
        confluence.add_factor('Extra Oscillators', extra_score, 10)
        
        # === Fibonacci Entry Zone (0-10) ===
        fib_levels = self.ind.fibonacci_levels(df_15m['high'], df_15m['low'])
        fib_score = 0
        price = current['close']
        fib_tolerance = atr_val * 0.4
        
        if abs(price - fib_levels['0.618']) < fib_tolerance:
            fib_score = 10
            reasoning.append(f"🎯 Золотое сечение Фибо 0.618 (${fib_levels['0.618']:.2f})")
        elif abs(price - fib_levels['0.786']) < fib_tolerance:
            fib_score = 8
        elif abs(price - fib_levels['0.5']) < fib_tolerance:
            fib_score = 5
        confluence.add_factor('Fibonacci', fib_score, 10)
        
        # === Supertrend (0-10) ===
        _, st_dir = self.ind.supertrend(df_15m['high'], df_15m['low'], df_15m['close'])
        if st_dir.iloc[-1] == 1:
            confluence.add_factor('Supertrend', 10, 10)
            reasoning.append("📈 Supertrend подтверждает LONG")
        else:
            confluence.add_factor('Supertrend', 0, 10)
            warnings.append("⚠️ Против Supertrend")
        
        # === Проверка минимального score ===
        if confluence.percentage < self.min_confluence:
            return None
        
        # === Entry/SL/TP (Dynamic Phase 5) ===
        entry = float(current['close'])
        atr_val = float(self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1])
        
        # Динамический множитель SL в зависимости от режима
        # В волатильном боковике даем больше "воздуха"
        sl_multiplier = 2.5 if regime == MarketRegime.RANGING_WIDE else 2.0
        stop_loss = entry - (sl_multiplier * atr_val)
        
        if nearest_support:
            sl_sr = nearest_support.price - (0.5 * atr_val)
            stop_loss = max(stop_loss, sl_sr) # Не ставим стоп слишком далеко от S/R
        
        df_15m_copy['bb_upper'], df_15m_copy['bb_middle'], df_15m_copy['bb_lower'] = self.ind.bollinger_bands(df_15m_copy['close'])
        
        # Динамический TP (Фаза 5)
        # 1. Если ADX растет, значит тренд усиливается -> держим до BB Upper
        # 2. Если BB Width большой (высокая волатильность) -> ставим цели более агрессивно
        
        adx_current = tf_15m.get('adx', 0)
        adx_prev = df_15m_copy['adx'].iloc[-2]
        bb_width = tf_15m.get('bb_width', 0)
        
        adx_growing = adx_current > adx_prev
        
        if adx_growing or bb_width > 0.05:
             # Агрессивный выход
             take_profit_1 = float(df_15m_copy['bb_upper'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_upper'].iloc[-1]) * 1.015
        else:
             # Консервативный выход (возврат к среднему)
             take_profit_1 = float(df_15m_copy['bb_middle'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_upper'].iloc[-1])
        
        risk = entry - stop_loss
        reward = take_profit_1 - entry
        
        if risk <= 0 or (reward / risk) < self.min_rr:
            logger.debug(f"{symbol}: LONG RR too low ({reward/risk:.2f})")
            return None
        
        # Warnings
        if regime == MarketRegime.WEAK_TREND_DOWN:
            warnings.append("⚠️ Слабый нисходящий тренд")
        
        probability = self._calc_probability(confluence)
        
        return AdvancedSignal(
            signal_type=SignalType.LONG,
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confluence=confluence,
            probability=probability,
            strength=confluence.get_strength(),
            timeframes_aligned={'15m': True, '1h': mtf['score'] >= 30, '4h': mtf['score'] >= 50},
            support_resistance_nearby=nearest_support,
            market_regime=regime,
            risk_reward_ratio=round(reward / risk, 2),
            position_size_percent=self._calc_position_size(probability),
            funding_rate=funding_rate,
            funding_interpretation=funding_interpretation,
            orderbook_imbalance=orderbook_imbalance,
            timestamp=datetime.now(),
            valid_until=datetime.now() + timedelta(hours=4),
            indicators={
                'rsi_15m': tf_15m['rsi'],
                'rsi_1h': tf_1h.get('rsi', 50),
                'rsi_4h': tf_4h.get('rsi'),
                'bb_position': bb_pos,
                'vol_ratio': vol_ratio,
                'atr_pct': (atr_val / entry) * 100 if entry > 0 else 0,
                'trend_adx': tf_15m.get('adx', 0),
                'funding_rate': funding_rate or 0,
                'hour_of_day': datetime.now().hour,
                'rsi_slope': tf_15m.get('rsi_slope', 0),
                'ema_dist': tf_15m.get('ema_dist', 0),
                'bb_width': tf_15m.get('bb_width', 0),
                'vol_zscore': tf_15m.get('vol_zscore', 0)
            },
            reasoning=reasoning,
            warnings=warnings
        )
    
    def _check_short(
        self, df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
        funding_rate, orderbook_imbalance
    ) -> Optional[AdvancedSignal]:
        """Зеркальная логика для SHORT"""
        
        # Dynamic RSI Thresholds
        adx = tf_15m.get('adx', 0)
        rsi_limit = 75 if adx > 30 else 70

        # === TREND GUARDIAN (Block counter-trend entries) ===
        if tf_1h.get('valid'):
            # If price is above 1H EMA 200 AND trend is strong up, BLOCK SHORT
            is_bullish_macro = tf_1h.get('ema_dist', 0) > 0.5 and tf_1h.get('trend_direction') == 'up'
            
            if is_bullish_macro:
                # Allow only if EXTREME exhaustion (RSI > 85)
                if tf_15m['rsi'] < 85:
                    logger.debug(f"{symbol}: Blocked SHORT by Trend Guardian (Bullish Macro)")
                    return None
        
        confluence = ConfluenceScore()
        reasoning = []
        warnings = []
        
        current = df_15m.iloc[-1]
        
        # RSI
        rsi = tf_15m['rsi']
        if rsi > 85:
            confluence.add_factor('RSI', 25, 25)
            reasoning.append(f"🔥 RSI={rsi:.1f} ЭКСТРЕМУМ")
        elif rsi > 80:
            confluence.add_factor('RSI', 20, 25)
            reasoning.append(f"RSI={rsi:.1f} сильно перекуплен")
        elif rsi > 75:
            confluence.add_factor('RSI', 15, 25)
            reasoning.append(f"RSI={rsi:.1f} перекуплен")
        else:
            confluence.add_factor('RSI', 10, 25)
        
        # BB
        bb_pos = tf_15m['bb_position']
        if bb_pos > 1.1:
            confluence.add_factor('Bollinger Bands', 15, 15)
            reasoning.append("Сильно выше BB Upper")
        elif bb_pos > 1.0:
            confluence.add_factor('Bollinger Bands', 10, 15)
            reasoning.append("Выше BB Upper")
        
        # MTF
        mtf = self.mtf_analyzer.check_alignment(tf_15m, tf_1h, tf_4h, 'SHORT')
        mtf_score = min(mtf['score'] // 4, 25)
        confluence.add_factor('Multi-Timeframe', mtf_score, 25)
        for detail in mtf['details'].values():
            reasoning.append(detail)
        
        # S/R
        sr_levels = self.sr_detector.find_levels(df_15m)
        nearest_support = self.sr_detector.find_nearest(sr_levels, current['close'], 'below')
        
        for level in sr_levels:
            if level.level_type == 'resistance':
                dist = abs(current['close'] - level.price) / current['close']
                if dist < 0.005:
                    confluence.add_factor('Support/Resistance', 15, 15)
                    reasoning.append(f"🎯 У сопротивления ${level.price:,.2f}")
                    break
                elif dist < 0.01:
                    confluence.add_factor('Support/Resistance', 10, 15)
                    break
        
        # Volume
        df_15m_copy = df_15m.copy()
        df_15m_copy['vol_ma'] = df_15m_copy['volume'].rolling(20).mean()
        vol_ratio = current['volume'] / df_15m_copy['vol_ma'].iloc[-1] if df_15m_copy['vol_ma'].iloc[-1] > 0 else 1
        
        # Calculate ADX for DataFrame (Required for Dynamic TP)
        df_15m_copy['adx'] = self.ind.adx(df_15m_copy['high'], df_15m_copy['low'], df_15m_copy['close'])[0]
        
        if vol_ratio > 2.0:
            confluence.add_factor('Volume', 10, 10)
            reasoning.append(f"📊 Объём {vol_ratio:.1f}x")
        elif vol_ratio > 1.5:
            confluence.add_factor('Volume', 7, 10)
        
        # MACD
        df_15m_copy['macd'], _, df_15m_copy['macd_hist'] = self.ind.macd(df_15m_copy['close'])
        if df_15m_copy['macd_hist'].iloc[-1] < df_15m_copy['macd_hist'].iloc[-2]:
            confluence.add_factor('MACD', 8, 10)
            reasoning.append("MACD разворачивается вниз")
        
        # Funding Rate (для SHORT: много лонгов = хорошо)
        funding_interpretation = None
        if funding_rate is not None:
            if funding_rate > 0.001:
                confluence.add_factor('Funding Rate', 10, 10)
                reasoning.append(f"🔥 Funding={funding_rate*100:.3f}% ЭКСТРЕМУМ LONG")
                funding_interpretation = "EXTREME_LONG_BIAS"
            elif funding_rate > 0.0005:
                confluence.add_factor('Funding Rate', 7, 10)
                reasoning.append(f"Funding={funding_rate*100:.3f}% много лонгов")
                funding_interpretation = "HIGH_LONG_BIAS"
            elif funding_rate > 0:
                confluence.add_factor('Funding Rate', 4, 10)
                funding_interpretation = "SLIGHT_LONG_BIAS"
        
        # Order Book (для SHORT: больше продавцов = хорошо)
        if orderbook_imbalance is not None:
            if orderbook_imbalance < 0.67:
                confluence.add_factor('Order Book', 5, 5)
                reasoning.append(f"📕 Стакан: продавцы {1/orderbook_imbalance:.2f}x")
            elif orderbook_imbalance < 0.83:
                confluence.add_factor('Order Book', 3, 5)
        
        # === Extra Oscillators (0-10) ===
        stoch_k, _ = self.ind.stochastic_rsi(df_15m['close'])
        williams = self.ind.williams_r(df_15m['high'], df_15m['low'], df_15m['close'])
        extra_score = 0
        if stoch_k.iloc[-1] > 80: extra_score += 5
        if williams.iloc[-1] > -20: extra_score += 5
        confluence.add_factor('Extra Oscillators', extra_score, 10)

        # === Fibonacci Entry Zone (0-10) ===
        fib_levels = self.ind.fibonacci_levels(df_15m['high'], df_15m['low'])
        fib_score = 0
        price = current['close']
        fib_tolerance = atr_val * 0.4
        
        if abs(price - fib_levels['0.618']) < fib_tolerance:
            fib_score = 10
            reasoning.append(f"🎯 Золотое сечение Фибо 0.618 (${fib_levels['0.618']:.2f})")
        elif abs(price - fib_levels['0.786']) < fib_tolerance:
            fib_score = 8
        elif abs(price - fib_levels['0.5']) < fib_tolerance:
            fib_score = 5
        confluence.add_factor('Fibonacci', fib_score, 10)
        
        # === Supertrend (0-10) ===
        _, st_dir = self.ind.supertrend(df_15m['high'], df_15m['low'], df_15m['close'])
        if st_dir.iloc[-1] == -1:
            confluence.add_factor('Supertrend', 10, 10)
            reasoning.append("📉 Supertrend подтверждает SHORT")
        else:
            confluence.add_factor('Supertrend', 0, 10)
            warnings.append("⚠️ Против Supertrend")
        
        if confluence.percentage < self.min_confluence:
            return None
        
        # === Entry/SL/TP (Dynamic Phase 5) ===
        entry = float(current['close'])
        atr_val = float(self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1])
        
        # Динамический множитель SL
        sl_multiplier = 2.5 if regime == MarketRegime.RANGING_WIDE else 2.0
        stop_loss = entry + (sl_multiplier * atr_val)
        
        # Calculate Bollinger Bands (Moved up for TP calculation)
        df_15m_copy['bb_upper'], df_15m_copy['bb_middle'], df_15m_copy['bb_lower'] = self.ind.bollinger_bands(df_15m_copy['close'])
        
        # Динамический TP (Фаза 5)
        adx_current = tf_15m.get('adx', 0)
        adx_prev = df_15m_copy['adx'].iloc[-2]
        bb_width = tf_15m.get('bb_width', 0)
        
        adx_growing = adx_current > adx_prev
        
        if adx_growing or bb_width > 0.05:
             # Агрессивный выход (до нижней границы)
             take_profit_1 = float(df_15m_copy['bb_lower'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_lower'].iloc[-1]) * 0.985
        else:
             # Консервативный выход (до средней)
             take_profit_1 = float(df_15m_copy['bb_middle'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_lower'].iloc[-1])
             
        risk = stop_loss - entry
        reward = entry - take_profit_1
        
        if risk <= 0 or (reward / risk) < self.min_rr:
            logger.debug(f"{symbol}: SHORT RR too low ({reward/risk:.2f})")
            return None
        
        if regime == MarketRegime.WEAK_TREND_UP:
            warnings.append("⚠️ Слабый восходящий тренд")
        
        probability = self._calc_probability(confluence)
        
        return AdvancedSignal(
            signal_type=SignalType.SHORT,
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confluence=confluence,
            probability=probability,
            strength=confluence.get_strength(),
            timeframes_aligned={'15m': True, '1h': mtf['score'] >= 30, '4h': mtf['score'] >= 50},
            support_resistance_nearby=nearest_support,
            market_regime=regime,
            risk_reward_ratio=round(reward / risk, 2),
            position_size_percent=self._calc_position_size(probability),
            funding_rate=funding_rate,
            funding_interpretation=funding_interpretation,
            orderbook_imbalance=orderbook_imbalance,
            timestamp=datetime.now(),
            valid_until=datetime.now() + timedelta(hours=4),
            indicators={
                'rsi_15m': tf_15m['rsi'],
                'rsi_1h': tf_1h.get('rsi', 50),
                'rsi_4h': tf_4h.get('rsi', 50),
                'bb_position': bb_pos,
                'vol_ratio': vol_ratio,
                'atr_pct': (atr_val / entry) * 100 if entry > 0 else 0,
                'trend_adx': tf_15m.get('adx', 0),
                'funding_rate': funding_rate or 0,
                'hour_of_day': datetime.now().hour,
                'rsi_slope': tf_15m.get('rsi_slope', 0),
                'ema_dist': tf_15m.get('ema_dist', 0),
                'bb_width': tf_15m.get('bb_width', 0),
                'vol_zscore': tf_15m.get('vol_zscore', 0)
            },
            reasoning=reasoning,
            warnings=warnings
        )
    
    def _calc_probability(self, confluence: ConfluenceScore) -> int:
        score = confluence.percentage
        if score >= 95:
            return min(92, int(85 + (score - 95) * 0.7))
        elif score >= 85:
            return int(85 + (score - 85) * 0.5)
        elif score >= 75:
            return int(80 + (score - 75) * 0.5)
        elif score >= 70:
            return int(75 + (score - 70) * 1.0)
        else:
            return int(60 + score * 0.2)
    
    def _calc_position_size(self, probability: int) -> float:
        if probability >= 90:
            return 2.0
        elif probability >= 85:
            return 1.5
        elif probability >= 80:
            return 1.0
        else:
            return 0.5


# ============================================================
# SIGNAL FORMATTER
# ============================================================

def format_signal(signal: AdvancedSignal, balance: float = 100) -> str:
    """Форматирует сигнал для отображения"""
    
    emoji = '🟢' if signal.signal_type == SignalType.LONG else '🔴'
    direction = 'LONG' if signal.signal_type == SignalType.LONG else 'SHORT'
    
    if signal.signal_type == SignalType.LONG:
        sl_pct = (signal.entry_price - signal.stop_loss) / signal.entry_price * 100
        tp1_pct = (signal.take_profit_1 - signal.entry_price) / signal.entry_price * 100
        tp2_pct = (signal.take_profit_2 - signal.entry_price) / signal.entry_price * 100
    else:
        sl_pct = (signal.stop_loss - signal.entry_price) / signal.entry_price * 100
        tp1_pct = (signal.entry_price - signal.take_profit_1) / signal.entry_price * 100
        tp2_pct = (signal.entry_price - signal.take_profit_2) / signal.entry_price * 100
    
    risk_amount = balance * (signal.position_size_percent / 100)
    position_usd = risk_amount / (sl_pct / 100) if sl_pct > 0 else 0
    
    output = f"""
{'═'*65}
{emoji} {signal.symbol} │ {direction} │ {signal.strength.value} {emoji}
{'═'*65}

📊 CONFLUENCE: {signal.confluence.percentage:.0f}/100
{signal.confluence.get_breakdown()}

🎯 ВЕРОЯТНОСТЬ: {signal.probability}%

{'─'*65}
💰 ВХОД:     ${signal.entry_price:,.4f}
🎯 ЦЕЛЬ 1:   ${signal.take_profit_1:,.4f}  (+{tp1_pct:.2f}%)
🎯 ЦЕЛЬ 2:   ${signal.take_profit_2:,.4f}  (+{tp2_pct:.2f}%)
🛑 СТОП:     ${signal.stop_loss:,.4f}  (-{sl_pct:.2f}%)
⚖️ R:R:      1:{signal.risk_reward_ratio}

{'─'*65}
✅ ПРИЧИНЫ:
"""
    
    for reason in signal.reasoning:
        output += f"   • {reason}\n"
    
    if signal.funding_rate is not None:
        output += f"\n📈 BYBIT DATA:\n"
        output += f"   Funding Rate: {signal.funding_rate*100:.4f}% ({signal.funding_interpretation})\n"
        if signal.orderbook_imbalance:
            output += f"   Order Book: {signal.orderbook_imbalance:.2f}x\n"
    
    if signal.warnings:
        output += f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ:\n"
        for w in signal.warnings:
            output += f"   {w}\n"
    
    output += f"""
{'─'*65}
📐 ТАЙМФРЕЙМЫ: 15m {'✅' if signal.timeframes_aligned['15m'] else '❌'} │ 1h {'✅' if signal.timeframes_aligned['1h'] else '❌'} │ 4h {'✅' if signal.timeframes_aligned['4h'] else '❌'}
📈 РЕЖИМ: {signal.market_regime.value}

{'─'*65}
💼 ДЛЯ ${balance:.0f} (риск {signal.position_size_percent}%):
   Размер: ${position_usd:.2f}
   Риск: ${risk_amount:.2f}

⏰ Действителен до: {signal.valid_until.strftime('%H:%M')}
{'═'*65}
"""
    
    return output


# ============================================================
# TEST
# ============================================================

def generate_test_data(periods: int = 500) -> pd.DataFrame:
    np.random.seed(42)
    base = 50000
    noise = np.random.randn(periods) * 0.01
    mean_rev = np.zeros(periods)
    for i in range(1, periods):
        mean_rev[i] = mean_rev[i-1] * 0.95 + noise[i]
    prices = base * (1 + mean_rev)
    
    return pd.DataFrame({
        'time': pd.date_range(start='2024-01-01', periods=periods, freq='15min'),
        'open': prices,
        'high': prices * (1 + np.abs(np.random.randn(periods)) * 0.003),
        'low': prices * (1 - np.abs(np.random.randn(periods)) * 0.003),
        'close': prices * (1 + np.random.randn(periods) * 0.002),
        'volume': np.random.randint(100, 1000, periods) * 1000
    })


# ============================================================
# 🔥 ULTIMATE TRADING ENGINE (10/10!)
# ============================================================

class UltimateTradingEngine:
    """
    Ultimate Trading Engine v3.0
    
    Объединяет:
    - Продвинутый Mean Reversion движок
    - Momentum стратегию
    - Фильтр новостей (FinBERT)
    - Circuit Breaker & Kelly Sizing
    """
    def __init__(self, cryptopanic_key: str = None, total_capital: float = 10000, min_confluence: int = 75):
        self.mr_engine = AdvancedMeanReversionEngine(min_confluence=min_confluence)
        # Use torch check for FinBERT
        use_finbert = False
        try:
             import torch
             use_finbert = torch.cuda.is_available()
        except: pass
        
        self.news_engine = NewsEngine(cryptopanic_key or os.getenv('CRYPTOPANIC_KEY'), use_finbert=use_finbert)
        self.risk_manager = RiskManager(total_capital=total_capital)
        self.performance_tracker = PerformanceTracker()
        
    def analyze(self, df_15m, df_1h, df_4h, symbol, funding_rate=None, orderbook_imbalance=None) -> Optional[AdvancedSignal]:
        # 1. Circuit Breaker & Limits
        if self.risk_manager.check_circuit_breaker():
            logger.warning(f"🚨 {symbol}: Circuit Breaker ACTIVE - Trading Paused")
            return None
        
        # 2. News Sentiment Filter
        news_bonus = 0
        if self.news_engine.api_key:
            currency = symbol.replace("USDT", "").replace("USDC", "")[:3]
            news = self.news_engine.get_market_sentiment(currency)
            
            if news.get('critical_events'):
                logger.warning(f"🛑 {symbol}: Critical news detected!")
                return None
                
            if news.get('score', 0) < -0.5:
                return None
            
            if abs(news.get('score', 0)) > 0.3:
                news_bonus = 15

        # 3. Market Regime & Strategy Routing
        ind = TechnicalIndicators()
        adx, _, _ = ind.adx(df_4h['high'], df_4h['low'], df_4h['close'])
        current_adx = adx.iloc[-1]
        
        # Bollinger Width for Breakout detection
        bb_upper, _, bb_lower = ind.bollinger_bands(df_1h['close'])
        bb_width = (bb_upper - bb_lower) / bb_upper
        
        if current_adx > 30:
            # TRENDING: Use Momentum
            signal = self._analyze_momentum(df_15m, symbol)
            strategy_name = "Momentum (Trend)"
        elif bb_width.iloc[-1] < 0.02:
            # SQUEEZE: Use Breakout
            signal = self._analyze_breakout(df_15m, symbol)
            strategy_name = "Breakout Hunter"
        else:
            # RANGING: Use Mean Reversion
            signal = self.mr_engine.analyze(df_15m, df_1h, df_4h, symbol, funding_rate, orderbook_imbalance)
            strategy_name = "Mean Reversion"
            
        if not signal: return None
        
        # 4. Integrate News Bonus
        if news_bonus > 0:
            signal.confluence.add_factor("News Alpha", news_bonus, 15)
            signal.reasoning.append(f"📰 News Alpha Alignment (+{news_bonus})")

        # 5. Kelly position sizing
        stats = self.performance_tracker.get_stats()
        if stats.get('total_trades', 0) >= 10:
            win_rate = stats['win_rate']
            p_ratio = stats['avg_win'] / stats['avg_loss'] if stats['avg_loss'] > 0 else 2.0
            k_pct = max(0.01, min(((win_rate * p_ratio - (1 - win_rate)) / p_ratio) * 0.25, 0.03))
            signal.position_size_percent = k_pct * 100
        
        return signal

    def _analyze_momentum(self, df, symbol) -> Optional[AdvancedSignal]:
        """EMA Momentum Cross + ADX Confirmation"""
        ind = TechnicalIndicators()
        ema9 = ind.ema(df['close'], 9)
        ema21 = ind.ema(df['close'], 21)
        adx, plus_di, minus_di = ind.adx(df['high'], df['low'], df['close'])
        
        curr = df.iloc[-1]
        if ema9.iloc[-1] > ema21.iloc[-1] and plus_di.iloc[-1] > minus_di.iloc[-1] and adx.iloc[-1] > 25:
            conf = ConfluenceScore(max_possible=135)
            conf.add_factor("Momentum Trend", 40, 40)
            conf.add_factor("ADX Power", 30, 30)
            entry = float(curr['close'])
            atr = ind.atr(df['high'], df['low'], df['close']).iloc[-1]
            return AdvancedSignal(
                signal_type=SignalType.LONG, symbol=symbol, entry_price=entry,
                stop_loss=entry - 2.5*atr, take_profit_1=entry + 3.5*atr,
                take_profit_2=entry + 6*atr, confluence=conf, probability=78,
                market_regime=MarketRegime.STRONG_TREND_UP, reasoning=["Momentum: EMA Cross + ADX > 25"]
            )
        return None

    def _analyze_breakout(self, df, symbol) -> Optional[AdvancedSignal]:
        """Volatility Squeeze Breakout"""
        ind = TechnicalIndicators()
        upper, mid, lower = ind.bollinger_bands(df['close'])
        curr = df.iloc[-1]
        
        if curr['close'] > upper.iloc[-1] and curr['volume'] > df['volume'].rolling(20).mean().iloc[-1] * 1.5:
            conf = ConfluenceScore(max_possible=135)
            conf.add_factor("BB Breakout", 50, 50)
            conf.add_factor("Volume Spike", 30, 30)
            entry = float(curr['close'])
            return AdvancedSignal(
                signal_type=SignalType.LONG, symbol=symbol, entry_price=entry,
                stop_loss=mid.iloc[-1], take_profit_1=entry + (entry - mid.iloc[-1]) * 2,
                take_profit_2=entry + (entry - mid.iloc[-1]) * 4, confluence=conf,
                probability=72, market_regime=MarketRegime.VOLATILE_BREAKOUT,
                reasoning=["Breakout: Price closed above BB Upper with Volume"]
            )
        return None

    def record_trade(self, trade: Trade):
        self.performance_tracker.add_trade(trade)
        self.risk_manager.daily_pnl += trade.pnl
        self.risk_manager.total_capital += trade.pnl


if __name__ == "__main__":
    print("Testing Advanced Mean Reversion Engine (Bybit Edition)...")
    
    engine = AdvancedMeanReversionEngine(min_confluence=70)
    
    df_15m = generate_test_data(500)
    df_1h = df_15m.iloc[::4].reset_index(drop=True)
    df_4h = df_15m.iloc[::16].reset_index(drop=True)
    
    signal = engine.analyze(
        df_15m, df_1h, df_4h, 'BTCUSDT',
        funding_rate=-0.0008,  # Симулируем экстремальный short bias
        orderbook_imbalance=1.6
    )
    
    if signal:
        print(format_signal(signal, balance=500))
    else:
        print("Нет сигналов с достаточным confluence score")
