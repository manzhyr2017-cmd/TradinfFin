"""
Execution Manager for Trading AI
================================
Модуль безопасного исполнения ордеров и риск-менеджмента.

Функции:
- Проверка лимитов риска (дневной убыток, макс. позиции)
- Расчет размера позиции с учетом баланса
- Исполнение ордеров через BybitClient
- Логирование сделок
"""

import logging
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from datetime import datetime, date

from bybit_client import BybitClient
from mean_reversion_bybit import AdvancedSignal, SignalType, RiskManager, PerformanceTracker, NewsEngine, NewsSentiment
from trade_logger import get_trade_logger

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Ограничения рисков"""
    max_daily_loss_usd: float = 5000.0      # Буфер для массовых сделок ($5000)
    max_open_positions: int = 50           # До 50 микро-позиций одновременно
    max_leverage: float = 10.0
    risk_per_trade_percent: float = 0.01   # Минимальный базовый риск
    max_position_size_usd: float = 100.0   # FIXED: Лимит $100 на одну сделку
    
    # Capital Accelerator (Step 1)
    compounding_enabled: bool = True
    acceleration_enabled: bool = True
    limit_sniper_enabled: bool = True
    vip_boost_enabled: bool = False         # Отключаем агрессивный буст для тестов
    
    # Phase 7: Dynamic settings
    atr_threshold_high: float = 0.03       # 3% ATR = high volatility
    atr_threshold_low: float = 0.01        # 1% ATR = low volatility
    
    # --- VOLATILITY HUNTER & SMART RISK (NEW) ---
    btc_vol_threshold_5m: float = 0.012    # 1.2% move in 5min on BTC pauses alts
    min_confidence_scale: float = 60.0     # Min confidence to start scaling
    max_confidence_scale: float = 95.0     # Max confidence for max scaling
    risk_multi_max: float = 1.5            # Max multiplier for high confidence (e.g. 1% -> 1.5%)
    risk_multi_min: float = 0.5            # Min multiplier for low confidence (e.g. 1% -> 0.5%)
    
    def get_dynamic_leverage(self, atr_percent: float) -> float:
        """
        Phase 7: Dynamic Leverage based on ATR.
        High volatility = lower leverage, Low volatility = higher leverage.
        """
        if atr_percent > self.atr_threshold_high:
            # High volatility: reduce to 2x
            return 2.0
        elif atr_percent > self.atr_threshold_low:
            # Normal: use 3x
            return 3.0
        else:
            # Low volatility: can use up to max
            return min(self.max_leverage, 5.0)
    
    def get_volatility_adjusted_risk(self, atr_percent: float, base_risk: float = None) -> float:
        """
        Phase 7: Volatility-Based Position Sizing.
        High ATR = smaller position, Low ATR = larger position.
        """
        base = base_risk or self.risk_per_trade_percent
        
        if atr_percent > self.atr_threshold_high:
            # High volatility: reduce risk to 50%
            return base * 0.5
        elif atr_percent > self.atr_threshold_low:
            # Normal: standard risk
            return base
        else:
            # Low volatility: can increase risk by 25%
            return base * 1.25


class ExecutionManager:
    """Менеджер исполнения сделок с интеграцией Tradingfin3.0"""
    
    def __init__(
        self, 
        client: BybitClient, 
        risk_limits: Optional[RiskLimits] = None,
        dry_run: bool = False,
        news_service: Optional[object] = None,
        analytics: Optional[object] = None,
        risk_manager: Optional[RiskManager] = None,
        performance_tracker: Optional[PerformanceTracker] = None,
        news_engine: Optional[NewsEngine] = None
    ):
        self.client = client
        self.risk_limits = risk_limits or RiskLimits()
        self.dry_run = dry_run
        self.news_service = news_service
        self.analytics = analytics
        
        # Tradingfin3.0 Integration
        self.risk_manager = risk_manager
        self.performance_tracker = performance_tracker
        self.news_engine = news_engine
        
        # Session state (legacy)
        self.daily_pnl = 0.0
        self.daily_loss = 0.0
        self.last_reset_date = date.today()
        self.circuit_triggered = False
        
        # Phase 5: Cooldown after losses
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.cooldown_until = None  # datetime when cooldown ends
        self.max_consecutive_losses = 3  # Trigger cooldown after 3 losses
        self.cooldown_minutes = 60  # 1 hour cooldown
        self.trade_logger = get_trade_logger()
        
        # V4.1: Initialize Enhanced Risk Manager if not provided
        if self.risk_manager is None:
            try:
                # Если нет валидных API ключей, используем fallback баланс
                if hasattr(self.client, 'has_valid_api') and not self.client.has_valid_api:
                    equity = 10000.0
                    logger.info("💰 No valid API keys, using fallback equity: $10000.00")
                else:
                    equity = self.client.get_total_equity()
                    if equity is None or equity <= 0:
                        equity = 10000.0
                from enhanced_risk_manager import EnhancedRiskManager
                self.risk_manager = EnhancedRiskManager(
                    total_capital=equity,
                    daily_loss_limit=0.10,      # 10% limit for testing
                    max_drawdown_limit=0.20,
                    max_positions=200,          # Практически безлимит
                    state_file="risk_state.json",
                )
                logger.info(f"✅ EnhancedRiskManager initialized with capital: ${equity:.2f}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize EnhancedRiskManager: {e}")
        
        # V4.1: Initialize Enhanced Performance Tracker if not provided
        if self.performance_tracker is None:
            try:
                # Если нет валидных API ключей, используем fallback баланс
                if hasattr(self.client, 'has_valid_api') and not self.client.has_valid_api:
                    equity = 10000.0
                    logger.info("💰 No valid API keys, using fallback equity: $10000.00")
                else:
                    equity = self.client.get_total_equity()
                    if equity is None or equity <= 0:
                        equity = 10000.0
                from enhanced_performance import EnhancedPerformanceTracker
                self.performance_tracker = EnhancedPerformanceTracker(initial_capital=equity)
                logger.info(f"✅ EnhancedPerformanceTracker initialized with capital: ${equity:.2f}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to initialize EnhancedPerformanceTracker: {e}")
        self.open_positions: Dict[str, dict] = {}
        self.symbol_blacklist: Dict[str, datetime] = {} # Symbol -> expiry_time
        
        # Accelerator State (Phase 9)
        try:
            self.initial_equity = self.client.get_total_equity()
            if self.initial_equity is None or self.initial_equity <= 0:
                self.initial_equity = 10000.0 # Standard fallback
        except:
            self.initial_equity = 10000.0
            
        logger.info(f"ExecutionManager initialized. Initial Equity: ${self.initial_equity:.2f}")
        logger.info(f"  Max Positions: {self.risk_limits.max_open_positions}")

    def calculate_kelly_size(self, win_rate: float, avg_win: float, avg_loss: float) -> float:
        """
        Calculates Conservative Kelly Size (25% of full Kelly)
        Kelly % = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
        """
        if avg_win <= 0 or win_rate <= 0:
            return 0.0
            
        kelly_pct = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        # Use Quarter Kelly for safety
        return max(0.0, min(kelly_pct * 0.25, self.risk_limits.risk_per_trade_percent / 100))

    def check_circuit_breaker(self, trade_pnl: float, total_capital: float) -> bool:
        """
        Circuit breaker logic from Ultimate Bot upgrade
        """
        today = date.today()
        if today != self.last_reset_date:
            self.daily_pnl = 0.0
            self.circuit_triggered = False
            self.last_reset_date = today
            
        self.daily_pnl += trade_pnl
        daily_loss_pct = self.daily_pnl / total_capital if total_capital > 0 else 0
        
        # If daily loss exceeds limit (e.g. 5%)
        if daily_loss_pct <= -0.05: # 5% limit
            self.circuit_triggered = True
            logger.error(f"🚨 CIRCUIT BREAKER TRIGGERED! Daily loss: {daily_loss_pct*100:.2f}%")
            return True
            
        return False
        
    
    def _reset_daily_stats_if_needed(self):
        """Reset daily stats"""
        today = date.today()
        if today != self.last_reset_date:
            logger.info("Resetting daily risk stats")
            self.daily_loss = 0.0
            self.last_reset_date = today
    
    def can_trade(self) -> bool:
        """Проверка возможности торговать"""
        self._reset_daily_stats_if_needed()
        
        # Проверка дневного лимита убытков
        if self.daily_loss >= self.risk_limits.max_daily_loss_usd:
            logger.warning(f"⛔ Торговля остановлена: превышен дневной лимит убытка (${self.daily_loss:.2f})")
            return False
        
        # Phase 5: Cooldown check
        if self.cooldown_until:
            if datetime.now() < self.cooldown_until:
                remaining = (self.cooldown_until - datetime.now()).seconds // 60
                logger.warning(f"❄️ Cooldown активен: {remaining} мин до возобновления торговли (после {self.consecutive_losses} убытков подряд)")
                return False
            else:
                # Cooldown ended
                logger.info("✅ Cooldown завершен. Торговля возобновлена.")
                self.cooldown_until = None
                self.consecutive_losses = 0

        # Phase 8: News Event Check
        if self.news_service and hasattr(self.news_service, 'check_danger_zone'):
            danger = self.news_service.check_danger_zone()
            if danger:
                event_name = danger.get('name', 'Unknown Event')
                logger.warning(f"🛑 NEWS PROTECT: Trading paused due to high-impact event: {event_name}")
                return False
        
        # --- BTC CIRCUIT BREAKER (NEW) ---
        if self.client:
            try:
                # Get BTC 5m change
                btc_df = self.client.get_klines("BTCUSDT", "5m", limit=2)
                if not btc_df.empty and len(btc_df) >= 2:
                    current_btc = btc_df['close'].iloc[-1]
                    prev_btc = btc_df['open'].iloc[-1]
                    btc_change = abs(current_btc - prev_btc) / prev_btc
                    if btc_change > self.risk_limits.btc_vol_threshold_5m:
                        logger.warning(f"🚨 BTC CIRCUIT BREAKER: BTC volatility too high ({btc_change*100:.2f}% in 5m). Alt-trading paused.")
                        return False
            except Exception as e:
                logger.debug(f"BTC Circuit Breaker check failed: {e}")
            
        return True
    
    def record_trade_result(self, is_win: bool, pnl: float = 0.0):
        """
        Phase 5: Records trade result for cooldown logic.
        Call this after a trade closes.
        """
        if is_win:
            self.consecutive_losses = 0
            self.daily_pnl += abs(pnl)
            logger.info(f"✅ Win recorded. Consecutive losses reset. Daily PnL: ${self.daily_pnl:.2f}")
        else:
            self.consecutive_losses += 1
            self.daily_loss += abs(pnl)
            self.daily_pnl -= abs(pnl)
            logger.info(f"❌ Loss #{self.consecutive_losses} recorded. Daily Loss: ${self.daily_loss:.2f}. Daily PnL: ${self.daily_pnl:.2f}")
            
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
                logger.warning(f"❄️ COOLDOWN ACTIVATED: {self.cooldown_minutes} minutes (after {self.consecutive_losses} losses)")
            
            # --- SYMBOL BLACKLIST (NEW) ---
            if hasattr(self, 'current_symbol'): # Assuming current_symbol is set before trade
                symbol = self.current_symbol
                expiry = datetime.now() + timedelta(hours=2)
                self.symbol_blacklist[symbol] = expiry
                logger.info(f"🚫 {symbol} blacklisted for 2 hours due to Loss.")

        
    def check_correlation(self, symbol: str, side: str, open_positions: List[Dict]) -> bool:
        """
        Directional Guard (Phase 8): 
        1. Запрещает открывать сделки в РАЗНЫХ направлениях для коррелирующих активов (напр. BTC Long + ETH Short = Ошибка).
        2. Ограничивает количество позиций в одной группе для снижения риска концентрации.
        """
        # Correlation Groups
        correlation_groups = [
            ['BTC', 'ETH', 'SOL', 'BNB', 'AVAX'],  # Blue Chips (high correlation)
            ['DOGE', 'SHIB', 'PEPE', 'FLOKI', 'WIF'],  # Meme Coins
            ['FET', 'AGIX', 'RNDR', 'WLD'],  # AI Coins
            ['MATIC', 'ARB', 'OP', 'MANTA'],  # L2s
            ['ATOM', 'TIA', 'INJ', 'SEI'],  # Cosmos Ecosystem
        ]
        
        # Извлекаем тикер (без USDT/USDC)
        ticker = symbol.replace('USDT', '').replace('USDC', '')
        
        # Find which group this ticker belongs to
        my_group = None
        for group in correlation_groups:
            if ticker in group:
                my_group = group
                break
        
        # Если монета не в списках, она всё равно может зависеть от BTC (Глобальный поводырь)
        if my_group is None:
            # Если это не BTC, но открыта позиция по BTC, проверяем направление
            my_group = ['BTC', ticker] if ticker != 'BTC' else None

        if my_group is None:
            return True
            
        for pos in open_positions:
            pos_ticker = pos['symbol'].replace('USDT', '').replace('USDC', '')
            
            if pos_ticker in my_group and pos_ticker != ticker:
                pos_side = pos['side'].upper() # 'BUY' or 'SELL'
                new_side = side.upper() # 'BUY' or 'SELL'
                
                # КРИТИЧЕСКОЕ ПРАВИЛО: Направление должно совпадать
                if pos_side != new_side:
                    logger.warning(f"❌ КОНФЛИКТ КОРРЕЛЯЦИИ: {pos['symbol']} в {pos_side}, а {symbol} хочет в {new_side}. Пропуск.")
                    return False
                
                # ПРАВИЛО КОНЦЕНТРАЦИИ: Не более 3 позиций на группу (повышено для лучшей доходности)
                group_count = sum(1 for p in open_positions if p['symbol'].replace('USDT', '').replace('USDC', '') in my_group)
                if group_count >= 3:
                    logger.warning(f"⚠️ РИСК КОНЦЕНТРАЦИИ: В группе уже {group_count} позиций. Пропуск {symbol}.")
                    return False
        
        return True
    
    def check_funding_rate_bias(self, symbol: str, side: str, funding_rate: Optional[float]) -> bool:
        """
        Phase 4: Funding Rate Signal Integration.
        Avoids going against extreme funding (e.g., don't LONG if funding is extremely positive = crowded long).
        """
        if funding_rate is None:
            return True  # No data, allow
        
        # Extreme thresholds
        EXTREME_LONG_FUNDING = 0.001  # 0.1% (8h) = crowded long
        EXTREME_SHORT_FUNDING = -0.001  # -0.1% (8h) = crowded short
        
        if side.upper() == "BUY" and funding_rate > EXTREME_LONG_FUNDING:
            logger.warning(f"⚠️ Funding Rate Filter: Skipping LONG {symbol}. Funding={funding_rate*100:.4f}% (Crowded Long).")
            return False
        
        if side.upper() == "SELL" and funding_rate < EXTREME_SHORT_FUNDING:
            logger.warning(f"⚠️ Funding Rate Filter: Skipping SHORT {symbol}. Funding={funding_rate*100:.4f}% (Crowded Short).")
            return False
        
        return True
    
    def get_performance_multiplier(self) -> float:
        """
        Step 1: Capital Accelerator logic.
        Returns a multiplier for risk based on account growth.
        """
        if not self.risk_limits.acceleration_enabled:
            return 1.0
            
        try:
            current_equity = self.client.get_total_equity()
            initial_equity = getattr(self, 'initial_equity', 10000.0)
            growth_pct = (current_equity - initial_equity) / initial_equity
            
            # Scale risk based on growth
            if growth_pct > 0.50: return 1.5  # 50% profit -> 1.5x risk
            if growth_pct > 0.25: return 1.3  # 25% profit -> 1.3x risk
            if growth_pct > 0.10: return 1.2  # 10% profit -> 1.2x risk
            if growth_pct < -0.10: return 0.8 # 10% loss -> 0.8x risk (De-acceleration)
            
        except Exception as e:
            logger.error(f"Error calculating performance multiplier: {e}")
            
        return 1.0

    def _check_liquidity_barriers(self, symbol: str, side: str, entry: float, tp: float) -> bool:
        """
        Whale Watcher (Phase 9): Analyses order book depth to find liquidity walls.
        If a massive wall (>3x avg) is blocking our TP, it's a risky trade.
        """
        try:
            # Fetch deeper orderbook
            ob = self.client.get_orderbook(symbol, depth=50)
            
            # Extract volumes
            bids = ob.get('bid_volume', 0)
            asks = ob.get('ask_volume', 0)
            avg_volume = (bids + asks) / 100 # Avg per level
            
            # Logic: If we are LONG, check ASK side for walls
            # If we are SHORT, check BID side for walls
            wall_threshold = avg_volume * 10.0 # Increased from 3x to 10x for "Turbo" mode
            min_wall_value_usd = 5000.0 # Don't trip over small walls (< $5k)
            
            # We need raw data for precise wall hunting
            raw_ob = self.client._request('/v5/market/orderbook', {
                'category': self.client.category.value, 'symbol': symbol, 'limit': 30
            })
            
            levels = raw_ob.get('a', []) if side.upper() == 'BUY' else raw_ob.get('b', [])
            
            # Check only nearby walls (within 0.5% of entry)
            for price_str, size_str in levels:
                p, s = float(price_str), float(size_str)
                dist_pct = abs(p - entry) / entry
                wall_value = p * s
                
                if dist_pct < 0.005 and s > wall_threshold and wall_value > min_wall_value_usd:
                    logger.warning(f"🐋 WHALE WATCHER: Massive wall at {p} (${wall_value:.1f}) detected within 0.5%. Skipping {symbol}.")
                    return False
                    
            return True
        except Exception as e:
            logger.warning(f"Whale Watcher error: {e}")
            return True # Don't block on error

    def _get_atr_percent(self, symbol: str) -> float:
        """Calculates ATR % for the last 14 candles (15m)"""
        try:
            df = self.client.get_klines(symbol, "15m", limit=30)
            if len(df) < 14: return 0.02 # Fallback 2%
            
            import pandas_ta as ta
            df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
            latest_atr = df['ATR'].iloc[-1]
            latest_price = df['close'].iloc[-1]
            
            return latest_atr / latest_price
        except:
            return 0.02

    def _optimize_entry_price(self, symbol: str, side: str, desired_price: float) -> float:
        """
        Step 2: Order Book Sniper.
        Analyzes the order book to find the best entry as a Maker.
        """
        if not self.risk_limits.limit_sniper_enabled:
            return desired_price
            
        try:
            ob = self.client.get_orderbook(symbol, depth=5)
            best_bid = ob['best_bid']
            best_ask = ob['best_ask']
            
            if side.upper() == 'BUY':
                # Try to buy at best bid or slightly above (but below ask)
                if best_bid > 0:
                    # If our signal price is much higher than market, just follow market
                    # But don't pay more than signal price
                    optimized = min(desired_price, best_bid)
                    logger.info(f"🎯 SNIPER: Optimized BUY entry {desired_price} -> {optimized} (Best Bid: {best_bid})")
                    return optimized
            else:
                # Try to sell at best ask or slightly below (but above bid)
                if best_ask > 0:
                    optimized = max(desired_price, best_ask)
                    logger.info(f"🎯 SNIPER: Optimized SELL entry {desired_price} -> {optimized} (Best Ask: {best_ask})")
                    return optimized
                    
        except Exception as e:
            logger.warning(f"Sniper optimization failed: {e}")
            
        return desired_price

    def execute_signal(self, signal: AdvancedSignal, risk_override: Optional[float] = None, sentiment_service=None) -> bool:
        """
        Исполняет торговый сигнал (Sniper Mode)
        
        Args:
            signal: Объект сигнала
            risk_override: Переопределение % риска
            sentiment_service: SentimentService для проверки направления
            
        Returns:
            bool: True если ордер отправлен успешно
        """
        if not self.can_trade():
            return False, "Daily loss limit or Cooldown/News protection"
        
        # --- SNIPER MODE: Daily Trade Limit ---
        try:
            from trade_logger import get_trade_logger
            trade_logger = get_trade_logger()
            # Check daily trade limit (Currently disabled by User)
            # if not trade_logger.can_trade_today():
            #     return False
            pass
        except ImportError:
            pass  # Logger not available, continue
        
        # --- TREND REGIME DIRECTION FILTER ---
        if sentiment_service:
            allowed = sentiment_service.allowed_direction
            side = 'LONG' if signal.signal_type.value == 'LONG' else 'SHORT'
            
            if allowed == 'NONE':
                msg = "🛑 RISK_OFF: Trading halted by Sentiment Service."
                logger.warning(msg)
                return False, msg
            
            if allowed == 'LONG_ONLY' and side == 'SHORT':
                msg = f"📈 TREND_UP: Only LONGs allowed. Skipping SHORT {signal.symbol}."
                logger.warning(msg)
                return False, msg
            
            if allowed == 'SHORT_ONLY' and side == 'LONG':
                msg = f"📉 TREND_DOWN: Only SHORTs allowed. Skipping LONG {signal.symbol}."
                logger.warning(msg)
                return False, msg
            
        logger.info(f"🚀 Исполнение сигнала: {signal.symbol} {signal.signal_type.value}")
        
        try:
            # 1. Проверяем открытые позиции
            positions = self.client.get_open_positions()
            if len(positions) >= self.risk_limits.max_open_positions:
                msg = f"Пропуск: достигнут лимит позиций ({len(positions)}/{self.risk_limits.max_open_positions})"
                logger.warning(msg)
                return False, msg
            
            # Если уже есть позиция по этому символу - пропускаем
            for pos in positions:
                if pos['symbol'] == signal.symbol:
                    msg = f"Пропуск: уже есть позиция по {signal.symbol}"
                    logger.warning(msg)
                    return False, msg

            # --- BLACKLIST CHECK (NEW) ---
            if signal.symbol in self.symbol_blacklist:
                if datetime.now() < self.symbol_blacklist[signal.symbol]:
                    remaining = (self.symbol_blacklist[signal.symbol] - datetime.now()).seconds // 60
                    msg = f"🚫 {signal.symbol} is in bad-trade blacklist ({remaining} min left). Skipping."
                    logger.warning(msg)
                    return False, msg
                else:
                    del self.symbol_blacklist[signal.symbol]
            
            self.current_symbol = signal.symbol # Save for record_trade_result

            # --- CORRELATION FILTER (Phase 2) ---
            side = 'Buy' if signal.signal_type == SignalType.LONG else 'Sell'
            if not self.check_correlation(signal.symbol, side, positions):
                msg = "Conflict with existing positions (Correlation/Concentration)"
                logger.warning(msg)
                return False, msg
            
            # --- FUNDING RATE FILTER (Phase 4) ---
            if not self.check_funding_rate_bias(signal.symbol, side, signal.funding_rate):
                msg = "Extreme Funding Rate (Crowded Side)"
                logger.warning(msg)
                return False, msg
            
            # Если нет валидных API ключей, используем fallback баланс
            if hasattr(self.client, 'has_valid_api') and not self.client.has_valid_api:
                balance = 10000.0
                available_balance = balance * 0.98
                logger.info(f"💰 No valid API keys, using fallback: Equity=${balance:.2f}, Available=${available_balance:.2f}")
            else:
                balance = self.client.get_total_equity()
                available_balance = self.client.get_wallet_balance('USDT', available_only=True)
                
                # Fallback: if balance is 0, use 10000 as default (for demo trading or API issues)
                if balance <= 0:
                    logger.warning(f"💰 Balance is 0 or negative, using fallback: $10000.00")
                    balance = 10000.0
                if available_balance <= 0:
                    available_balance = balance * 0.98  # Use 98% of equity as available
                    logger.info(f"💰 Available balance is 0, using fallback: ${available_balance:.2f}")
            
            if available_balance <= 1.0 and balance > 10 and len(positions) == 0:
                logger.info(f"ℹ️ Use Equity as available margin (Correction for UTA reporting glitch): Avail=${available_balance:.2f} -> ${balance*0.98:.2f}")
                available_balance = balance * 0.98 
            
            # --- MARGIN RECOVERY (Phase 10) ---
            # If we have equity but NO available margin, it's usually because of open LIMIT orders.
            if balance > 10 and available_balance <= 1.0:
                logger.warning(f"⚠️ Low margin (Avail: ${available_balance:.2f}). Attempting recovery by cancelling open orders...")
                try:
                    self.client.cancel_all_orders() # Cancel global USDT orders
                    import time
                    time.sleep(1) # Give Bybit a second to update
                    available_balance = self.client.get_wallet_balance('USDT', available_only=True)
                    logger.info(f"🔄 Recovered available margin: ${available_balance:.2f}")
                except Exception as e:
                    logger.error(f"Failed to recover margin: {e}")

            if balance <= 0 or (available_balance <= 0 and balance > 0):
                msg = f"Ошибка: Недостаточно средств для маржи (Equity: {balance:.2f}, Available: {available_balance:.2f})"
                if available_balance <= 0 and balance > 0:
                    msg += " | Подсказка: Проверьте, не занята ли маржа другими позициями или ордерами."
                logger.error(msg)
                return False, msg
                
            logger.info(f"💰 Актуальный баланс: Equity=${balance:.2f}, Available=${available_balance:.2f}")
            
            # 3. Рассчитываем размер позиции
            
            # Получаем инфо об инструменте для точности
            instr_info = self.client.get_instrument_info(signal.symbol)
            lot_filter = instr_info.get('lotSizeFilter', {})
            price_filter = instr_info.get('priceFilter', {})

            def _parse_float(val, default):
                try:
                    if val is None or str(val).strip() == "": return default
                    return float(val)
                except: return default

            qty_step = _parse_float(lot_filter.get('qtyStep'), 0.001)
            min_qty = _parse_float(lot_filter.get('minOrderQty'), 0.001)
            price_tick = _parse_float(price_filter.get('tickSize'), 0.01)
            
            # --- CIRCUIT BREAKER ---
            if self.circuit_triggered:
                return False, "🚨 Trading HALTED by Circuit Breaker (Max daily loss reached)"

            # --- KELLY CRITERION SIZING ---
            kelly_risk = None
            if self.analytics:
                try:
                    metrics = self.analytics.calculate_metrics()
                    if metrics['total_trades'] >= 10:
                        kelly_risk = self.calculate_kelly_size(
                            win_rate=metrics['win_rate'] / 100,
                            avg_win=metrics['avg_win'],
                            avg_loss=abs(metrics['avg_loss'])
                        )
                        if kelly_risk > 0:
                            logger.info(f"🧬 Kelly Sizing: Optimized Risk {kelly_risk*100:.2f}% (based on {metrics['total_trades']} trades)")
                except Exception as e:
                    logger.warning(f"Failed to calculate Kelly: {e}")

            # Риск в %: Приоритет risk_override -> Kelly -> конфиг
            base_risk = risk_override if risk_override is not None else (kelly_risk * 100 if kelly_risk else self.risk_limits.risk_per_trade_percent)
            
            # --- CAPITAL ACCELERATOR MULTIPLIER ---
            perf_multiplier = self.get_performance_multiplier()

            # --- VOLATILITY-BASED RISK (Phase 9) ---
            atr_pct = self._get_atr_percent(signal.symbol)
            vol_risk = self.risk_limits.get_volatility_adjusted_risk(atr_pct, base_risk)
            effective_risk = vol_risk * perf_multiplier
            
            if vol_risk != base_risk:
                logger.info(f"🛡️ Volatility sizing: ATR={atr_pct*100:.2f}%. Risk adjusted {base_risk:.1f}% -> {vol_risk:.1f}%")

            # --- WHALE WATCHER (Phase 9) ---
            # Now enabled and optimized for scalping
            if not self._check_liquidity_barriers(signal.symbol, side, signal.entry_price, signal.take_profit_1):
                return False, "Whale wall found blocking movement"
            
            # --- SMART RISK SCALER (NEW) ---
            confidence = getattr(signal, 'probability', 0) or getattr(signal.confluence, 'percentage', 0)
            tp_multiplier = 1.0
            if confidence >= self.risk_limits.min_confidence_scale:
                # Linear scale from risk_multi_min to risk_multi_max
                scale_range = self.risk_limits.max_confidence_scale - self.risk_limits.min_confidence_scale
                norm_conf = (confidence - self.risk_limits.min_confidence_scale) / scale_range
                norm_conf = max(0, min(1, norm_conf))
                
                multi_range = self.risk_limits.risk_multi_max - self.risk_limits.risk_multi_min
                smart_multiplier = self.risk_limits.risk_multi_min + (norm_conf * multi_range)
                
                effective_risk *= smart_multiplier
                # If confidence is extreme, aim for higher TP
                if confidence > 85: tp_multiplier = 1.5
                elif confidence > 75: tp_multiplier = 1.2
                
                logger.info(f"🧬 Smart Risk Scaler: Conf {confidence}% -> Risk {effective_risk:.2f}%, TP Multi {tp_multiplier}x")

            # --- ADAPTIVE TP/SL (Phase 11) ---
            # Adjust TP based on ATR and Confidence
            atr_pct = self._get_atr_percent(signal.symbol)
            if hasattr(signal, 'take_profit_1'):
                # Base TP on Volatility or default
                base_tp_pct = max(0.005, atr_pct * 1.5) # Aim for 1.5x ATR move
                final_tp_pct = base_tp_pct * tp_multiplier
                
                if signal.signal_type == SignalType.LONG:
                    signal.take_profit_1 = signal.entry_price * (1 + final_tp_pct)
                    signal.stop_loss = signal.entry_price * (1 - (final_tp_pct / 1.5)) # Maintain 1.5 RR
                else:
                    signal.take_profit_1 = signal.entry_price * (1 - final_tp_pct)
                    signal.stop_loss = signal.entry_price * (1 + (final_tp_pct / 1.5))
                
                logger.info(f"🎯 ADAPTIVE TARGETS: TP set to {final_tp_pct*100:.2f}% (ATR-based with {tp_multiplier}x boost)")

            # --- VIP SIGNAL BOOST (Disabled for uniform testing) ---
            if self.risk_limits.vip_boost_enabled and hasattr(signal, 'is_vip') and signal.is_vip:
                effective_risk = max(effective_risk, 2.0)  # Lower boost to 2%
                logger.info(f"⭐ VIP BOOST: Risk increased to {effective_risk}% for {signal.symbol}")
            
            # 2. Расчет в USD
            risk_usd = balance * (effective_risk / 100)
            
            # --- MINIMUM RISK PROTECTION ---
            if risk_usd < 10.0 and balance > 1000:
                risk_usd = 10.0 # Минимум $10 риска на сделку
            
            # Дистанция до стопа %
            stop_loss_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
            
            if stop_loss_pct < 0.005:
                logger.info(f"🛡️ Трейд слишком рискованный (SL {stop_loss_pct*100:.2f}% < 0.5%). Корректировка сайзинга.")
                stop_loss_pct = 0.005
                
            if stop_loss_pct == 0:
                msg = "Ошибка: Стоп-лосс равен цене входа"
                logger.error(msg)
                return False, msg
                
            # --- POSITION SIZING LOGGING ---
            logger.info(f"📐 Sizing: Risk=${risk_usd:.2f}, SL_dist={stop_loss_pct*100:.2f}%, PosPrice={signal.entry_price}")
            
            # Размер позиции в USDT = Риск / Стоп%
            position_size_usd = risk_usd / stop_loss_pct
            
            # --- POSITION CAPS ---
            # 1. Лимит плеча
            max_pos_leverage = balance * self.risk_limits.max_leverage
            # 2. Жесткий лимит из конфига
            max_pos_hard = self.risk_limits.max_position_size_usd
            
            final_max_pos = min(max_pos_leverage, max_pos_hard)
            
            if position_size_usd > final_max_pos:
                logger.info(f"🛠️ POSITION SIZING: Calculated ${position_size_usd:.0f} exceeds limit. Capping at ${final_max_pos:.0f}")
                position_size_usd = final_max_pos
            
            # Проверка минимальной стоимости ордера (обычно $5 на Bybit)
            if position_size_usd < 6.0: 
               if position_size_usd < 5.0 and balance < 100:
                   logger.warning(f"Позиция ${position_size_usd:.2f} слишком мала для Bybit (<$5), а баланс мал. Пропуск.")
                   return False
               elif position_size_usd < 5.0:
                    logger.warning(f"Позиция ${position_size_usd:.2f} < $5. Увеличиваем до мин. лимита $6.")
                    position_size_usd = 6.0
            
            # Кол-во монет
            qty = position_size_usd / signal.entry_price
            
            # --- SAFETY CLAMP: Exchange Max Quantity ---
            max_qty = _parse_float(lot_filter.get('maxOrderQty'), 1e12)
            if qty > max_qty:
                logger.warning(f"🚨 Qty {qty} exceeds Exchange Max {max_qty}. Clamping...")
                qty = max_qty
                
            # --- CIRCUIT BREAKER: Anomaly Check ---
            # If QTY is astronomically high (e.g. > 10^12), something is likely wrong with price/units
            if qty > 1e12 and signal.symbol not in ['SHIBUSDT', 'BONKUSDT', 'PEPEUSDT']:
                 msg = f"❌ ANOMALY: Qty {qty} is too large. Aborting to protect capital."
                 logger.error(msg)
                 return False, msg

            # SMART ROUNDING (Умное округление)
            from decimal import Decimal, ROUND_FLOOR, ROUND_DOWN
            
            # Using Decimal for precise lot sizing
            d_qty = Decimal(str(qty))
            d_step = Decimal(str(qty_step))
            d_min = Decimal(str(min_qty))
            
            # Floor to nearest step
            qty_final = (d_qty / d_step).quantize(Decimal('1'), rounding=ROUND_FLOOR) * d_step
            
            # Normalize to avoid scientific notation and floating point junk
            qty_final = qty_final.normalize()
            
            if qty_final < d_min:
                msg = f"Количество {qty_final} меньше минимального {d_min}. Пропуск."
                logger.warning(msg)
                return False, msg
                
            qty = float(qty_final)
            
            # 4. Исполнение (Настройка + Ордер)
            side = 'Buy' if signal.signal_type == SignalType.LONG else 'Sell'
            
            # --- SNIPER: ENTRY OPTIMIZATION ---
            final_entry = self._optimize_entry_price(signal.symbol, side, signal.entry_price)

            # --- MARGIN CHECK & AUTO-SCALING ---
            # Determine leverage BEFORE placing order for margin check
            leverage = self.risk_limits.get_dynamic_leverage(atr_pct)
            required_margin = (qty * final_entry) / leverage
            
            # Buffer for fees and slippage (10%)
            # Buffer for fees and slippage (Flexible 5-10%)
            if required_margin > (available_balance * 0.95):
                logger.warning(f"⚠️ Low Balance Warning: Need ${required_margin:.2f}, Have ${available_balance:.2f}")
                
                # Attempt to fit trade into 95% of available balance
                old_qty = qty
                max_margin_usable = available_balance * 0.95
                qty = (max_margin_usable * leverage) / final_entry
                
                # Re-apply rounding
                qty_final = (Decimal(str(qty)) / Decimal(str(qty_step))).quantize(Decimal('1'), rounding=ROUND_FLOOR) * Decimal(str(qty_step))
                qty = float(qty_final.normalize())
                
                new_margin = (qty * final_entry) / leverage
                
                if qty < min_qty:
                    msg = f"Insufficient funds: Have ${available_balance:.2f}, Need min ${((min_qty*final_entry)/leverage):.2f}"
                    logger.error(msg)
                    return False, msg
                    
                logger.warning(f"📉 Downsizing Position: {old_qty} -> {qty} (Margin: ${new_margin:.2f})")

            logger.info(f"🚀 Итоговый расчет: Кол-во={qty}, Плечо={leverage}x, Маржа=${(qty*final_entry/leverage):.2f}")
            
            if self.dry_run:
                logger.info("[DRY RUN] Ордер бы был отправлен:")
                logger.info(f"  Side: {signal.signal_type.value}")
                logger.info(f"  Qty: {qty}")
                logger.info(f"  Price: {final_entry}")
                logger.info(f"  SL: {signal.stop_loss}")
                logger.info(f"  TP: {signal.take_profit_1}")
                return True, "DRY_RUN: Order simulated successfully"
            
            # Установка плеча и режима маржи
            leverage = self.risk_limits.get_dynamic_leverage(atr_pct)
            self.client.switch_margin_mode(signal.symbol, is_isolated=True, leverage=leverage)
            self.client.set_leverage(signal.symbol, leverage)
            logger.info(f"⚙️ Dynamic Leverage set to {leverage}x (based on ATR)")
            
            # Limit Order Execution (Fee Saving & Slippage Protection)
            order_type = 'Limit'
            price = final_entry
            
            # Use PostOnly to ensure Maker rebate (if supported/configured)
            # For now, just Limit is enough improvement over Market
            
            logger.info(f"⚙️ Placing {order_type} Order at {price}")
            
            response = self.client.place_order(
                symbol=signal.symbol,
                side=side,
                qty=qty,
                price=price,
                order_type=order_type,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit_1
            )
            
            order_id = response.get('orderId') or response.get('orderLinkId', 'N/A')
            logger.info(f"✅ Ордер отправлен успешно! ID: {order_id} (Type: {order_type} @ {price})")
            
            # --- UNIFIED LOGGING & SAFETY GUARDIAN ---
            try:
                # 1. Log the trade
                t_logger = get_trade_logger()
                t_logger.log_trade_open(
                    symbol=signal.symbol,
                    side=side,
                    price=final_entry,
                    qty=qty,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit_1,
                    order_id=order_id,
                    status="OPEN",
                    confluence_score=int(signal.confluence.percentage) if hasattr(signal.confluence, 'percentage') else 0,
                    risk_reward=signal.risk_reward_ratio,
                    regime=signal.market_regime.value if hasattr(signal.market_regime, 'value') else str(signal.market_regime)
                )

                # 2. SAFETY GUARDIAN: Verify TP/SL were actually accepted by Bybit
                # Sometimes Market orders execute so fast that params are ignored or rejected silently
                import time
                time.sleep(1) # Give Bybit API 1 second to update position state
                
                full_pos = self.client.get_open_positions(symbol=signal.symbol)
                if full_pos:
                    p = full_pos[0] # Should be our position
                    p_sl = float(p.get('stop_loss', 0))
                    p_tp = float(p.get('take_profit', 0))
                    
                    # If protection is missing, FORCE it immediately
                    if p_sl == 0 or p_tp == 0:
                        logger.warning(f"🛡️ Safety Guardian: TP/SL missing for {signal.symbol}! Forcing update...")
                        # The client method now handles rounding internally
                        self.client.set_trading_stop(
                            symbol=signal.symbol,
                            stop_loss=signal.stop_loss,
                            take_profit=signal.take_profit_1,
                            position_idx=p.get('position_idx', 0) 
                        )
                        logger.info(f"✅ Safety Guardian: Protection ENFORCED for {signal.symbol} (idx: {p.get('position_idx', 0)})")
                    else:
                        logger.info(f"🛡️ Safety Guardian: TP/SL verified for {signal.symbol}")
                else:
                    logger.warning(f"🛡️ Safety Guardian: Could not find position for {signal.symbol} to verify TP/SL")

            except Exception as e:
                logger.error(f"Unified Log/Safety Error: {e}")
            # ------------------
            
            return True, str(order_id)
            
        except Exception as e:
            msg = f"❌ Ошибка исполнения: {e}"
            logger.error(msg)
            return False, msg

    def check_trailing_stop(self):
        """
        Dynamic Trailing Stop:
        - Default: Trail by initial risk distance (1:1).
        - Level 1 (PnL > 1.0%): Tighten to 0.3%.
        - Level 2 (PnL > 2.0%): Tighten to 0.1% (Lock profits).
        """
        try:
            positions = self.client.get_open_positions()
            for pos in positions:
                symbol = pos['symbol']
                size = float(pos.get('size', 0))
                if size == 0: continue

                entry_price = float(pos.get('entry_price', 0))
                stop_loss = float(pos.get('stop_loss', 0) or 0)
                
                # Safe Price Resolution
                mark = float(pos.get('mark_price', 0))
                current_price = mark if mark > 0 else entry_price
                
                if entry_price == 0: continue
                
                # Current Trailing Distance (e.g. 50.0)
                active_trail = float(pos.get('trailing_stop', 0) or 0)
                
                # Calculate PnL %
                side = pos['side']
                if side == 'Buy' or side == 'Long':
                    pnl_pct = (current_price - entry_price) / entry_price
                else:
                    pnl_pct = (entry_price - current_price) / entry_price
                
                # Determine Target Trail Distance
                target_dist = 0.0
                
                # Base Risk Distance
                base_dist = abs(entry_price - stop_loss) if stop_loss > 0 else (entry_price * 0.01)
                
                # Tiered Logic
                if pnl_pct > 0.02: # > 2% Profit
                    target_dist = entry_price * 0.001 # 0.1% Ultra Tight
                elif pnl_pct > 0.01: # > 1% Profit
                    target_dist = entry_price * 0.003 # 0.3% Tight
                elif active_trail == 0: # Only set initial if not present
                    target_dist = base_dist
                    
                # If target is defined and different from active
                if target_dist > 0:
                    # Logic to minimize API calls:
                    # 1. If no active trail, set it.
                    # 2. If active trail is much looser than target (e.g. current 0.5%, target 0.1%), update it.
                    # We accept implied volatility, so we don't loosen it (target < active).
                    
                    needs_update = False
                    if active_trail == 0:
                        needs_update = True
                    elif target_dist < (active_trail * 0.9): # Tighten by at least 10%
                        needs_update = True
                        
                    if needs_update:
                        logger.info(f"⚡ Trailing Stop Update for {symbol}: {active_trail} -> {target_dist:.4f} (PnL {pnl_pct*100:.1f}%)")
                        self.client.set_trading_stop(
                            symbol=symbol,
                            trailing_stop=target_dist,
                            position_idx=pos.get('position_idx', 0)
                        )
                        
        except Exception as e:
            logger.error(f"Error in trailing stop: {e}")
        
        return # Skip old logic

        try:
            positions = self.client.get_open_positions()
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side'] # Buy or Sell
                entry_price = float(pos.get('entry_price', 0))
                size = float(pos.get('size', 0))
                stop_loss = float(pos.get('stop_loss', 0) or 0)
                take_profit = float(pos.get('take_profit', 0) or 0)
                
                if size == 0: 
                    continue

                # Get current ticker price
                ticker_data = self.client._request("/v5/market/tickers", {"category": self.client.category.value, "symbol": symbol})
                if not ticker_data or 'list' not in ticker_data or not ticker_data['list']:
                    continue
                
                current_price = float(ticker_data['list'][0]['lastPrice'])
                
                # Calculate PnL %
                if side == 'Buy' or side == 'Long':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                    side_key = 'Buy'
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                    side_key = 'Sell'
                    
                # 1. Break-Even at > 1.0% profit
                if pnl_pct > 1.0:
                    new_sl = 0.0
                    if side_key == 'Buy':
                        target_sl = entry_price * 1.001 # 0.1% profit
                        if stop_loss < target_sl:
                            new_sl = target_sl
                    else:
                        target_sl = entry_price * 0.999 # 0.1% profit
                        if stop_loss == 0 or stop_loss > target_sl:
                            new_sl = target_sl
                            
                    if new_sl > 0:
                        logger.info(f"🔄 Moving SL to Break-Even for {symbol}: {new_sl} (PnL: {pnl_pct:.2f}%)")
                        
                        # Use the client helper which handles rounding
                        self.client.set_trading_stop(
                            symbol=symbol,
                            stop_loss=new_sl,
                            take_profit=take_profit if take_profit > 0 else None,
                            position_idx=pos.get('position_idx', 0)
                        )
        
        except Exception as e:
            logger.error(f"Error in trailing stop: {e}")

    def check_time_exits(self, max_hold_hours: int = 6):
        """
        TIME BASED EXITS DISABLED per User Request.
        """
        return

        try:
            positions = self.client.get_open_positions()
            now = datetime.now().timestamp() * 1000 # ms
            
            for pos in positions:
                created_time = pos.get('created_time', 0)
                if created_time == 0:
                    continue
                    
                hold_duration_ms = now - created_time
                hold_hours = hold_duration_ms / (1000 * 60 * 60)
                
                if hold_hours > max_hold_hours:
                    symbol = pos['symbol']
                    side = pos['side']
                    size = pos['size']
                    
                    logger.warning(f"⌛ TIME_EXIT: {symbol} удерживается {hold_hours:.1f}ч > {max_hold_hours}ч. Закрытие.")
                    
                    close_side = 'Sell' if side == 'Buy' else 'Buy'
                    self.client.place_order(
                        symbol=symbol,
                        side=close_side,
                        qty=size,
                        order_type='Market'
                    )
                    
        except Exception as e:
            logger.error(f"Error in check_time_exits: {e}")

    def execute_grid_orders(self, symbol: str, orders: List[object]) -> int:
        """
        Исполняет пачку Grid ордеров.
        Принимает список объектов GridOrder (duck typing).
        """
        if not self.can_trade():
            return 0
            
        if self.dry_run:
            logger.info(f"[DRY RUN] Would place {len(orders)} GRID Limit orders for {symbol}")
            return len(orders)
            
        success_count = 0
        try:
            # 1. Отменяем старые ордера (для чистоты эксперимента)
            # В реальной сетке так делать нельзя (потеря очереди), но для старта ок
            self.client.cancel_all_orders(symbol)
            
            # 2. Выставляем новые
            for order in orders:
                try:
                    # Корректировка сайзинга под риск (опционально)
                    # Но Gridengine уже посчитал qty исходя из баланса.
                    # Просто исполняем.
                    
                    side = order.side.capitalize() # 'Buy' or 'Sell'
                    
                    resp = self.client.place_order(
                        symbol=symbol,
                        side=side,
                        qty=order.qty,
                        price=order.price,
                        order_type='Limit'
                    )
                    if resp and 'orderId' in resp:
                        success_count += 1
                        
                except Exception as oe:
                    logger.error(f"Grid order failed {order}: {oe}")
                    
            logger.info(f"🕸️ Placed {success_count}/{len(orders)} GRID orders for {symbol}")
            
        except Exception as e:
            logger.error(f"Grid execution error: {e}")
            
        return success_count

    def panic_close_all(self) -> Dict[str, int]:
        """
        ЭКСТРЕННОЕ ЗАКРЫТИЕ ВСЕХ ПОЗИЦИЙ И ОРДЕРОВ.
        """
        logger.warning("🚨 [PANIC] Инициировано полное закрытие всех позиций!")
        
        results = {"positions_closed": 0, "orders_cancelled": 0}
        
        try:
            # 1. Отмена всех активных ордеров (на всех рынках/символах)
            # В Bybit V5 можно отменить все ордера для категории
            self.client.cancel_all_orders("") # Пустая строка часто означает "все" в обертках, либо цикл по активным
            
            # 2. Получение и закрытие всех позиций
            positions = self.client.get_open_positions()
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side']
                size = pos['size']
                
                if float(size) == 0: continue
                
                # Сторона для закрытия - противоположная
                close_side = 'Sell' if side == 'Buy' else 'Buy'
                
                logger.info(f"🚨 [PANIC] Закрытие {symbol} ({side} {size})")
                
                try:
                    # Market Order for instant exit
                    self.client.place_order(
                        symbol=symbol,
                        side=close_side,
                        qty=float(size),
                        order_type='Market'
                    )
                    results["positions_closed"] += 1
                except Exception as e:
                    logger.error(f"Failed to panic close {symbol}: {e}")
                    
            return results
            
        except Exception as e:
            logger.error(f"Panic operation failed: {e}")
            return results

    # ═══════════════════════════════════════════════════════════
    # TRADINGFIN3.0 INTEGRATION METHODS
    # ═══════════════════════════════════════════════════════════

    def check_trading_allowed(self, symbol: str, position_size_usd: float, 
                              current_volatility: float = 0.0, 
                              normal_volatility: float = 0.0) -> Tuple[bool, str]:
        """
        Проверка возможности торговли через улучшенный RiskManager.
        Использует Circuit Breaker, Drawdown Protection и Cooldown.
        """
        if not self.risk_manager:
            return True, "RiskManager not initialized"
        
        return self.risk_manager.can_open_trade(
            symbol=symbol,
            position_size_usd=position_size_usd,
            current_volatility=current_volatility,
            normal_volatility=normal_volatility
        )

    def register_position(self, symbol: str, side: str, entry_price: float,
                         position_size: float, confluence_score: float = 0.0):
        """Регистрация открытой позиции в RiskManager"""
        if self.risk_manager:
            self.risk_manager.register_position(symbol, side, entry_price, position_size, confluence_score)

    def close_position(self, symbol: str, exit_price: float, pnl: float,
                      trade_details: Optional[dict] = None):
        """Закрытие позиции и обновление статистики"""
        if self.risk_manager:
            self.risk_manager.close_position(symbol, exit_price, pnl)
        
        if self.performance_tracker and trade_details:
            self.performance_tracker.add_trade(trade_details)

    def get_performance_report(self) -> dict:
        """Получение полного отчета о производительности"""
        if not self.performance_tracker:
            return {"error": "PerformanceTracker not initialized"}
        
        return self.performance_tracker.get_statistics()

    def get_risk_status(self) -> dict:
        """Получение полного статуса рисков"""
        if not self.risk_manager:
            return {"error": "RiskManager not initialized"}
        
        return self.risk_manager.get_status_report()

    def get_news_sentiment(self, currency: str) -> Optional[NewsSentiment]:
        """Получение новостного сентимента через NewsEngine"""
        if not self.news_engine:
            return None
        
        return self.news_engine.get_market_sentiment(currency)
