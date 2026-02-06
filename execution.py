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
from typing import Optional, Dict, List
from datetime import datetime, date

from bybit_client import BybitClient
from mean_reversion_bybit import AdvancedSignal, SignalType
from trade_logger import get_trade_logger

logger = logging.getLogger(__name__)


@dataclass
class RiskLimits:
    """Ограничения рисков"""
    max_daily_loss_usd: float = 200.0       # Increased daily loss buffer
    max_open_positions: int = 15            # XP Mode: Allow many positions
    max_leverage: float = 10.0             # Allow higher leverage for small positions
    risk_per_trade_percent: float = 1.5    # Moderate risk per trade
    
    # Capital Accelerator (Step 1)
    compounding_enabled: bool = True       # Реинвест прибыли
    acceleration_enabled: bool = True      # Увеличение риска при серии побед
    limit_sniper_enabled: bool = True      # Вход лимитками для экономии комиссии
    
    # Phase 7: Dynamic settings
    atr_threshold_high: float = 0.03       # 3% ATR = high volatility
    atr_threshold_low: float = 0.01        # 1% ATR = low volatility
    
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
    """Менеджер исполнения сделок"""
    
    def __init__(
        self, 
        client: BybitClient, 
        risk_limits: Optional[RiskLimits] = None,
        dry_run: bool = False,
        news_service: Optional[object] = None
    ):
        self.client = client
        self.risk_limits = risk_limits or RiskLimits()
        self.dry_run = dry_run
        self.news_service = news_service
        
        # Session state
        self.daily_loss = 0.0
        self.last_reset_date = date.today()
        
        # Phase 5: Cooldown after losses
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.cooldown_until = None  # datetime when cooldown ends
        self.max_consecutive_losses = 3  # Trigger cooldown after 3 losses
        self.cooldown_minutes = 60  # 1 hour cooldown
        
        # Accelerator State
        self.initial_equity = self.client.get_total_equity()
        if self.initial_equity is None:
            self.initial_equity = 100.0 # Fallback 
        
        logger.info(f"ExecutionManager initialized. Initial Equity: ${self.initial_equity:.2f}")
        logger.info(f"  Dry Run: {dry_run}")
        logger.info(f"  Max Positions: {self.risk_limits.max_open_positions}")
    
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
            
        return True
    
    def record_trade_result(self, is_win: bool, pnl: float = 0.0):
        """
        Phase 5: Records trade result for cooldown logic.
        Call this after a trade closes.
        """
        if is_win:
            self.consecutive_losses = 0
            logger.info(f"✅ Win recorded. Consecutive losses reset.")
        else:
            self.consecutive_losses += 1
            self.daily_loss += abs(pnl)
            logger.info(f"❌ Loss #{self.consecutive_losses} recorded. Daily Loss: ${self.daily_loss:.2f}")
            
            if self.consecutive_losses >= self.max_consecutive_losses:
                self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
                logger.warning(f"❄️ COOLDOWN ACTIVATED: {self.cooldown_minutes} minutes (after {self.consecutive_losses} losses)")

        
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
            growth_pct = (current_equity - self.initial_equity) / self.initial_equity
            
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
            wall_threshold = avg_volume * 4.0 # 400% of average depth
            
            # We need raw data for precise wall hunting
            raw_ob = self.client._request('/v5/market/orderbook', {
                'category': 'linear', 'symbol': symbol, 'limit': 50
            })
            
            levels = raw_ob.get('a', []) if side.upper() == 'BUY' else raw_ob.get('b', [])
            
            for price_str, size_str in levels:
                p, s = float(price_str), float(size_str)
                
                # Check if level is between entry and TP
                is_between = (entry < p < tp) if side.upper() == 'BUY' else (tp < p < entry)
                
                if is_between and s > wall_threshold:
                    logger.warning(f"🐋 WHALE WATCHER: Found massive wall at {p} ({s:.1f} coins). Blocking our TP. Skipping.")
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

            balance = self.client.get_total_equity()
            available_balance = self.client.get_wallet_balance('USDT', available_only=True)
            
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
            
            # Риск в %: Приоритет risk_override -> конфиг
            base_risk = risk_override if risk_override is not None else self.risk_limits.risk_per_trade_percent
            
            # --- CAPITAL ACCELERATOR MULTIPLIER ---
            perf_multiplier = self.get_performance_multiplier()

            # --- VOLATILITY-BASED RISK (Phase 9) ---
            atr_pct = self._get_atr_percent(signal.symbol)
            vol_risk = self.risk_limits.get_volatility_adjusted_risk(atr_pct, base_risk)
            effective_risk = vol_risk * perf_multiplier
            
            if vol_risk != base_risk:
                logger.info(f"🛡️ Volatility sizing: ATR={atr_pct*100:.2f}%. Risk adjusted {base_risk}% -> {vol_risk:.1f}%")

            # --- WHALE WATCHER (Phase 9) --- (Disabled for better trade frequency)
            # if not self._check_liquidity_barriers(signal.symbol, side, signal.entry_price, signal.take_profit_1):
            #     return False, "Whale wall found blocking TP"
            pass

            # --- VIP SIGNAL BOOST (5% for top Selector coins) ---
            if hasattr(signal, 'is_vip') and signal.is_vip:
                effective_risk = max(effective_risk, 5.0)  # At least 5%
                logger.info(f"⭐ VIP BOOST: Risk increased to {effective_risk}% for {signal.symbol}")
            
            # Риск в $ = Баланс * Риск%
            risk_usd = balance * (effective_risk / 100)
            
            # Дистанция до стопа %
            stop_loss_pct = abs(signal.entry_price - signal.stop_loss) / signal.entry_price
            
            if stop_loss_pct < 0.005:
                logger.info(f"🛡️ Трейд слишком рискованный (SL {stop_loss_pct*100:.2f}% < 0.5%). Корректировка сайзинга.")
                stop_loss_pct = 0.005
                
            if stop_loss_pct == 0:
                msg = "Ошибка: Стоп-лосс равен цене входа"
                logger.error(msg)
                return False, msg
                
            # Размер позиции в USDT = Риск / Стоп%
            position_size_usd = risk_usd / stop_loss_pct
            
            # Ограничиваем плечом (Position < Balance * MaxLeverage)
            max_pos_usd = balance * self.risk_limits.max_leverage
            
            if position_size_usd > max_pos_usd:
                logger.warning(f"Уменьшение позиции с ${position_size_usd:.0f} до ${max_pos_usd:.0f} (лимит плеча)")
                position_size_usd = max_pos_usd
            
            # Проверка минимальной стоимости ордера (обычно $5 на Bybit)
            if position_size_usd < 6.0: 
               # Если позиция меньше $6, пробуем увеличить до минимума, ЕСЛИ риск позволяет
               # Но лучше просто пропустить, чтобы не нарушать риск менджмент
               # Или если у пользователя $50 баланс, то сделка $2 вообще невозможна.
               if position_size_usd < 5.0 and balance < 100:
                   logger.warning(f"Позиция ${position_size_usd:.2f} слишком мала для Bybit (<$5), а баланс мал. Пропуск.")
                   return False
               elif position_size_usd < 5.0:
                    logger.warning(f"Позиция ${position_size_usd:.2f} < $5. Увеличиваем до мин. лимита $6.")
                    position_size_usd = 6.0
            
            # Кол-во монет
            qty = position_size_usd / signal.entry_price
            
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
            
            # Отправка ордера (Используем Market для гарантированного входа в Sniper режиме)
            response = self.client.place_order(
                symbol=signal.symbol,
                side=side,
                qty=qty,
                price=None, # Market
                order_type='Market',
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit_1
            )
            
            order_id = response.get('orderId') or response.get('orderLinkId', 'N/A')
            logger.info(f"✅ Ордер отправлен успешно! ID: {order_id} (Type: Market)")
            
            # --- UNIFIED LOGGING ---
            try:
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
                    confluence_score=getattr(signal, 'confluence_score', 0),
                    risk_reward=getattr(signal, 'risk_reward', 0)
                )
            except Exception as e:
                logger.error(f"Unified Log Error: {e}")
            # ------------------
            
            return True, str(order_id)
            
        except Exception as e:
            msg = f"❌ Ошибка исполнения: {e}"
            logger.error(msg)
            return False, msg

    def check_trailing_stop(self):
        """
        Проверяет и обновляет трейлинг-стоп для открытых позиций.
        Логика:
        1. Если прибыль > 1% -> Ставим SL в безубыток (+0.1%)
        2. Если прибыль > 2.5% -> Подтягиваем SL за ценой (Trailing)
        """
        if not self.can_trade() or self.dry_run:
            return

        try:
            positions = self.client.get_open_positions()
            for pos in positions:
                symbol = pos['symbol']
                side = pos['side'] # Buy or Sell
                entry_price = float(pos['avgPrice'])
                size = float(pos['size'])
                stop_loss = float(pos.get('stopLoss', 0) or 0)
                
                if size == 0: continue

                # Получаем текущую цену
                # В идеале лучше получать ticker один раз для всех, но пока так
                ticker = self.client._request(f"/v5/market/tickers?category=linear&symbol={symbol}")
                if not ticker or 'list' not in ticker or not ticker['list']:
                    continue
                
                current_price = float(ticker['list'][0]['lastPrice'])
                
                # Расчет PnL %
                if side == 'Buy':
                    pnl_pct = (current_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - current_price) / entry_price * 100
                    
                # 1. Безубыток (Break-Even) при > 1% профита
                if pnl_pct > 1.0:
                    new_sl = 0.0
                    if side == 'Buy':
                        # Ставим чуть выше входа для покрытия комиссий
                        target_sl = entry_price * 1.002 
                        if stop_loss < target_sl: # Если SL ниже безубытка
                            new_sl = target_sl
                    else:
                        target_sl = entry_price * 0.998
                        if stop_loss == 0 or stop_loss > target_sl:
                            new_sl = target_sl
                            
                    if new_sl > 0:
                        logger.info(f"🔄 Moving SL to Break-Even for {symbol}: {new_sl}")
                        self.client._request('/v5/order/create', {
                            'category': 'linear',
                            'symbol': symbol,
                            'action': 'Move', # Используем tradingStop (редактирование позиции)
                             # В V5 редактирование SL делается через tpslMode='Full' или просто setTradingStop
                        }, method='POST', signed=True) 
                        
                        # Корректный метод для V5 - set_trading_stop
                        # Но так как его нет в client, используем универсальный request
                        params = {
                            'category': 'linear',
                            'symbol': symbol,
                            'stopLoss': str(round(new_sl, 4)),
                            'positionIdx': 0 # 0 for one-way mode
                        }
                        self.client._request('/v5/position/trading-stop', params, method='POST', signed=True)
        
        except Exception as e:
            logger.error(f"Error in trailing stop: {e}")

    def check_time_exits(self, max_hold_hours: int = 6):
        # Hot-reload config for max_hold_hours
        try:
            import json
            with open('bot_config.json', 'r') as f:
                config = json.load(f)
                max_hold_hours = int(config.get('time_exit_hours', max_hold_hours))
        except Exception:
            pass
        """
        Проверяет и закрывает позиции, которые удерживаются слишком долго
        """
        if not self.can_trade() or self.dry_run:
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
