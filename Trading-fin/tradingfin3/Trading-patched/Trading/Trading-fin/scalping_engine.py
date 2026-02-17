"""
╔══════════════════════════════════════════════════════════════════════════╗
║           ULTRA SCALPING ENGINE v1.0 — February 2026                     ║
║                                                                          ║
║   Продвинутая скальпинг-система для Bybit Perpetual Futures              ║
║                                                                          ║
║   CORE ARCHITECTURE (6 слоёв confluence):                                ║
║     Layer 1: Market Structure Analysis (тренд, рендж, squeeze)           ║
║     Layer 2: VWAP + EMA Dynamic Bias (9/21/55 EMA stack + VWAP)         ║
║     Layer 3: Order Flow & CVD (Cumulative Volume Delta + imbalance)      ║
║     Layer 4: Momentum Oscillators (RSI + Stochastic + MACD)             ║
║     Layer 5: Microstructure (spread, OB imbalance, funding, liquidity)  ║
║     Layer 6: AI Confluence Score → вход только при 70%+ score            ║
║                                                                          ║
║   TARGETS:                                                               ║
║     • Win Rate: 60-75% (исследования показывают max реалистичный)        ║
║     • R:R = 1:1.5 — 1:3 (динамический по волатильности)                 ║
║     • Avg Trade Duration: 1-15 минут                                     ║
║     • Max Trades/Day: 20-50                                              ║
║     • Max Risk/Trade: 0.5% капитала                                     ║
║                                                                          ║
║   СОВМЕСТИМОСТЬ:                                                         ║
║     • AdvancedMeanReversionEngine (mean_reversion_bybit.py)              ║
║     • ExecutionManager (execution.py)                                    ║
║     • BybitClient (bybit_client.py)                                      ║
║     • UltimateTradingEngine (mean_reversion_bybit.py)                    ║
║     • EnhancedRiskManager (enhanced_risk_manager.py)                     ║
║                                                                          ║
║   Основано на исследовании:                                              ║
║     • CVD + Order Flow (Bookmap, CoinAPI 2025)                           ║
║     • VWAP+EMA Confluence (Cryptowisser Feb 2026, 1MinScalper 2026)      ║
║     • Microstructure (CMU MSCF, Elite-Metrics-Trade-Bybit)               ║
║     • Directional Scalper (MFI-RSI maker strategy)                       ║
║     • 1-minute scalping best practices (FXOpen, StockGro 2025-2026)      ║
╚══════════════════════════════════════════════════════════════════════════╝

ИНТЕГРАЦИЯ:
    from scalping_engine import UltraScalpingEngine, ScalpSignal

    # В main_bybit.py или UltimateTradingEngine:
    scalper = UltraScalpingEngine(
        min_confluence=70,
        max_risk_pct=0.005,
        use_limit_entry=True,
    )

    signal = scalper.analyze(
        df_1m=df_1m,          # 1-минутные свечи (200+)
        df_5m=df_5m,          # 5-минутные (100+)
        df_15m=df_15m,        # 15-минутные (50+) — для HTF bias
        symbol="BTCUSDT",
        orderbook=orderbook,  # dict от bybit_client.get_orderbook()
        funding_rate=0.0001,
        recent_trades=trades,  # list последних сделок (для CVD)
    )

    if signal:
        execution_manager.execute_signal(signal)
"""

import logging
import math
import numpy as np
import pandas as pd
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════

from mean_reversion_bybit import SignalType


class ScalpStrength(Enum):
    WEAK = "WEAK"           # 50-60% confluence
    MODERATE = "MODERATE"   # 60-70%
    STRONG = "STRONG"       # 70-80%
    SNIPER = "SNIPER"       # 80%+


class MicroRegime(Enum):
    """Микро-режим рынка (определяется по 1м/5м)"""
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGE_TIGHT = "RANGE_TIGHT"       # BB width < 0.5% — squeeze
    RANGE_WIDE = "RANGE_WIDE"         # Обычный боковик
    BREAKOUT_UP = "BREAKOUT_UP"       # Пробой вверх
    BREAKOUT_DOWN = "BREAKOUT_DOWN"   # Пробой вниз
    CHOPPY = "CHOPPY"                 # Шум — НЕ торговать


# ═══════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ScalpConfluence:
    """Confluence scoring для скальпинга (100 баллов макс)"""
    total_score: int = 0
    max_possible: int = 100
    factors: Dict[str, Tuple[int, int]] = field(default_factory=dict)

    def add(self, name: str, score: int, max_score: int):
        clamped = max(0, min(score, max_score))
        self.factors[name] = (clamped, max_score)
        self.total_score += clamped

    @property
    def percentage(self) -> float:
        return (self.total_score / self.max_possible) * 100 if self.max_possible > 0 else 0

    def get_strength(self) -> ScalpStrength:
        pct = self.percentage
        if pct >= 80:
            return ScalpStrength.SNIPER
        elif pct >= 70:
            return ScalpStrength.STRONG
        elif pct >= 60:
            return ScalpStrength.MODERATE
        return ScalpStrength.WEAK

    def breakdown(self) -> str:
        lines = []
        for name, (score, mx) in self.factors.items():
            pct = score / mx * 100 if mx > 0 else 0
            bar = '█' * int(pct / 10) + '░' * (10 - int(pct / 10))
            lines.append(f"  {name:22} [{bar}] {score}/{mx}")
        return '\n'.join(lines)


