"""
╔══════════════════════════════════════════════════════════════════════════╗
║        DEPOSIT ACCELERATION ENGINE v1.0 — February 2026                  ║
║                                                                          ║
║   Система разгона депозита $100 → $1000+ на Bybit Futures                ║
║                                                                          ║
║   КЛЮЧЕВЫЕ ОСОБЕННОСТИ:                                                 ║
║     • 3 фазы разгона (Conservative → Moderate → Aggressive)              ║
║     • 10 индикаторов с мульти-таймфреймовым анализом                    ║
║     • Адаптивный риск-менеджмент (auto-phase по балансу)                ║
║     • Anti-tilt (пауза после серии убытков)                             ║
║     • Корреляционная защита                                              ║
║     • Break-even + Trailing Stop + Partial Close                        ║
║                                                                          ║
║   ИНТЕГРАЦИЯ:                                                           ║
║     main_bybit.py → --strategy deposit_accel                            ║
║     Совместимость: AdvancedSignal, ExecutionManager, BybitClient        ║
║                                                                          ║
║   ФАЗЫ:                                                                 ║
║     Phase 1 ($100-$200): 1.5% risk, 5x lev, 1 pos, 75%+ score         ║
║     Phase 2 ($200-$500): 2.0% risk, 7x lev, 2 pos, 65%+ score         ║
║     Phase 3 ($500+):     2.5% risk, 10x lev, 3 pos, 60%+ score        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
import time
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from mean_reversion_bybit import (
    AdvancedSignal, SignalType, SignalStrength, ConfluenceScore,
    MarketRegime, TechnicalIndicators
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# ФАЗЫ РАЗГОНА
# ═══════════════════════════════════════════════════════════════

class AccelPhase(Enum):
    CONSERVATIVE = "CONSERVATIVE"   # $100-200
    MODERATE = "MODERATE"           # $200-500
    AGGRESSIVE = "AGGRESSIVE"       # $500+


@dataclass
class PhaseConfig:
    """Параметры одной фазы"""
    phase: AccelPhase
    max_balance: float          # Верхняя граница баланса для этой фазы
    risk_per_trade: float       # % от баланса на сделку
    max_leverage: int           # Максимальное плечо
    max_positions: int          # Макс одновременных позиций
    min_confluence_pct: float   # Мин. confluence % для входа
    tp_sl_ratio: float          # Take Profit : Stop Loss
    valid_minutes: int          # Сколько минут сигнал валиден


# Конфигурация фаз
PHASES = [
    PhaseConfig(
        phase=AccelPhase.CONSERVATIVE,
        max_balance=200.0,
        risk_per_trade=1.5,
        max_leverage=5,
        max_positions=1,
        min_confluence_pct=70.0,   # 70% — строго, но не 85
        tp_sl_ratio=2.0,
        valid_minutes=30,
    ),
    PhaseConfig(
        phase=AccelPhase.MODERATE,
        max_balance=500.0,
        risk_per_trade=2.0,
        max_leverage=7,
        max_positions=2,
        min_confluence_pct=58.0,
        tp_sl_ratio=2.5,
        valid_minutes=45,
    ),
    PhaseConfig(
        phase=AccelPhase.AGGRESSIVE,
        max_balance=999999.0,
        risk_per_trade=2.5,
        max_leverage=10,
        max_positions=3,
        min_confluence_pct=55.0,
        tp_sl_ratio=3.0,
        valid_minutes=60,
    ),
]


# Корреляционные группы — нельзя открыть 2 позиции из одной группы
CORRELATION_GROUPS = {
    "BTC":  ["BTCUSDT"],
    "ETH":  ["ETHUSDT"],
    "SOL":  ["SOLUSDT", "SUIUSDT"],
    "MEME": ["1000PEPEUSDT", "DOGEUSDT", "SHIBUSDT", "FLOKIUSDT"],
    "ALT":  ["XRPUSDT", "AVAXUSDT", "ADAUSDT", "DOTUSDT"],
    "AI":   ["RENDERUSDT", "FETUSDT", "NEARUSDT"],
}


def get_correlation_group(symbol: str) -> Optional[str]:
    for group, symbols in CORRELATION_GROUPS.items():
        if symbol in symbols:
            return group
    return None


def get_phase_config(balance: float) -> PhaseConfig:
    """Определяет текущую фазу по балансу"""
    for phase_cfg in PHASES:
        if balance < phase_cfg.max_balance:
            return phase_cfg
    return PHASES[-1]  # Aggressive


# ═══════════════════════════════════════════════════════════════
# ANTI-TILT СИСТЕМА
# ═══════════════════════════════════════════════════════════════

class AntiTiltTracker:
    """Отслеживает серии убытков и блокирует торговлю"""
    
    def __init__(self):
        self.consecutive_losses = 0
        self.cooldown_until = 0.0
        self.daily_loss_usd = 0.0
        self.daily_reset_ts = time.time()
        self.trades_today = 0
    
    def reset_daily_if_needed(self):
        if time.time() - self.daily_reset_ts > 86400:
            self.daily_loss_usd = 0.0
            self.daily_reset_ts = time.time()
            self.trades_today = 0
    
    def on_loss(self, loss_usd: float):
        self.consecutive_losses += 1
        self.daily_loss_usd += abs(loss_usd)
        self.trades_today += 1
        
        if self.consecutive_losses >= 3:
            self.cooldown_until = time.time() + 7200  # 2 часа
            logger.warning(f"🧊 ANTI-TILT: 2h cooldown after {self.consecutive_losses} consecutive losses")
        elif self.consecutive_losses >= 2:
            self.cooldown_until = time.time() + 1800  # 30 мин
            logger.warning(f"⏸️ ANTI-TILT: 30min cooldown after {self.consecutive_losses} losses")
    
    def on_win(self):
        self.consecutive_losses = 0
        self.trades_today += 1
    
    def can_trade(self, balance: float) -> Tuple[bool, str]:
        self.reset_daily_if_needed()
        
        # Cooldown
        if time.time() < self.cooldown_until:
            remaining = int(self.cooldown_until - time.time())
            return False, f"🧊 Cooldown: {remaining}s left (after {self.consecutive_losses} losses)"
        
        # Дневной лимит убытков — 5%
        max_daily = balance * 0.05
        if self.daily_loss_usd >= max_daily:
            return False, f"🛑 Daily loss limit: ${self.daily_loss_usd:.2f} / ${max_daily:.2f}"
        
        # Мин. баланс
        if balance < 10:
            return False, f"💸 Balance too low: ${balance:.2f}"
        
        return True, "✅ OK"


# ═══════════════════════════════════════════════════════════════
# DEPOSIT ACCELERATION ENGINE
# ═══════════════════════════════════════════════════════════════

class DepositAccelerationEngine:
    """
    Стратегия разгона депозита $100 → $1000+.
    
    Интегрируется как стандартная стратегия в main_bybit.py.
    Возвращает AdvancedSignal — совместимо с ExecutionManager.
    
    Использование:
        engine = DepositAccelerationEngine(equity=100)
        signal = engine.analyze(df_5m, "BTCUSDT", funding_rate=0.0001)
        if signal:
            execution_manager.execute_signal(signal)
    """
    
    # Confluence weights (max = 150)
    FACTOR_WEIGHTS = {
        "ema_trend":    {"max": 20, "desc": "EMA 9/21/55 trend alignment"},
        "rsi":          {"max": 15, "desc": "RSI zones + divergence"},
        "macd":         {"max": 15, "desc": "MACD cross + histogram"},
        "bollinger":    {"max": 12, "desc": "BB position + squeeze"},
        "stoch_rsi":    {"max": 12, "desc": "Stoch RSI cross in zones"},
        "adx":          {"max": 12, "desc": "Trend strength (ADX)"},
        "volume":       {"max": 12, "desc": "Volume confirmation"},
        "support_res":  {"max": 12, "desc": "S/R proximity"},
        "atr_quality":  {"max": 10, "desc": "ATR-based trade quality"},
        "funding":      {"max": 10, "desc": "Funding rate analysis"},
        "mtf_bonus":    {"max": 20, "desc": "Multi-TF agreement bonus"},
        "open_interest": {"max": 10, "desc": "OI trend confirmation"},
    }
    MAX_CONFLUENCE = sum(v["max"] for v in FACTOR_WEIGHTS.values())  # = 160
    
    def __init__(self, equity: float = 100.0, min_confluence: int = 65, max_risk_pct: float = 0.02):
        self.equity = equity
        self.min_confluence_pct = min_confluence
        self.max_risk_pct = max_risk_pct
        self.anti_tilt = AntiTiltTracker()
        self.open_symbols: List[str] = []
        
        self._phase_config = get_phase_config(equity)
        self.name = f"Deposit Acceleration ({self._phase_config.phase.value})"
        
        logger.info(f"🚀 {self.name} initialized | Equity: ${equity:.2f} | "
                     f"Risk: {self._phase_config.risk_per_trade}% | "
                     f"Leverage: {self._phase_config.max_leverage}x | "
                     f"Min Confluence: {self._phase_config.min_confluence_pct}%")
    
    def update_equity(self, equity: float):
        """Обновление баланса → возможная смена фазы"""
        old_phase = self._phase_config.phase
        self.equity = equity
        self._phase_config = get_phase_config(equity)
        
        if self._phase_config.phase != old_phase:
            logger.info(f"🚀 PHASE CHANGE: {old_phase.value} → {self._phase_config.phase.value} | Balance: ${equity:.2f}")
            self.name = f"Deposit Acceleration ({self._phase_config.phase.value})"
    
    def set_open_positions(self, symbols: List[str]):
        """Передаём список открытых позиций для корреляционной проверки"""
        self.open_symbols = symbols
    
    # ═══════════════════════════════════════════════════════════
    # ГЛАВНЫЙ МЕТОД АНАЛИЗА
    # ═══════════════════════════════════════════════════════════
    
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        funding_rate: float = 0.0,
        orderbook_imbalance: float = None,
        df_15m: pd.DataFrame = None,
        df_1h: pd.DataFrame = None,
        df_4h: pd.DataFrame = None,
        oi_change_pct: float = None,
        **kwargs
    ) -> Optional[AdvancedSignal]:
        """
        Анализ одного символа. Возвращает AdvancedSignal или None.
        
        df: DataFrame со свечами (основной ТФ — 5m рекомендуется)
             Колонки: open, high, low, close, volume
        """
        if df is None or len(df) < 50:
            return None
        
        # --- Pre-checks ---
        can_trade, reason = self.anti_tilt.can_trade(self.equity)
        if not can_trade:
            logger.debug(f"🚫 {symbol}: {reason}")
            return None
        
        # Корреляционная проверка
        if not self._check_correlation(symbol):
            logger.debug(f"🔗 {symbol}: Correlation blocked")
            return None
        
        # Количество позиций
        if len(self.open_symbols) >= self._phase_config.max_positions:
            return None
        
        # --- Вычисляем индикаторы ---
        close = df['close'].astype(float)
        high = df['high'].astype(float)
        low = df['low'].astype(float)
        volume = df['volume'].astype(float)
        
        # EMA
        ema9 = TechnicalIndicators.ema(close, 9)
        ema21 = TechnicalIndicators.ema(close, 21)
        ema55 = TechnicalIndicators.ema(close, 55)
        
        # RSI
        rsi = TechnicalIndicators.rsi(close, 14)
        
        # Stoch RSI
        stoch_k, stoch_d = TechnicalIndicators.stochastic_rsi(close)
        
        # BB
        bb_upper, bb_mid, bb_lower = TechnicalIndicators.bollinger_bands(close)
        
        # ATR
        atr = TechnicalIndicators.atr(high, low, close, 14)
        
        # ADX
        adx, plus_di, minus_di = TechnicalIndicators.adx(high, low, close, 14)
        
        # MACD
        ema12 = TechnicalIndicators.ema(close, 12)
        ema26 = TechnicalIndicators.ema(close, 26)
        macd_line = ema12 - ema26
        macd_signal = TechnicalIndicators.ema(macd_line, 9)
        macd_hist = macd_line - macd_signal
        
        # Volume SMA
        vol_sma = volume.rolling(20).mean()
        
        # Текущие значения
        c = close.iloc[-1]
        c_prev = close.iloc[-2]
        
        # --- CONFLUENCE SCORING ---
        confluence = ConfluenceScore(max_possible=self.MAX_CONFLUENCE)
        direction_votes = {"LONG": 0, "SHORT": 0}
        
        # 1. EMA TREND (0-20)
        ema_score, ema_dir = self._score_ema(ema9, ema21, ema55)
        confluence.add_factor("EMA Trend", ema_score, 20)
        direction_votes[ema_dir] += ema_score
        
        # 2. RSI (0-15)
        rsi_score, rsi_dir = self._score_rsi(rsi, close)
        confluence.add_factor("RSI", rsi_score, 15)
        direction_votes[rsi_dir] += rsi_score
        
        # 3. MACD (0-15)
        macd_score, macd_dir = self._score_macd(macd_line, macd_signal, macd_hist)
        confluence.add_factor("MACD", macd_score, 15)
        direction_votes[macd_dir] += macd_score
        
        # 4. BOLLINGER (0-12)
        bb_score, bb_dir = self._score_bollinger(close, bb_upper, bb_lower, bb_mid)
        confluence.add_factor("Bollinger", bb_score, 12)
        direction_votes[bb_dir] += bb_score
        
        # 5. STOCH RSI (0-12)
        sr_score, sr_dir = self._score_stoch_rsi(stoch_k, stoch_d)
        confluence.add_factor("Stoch RSI", sr_score, 12)
        direction_votes[sr_dir] += sr_score
        
        # 6. ADX (0-12)
        adx_score, adx_dir = self._score_adx(adx, plus_di, minus_di)
        confluence.add_factor("ADX", adx_score, 12)
        direction_votes[adx_dir] += adx_score
        
        # 7. VOLUME (0-12)
        vol_score, vol_dir = self._score_volume(volume, vol_sma, close)
        confluence.add_factor("Volume", vol_score, 12)
        direction_votes[vol_dir] += vol_score
        
        # 8. SUPPORT/RESISTANCE (0-12)
        sr_lvl_score, sr_lvl_dir = self._score_support_resistance(high, low, close)
        confluence.add_factor("Support/Resistance", sr_lvl_score, 12)
        direction_votes[sr_lvl_dir] += sr_lvl_score
        
        # 9. ATR QUALITY (0-10)
        atr_score = self._score_atr_quality(atr, close)
        confluence.add_factor("ATR Quality", atr_score, 10)
        
        # 10. FUNDING RATE (0-10)
        fund_score, fund_dir = self._score_funding(funding_rate)
        confluence.add_factor("Funding", fund_score, 10)
        direction_votes[fund_dir] += fund_score
        
        # 11. MULTI-TIMEFRAME BONUS (0-20)
        mtf_score, mtf_dir = self._score_mtf(df_15m, df_1h, df_4h)
        confluence.add_factor("Multi-Timeframe", mtf_score, 20)
        direction_votes[mtf_dir] += mtf_score
        
        # 12. OPEN INTEREST (0-10)
        oi_score, oi_dir = self._score_open_interest(oi_change_pct)
        confluence.add_factor("Open Interest", oi_score, 10)
        direction_votes[oi_dir] += oi_score
        
        # --- ОПРЕДЕЛЯЕМ НАПРАВЛЕНИЕ ---
        if direction_votes["LONG"] > direction_votes["SHORT"]:
            signal_type = SignalType.LONG
        elif direction_votes["SHORT"] > direction_votes["LONG"]:
            signal_type = SignalType.SHORT
        else:
            return None  # Нет консенсуса
        
        # --- ПРОВЕРКА ПОРОГА ---
        pct = confluence.percentage
        min_pct = self._phase_config.min_confluence_pct
        
        if pct < min_pct:
            if pct > 40: # Log symbols that are at least somewhat interesting
                logger.info(f"📊 {symbol}: Confluence {pct:.1f}% < {min_pct}% (Threshold Not Met)")
            else:
                logger.debug(f"📊 {symbol}: Confluence {pct:.1f}% < {min_pct}% threshold → SKIP")
            return None
        
        # --- РАСЧЁТ SL/TP ---
        atr_val = float(atr.iloc[-1])
        entry_price = float(c)
        
        sl_mult = 1.5
        tp_mult = sl_mult * self._phase_config.tp_sl_ratio
        
        if signal_type == SignalType.LONG:
            stop_loss = entry_price - (atr_val * sl_mult)
            take_profit_1 = entry_price + (atr_val * tp_mult)
            take_profit_2 = entry_price + (atr_val * tp_mult * 1.3)
        else:
            stop_loss = entry_price + (atr_val * sl_mult)
            take_profit_1 = entry_price - (atr_val * tp_mult)
            take_profit_2 = entry_price - (atr_val * tp_mult * 1.3)
        
        rr = abs(take_profit_1 - entry_price) / abs(stop_loss - entry_price) if abs(stop_loss - entry_price) > 0 else 0
        
        # --- ОПРЕДЕЛЯЕМ СИЛУ ---
        if pct >= 80:
            strength = SignalStrength.EXTREME
        elif pct >= 65:
            strength = SignalStrength.STRONG
        elif pct >= 50:
            strength = SignalStrength.MODERATE
        else:
            strength = SignalStrength.WEAK
        
        # --- REASONING ---
        reasoning = [
            f"Phase: {self._phase_config.phase.value}",
            f"Confluence: {confluence.total_score}/{self.MAX_CONFLUENCE} ({pct:.1f}%)",
            f"Direction votes: LONG={direction_votes['LONG']} SHORT={direction_votes['SHORT']}",
            f"R:R = 1:{rr:.1f}",
            f"ATR SL: {sl_mult}x, TP: {tp_mult:.1f}x",
            confluence.get_breakdown(),
        ]
        
        warnings = []
        if self._phase_config.phase == AccelPhase.AGGRESSIVE:
            warnings.append("⚡ Aggressive Phase — higher risk")
        if self.anti_tilt.consecutive_losses > 0:
            warnings.append(f"⚠️ {self.anti_tilt.consecutive_losses} recent loss(es)")
        if funding_rate and abs(funding_rate) > 0.001:
            warnings.append(f"⚠️ High funding: {funding_rate:.4f}")
        
        # --- TIMESTAMP ---
        try:
            ts = pd.to_datetime(df.iloc[-1].get('time', df.index[-1]))
        except:
            ts = datetime.now()
        
        valid_until = ts + timedelta(minutes=self._phase_config.valid_minutes)
        
        # --- POSITION SIZE ---
        # Рассчитываем позицию от SL-дистанции
        sl_pct = abs(stop_loss - entry_price) / entry_price
        risk_amount = self.equity * (self._phase_config.risk_per_trade / 100)
        pos_value = risk_amount / sl_pct if sl_pct > 0 else 0
        pos_pct = (pos_value / self.equity * 100) if self.equity > 0 else 0
        
        # Ограничиваем маржу 30%
        max_margin = self.equity * 0.30
        margin_needed = pos_value / self._phase_config.max_leverage
        if margin_needed > max_margin:
            pos_pct = pos_pct * (max_margin / margin_needed)
        
        signal = AdvancedSignal(
            symbol=symbol,
            signal_type=signal_type,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confluence=confluence,
            probability=int(pct),
            strength=strength,
            timeframes_aligned={},
            support_resistance_nearby=None,
            market_regime=self._detect_regime(ema9, ema21, ema55, adx, close),
            risk_reward_ratio=rr,
            position_size_percent=min(pos_pct, 30.0),
            funding_rate=funding_rate,
            funding_interpretation=self._interpret_funding(funding_rate),
            orderbook_imbalance=orderbook_imbalance or 0,
            timestamp=ts,
            valid_until=valid_until,
            indicators={
                'rsi': float(rsi.iloc[-1]),
                'stoch_k': float(stoch_k.iloc[-1]) if not pd.isna(stoch_k.iloc[-1]) else 50,
                'adx': float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0,
                'atr': atr_val,
                'ema9': float(ema9.iloc[-1]),
                'ema21': float(ema21.iloc[-1]),
                'bb_width': float((bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_mid.iloc[-1]) if bb_mid.iloc[-1] > 0 else 0,
                'vol_ratio': float(volume.iloc[-1] / vol_sma.iloc[-1]) if vol_sma.iloc[-1] > 0 else 1,
                'macd_hist': float(macd_hist.iloc[-1]),
                'phase': self._phase_config.phase.value,
                'leverage': self._phase_config.max_leverage,
            },
            reasoning=reasoning,
            warnings=warnings,
        )
        
        logger.info(
            f"🎯 ACCEL SIGNAL: {signal_type.value} {symbol} | "
            f"Score: {pct:.1f}% | Phase: {self._phase_config.phase.value} | "
            f"R:R=1:{rr:.1f} | Entry={entry_price:.4f}"
        )
        
        return signal
    
    # ═══════════════════════════════════════════════════════════
    # SCORING FUNCTIONS (каждая возвращает (score, direction))
    # ═══════════════════════════════════════════════════════════
    
    def _score_ema(self, ema9, ema21, ema55) -> Tuple[int, str]:
        e9, e21, e55 = float(ema9.iloc[-1]), float(ema21.iloc[-1]), float(ema55.iloc[-1])
        pe9, pe21 = float(ema9.iloc[-2]), float(ema21.iloc[-2])
        
        score = 0
        direction = "LONG"
        
        # Alignment
        if e9 > e21 > e55:
            score += 12; direction = "LONG"
        elif e9 < e21 < e55:
            score += 12; direction = "SHORT"
        elif e9 > e21:
            score += 6; direction = "LONG"
        elif e9 < e21:
            score += 6; direction = "SHORT"
        
        # Fresh cross
        if pe9 <= pe21 and e9 > e21:
            score += 8; direction = "LONG"
        elif pe9 >= pe21 and e9 < e21:
            score += 8; direction = "SHORT"
        
        return min(score, 20), direction
    
    def _score_rsi(self, rsi, close) -> Tuple[int, str]:
        val = float(rsi.iloc[-1])
        val_prev = float(rsi.iloc[-5]) if len(rsi) > 5 else val
        c = float(close.iloc[-1])
        c_prev = float(close.iloc[-5]) if len(close) > 5 else c
        
        score = 0
        direction = "LONG"
        
        if val < 25:
            score = 12; direction = "LONG"
        elif val < 35:
            score = 8; direction = "LONG"
        elif val > 75:
            score = 12; direction = "SHORT"
        elif val > 65:
            score = 8; direction = "SHORT"
        
        # Бычья дивергенция
        if c < c_prev and val > val_prev and val < 40:
            score += 3; direction = "LONG"
        # Медвежья дивергенция
        elif c > c_prev and val < val_prev and val > 60:
            score += 3; direction = "SHORT"
        
        return min(score, 15), direction
    
    def _score_macd(self, macd_line, macd_signal, macd_hist) -> Tuple[int, str]:
        ml = float(macd_line.iloc[-1])
        ms = float(macd_signal.iloc[-1])
        mh = float(macd_hist.iloc[-1])
        pml = float(macd_line.iloc[-2])
        pms = float(macd_signal.iloc[-2])
        pmh = float(macd_hist.iloc[-2])
        
        score = 0
        direction = "LONG" if ml > ms else "SHORT"
        
        # MACD > Signal
        if ml > ms:
            score += 5
        else:
            score += 5
        
        # Fresh cross
        if pml <= pms and ml > ms:
            score += 7; direction = "LONG"
        elif pml >= pms and ml < ms:
            score += 7; direction = "SHORT"
        
        # Histogram growing
        if mh > pmh and mh > 0:
            score += 3; direction = "LONG"
        elif mh < pmh and mh < 0:
            score += 3; direction = "SHORT"
        
        return min(score, 15), direction
    
    def _score_bollinger(self, close, bb_upper, bb_lower, bb_mid) -> Tuple[int, str]:
        c = float(close.iloc[-1])
        u = float(bb_upper.iloc[-1])
        l = float(bb_lower.iloc[-1])
        m = float(bb_mid.iloc[-1])
        
        bb_range = u - l
        if bb_range <= 0:
            return 0, "LONG"
        
        position = (c - l) / bb_range
        
        score = 0
        direction = "LONG"
        
        if position < 0.1:
            score = 10; direction = "LONG"
        elif position < 0.25:
            score = 6; direction = "LONG"
        elif position > 0.9:
            score = 10; direction = "SHORT"
        elif position > 0.75:
            score = 6; direction = "SHORT"
        
        # Squeeze bonus
        bb_width = bb_range / m if m > 0 else 0
        width_sma = pd.Series([float(bb_upper.iloc[i] - bb_lower.iloc[i]) / float(bb_mid.iloc[i]) 
                               if float(bb_mid.iloc[i]) > 0 else 0 
                               for i in range(max(0, len(close)-20), len(close))]).mean()
        if bb_width < width_sma * 0.7 and score > 0:
            score += 2  # Squeeze bonus
        
        return min(score, 12), direction
    
    def _score_stoch_rsi(self, k, d) -> Tuple[int, str]:
        kv = float(k.iloc[-1]) if not pd.isna(k.iloc[-1]) else 50
        dv = float(d.iloc[-1]) if not pd.isna(d.iloc[-1]) else 50
        pk = float(k.iloc[-2]) if len(k) > 2 and not pd.isna(k.iloc[-2]) else 50
        pd_val = float(d.iloc[-2]) if len(d) > 2 and not pd.isna(d.iloc[-2]) else 50
        
        score = 0
        direction = "LONG"
        
        if kv < 20 and dv < 20:
            score = 6; direction = "LONG"
            if pk < pd_val and kv > dv:
                score = 10  # Бычий кросс в перепроданности
        elif kv > 80 and dv > 80:
            score = 6; direction = "SHORT"
            if pk > pd_val and kv < dv:
                score = 10
        
        return min(score, 12), direction
    
    def _score_adx(self, adx, plus_di, minus_di) -> Tuple[int, str]:
        a = float(adx.iloc[-1]) if not pd.isna(adx.iloc[-1]) else 0
        di_p = float(plus_di.iloc[-1]) if not pd.isna(plus_di.iloc[-1]) else 0
        di_m = float(minus_di.iloc[-1]) if not pd.isna(minus_di.iloc[-1]) else 0
        
        if a < 20:
            return 0, "LONG"  # No trend
        
        direction = "LONG" if di_p > di_m else "SHORT"
        strength = min((a - 20) / 30, 1.0)
        score = int(strength * 12)
        
        return min(score, 12), direction
    
    def _score_volume(self, volume, vol_sma, close) -> Tuple[int, str]:
        v = float(volume.iloc[-1])
        vs = float(vol_sma.iloc[-1]) if not pd.isna(vol_sma.iloc[-1]) else v
        c_change = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) if float(close.iloc[-2]) > 0 else 0
        
        ratio = v / vs if vs > 0 else 1
        
        score = 0
        direction = "LONG" if c_change > 0 else "SHORT"
        
        if ratio > 2.0:
            score = 10
        elif ratio > 1.5:
            score = 7
        elif ratio > 1.2:
            score = 4
        
        return min(score, 12), direction
    
    def _score_support_resistance(self, high, low, close) -> Tuple[int, str]:
        c = float(close.iloc[-1])
        pivot = (float(high.iloc[-1]) + float(low.iloc[-1]) + c) / 3
        s1 = 2 * pivot - float(high.iloc[-1])
        r1 = 2 * pivot - float(low.iloc[-1])
        
        dist_s = (c - s1) / c if c > 0 else 1
        dist_r = (r1 - c) / c if c > 0 else 1
        
        score = 0
        direction = "LONG"
        
        if dist_s < 0.005:
            score = 10; direction = "LONG"
        elif dist_s < 0.01:
            score = 6; direction = "LONG"
        
        if dist_r < 0.005:
            score = 10; direction = "SHORT"
        elif dist_r < 0.01:
            score = 6; direction = "SHORT"
        
        return min(score, 12), direction
    
    def _score_atr_quality(self, atr, close) -> int:
        """ATR должен быть достаточным для прибыльной торговли, но не экстремальным"""
        atr_pct = float(atr.iloc[-1]) / float(close.iloc[-1]) if float(close.iloc[-1]) > 0 else 0
        
        if 0.005 < atr_pct < 0.03:
            return 8  # Sweet spot
        elif 0.003 < atr_pct < 0.05:
            return 5
        else:
            return 2  # Слишком тихо или слишком волатильно
    
    def _score_funding(self, funding_rate: float) -> Tuple[int, str]:
        if not funding_rate:
            return 0, "LONG"
        
        if funding_rate > 0.001:
            return 8, "SHORT"  # Перекос лонгов → шорт
        elif funding_rate > 0.0005:
            return 4, "SHORT"
        elif funding_rate < -0.001:
            return 8, "LONG"  # Перекос шортов → лонг
        elif funding_rate < -0.0005:
            return 4, "LONG"
        
        return 0, "LONG"
    
    def _score_mtf(self, df_15m, df_1h, df_4h) -> Tuple[int, str]:
        """Бонус за согласованность на старших ТФ"""
        votes = {"LONG": 0, "SHORT": 0}
        
        for df_htf in [df_15m, df_1h, df_4h]:
            if df_htf is not None and len(df_htf) > 30:
                try:
                    c = df_htf['close'].astype(float)
                    e9 = TechnicalIndicators.ema(c, 9)
                    e21 = TechnicalIndicators.ema(c, 21)
                    r = TechnicalIndicators.rsi(c, 14)
                    
                    if float(e9.iloc[-1]) > float(e21.iloc[-1]) and float(r.iloc[-1]) > 45:
                        votes["LONG"] += 1
                    elif float(e9.iloc[-1]) < float(e21.iloc[-1]) and float(r.iloc[-1]) < 55:
                        votes["SHORT"] += 1
                except:
                    pass
        
        agreement = max(votes.values())
        direction = "LONG" if votes["LONG"] >= votes["SHORT"] else "SHORT"
        
        if agreement >= 3:
            return 18, direction
        elif agreement == 2:
            return 12, direction
        elif agreement == 1:
            return 5, direction
        return 0, direction
    
    def _score_open_interest(self, oi_change_pct: float = None) -> Tuple[int, str]:
        if oi_change_pct is None:
            return 0, "LONG"
        
        if oi_change_pct > 5:
            return 7, "LONG"  # Растущий OI → тренд подтверждён
        elif oi_change_pct > 2:
            return 4, "LONG"
        elif oi_change_pct < -5:
            return 4, "SHORT"
        
        return 0, "LONG"
    
    # ═══════════════════════════════════════════════════════════
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ═══════════════════════════════════════════════════════════
    
    def _check_correlation(self, symbol: str) -> bool:
        """Проверка корреляции с открытыми позициями"""
        new_group = get_correlation_group(symbol)
        if not new_group:
            return True
        
        for open_sym in self.open_symbols:
            if open_sym == symbol:
                return False  # Уже открыта
            open_group = get_correlation_group(open_sym)
            if open_group and open_group == new_group:
                return False  # Коррелирующая пара уже открыта
        
        return True

    def _detect_regime(self, ema9, ema21, ema55, adx, close) -> MarketRegime:
        try:
            a = float(adx.iloc[-1])
            e9 = float(ema9.iloc[-1])
            e21 = float(ema21.iloc[-1])
            e55 = float(ema55.iloc[-1])
            
            if a > 25:
                if e9 > e21 > e55: return MarketRegime.STRONG_TREND_UP
                if e9 < e21 < e55: return MarketRegime.STRONG_TREND_DOWN
            
            return MarketRegime.RANGING_WIDE
        except:
            return MarketRegime.RANGING_WIDE

    def _interpret_funding(self, rate: float) -> str:
        if not rate: return "NEUTRAL"
        if rate > 0.0005: return "BEARISH OVERBOUGHT"
        if rate < -0.0005: return "BULLISH OVERSOLD"
        return "NEUTRAL"

    def record_result(self, pnl_usd: float):
        """Коллбек для ExecutionManager при закрытии сделки"""
        if pnl_usd < 0:
            self.anti_tilt.on_loss(pnl_usd)
        else:
            self.anti_tilt.on_win()
