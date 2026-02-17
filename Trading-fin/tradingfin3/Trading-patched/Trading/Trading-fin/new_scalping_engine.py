"""
╔══════════════════════════════════════════════════════════════════════════╗
║           NEW SCALPING ENGINE (MODIFIED) v2.0                            ║
║                                                                          ║
║   Dedicated logic for "New Scalping" mode requested by user.             ║
║   Based on UltraScalpingEngine but isolated for safe modifications.      ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
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

# Re-use Enums and DataClasses from existing files to maintain compatibility
from mean_reversion_bybit import SignalType
from scalping_engine import ScalpStrength, MicroRegime, ScalpConfluence, ScalpSignal, ScalpIndicators, SessionFilter

# ═══════════════════════════════════════════════════════════════════
# NEW SCALPING ENGINE
# ═══════════════════════════════════════════════════════════════════

class NewScalpingEngine:
    """
    Separate engine for 'New Scalping' mode.
    Currently identical to UltraScalpingEngine but allows independent tuning.
    """

    def __init__(
        self,
        min_confluence: int = 60,       # Lowered to 60 for more activity
        max_risk_pct: float = 0.005,    # 0.5% per trade
        use_limit_entry: bool = True,   # Limit orders
        min_rr: float = 1.2,            # Min R:R
        max_spread_bps: float = 5.0,    # Max spread
        session_filter: bool = False,   # DISABLED by default for testing
        cooldown_bars: int = 2,         # Faster cooldown (2 mins)
        **kwargs
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
        self.max_trades_per_day = 100  # Higher limit for "New Scalping"

        # AI model (RESTORED for 8GB RAM)
        self.ai = None
        try:
            from ai_engine import AIEngine
            self.ai = AIEngine()
        except ImportError:
            pass

        logger.info(
            f"🔥 NEW SCALPING ENGINE INITIALIZED 🔥\n"
            f"   Confluence: >={min_confluence}%\n"
            f"   Risk: {max_risk_pct*100}%\n"
            f"   Cooldown: {cooldown_bars} bars"
        )

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
        Main analysis logic.
        """
        # ── Pre-checks ──
        if len(df_1m) < 50 or len(df_5m) < 30:
            logger.debug(f"🔍 {symbol} skipped: Insufficient data (1m: {len(df_1m)}, 5m: {len(df_5m)})")
            return None

        # Cooldown
        if self.last_signal_time:
            bars_since = (datetime.now() - self.last_signal_time).total_seconds() / 60
            if bars_since < self.cooldown_bars:
                return None

        # Session filter
        if self.session_filter:
            ok, reason = self.session_filter.is_good_session()
            if not ok:
                 logger.info(f"{symbol}: Scalping skipped ({reason})")
                 return None

        # Spread check
        if orderbook:
            bid = orderbook.get('best_bid', 0)
            ask = orderbook.get('best_ask', 0)
            if bid > 0 and ask > 0:
                spread_bps = ((ask - bid) / bid) * 10000
                if spread_bps > self.max_spread_bps:
                    return None

        # ── LAYER 1: Market Structure (Micro-Regime) ──
        regime = self._detect_micro_regime(df_1m, df_5m)
        # Even choppy markets can have scalpable micro-spikes
        # if regime == MicroRegime.CHOPPY:
        #    return None

        # ── Indicators ──
        ctx = self._compute_indicators(df_1m, df_5m, df_15m)

        # ── Direction Evaluation ──
        long_signal = self._evaluate_long(ctx, symbol, regime, orderbook, funding_rate)
        short_signal = self._evaluate_short(ctx, symbol, regime, orderbook, funding_rate)

        # Pick best
        best = None
        if long_signal and short_signal:
            best = long_signal if long_signal.confluence.total_score >= short_signal.confluence.total_score else short_signal
        elif long_signal:
            best = long_signal
        elif short_signal:
            best = short_signal
        
        if best:
            # DIAGNOSTIC LOGGING: Why checked but rejected?
            if best.confluence.percentage < self.min_confluence:
                missing = []
                # Factors that COULD HAVE added score
                all_factors = ["Trend", "EMA Stack", "VWAP", "RSI", "Momentum", "Orderbook", "Impulse"]
                current_factors = best.confluence.factors.keys()
                missing = [f for f in all_factors if f not in current_factors]
                
                logger.info(f"🔍 {symbol}: Reject ({best.confluence.percentage:.0f}/{self.min_confluence}). Missing: {', '.join(missing)}")
            
            if best.confluence.percentage >= self.min_confluence:
                # AI filter
                if self.ai:
                    try:
                        ai_prob = self.ai.predict_success_probability(best.indicators)
                        # If model is untrained (returns 0.50), we rely on our strong Technical Confluence
                        if 0.49 <= ai_prob <= 0.51:
                             # Smart Filter: If AI is neutral, we require +10% more Technical Confluence
                             threshold = self.min_confluence + 10
                             if best.confluence.percentage < threshold:
                                 logger.info(f"🤖 {symbol}: AI Neutral (0.50) - Technicals {best.confluence.percentage}% too low (Need {threshold}%)")
                                 return None
                             logger.info(f"🤖 {symbol}: AI Neutral (0.50) - Using ULTRA Technicals ({best.confluence.percentage}%)")
                             best.reasoning.append(f"🤖 AI: Neutral (0.50) + Ultra Tech")
                        elif ai_prob < 0.55: 
                             logger.info(f"🤖 {symbol}: AI Rejected (Weak Prob {ai_prob:.2f})")
                             return None
                        else:
                             best.indicators['ai_score'] = ai_prob
                             best.reasoning.append(f"🤖 AI: {ai_prob*100:.0f}%")
                    except Exception as e:
                        logger.error(f"AI Filter Error: {e}")

                self.last_signal_time = datetime.now()
                self.trade_count_today += 1
                return best

        return None

    # Reuse logic from UltraScalpingEngine via copy-paste to ensure independence
    # (Or I could inherit, but complete isolation is safer for "New Mode" tweaks)
    
    def _detect_micro_regime(self, df_1m: pd.DataFrame, df_5m: pd.DataFrame) -> MicroRegime:
        ind = self.ind
        df = df_5m.copy()
        bb_upper, bb_mid, bb_lower = ind.bollinger_bands(df['close'], 20, 2.0)
        bb_width = ((bb_upper - bb_lower) / bb_mid.replace(0, 1e-10)).iloc[-1]
        
        # Squeeze
        if bb_width < 0.005: 
            return MicroRegime.RANGE_TIGHT

        # Simple Trend
        ema9 = ind.ema(df['close'], 9).iloc[-1]
        price = df['close'].iloc[-1]
        
        if price > ema9: return MicroRegime.TRENDING_UP
        if price < ema9: return MicroRegime.TRENDING_DOWN
        
        return MicroRegime.RANGE_WIDE

    def _compute_indicators(self, df_1m, df_5m, df_15m) -> dict:
        # Simplified standard indicators computation
        ind = self.ind
        d1 = df_1m.copy()
        
        ctx = {}
        ctx['price'] = float(d1['close'].iloc[-1])
        ctx['ema9_1m'] = float(ind.ema(d1['close'], 9).iloc[-1])
        ctx['ema21_1m'] = float(ind.ema(d1['close'], 21).iloc[-1])
        ctx['rsi_1m'] = float(ind.rsi(d1['close'], 7).iloc[-1])
        
        vwap_line = ind.vwap(d1['high'], d1['low'], d1['close'], d1['volume'])
        ctx['vwap'] = float(vwap_line.iloc[-1])
        
        # MACD
        _, _, macd_hist = ind.macd(d1['close'], 8, 21, 5)
        ctx['macd_hist'] = float(macd_hist.iloc[-1])
        
        # EMA Stack (Turbo Trend)
        ctx['ema9_1m'] = float(ind.ema(d1['close'], 9).iloc[-1])
        ctx['ema50_1m'] = float(ind.ema(d1['close'], 50).iloc[-1])
        
        # ATR (Volatility)
        high, low, close = d1['high'], d1['low'], d1['close']
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        ctx['atr'] = float(atr.iloc[-1])
        
        # Volume Stats for Impulse
        avg_vol = d1['volume'].rolling(20).mean().iloc[-1]
        cur_vol = d1['volume'].iloc[-1]
        ctx['vol_ratio'] = cur_vol / avg_vol if avg_vol > 0 else 1.0
        
        return ctx

    def _evaluate_long(self, ctx, symbol, regime, orderbook, funding) -> Optional[ScalpSignal]:
        conf = ScalpConfluence()
        reasons = []

        # 1. Trend (EMA 21 + EMA 9/50 Stack)
        if ctx['price'] > ctx['ema21_1m']:
            conf.add('Trend', 15, 15)
            reasons.append("Price > EMA21")
        
        if ctx['ema9_1m'] > ctx['ema21_1m'] > ctx['ema50_1m']:
            conf.add('EMA Stack', 10, 10)
            reasons.append("Bullish EMA Stack")
            
        # 2. VWAP
        if ctx['price'] > ctx['vwap']:
            conf.add('VWAP', 15, 15)
            reasons.append("Price > VWAP")
            
        # 3. RSI
        if 40 < ctx['rsi_1m'] < 70:
            conf.add('RSI', 15, 15)
        elif 30 < ctx['rsi_1m'] < 80:
            conf.add('RSI', 10, 15)
            
        # 4. Momentum (MACD)
        if ctx['macd_hist'] > 0:
            conf.add('Momentum', 15, 15)
            
        # 5. Advanced Orderbook Imbalance
        if orderbook:
            bids = orderbook.get('bid_volume', 1)
            asks = orderbook.get('ask_volume', 1)
            ratio = bids / (bids + asks)
            if ratio > 0.6: # 60% bids
                conf.add('Orderbook', 20, 20)
                reasons.append(f"OB Imbalance: {ratio:.0%}")
            elif ratio > 0.52:
                conf.add('Orderbook', 10, 20)

        # 6. Impulse
        if ctx['vol_ratio'] > 1.5:
            conf.add('Impulse', 10, 10)
            reasons.append(f"Vol Surge: {ctx['vol_ratio']:.1f}x")

        if conf.percentage >= self.min_confluence:
            # DYNAMIC ATR-BASED STOPS (Adaptive to Volatility)
            atr = ctx.get('atr', ctx['price'] * 0.002)
            sl = ctx['price'] - (2.0 * atr)
            tp1 = ctx['price'] + (3.0 * atr)
            tp2 = ctx['price'] + (5.0 * atr)

            sig = ScalpSignal(
                symbol=symbol,
                signal_type=SignalType.LONG,
                entry_price=ctx['price'],
                stop_loss=sl,
                take_profit_1=tp1,
                take_profit_2=tp2,
                confluence=conf,
                probability=int(conf.percentage), # FIXED: Actual probability
                reasoning=reasons,
                risk_reward_ratio=1.5
            )
            sig.indicators = ctx
            sig.indicators['trailing_stop_callback'] = 0.002 # Tight trailing
            return sig
        return None

    def _evaluate_short(self, ctx, symbol, regime, orderbook, funding) -> Optional[ScalpSignal]:
        conf = ScalpConfluence()
        reasons = []

        # 1. Trend
        if ctx['price'] < ctx['ema21_1m']:
             conf.add('Trend', 15, 15)
             reasons.append("Price < EMA21")
             
        if ctx['ema9_1m'] < ctx['ema21_1m'] < ctx['ema50_1m']:
            conf.add('EMA Stack', 10, 10)
            reasons.append("Bearish EMA Stack")
            
        # 2. VWAP
        if ctx['price'] < ctx['vwap']:
            conf.add('VWAP', 15, 15)
            reasons.append("Price < VWAP")
            
        # 3. RSI
        if 30 < ctx['rsi_1m'] < 60:
            conf.add('RSI', 15, 15)
        elif 20 < ctx['rsi_1m'] < 70:
            conf.add('RSI', 10, 15)
            
        # 4. Momentum
        if ctx['macd_hist'] < 0:
            conf.add('Momentum', 15, 15)
            
        # 5. Advanced Orderbook Imbalance
        if orderbook:
            bids = orderbook.get('bid_volume', 1)
            asks = orderbook.get('ask_volume', 1)
            ratio = asks / (bids + asks)
            if ratio > 0.6: # 60% asks
                conf.add('Orderbook', 20, 20)
                reasons.append(f"OB Imbalance: {ratio:.0%}")
            elif ratio > 0.52:
                conf.add('Orderbook', 10, 20)

        # 6. Impulse
        if ctx['vol_ratio'] > 1.5:
            conf.add('Impulse', 10, 10)
            reasons.append(f"Vol Surge: {ctx['vol_ratio']:.1f}x")

        if conf.percentage >= self.min_confluence:
            # DYNAMIC ATR-BASED STOPS
            atr = ctx.get('atr', ctx['price'] * 0.002)
            sl = ctx['price'] + (2.0 * atr)
            tp1 = ctx['price'] - (3.0 * atr)
            tp2 = ctx['price'] - (5.0 * atr)

            sig = ScalpSignal(
                symbol=symbol,
                signal_type=SignalType.SHORT,
                entry_price=ctx['price'],
                stop_loss=sl,
                take_profit_1=tp1,
                take_profit_2=tp2,
                confluence=conf,
                probability=int(conf.percentage), # FIXED: Actual probability
                reasoning=reasons,
                risk_reward_ratio=1.5
            )
            sig.indicators = ctx
            sig.indicators['trailing_stop_callback'] = 0.002
            return sig
        return None