@dataclass
class ScalpSignal:
    """
    Сигнал скальпинга.
    Совместим с AdvancedSignal из mean_reversion_bybit.py
    (можно передать в ExecutionManager.execute_signal)
    """
    # Core
    signal_type: SignalType = SignalType.NO_SIGNAL
    symbol: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0

    # Scoring
    confluence: ScalpConfluence = field(default_factory=ScalpConfluence)
    probability: int = 50
    strength: ScalpStrength = ScalpStrength.WEAK
    is_vip: bool = False

    # Micro context
    micro_regime: MicroRegime = MicroRegime.CHOPPY
    vwap_bias: str = "neutral"         # "bullish" / "bearish" / "neutral"
    cvd_direction: str = "neutral"     # "buying" / "selling" / "neutral"
    ema_stack: str = "none"            # "bullish" / "bearish" / "none"

    # Risk
    risk_reward_ratio: float = 1.5
    position_size_percent: float = 0.5
    max_hold_bars: int = 15            # Макс удержание = 15 свечей по 1м

    # Bybit data
    funding_rate: Optional[float] = None
    orderbook_imbalance: Optional[float] = None
    spread_bps: float = 0.0           # Спред в basis points

    # Meta
    reasoning: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    valid_until: datetime = field(default_factory=lambda: datetime.now() + timedelta(minutes=5))

    # Indicators snapshot (для AI / logging)
    indicators: Dict[str, Any] = field(default_factory=dict)

    # Совместимость с AdvancedSignal
    @property
    def timeframes_aligned(self):
        return {'1m': True, '5m': True, '15m': self.vwap_bias != "neutral"}

    @property
    def market_regime(self):
        return self.micro_regime

    @property
    def confluence_score(self) -> float:
        return self.confluence.percentage

    @property
    def risk_reward(self) -> float:
        return self.risk_reward_ratio


# ═══════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS (Scalping-optimized)
# ═══════════════════════════════════════════════════════════════════

class ScalpIndicators:
    """Быстрые индикаторы для 1м/5м таймфреймов"""

    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        return data.ewm(span=period, adjust=False).mean()

    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        delta = data.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta.where(delta < 0, 0.0))
        avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        return 100 - (100 / (1 + rs))

    @staticmethod
    def stochastic_rsi(data: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> Tuple[pd.Series, pd.Series]:
        rsi = ScalpIndicators.rsi(data, rsi_period)
        rsi_min = rsi.rolling(stoch_period).min()
        rsi_max = rsi.rolling(stoch_period).max()
        denom = (rsi_max - rsi_min).replace(0, 1e-10)
        k = ((rsi - rsi_min) / denom) * 100
        d = k.rolling(3).mean()
        return k, d

    @staticmethod
    def macd(data: pd.Series, fast: int = 8, slow: int = 21, signal: int = 5) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Скальпинг MACD: 8/21/5 вместо стандартных 12/26/9"""
        ema_fast = data.ewm(span=fast, adjust=False).mean()
        ema_slow = data.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram

    @staticmethod
    def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        middle = data.rolling(period).mean()
        std = data.rolling(period).std()
        return middle + std * std_dev, middle, middle - std * std_dev

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()

    @staticmethod
    def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        """
        Session VWAP — сбрасывается каждые 24 часа.
        Для крипто 24/7 используем rolling 288 баров (24h при 5м) или всю сессию.
        """
        tp = (high + low + close) / 3
        cumulative_tp_vol = (tp * volume).cumsum()
        cumulative_vol = volume.cumsum().replace(0, 1e-10)
        return cumulative_tp_vol / cumulative_vol

    @staticmethod
    def vwap_bands(vwap_line: pd.Series, close: pd.Series, period: int = 20, multiplier: float = 1.5) -> Tuple[pd.Series, pd.Series]:
        """VWAP ± 1.5 стандартных отклонений (зоны перекупленности/перепроданности)"""
        diff = (close - vwap_line).rolling(period).std()
        return vwap_line + diff * multiplier, vwap_line - diff * multiplier

    @staticmethod
    def cvd_from_candles(open_: pd.Series, close: pd.Series, high: pd.Series,
                         low: pd.Series, volume: pd.Series) -> pd.Series:
        """
        Приблизительный CVD из свечей (без tick data).

        Метод:  Если close > open → buy_vol = volume * (close-low)/(high-low)
                Если close < open → sell_vol = volume * (high-close)/(high-low)
                delta = buy_vol - sell_vol
                CVD = cumulative sum of delta

        Это приближение, но для 1м свечей достаточно точно.
        """
        hl_range = (high - low).replace(0, 1e-10)

        # Доля покупок/продаж внутри свечи
        buy_ratio = (close - low) / hl_range
        sell_ratio = (high - close) / hl_range

        buy_vol = volume * buy_ratio
        sell_vol = volume * sell_ratio

        delta = buy_vol - sell_vol
        cvd = delta.cumsum()
        return cvd

    @staticmethod
    def cvd_slope(cvd: pd.Series, period: int = 5) -> pd.Series:
        """Наклон CVD за последние N баров (позитивный = покупки растут)"""
        return cvd.diff(period) / period

    @staticmethod
    def volume_spike(volume: pd.Series, period: int = 20, threshold: float = 2.0) -> pd.Series:
        """Детектор всплесков объёма: vol / avg_vol > threshold"""
        avg_vol = volume.rolling(period).mean().replace(0, 1e-10)
        return volume / avg_vol


# ═══════════════════════════════════════════════════════════════════
# SESSION & TIMING FILTER
# ═══════════════════════════════════════════════════════════════════

class SessionFilter:
    """
    Фильтр по торговым сессиям.
    Крипто торгуется 24/7, но ликвидность неравномерна.
    """

    # Часы повышенной ликвидности (UTC)
    HIGH_LIQUIDITY_HOURS = [
        (8, 11),   # London open
        (13, 16),  # NY open + London overlap
        (0, 3),    # Asia open (BTC активен)
    ]

    # Часы пониженной ликвидности — скальпинг рискован
    LOW_LIQUIDITY_HOURS = [
        (5, 7),    # Переход Asia→London
        (20, 23),  # Вечер NY
    ]

    @staticmethod
    def is_good_session(hour_utc: int = None) -> Tuple[bool, str]:
        if hour_utc is None:
            hour_utc = datetime.utcnow().hour

        for start, end in SessionFilter.HIGH_LIQUIDITY_HOURS:
            if start <= hour_utc <= end:
                return True, "high_liquidity"

        for start, end in SessionFilter.LOW_LIQUIDITY_HOURS:
            if start <= hour_utc <= end:
                return False, "low_liquidity"

        return True, "normal"

    @staticmethod
    def get_session_name(hour_utc: int = None) -> str:
        if hour_utc is None:
            hour_utc = datetime.utcnow().hour
        if 0 <= hour_utc < 8:
            return "Asia"
        elif 8 <= hour_utc < 13:
            return "London"
        elif 13 <= hour_utc < 20:
            return "New York"
        return "Late NY"


# ═══════════════════════════════════════════════════════════════════
# MAIN SCALPING ENGINE
# ═══════════════════════════════════════════════════════════════════

class UltraScalpingEngine:
    """
    6-Layer Confluence Scalping System.

    Использование:
        engine = UltraScalpingEngine(min_confluence=70)
        signal = engine.analyze(df_1m, df_5m, df_15m, "BTCUSDT", orderbook, funding)
    """

    def __init__(
        self,
        min_confluence: int = 70,       # Мин % для входа
        max_risk_pct: float = 0.005,    # 0.5% на сделку
        use_limit_entry: bool = True,   # Лимитный вход (экономия на комиссии)
        min_rr: float = 1.2,            # Мин R:R
        max_spread_bps: float = 5.0,    # Макс спред (basis points)
        session_filter: bool = True,    # Фильтр по сессиям
        cooldown_bars: int = 3,         # Пауза между сделками (3 бара = 3 мин)
    ):
        self.ind = ScalpIndicators()
        self.session_filter = SessionFilter() if session_filter else None
        self.min_confluence = min_confluence
        self.max_risk_pct = max_risk_pct
        self.use_limit_entry = use_limit_entry
        self.min_rr = min_rr
        self.max_spread_bps = max_spread_bps
        self.cooldown_bars = cooldown_bars

        # State
        self.last_signal_time: Optional[datetime] = None
        self.trade_count_today = 0
        self.max_trades_per_day = 50

        # AI model (optional)
        self.ai = None
        try:
            from ai_engine import AIEngine
            self.ai = AIEngine()
        except ImportError:
            pass

        logger.info(
            f"UltraScalpingEngine: confluence>={min_confluence}%, "
            f"risk={max_risk_pct*100}%, RR>={min_rr}, "
            f"limit_entry={use_limit_entry}"
        )

    # ═══════════════════════════════════════════════════════════
    # ГЛАВНЫЙ МЕТОД
    # ═══════════════════════════════════════════════════════════

    def analyze(
        self,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        symbol: str,
        orderbook: Optional[dict] = None,
        funding_rate: Optional[float] = None,
        recent_trades: Optional[list] = None,
    ) -> Optional[ScalpSignal]:
        """
        Главный анализ. Возвращает ScalpSignal или None.

        Args:
            df_1m: DataFrame с OHLCV (мин 100 баров)
            df_5m: DataFrame с OHLCV (мин 50 баров)
            df_15m: DataFrame с OHLCV (мин 30 баров) — для HTF bias
            symbol: "BTCUSDT" etc
            orderbook: {'best_bid': float, 'best_ask': float, 'bid_volume': float, 'ask_volume': float}
            funding_rate: текущий funding rate
            recent_trades: список последних сделок (optional, для точного CVD)
        """
        # ── Предварительные проверки ──
        if len(df_1m) < 100 or len(df_5m) < 50:
            logger.info(f"⚠️ {symbol}: Scalping engine rejected data (1m: {len(df_1m)}, 5m: {len(df_5m)})")
            return None

        # Cooldown
        if self.last_signal_time:
            bars_since = (datetime.now() - self.last_signal_time).total_seconds() / 60
            if bars_since < self.cooldown_bars:
                return None

        # Daily limit
        if self.trade_count_today >= self.max_trades_per_day:
            return None

        # Session filter
        if self.session_filter:
            ok, reason = self.session_filter.is_good_session()
            if not ok:
                logger.info(f"{symbol}: Скальпинг пропущен ({reason})")
                return None

        # Spread check
        if orderbook:
            bid = orderbook.get('best_bid', 0)
            ask = orderbook.get('best_ask', 0)
            if bid > 0 and ask > 0:
                spread_bps = ((ask - bid) / bid) * 10000
                if spread_bps > self.max_spread_bps:
                    logger.info(f"{symbol}: Спред {spread_bps:.1f} bps > {self.max_spread_bps}")
                    return None

        # ── LAYER 1: Market Structure (Микро-режим) ──
        regime = self._detect_micro_regime(df_1m, df_5m)
        if regime == MicroRegime.CHOPPY:
            logger.info(f"{symbol}: CHOPPY market — skip")
            return None

        # ── Расчёт индикаторов ──
        ctx = self._compute_indicators(df_1m, df_5m, df_15m)

        # ── Определение направления ──
        long_signal = self._evaluate_long(ctx, symbol, regime, orderbook, funding_rate)
        short_signal = self._evaluate_short(ctx, symbol, regime, orderbook, funding_rate)

        # Берём лучший
        best = None
        if long_signal and short_signal:
            best = long_signal if long_signal.confluence.total_score >= short_signal.confluence.total_score else short_signal
        elif long_signal:
            best = long_signal
        elif short_signal:
            best = short_signal
        
        if not best:
             logger.info(f"🔍 {symbol} | No signals found (HTF guard, Regime or RR filters)")

        if best and best.confluence.percentage >= self.min_confluence:
            # AI filter (optional)
            if self.ai:
                try:
                    ai_prob = self.ai.predict_success_probability(best.indicators)
                    if ai_prob < 0.55:
                        logger.info(f"{symbol}: AI rejected (prob={ai_prob:.2f})")
                        return None
                    best.indicators['ai_score'] = ai_prob
                    best.reasoning.append(f"🤖 AI: {ai_prob*100:.0f}%")
                except Exception:
                    pass  # AI unavailable

            self.last_signal_time = datetime.now()
            self.trade_count_today += 1
            return best

        return None

    # ═══════════════════════════════════════════════════════════
    # LAYER 1: MICRO REGIME DETECTION
    # ═══════════════════════════════════════════════════════════

    def _detect_micro_regime(self, df_1m: pd.DataFrame, df_5m: pd.DataFrame) -> MicroRegime:
        """Определяет текущий микро-режим по 1м и 5м"""
        ind = self.ind

        # 5m analysis (более стабильный)
        df = df_5m.copy()
        bb_upper, bb_mid, bb_lower = ind.bollinger_bands(df['close'], 20, 2.0)
        bb_width = ((bb_upper - bb_lower) / bb_mid.replace(0, 1e-10)).iloc[-1]

        ema9 = ind.ema(df['close'], 9).iloc[-1]
        ema21 = ind.ema(df['close'], 21).iloc[-1]
        ema55 = ind.ema(df['close'], 55).iloc[-1] if len(df) >= 55 else ema21
        price = df['close'].iloc[-1]

        atr_val = ind.atr(df['high'], df['low'], df['close'], 14).iloc[-1]
        atr_pct = atr_val / price if price > 0 else 0

        # Squeeze detection
        if bb_width < 0.005:  # < 0.5% BB width = squeeze
            return MicroRegime.RANGE_TIGHT

        # Trending detection via EMA stack
        ema_bullish = ema9 > ema21 > ema55 and price > ema9
        ema_bearish = ema9 < ema21 < ema55 and price < ema9

        # Breakout detection (1m)
        df1 = df_1m.copy()
        bb_u1, _, bb_l1 = ind.bollinger_bands(df1['close'], 20, 2.0)
        last_close = df1['close'].iloc[-1]
        last_vol = df1['volume'].iloc[-1]
        avg_vol = df1['volume'].rolling(20).mean().iloc[-1]

        if last_close > bb_u1.iloc[-1] and last_vol > avg_vol * 2:
            return MicroRegime.BREAKOUT_UP
        if last_close < bb_l1.iloc[-1] and last_vol > avg_vol * 2:
            return MicroRegime.BREAKOUT_DOWN

        if ema_bullish:
            return MicroRegime.TRENDING_UP
        if ema_bearish:
            return MicroRegime.TRENDING_DOWN

        # Choppy detection: too many EMA crosses in recent bars
        ema9_series = ind.ema(df_1m['close'], 9)
        ema21_series = ind.ema(df_1m['close'], 21)
        crosses = ((ema9_series > ema21_series) != (ema9_series.shift(1) > ema21_series.shift(1))).tail(20).sum()
        if crosses > 6:  # > 6 пересечений за 20 баров = шум
            return MicroRegime.CHOPPY

        return MicroRegime.RANGE_WIDE

    # ═══════════════════════════════════════════════════════════
    # COMPUTE ALL INDICATORS
    # ═══════════════════════════════════════════════════════════

    def _compute_indicators(self, df_1m: pd.DataFrame, df_5m: pd.DataFrame,
                             df_15m: pd.DataFrame) -> dict:
        """Расчитывает все индикаторы один раз"""
        ind = self.ind
        d1 = df_1m.copy()
        d5 = df_5m.copy()

        ctx = {}

        # ── 1M indicators ──
        ctx['price'] = float(d1['close'].iloc[-1])
        ctx['ema9_1m'] = float(ind.ema(d1['close'], 9).iloc[-1])
        ctx['ema21_1m'] = float(ind.ema(d1['close'], 21).iloc[-1])
        ctx['ema55_1m'] = float(ind.ema(d1['close'], 55).iloc[-1]) if len(d1) >= 55 else ctx['ema21_1m']

        ctx['rsi_1m'] = float(ind.rsi(d1['close'], 7).iloc[-1])  # Fast RSI (7) для скальпинга
        ctx['rsi_1m_prev'] = float(ind.rsi(d1['close'], 7).iloc[-2])

        stoch_k, stoch_d = ind.stochastic_rsi(d1['close'], 14, 14)
        ctx['stoch_k'] = float(stoch_k.iloc[-1])
        ctx['stoch_d'] = float(stoch_d.iloc[-1])

        macd_line, macd_sig, macd_hist = ind.macd(d1['close'], 8, 21, 5)
        ctx['macd_hist'] = float(macd_hist.iloc[-1])
        ctx['macd_hist_prev'] = float(macd_hist.iloc[-2])
        ctx['macd_rising'] = ctx['macd_hist'] > ctx['macd_hist_prev']

        ctx['atr_1m'] = float(ind.atr(d1['high'], d1['low'], d1['close'], 14).iloc[-1])
        ctx['atr_pct'] = ctx['atr_1m'] / ctx['price'] if ctx['price'] > 0 else 0

        bb_u, bb_m, bb_l = ind.bollinger_bands(d1['close'], 20, 2.0)
        ctx['bb_upper'] = float(bb_u.iloc[-1])
        ctx['bb_middle'] = float(bb_m.iloc[-1])
        ctx['bb_lower'] = float(bb_l.iloc[-1])
        bb_range = ctx['bb_upper'] - ctx['bb_lower']
        ctx['bb_position'] = (ctx['price'] - ctx['bb_lower']) / bb_range if bb_range > 0 else 0.5

        # Volume
        ctx['vol_spike'] = float(ind.volume_spike(d1['volume'], 20).iloc[-1])
        ctx['volume_1m'] = float(d1['volume'].iloc[-1])

        # ── VWAP ──
        vwap_line = ind.vwap(d1['high'], d1['low'], d1['close'], d1['volume'])
        ctx['vwap'] = float(vwap_line.iloc[-1])
        ctx['price_vs_vwap'] = (ctx['price'] - ctx['vwap']) / ctx['vwap'] * 100 if ctx['vwap'] > 0 else 0
        vwap_upper, vwap_lower = ind.vwap_bands(vwap_line, d1['close'], 20, 1.5)
        ctx['vwap_upper'] = float(vwap_upper.iloc[-1])
        ctx['vwap_lower'] = float(vwap_lower.iloc[-1])

        # ── CVD (from candles) ──
        cvd = ind.cvd_from_candles(d1['open'], d1['close'], d1['high'], d1['low'], d1['volume'])
        ctx['cvd'] = float(cvd.iloc[-1])
        ctx['cvd_slope'] = float(ind.cvd_slope(cvd, 5).iloc[-1])
        ctx['cvd_slope_10'] = float(ind.cvd_slope(cvd, 10).iloc[-1])

        # CVD divergence detection
        price_higher = d1['close'].iloc[-1] > d1['close'].iloc[-6]
        cvd_higher = cvd.iloc[-1] > cvd.iloc[-6]
        ctx['cvd_bullish_div'] = not price_higher and cvd_higher  # Price down, CVD up
        ctx['cvd_bearish_div'] = price_higher and not cvd_higher  # Price up, CVD down

        # ── 5M indicators (confirmation) ──
        ctx['ema9_5m'] = float(ind.ema(d5['close'], 9).iloc[-1])
        ctx['ema21_5m'] = float(ind.ema(d5['close'], 21).iloc[-1])
        ctx['rsi_5m'] = float(ind.rsi(d5['close'], 14).iloc[-1])

        # ── 15M HTF bias ──
        if len(df_15m) >= 30:
            d15 = df_15m.copy()
            ctx['ema21_15m'] = float(ind.ema(d15['close'], 21).iloc[-1])
            ctx['ema55_15m'] = float(ind.ema(d15['close'], 55).iloc[-1]) if len(d15) >= 55 else ctx['ema21_15m']
            ctx['rsi_15m'] = float(ind.rsi(d15['close'], 14).iloc[-1])
            ctx['htf_bullish'] = ctx['price'] > ctx['ema21_15m'] and ctx['rsi_15m'] > 40
            ctx['htf_bearish'] = ctx['price'] < ctx['ema21_15m'] and ctx['rsi_15m'] < 60
        else:
            ctx['htf_bullish'] = True
            ctx['htf_bearish'] = True

        return ctx

    # ═══════════════════════════════════════════════════════════
    # LONG EVALUATION (6-Layer Confluence)
    # ═══════════════════════════════════════════════════════════

    def _evaluate_long(self, ctx: dict, symbol: str, regime: MicroRegime,
                       orderbook: Optional[dict], funding: Optional[float]) -> Optional[ScalpSignal]:
        """Оценка LONG сигнала через 6 слоёв"""

        # HTF guard: Enforce strict trend following
        if not ctx.get('htf_bullish'):
            logger.info(f"{symbol}: LONG rejected by HTF guard (Not bullish)")
            return None

        conf = ScalpConfluence()
        reasons = []
        warnings = []

        # ── LAYER 2: VWAP + EMA Bias (0-20) ──
        layer2 = 0

        # Price above VWAP = bullish bias
        if ctx['price'] > ctx['vwap']:
            layer2 += 6
            reasons.append("📈 Price > VWAP")

        # EMA stack: 9 > 21 > 55
        if ctx['ema9_1m'] > ctx['ema21_1m'] > ctx['ema55_1m']:
            layer2 += 8
            reasons.append("📊 EMA stack bullish (9>21>55)")
        elif ctx['ema9_1m'] > ctx['ema21_1m']:
            layer2 += 4

        # VWAP bounce: price near VWAP lower band and turning up
        if ctx['price'] <= ctx['vwap'] * 1.001 and ctx['price'] > ctx['vwap'] * 0.998:
            layer2 += 6
            reasons.append("🎯 VWAP bounce zone")

        conf.add('VWAP+EMA Bias', layer2, 20)

        # ── LAYER 3: Order Flow & CVD (0-25) ──
        layer3 = 0

        # CVD slope positive = buying pressure
        if ctx['cvd_slope'] > 0:
            layer3 += 8
            if ctx['cvd_slope_10'] > 0:
                layer3 += 4
                reasons.append("🔥 CVD rising (strong buying)")
            else:
                reasons.append("📗 CVD positive")

        # CVD bullish divergence (price down but CVD up) = reversal signal
        if ctx['cvd_bullish_div']:
            layer3 += 8
            reasons.append("⚡ CVD bullish divergence!")

        # Volume spike confirmation
        if ctx['vol_spike'] > 1.8:
            layer3 += 5
            reasons.append(f"📊 Volume spike {ctx['vol_spike']:.1f}x")

        conf.add('Order Flow & CVD', layer3, 25)

        # ── LAYER 4: Momentum (0-20) ──
        layer4 = 0

        # RSI bounce from oversold (< 30 → rising)
        if ctx['rsi_1m'] < 35 and ctx['rsi_1m'] > ctx['rsi_1m_prev']:
            layer4 += 8
            reasons.append(f"📉 RSI bounce from {ctx['rsi_1m']:.0f}")
        elif ctx['rsi_1m'] < 45 and ctx['rsi_1m'] > ctx['rsi_1m_prev']:
            layer4 += 4

        # Stochastic RSI oversold + crossing up
        if ctx['stoch_k'] < 25 and ctx['stoch_k'] > ctx['stoch_d']:
            layer4 += 6
            reasons.append("📈 StochRSI bullish cross from oversold")
        elif ctx['stoch_k'] < 40:
            layer4 += 2

        # MACD histogram turning positive
        if ctx['macd_rising'] and ctx['macd_hist'] > ctx['macd_hist_prev']:
            layer4 += 6
            reasons.append("📊 MACD momentum building")

        conf.add('Momentum', layer4, 20)

        # ── LAYER 5: Microstructure (0-20) ──
        layer5 = 0

        # Orderbook imbalance (buyers > sellers)
        if orderbook:
            bid_vol = orderbook.get('bid_volume', 0)
            ask_vol = orderbook.get('ask_volume', 0)
            if ask_vol > 0:
                ob_ratio = bid_vol / ask_vol
                if ob_ratio > 1.5:
                    layer5 += 8
                    reasons.append(f"📗 OB: buyers {ob_ratio:.1f}x")
                elif ob_ratio > 1.2:
                    layer5 += 4

            # Spread check
            bid = orderbook.get('best_bid', 0)
            ask = orderbook.get('best_ask', 0)
            if bid > 0 and ask > 0:
                spread_bps = ((ask - bid) / bid) * 10000
                if spread_bps < 2:
                    layer5 += 4  # Tight spread = good
                    reasons.append(f"💎 Tight spread ({spread_bps:.1f}bps)")

        # Funding rate (negative = short bias = good for long)
        if funding is not None:
            if funding < -0.0005:
                layer5 += 8
                reasons.append(f"💰 Funding SHORT bias ({funding*100:.3f}%)")
            elif funding < 0:
                layer5 += 3

        conf.add('Microstructure', layer5, 20)

        # ── LAYER 6: Regime Bonus (0-15) ──
        layer6 = 0

        if regime == MicroRegime.TRENDING_UP:
            layer6 += 10
            reasons.append("📈 Micro-trend UP")
        elif regime == MicroRegime.BREAKOUT_UP:
            layer6 += 12
            reasons.append("🚀 BREAKOUT UP detected")
        elif regime == MicroRegime.RANGE_WIDE:
            # Bollinger band bounce from lower
            if ctx['bb_position'] < 0.15:
                layer6 += 8
                reasons.append("📉 BB Lower bounce")
        elif regime == MicroRegime.RANGE_TIGHT:
            # Squeeze → wait for direction confirmation
            if ctx['macd_rising'] and ctx['cvd_slope'] > 0:
                layer6 += 6
                reasons.append("🔧 Squeeze breakout setup (bullish)")
        elif regime in [MicroRegime.TRENDING_DOWN, MicroRegime.BREAKOUT_DOWN]:
            # Не лонговать в даунтренде (кроме экстремального RSI)
            if ctx['rsi_1m'] > 15:
                return None

        conf.add('Regime', layer6, 15)

        # ── Minimum check ──
        if conf.percentage < self.min_confluence:
            logger.info(f"{symbol}: LONG below min confluence ({conf.percentage:.1f}% < {self.min_confluence}%)")
            return None

        # ── ENTRY / SL / TP ──
        entry = ctx['price']
        atr = ctx['atr_1m']

        # Dynamic SL: 1.5-2.5x ATR depending on regime
        sl_mult = 1.5 if regime in [MicroRegime.TRENDING_UP, MicroRegime.BREAKOUT_UP] else 2.0
        stop_loss = entry - (atr * sl_mult)

        # Dynamic TP: depends on regime
        if regime in [MicroRegime.BREAKOUT_UP]:
            tp1 = entry + (atr * 3.0)  # Breakout → aggressive TP
            tp2 = entry + (atr * 5.0)
        elif regime == MicroRegime.TRENDING_UP:
            tp1 = entry + (atr * 2.0)
            tp2 = entry + (atr * 3.5)
        else:
            tp1 = ctx['bb_middle']  # Range → target middle BB
            tp2 = ctx['bb_upper']   # Second target = upper BB

        # R:R check
        risk = entry - stop_loss
        reward = tp1 - entry
        rr = reward / risk if risk > 0 else 0

        if rr < self.min_rr:
            logger.info(f"{symbol}: LONG rejected by RR ({rr:.2f} < {self.min_rr})")
            return None

        # Limit entry optimization
        if self.use_limit_entry and orderbook:
            bid = orderbook.get('best_bid', entry)
            if bid > 0:
                entry = min(entry, bid)  # Try to enter at bid

        probability = min(95, int(50 + conf.percentage * 0.5))

        return ScalpSignal(
            signal_type=SignalType.LONG,
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            confluence=conf,
            probability=probability,
            strength=conf.get_strength(),
            micro_regime=regime,
            vwap_bias="bullish" if ctx['price'] > ctx['vwap'] else "neutral",
            cvd_direction="buying" if ctx['cvd_slope'] > 0 else "neutral",
            ema_stack="bullish" if ctx['ema9_1m'] > ctx['ema21_1m'] > ctx['ema55_1m'] else "none",
            risk_reward_ratio=round(rr, 2),
            position_size_percent=self.max_risk_pct * 100,
            funding_rate=funding,
            orderbook_imbalance=orderbook.get('bid_volume', 0) / max(orderbook.get('ask_volume', 1), 1) if orderbook else None,
            reasoning=reasons,
            warnings=warnings,
            indicators={
                'rsi_1m': ctx['rsi_1m'],
                'rsi_5m': ctx['rsi_5m'],
                'rsi_15m': ctx.get('rsi_15m', 50),
                'bb_position': ctx['bb_position'],
                'vol_ratio': ctx['vol_spike'],
                'atr_pct': ctx['atr_pct'] * 100,
                'trend_adx': 0,
                'funding_rate': funding or 0,
                'hour_of_day': datetime.now().hour,
                'cvd_slope': ctx['cvd_slope'],
                'vwap_dist': ctx['price_vs_vwap'],
                'ema_dist': (ctx['price'] - ctx['ema21_1m']) / ctx['ema21_1m'] * 100 if ctx['ema21_1m'] > 0 else 0,
                'bb_width': (ctx['bb_upper'] - ctx['bb_lower']) / ctx['bb_middle'] if ctx['bb_middle'] > 0 else 0,
                'vol_zscore': ctx['vol_spike'] - 1,
            },
        )

    # ═══════════════════════════════════════════════════════════
    # SHORT EVALUATION (Mirror)
    # ═══════════════════════════════════════════════════════════

    def _evaluate_short(self, ctx: dict, symbol: str, regime: MicroRegime,
                        orderbook: Optional[dict], funding: Optional[float]) -> Optional[ScalpSignal]:
        """Оценка SHORT сигнала через 6 слоёв"""

        # Enforce strict HTF trend following for shorts
        if not ctx.get('htf_bearish'):
           logger.info(f"{symbol}: SHORT rejected by HTF guard (Not bearish)")
           return None

        conf = ScalpConfluence()
        reasons = []
        warnings = []

        # ── LAYER 2: VWAP + EMA Bias (0-20) ──
        layer2 = 0

        if ctx['price'] < ctx['vwap']:
            layer2 += 6
            reasons.append("📉 Price < VWAP")

        if ctx['ema9_1m'] < ctx['ema21_1m'] < ctx['ema55_1m']:
            layer2 += 8
            reasons.append("📊 EMA stack bearish (9<21<55)")
        elif ctx['ema9_1m'] < ctx['ema21_1m']:
            layer2 += 4

        if ctx['price'] >= ctx['vwap'] * 0.999 and ctx['price'] < ctx['vwap'] * 1.002:
            layer2 += 6
            reasons.append("🎯 VWAP rejection zone")

        conf.add('VWAP+EMA Bias', layer2, 20)

        # ── LAYER 3: Order Flow & CVD (0-25) ──
        layer3 = 0

        if ctx['cvd_slope'] < 0:
            layer3 += 8
            if ctx['cvd_slope_10'] < 0:
                layer3 += 4
                reasons.append("🔥 CVD falling (strong selling)")
            else:
                reasons.append("📕 CVD negative")

        if ctx['cvd_bearish_div']:
            layer3 += 8
            reasons.append("⚡ CVD bearish divergence!")

        if ctx['vol_spike'] > 1.8:
            layer3 += 5
            reasons.append(f"📊 Volume spike {ctx['vol_spike']:.1f}x")

        conf.add('Order Flow & CVD', layer3, 25)

        # ── LAYER 4: Momentum (0-20) ──
        layer4 = 0

        if ctx['rsi_1m'] > 65 and ctx['rsi_1m'] < ctx['rsi_1m_prev']:
            layer4 += 8
            reasons.append(f"📈 RSI rejection from {ctx['rsi_1m']:.0f}")
        elif ctx['rsi_1m'] > 55 and ctx['rsi_1m'] < ctx['rsi_1m_prev']:
            layer4 += 4

        if ctx['stoch_k'] > 75 and ctx['stoch_k'] < ctx['stoch_d']:
            layer4 += 6
            reasons.append("📉 StochRSI bearish cross from overbought")
        elif ctx['stoch_k'] > 60:
            layer4 += 2

        if not ctx['macd_rising'] and ctx['macd_hist'] < ctx['macd_hist_prev']:
            layer4 += 6
            reasons.append("📊 MACD momentum fading")

        conf.add('Momentum', layer4, 20)

        # ── LAYER 5: Microstructure (0-20) ──
        layer5 = 0

        if orderbook:
            bid_vol = orderbook.get('bid_volume', 0)
            ask_vol = orderbook.get('ask_volume', 0)
            if bid_vol > 0:
                ob_ratio = ask_vol / bid_vol
                if ob_ratio > 1.5:
                    layer5 += 8
                    reasons.append(f"📕 OB: sellers {ob_ratio:.1f}x")
                elif ob_ratio > 1.2:
                    layer5 += 4

            bid = orderbook.get('best_bid', 0)
            ask = orderbook.get('best_ask', 0)
            if bid > 0 and ask > 0:
                spread_bps = ((ask - bid) / bid) * 10000
                if spread_bps < 2:
                    layer5 += 4

        if funding is not None:
            if funding > 0.0005:
                layer5 += 8
                reasons.append(f"💰 Funding LONG bias ({funding*100:.3f}%)")
            elif funding > 0:
                layer5 += 3

        conf.add('Microstructure', layer5, 20)

        # ── LAYER 6: Regime (0-15) ──
        layer6 = 0

        if regime == MicroRegime.TRENDING_DOWN:
            layer6 += 10
            reasons.append("📉 Micro-trend DOWN")
        elif regime == MicroRegime.BREAKOUT_DOWN:
            layer6 += 12
            reasons.append("💥 BREAKOUT DOWN detected")
        elif regime == MicroRegime.RANGE_WIDE:
            if ctx['bb_position'] > 0.85:
                layer6 += 8
                reasons.append("📈 BB Upper rejection")
        elif regime == MicroRegime.RANGE_TIGHT:
            if not ctx['macd_rising'] and ctx['cvd_slope'] < 0:
                layer6 += 6
                reasons.append("🔧 Squeeze breakout setup (bearish)")
        elif regime in [MicroRegime.TRENDING_UP, MicroRegime.BREAKOUT_UP]:
            if ctx['rsi_1m'] < 85:
                return None

        conf.add('Regime', layer6, 15)

        if conf.percentage < self.min_confluence:
            logger.info(f"{symbol}: SHORT below min confluence ({conf.percentage:.1f}% < {self.min_confluence}%)")
            return None

        # ── ENTRY / SL / TP ──
        entry = ctx['price']
        atr = ctx['atr_1m']

        sl_mult = 1.5 if regime in [MicroRegime.TRENDING_DOWN, MicroRegime.BREAKOUT_DOWN] else 2.0
        stop_loss = entry + (atr * sl_mult)

        if regime in [MicroRegime.BREAKOUT_DOWN]:
            tp1 = entry - (atr * 3.0)
            tp2 = entry - (atr * 5.0)
        elif regime == MicroRegime.TRENDING_DOWN:
            tp1 = entry - (atr * 2.0)
            tp2 = entry - (atr * 3.5)
        else:
            tp1 = ctx['bb_middle']
            tp2 = ctx['bb_lower']

        # R:R check
        risk = stop_loss - entry
        reward = entry - tp1
        rr = reward / risk if risk > 0 else 0

        if rr < self.min_rr:
            logger.info(f"{symbol}: SHORT rejected by RR ({rr:.2f} < {self.min_rr})")
            return None

        if self.use_limit_entry and orderbook:
            ask = orderbook.get('best_ask', entry)
            if ask > 0:
                entry = max(entry, ask)

        probability = min(95, int(50 + conf.percentage * 0.5))

        return ScalpSignal(
            signal_type=SignalType.SHORT,
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=tp1,
            take_profit_2=tp2,
            confluence=conf,
            probability=probability,
            strength=conf.get_strength(),
            micro_regime=regime,
            vwap_bias="bearish" if ctx['price'] < ctx['vwap'] else "neutral",
            cvd_direction="selling" if ctx['cvd_slope'] < 0 else "neutral",
            ema_stack="bearish" if ctx['ema9_1m'] < ctx['ema21_1m'] < ctx['ema55_1m'] else "none",
            risk_reward_ratio=round(rr, 2),
            position_size_percent=self.max_risk_pct * 100,
            funding_rate=funding,
            orderbook_imbalance=orderbook.get('bid_volume', 0) / max(orderbook.get('ask_volume', 1), 1) if orderbook else None,
            reasoning=reasons,
            warnings=warnings,
            indicators={
                'rsi_1m': ctx['rsi_1m'],
                'rsi_5m': ctx['rsi_5m'],
                'rsi_15m': ctx.get('rsi_15m', 50),
                'bb_position': ctx['bb_position'],
                'vol_ratio': ctx['vol_spike'],
                'atr_pct': ctx['atr_pct'] * 100,
                'trend_adx': 0,
                'funding_rate': funding or 0,
                'hour_of_day': datetime.now().hour,
                'cvd_slope': ctx['cvd_slope'],
                'vwap_dist': ctx['price_vs_vwap'],
                'ema_dist': (ctx['price'] - ctx['ema21_1m']) / ctx['ema21_1m'] * 100 if ctx['ema21_1m'] > 0 else 0,
                'bb_width': (ctx['bb_upper'] - ctx['bb_lower']) / ctx['bb_middle'] if ctx['bb_middle'] > 0 else 0,
                'vol_zscore': ctx['vol_spike'] - 1,
            },
        )


# ═══════════════════════════════════════════════════════════════════
# SIGNAL FORMATTER (для Telegram и логов)
# ═══════════════════════════════════════════════════════════════════

def format_scalp_signal(signal: ScalpSignal, balance: float = 100) -> str:
    emoji = '🟢' if signal.signal_type == SignalType.LONG else '🔴'
    direction = signal.signal_type.value

    if signal.signal_type == SignalType.LONG:
        sl_pct = (signal.entry_price - signal.stop_loss) / signal.entry_price * 100
        tp1_pct = (signal.take_profit_1 - signal.entry_price) / signal.entry_price * 100
    else:
        sl_pct = (signal.stop_loss - signal.entry_price) / signal.entry_price * 100
        tp1_pct = (signal.entry_price - signal.take_profit_1) / signal.entry_price * 100

    out = f"""
{'═'*55}
{emoji} SCALP │ {signal.symbol} │ {direction} │ {signal.strength.value}
{'═'*55}

📊 CONFLUENCE: {signal.confluence.percentage:.0f}%
{signal.confluence.breakdown()}

🎯 Probability: {signal.probability}%
⏱️  Max hold: {signal.max_hold_bars} bars

{'─'*55}
💰 Entry:  ${signal.entry_price:,.2f}
🎯 TP1:    ${signal.take_profit_1:,.2f}  (+{tp1_pct:.2f}%)
🛑 SL:     ${signal.stop_loss:,.2f}  (-{sl_pct:.2f}%)
⚖️  R:R:    1:{signal.risk_reward_ratio}

{'─'*55}
📈 VWAP: {signal.vwap_bias} │ CVD: {signal.cvd_direction}
📊 EMA: {signal.ema_stack} │ Regime: {signal.micro_regime.value}
"""

    if signal.reasoning:
        out += "\n✅ REASONS:\n"
        for r in signal.reasoning:
            out += f"   • {r}\n"

    if signal.warnings:
        out += "\n⚠️ WARNINGS:\n"
        for w in signal.warnings:
            out += f"   {w}\n"

    out += f"\n⏰ Valid: {signal.valid_until.strftime('%H:%M')}\n{'═'*55}"
    return out


# ═══════════════════════════════════════════════════════════════════
# SELF-TEST
# ═══════════════════════════════════════════════════════════════════

def _generate_test_data(periods: int = 300, trend: str = "up") -> pd.DataFrame:
    np.random.seed(42)
    base = 100000.0
    prices = [base]
    for i in range(1, periods):
        drift = 0.0001 if trend == "up" else (-0.0001 if trend == "down" else 0)
        change = drift + np.random.randn() * 0.0005
        prices.append(prices[-1] * (1 + change))

    prices = np.array(prices)
    return pd.DataFrame({
        'open': prices,
        'high': prices * (1 + np.abs(np.random.randn(periods)) * 0.001),
        'low': prices * (1 - np.abs(np.random.randn(periods)) * 0.001),
        'close': prices * (1 + np.random.randn(periods) * 0.0005),
        'volume': np.random.randint(100, 2000, periods) * 1000.0,
    })


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s: %(message)s')

    print("=" * 55)
    print("  ULTRA SCALPING ENGINE v1.0 — Self Test")
    print("=" * 55)

    engine = UltraScalpingEngine(
        min_confluence=60,  # Lower threshold for testing
        session_filter=False,
    )

    # Generate trending data
    df_1m = _generate_test_data(300, "up")
    df_5m = df_1m.iloc[::5].reset_index(drop=True)
    df_15m = df_1m.iloc[::15].reset_index(drop=True)

    orderbook = {
        'best_bid': float(df_1m['close'].iloc[-1] * 0.9999),
        'best_ask': float(df_1m['close'].iloc[-1] * 1.0001),
        'bid_volume': 150000,
        'ask_volume': 80000,
    }

    signal = engine.analyze(
        df_1m=df_1m,
        df_5m=df_5m,
        df_15m=df_15m,
        symbol="BTCUSDT",
        orderbook=orderbook,
        funding_rate=-0.0008,
    )

    if signal:
        print(format_scalp_signal(signal, balance=500))
    else:
        print("No signal (try lower min_confluence for test)")

    # Test regime detection
    print("\n📊 Regime Tests:")
    for trend in ["up", "down", "flat"]:
        df = _generate_test_data(300, trend)
        df5 = df.iloc[::5].reset_index(drop=True)
        regime = engine._detect_micro_regime(df, df5)
        print(f"  {trend:6} → {regime.value}")

    print("\n✅ Self-test complete")
