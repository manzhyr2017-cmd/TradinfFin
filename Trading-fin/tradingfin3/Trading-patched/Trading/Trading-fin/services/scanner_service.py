import asyncio
import time
import logging
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from main_bybit import TradingBot

from bybit_client import MarketData
from mean_reversion_bybit import AdvancedSignal, format_signal, generate_test_data
from trade_logger import get_trade_logger

logger = logging.getLogger(__name__)

class ScannerService:
    """Сервис для сканирования рынка и управления циклом мониторинга"""
    
    def __init__(self, bot: 'TradingBot'):
        self.bot = bot
        self.blacklist = [
            'USDC', 'USD', 'DAI', 'USDT', 'BUSD', 'TUSD', 'UST',
            'PIPPINUSDT', 'MEUSDT', 'ZKPUSDT', 'RIVERUSDT', 'GPSUSDT'
        ]
        
    def scan_symbol(self, market_data: MarketData) -> Optional[AdvancedSignal]:
        """Анализирует один символ"""
        # Blacklist check
        if market_data.symbol in self.blacklist:
            return None

        # Relax requirement for scalping
        if self.bot.strategy_name == "scalping":
            if market_data.df_1m.empty or market_data.df_5m.empty:
                logger.info(f"⚠️ {market_data.symbol}: Missing 1m/5m data")
                return None
            # ── Предварительные проверки для скальпинга ──
            # Ensure enough data points for scalping strategy analysis
            if len(market_data.df_1m) < 100 or len(market_data.df_5m) < 50:
                logger.info(f"⚠️ {market_data.symbol}: Not enough data for scalping (1m: {len(market_data.df_1m)}/100, 5m: {len(market_data.df_5m)}/50)")
                return None
        elif market_data.df_1h.empty:
            logger.info(f"⚠️ {market_data.symbol}: Missing 1h data")
            return None
        
        if self.bot.strategy_name == "mean_reversion" and market_data.df_4h.empty:
            logger.info(f"⚠️ {market_data.symbol}: Missing 4h data for mean_reversion")
            return None
            
        funding_rate = market_data.funding_rate
        ob_data = None
        orderbook_imbalance = None
        if self.bot.client and not self.bot.demo_mode:
            try:
                ob_data = self.bot.client.get_orderbook(market_data.symbol)
                orderbook_imbalance = ob_data.get('imbalance')
            except:
                pass

        if self.bot.strategy_name == "trend":
            return self.bot.engine.analyze(market_data.df_1h, market_data.symbol)
        elif self.bot.strategy_name == "breakout":
            return self.bot.engine.analyze(market_data.df_15m, market_data.symbol)
        elif self.bot.strategy_name == "acceleration":
            # Acceleration strategy uses kwargs for funding/imbalance
            return self.bot.engine.analyze(
                market_data.df_15m, # Use 5m/15m timeframe
                market_data.symbol, 
                funding_rate=funding_rate,
                orderbook_imbalance=orderbook_imbalance
            )
        elif self.bot.strategy_name in ["scalping", "new_scalping"]:
            # Scalping engines (Ultra and New) use 1m, 5m, 15m
            return self.bot.engine.analyze(
                df_1m=market_data.df_1m,
                df_5m=market_data.df_5m,
                df_15m=market_data.df_15m,
                symbol=market_data.symbol,
                orderbook=ob_data,
                funding_rate=funding_rate
            )
        else:
            return self.bot.engine.analyze(
                market_data.df_15m,
                market_data.df_1h,
                market_data.df_4h,
                market_data.symbol,
                funding_rate=funding_rate,
                orderbook_imbalance=orderbook_imbalance
            )
    
    async def scan_all(self) -> List[AdvancedSignal]:
        """Унифицированный метод сканирования и исполнения сигналов"""
        
        # 1. SENTIMENT FILTER (The General)
        if hasattr(self.bot, 'sentiment_service') and self.bot.sentiment_service:
            regime = self.bot.sentiment_service.regime
            allowed = getattr(self.bot.sentiment_service, 'allowed_direction', 'BOTH')
            reason = self.bot.sentiment_service.reasoning # Define reason here
            
            if allowed == "NONE":
                logger.warning(f"⛔ Market is RISK_OFF ({reason}). Trading HALTED.")
                return []
            
            if regime == "RISK_OFF":
                if self.bot.strategy_name != "scalping":
                    logger.warning(f"⛔ Market is RISK_OFF ({reason}). Trading HALTED for strategy '{self.bot.strategy_name}'.")
                    return []
                else:
                    logger.info(f"⚠️ Market is RISK_OFF ({reason}), but continuing with SCALPING mode (high frequency).")
            
            if regime == "RISK_OFF" and allowed != "BOTH":
                 logger.info(f"⚠️ Market Regime: {regime} | Allowed: {allowed}")

            if regime == "RISK_ON":
                logger.info(f"✅ Market is RISK_ON. Direction: {allowed}")

        # --- DYNAMIC SYMBOL SELECTION ---
        # If no fixed symbols are provided, use top picks from SelectorService
        if not self.bot.scanner.symbols or len(self.bot.scanner.symbols) <= 3:
             if hasattr(self.bot, 'selector_service') and self.bot.selector_service:
                 longs = self.bot.selector_service.primary_list[:15]
                 shorts = self.bot.selector_service.secondary_list[:15]
                 combined = list(set(longs + shorts))
                 if combined:
                     logger.info(f"🔄 Updating scanner with dynamic picks: {len(combined)} symbols (15L/15S)")
                     self.bot.scanner.symbols = combined

        # 2. TURBO PARALLEL FETCH (8GB RAM mode)
        self.bot.stats['scans'] += 1
        signals = []
        
        symbols = self.bot.scanner.symbols
        
        # --- SMART LOSS COOLDOWN (NEW) ---
        # Don't trade symbols that just hit a LOSS (revenge trading prevention)
        loss_symbols = []
        try:
            recent = get_trade_logger().get_recent_trades(30)
            now = datetime.now()
            for t in recent:
                if t.get('status') == 'LOSS':
                    t_time = datetime.fromisoformat(t['timestamp'])
                    if (now - t_time).total_seconds() < 7200: # 2 hour cooldown
                        loss_symbols.append(t['symbol'])
            
            if loss_symbols:
                loss_symbols = list(set(loss_symbols))
                logger.info(f"🛡️ Smart Cooldown: Ignoring {len(loss_symbols)} losing symbols: {', '.join(loss_symbols)}")
        except Exception as e:
            logger.error(f"Cooldown check error: {e}")

        logger.info(f"🔍 Starting Turbo-Parallel Scan of {len(symbols)} symbols...")
        
        # Fetch all market data at once
        tasks = [self.bot.client.get_complete_market_data_async(s) for s in symbols]
        all_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        fetched = len([r for r in all_results if r and not isinstance(r, Exception)])
        logger.info(f"✅ Fast-Scan Data Fetched: {fetched}/{len(symbols)} coins")
        
        for i, market_data in enumerate(all_results):
            symbol = symbols[i]
            if not market_data or isinstance(market_data, Exception):
                continue
            
            if symbol in loss_symbols:
                continue # Skip losing symbols
                
            try:
                self.bot.stats['symbols_scanned'] += 1
                logger.debug(f"🔍 Analyzing {symbol}...")
                
                # Analyze immediately
                signal = self.scan_symbol(market_data)
                
                if signal:
                    self.bot.stats['signals_found'] += 1
                    
                    # Log finding a raw signal
                    logger.info(f"📡 Found Raw Signal: {symbol} {signal.signal_type.value} ({signal.probability}%)")

                    if signal.probability >= self.bot.min_probability:
                        # --- SENTIMENT FILTER ---
                        if hasattr(self.bot, 'sentiment_service'):
                            allowed = getattr(self.bot.sentiment_service, 'allowed_direction', 'BOTH')
                            from mean_reversion_bybit import SignalType
                            
                            reject = False
                            if (allowed == "LONG_ONLY" and signal.signal_type != SignalType.LONG) or \
                               (allowed == "SHORT_ONLY" and signal.signal_type != SignalType.SHORT) or \
                               (allowed == "NONE"):
                                reject = True
                                
                            if reject:
                                logger.info(f"⏭️ {symbol} Rejected: Market Regime ({allowed})")
                                continue

                        # --- ML & NEWS FILTERS (TURBO) ---
                        if hasattr(self.bot, 'ml_service') and self.bot.ml_service and self.bot.ml_service.is_ready:
                            try:
                                ml_res = self.bot.ml_service.predict(market_data.get('df_15m'))
                                prediction, confidence = ml_res['prediction'], ml_res['confidence']
                                from mean_reversion_bybit import SignalType
                                if (signal.signal_type == SignalType.LONG and prediction < 0) or \
                                   (signal.signal_type == SignalType.SHORT and prediction > 0):
                                    if confidence > 0.65: 
                                        logger.info(f"⏭️ {symbol} Rejected: ML Disagreement (Conf: {confidence:.2f})")
                                        continue
                            except Exception as e:
                                logger.error(f"ML Step Error: {e}")

                        if hasattr(self.bot, 'news_service') and self.bot.news_service:
                            news_res = await self.bot.news_service.get_symbol_sentiment(symbol)
                            if (signal.signal_type == SignalType.LONG and news_res['score'] < -0.35) or \
                               (signal.signal_type == SignalType.SHORT and news_res['score'] > 0.35):
                                logger.info(f"⏭️ {symbol} Rejected: Poor News Sentiment ({news_res['score']:.2f})")
                                continue

                        signals.append(signal)
                        self.bot.signals_history.append(signal)
                        self.bot.stats['signals_qualified'] += 1
                        
                        logger.info(f"🎯 SIGNAL QUALIFIED: {symbol} {signal.signal_type.value} ({signal.probability}%)")
                        
                        # --- TELEGRAM (PRIORITY) ---
                        tg_sent = False
                        # Try interactive bot first (with buttons)
                        if hasattr(self.bot, 'telegram_bot') and self.bot.telegram_bot:
                            try:
                                logger.info(f"📨 TG (Interactive): Sending for {symbol}...")
                                await self.bot.telegram_bot.send_signal_with_actions(signal)
                                tg_sent = True
                            except Exception as te:
                                logger.error(f"❌ TG Bot Error: {te}")
                        
                        # Fallback to simple notifier if bot failed or not available
                        if not tg_sent and hasattr(self.bot, 'telegram') and self.bot.telegram:
                            try:
                                logger.info(f"📨 TG (Notifier): Sending for {symbol}...")
                                await self.bot.telegram.send(signal) # Async await instead of sync
                            except Exception as te:
                                logger.error(f"❌ TG Notifier Error: {te}")

                        # --- EXECUTION ---
                        if self.bot.execution and self.bot.auto_trade:
                            logger.info(f"⚙️ EXECUTING: {symbol}...")
                            if hasattr(self.bot.execution, 'execute_signal_async'):
                                await self.bot.execution.execute_signal_async(signal)
                            else:
                                self.bot.execution.execute_signal(signal)
                    else:
                        logger.info(f"⏭️ {symbol} Rejected: Low Prob ({signal.probability}% < {self.bot.min_probability}%)")

            except Exception as e:
                logger.error(f"Error scanning {symbol}: {e}")
        
        return signals
        
        return signals

    def _demo_scan(self) -> List[AdvancedSignal]:
        """Демо сканирование"""
        import random
        signals = []
        
        for symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT']:
            df_15m = generate_test_data(500)
            df_1h = df_15m.iloc[::4].reset_index(drop=True)
            df_4h = df_15m.iloc[::16].reset_index(drop=True)
            
            signal = self.bot.engine.analyze(
                df_15m, df_1h, df_4h, symbol,
                funding_rate=random.uniform(-0.001, 0.001),
                orderbook_imbalance=random.uniform(0.5, 2.0)
            )
            
            if signal and signal.probability >= self.bot.min_probability:
                signals.append(signal)
                self.bot.signals_history.append(signal)
                self.bot.stats['signals_qualified'] += 1
        
        self.bot.stats['symbols_scanned'] += 5
        return signals

    async def run_continuous_async(self, interval_minutes: int = 15):
        """Непрерывный мониторинг (async version)"""
        
        # Start Sentiment Service if available
        if hasattr(self.bot, 'sentiment_service') and self.bot.sentiment_service and not self.bot.sentiment_service.is_running:
            import asyncio
            asyncio.create_task(self.bot.sentiment_service.start(interval_hours=1))
            
        logger.info(f"Мониторинг каждые {interval_minutes} мин (Async)")
        
        try:
            while True:
                if not self.bot.is_active:
                    await asyncio.sleep(5)
                    continue
                    
                # DYNAMIC SYMBOL UPDATE
                if self.bot.selector_service and self.bot.selector_service.primary_list:
                    # Merge Shortlist + Longlist
                    dynamic_list = self.bot.selector_service.get_combined_list()
                    if dynamic_list:
                        self.bot.scanner.symbols = dynamic_list
                        logger.info(f"📋 Scanner List Updated ({len(dynamic_list)} coins): {dynamic_list[:5]}...")
                    
                logger.info(f"--- Scan Cycle {self.bot.stats['scans'] + 1} ---")
                
                leader_symbol = 'BTCUSDT'
                regime_info = "Unknown"
                active_strategy = "MEAN_REVERSION"
                recommendation = "Hold"
                
                try:
                    df = None
                    if self.bot.demo_mode:
                        import numpy as np
                        dates = pd.date_range(end=datetime.now(), periods=100, freq='15min')
                        df = pd.DataFrame({
                            'startTime': dates,
                            'open': 50000 + np.random.randn(100)*100,
                            'close': 50000 + np.random.randn(100)*100,
                            'high': 50200, 'low': 49800, 'volume': 1000
                        })
                        
                    elif self.bot.client:
                        loop = asyncio.get_running_loop()
                        klines = await loop.run_in_executor(
                            None, 
                            lambda: self.bot.client.get_kline("linear", leader_symbol, "15", 100)
                        )
                        
                        if klines['retCode'] == 0:
                            raw = klines['result']['list']
                            if raw:
                                df = pd.DataFrame(raw, columns=['startTime', 'open', 'high', 'low', 'close', 'volume', 'turnover'])
                                df = df.astype(float).sort_values('startTime').reset_index(drop=True)
                    
                    if df is not None and not df.empty:
                        # Use new Strategy Router
                        regime = self.bot.strategy_router.detect_regime(df)
                        regime_info = regime.value
                        
                        # --- AUTONOMOUS DECISION CORE (New) ---
                        
                        # 1. Check Balance
                        balance = 0.0
                        start_balance = 1000.0 # Default fallback
                        
                        if self.bot.client:
                             try:
                                 balance = self.bot.client.get_wallet_balance('USDT')
                             except: 
                                 balance = start_balance
                        
                        # 2. Select Strategy via Router
                        selected_strat = self.bot.strategy_router.select_strategy(regime)
                        
                        # 3. Dynamic overrides based on state
                        if balance < 200 and balance > 0:
                            active_strategy = "ACCELERATION"
                            recommendation = "Low Balance (<$200) -> ACCELERATION Mode"
                            self.bot.switch_strategy("acceleration")
                        else:
                            active_strategy = selected_strat.upper()
                            recommendation = f"Market Regime {regime_info} -> {active_strategy} Strategy"
                            self.bot.switch_strategy(selected_strat)
                        
                        logger.info(f"🧠 AI DECISION (V2): {recommendation} (Regime: {regime_info}, Bal: ${balance:.0f})")
                        
                        # Execute based on decided strategy
                        if active_strategy == "GRID":
                             pass # Already handled above
                        else:
                             await self.scan_all()
                    else:
                        await self.scan_all()
                        
                    self.bot.last_state = {
                        'regime': regime_info,
                        'current_strategy': active_strategy,
                        'recommendation': recommendation,
                        'last_update': datetime.now().isoformat(),
                        'sentiment_regime': self.bot.sentiment_service.regime if self.bot.sentiment_service else 'N/A',
                        'sentiment_reason': self.bot.sentiment_service.reasoning if self.bot.sentiment_service else 'N/A'
                    }
                    with open('bot_state.json', 'w') as f:
                        json.dump(self.bot.last_state, f)
                                    
                except Exception as e:
                    logger.error(f"Auto-Adaptation error: {e}")
                    await self.scan_all()
                
                if self.bot.scanner and self.bot.stats['scans'] % 24 == 0:
                    self.bot.scanner.refresh_symbols()
                
                if self.bot.execution and self.bot.auto_trade:
                    try:
                        self.bot.execution.check_trailing_stop()
                        self.bot.execution.check_time_exits() # NEW: Time-Exit check
                    except Exception as e:
                         logger.error(f"Execution loop error: {e}")

                # Daily Briefing Trigger (07:00 Kamchatka Time = UTC+12)
                try:
                    from datetime import timedelta
                    utc_now = datetime.utcnow()
                    kamchatka_hour = (utc_now + timedelta(hours=12)).hour
                    kamchatka_minute = (utc_now + timedelta(hours=12)).minute
                    
                    # Send at 07:00 (first scan of that hour)
                    if kamchatka_hour == 7 and kamchatka_minute < 20:
                        if hasattr(self.bot, 'telegram_bot') and self.bot.telegram_bot:
                            await self.bot.telegram_bot.send_daily_briefing(
                                sentiment_service=self.bot.sentiment_service,
                                selector_service=self.bot.selector_service
                            )
                except Exception as e:
                    logger.debug(f"Daily briefing check: {e}")

                await asyncio.sleep(interval_minutes * 60)
                
        except asyncio.CancelledError:
            logger.info("Bot Task Cancelled")
        except Exception as e:
            logger.error(f"Async Loop Error: {e}")
    def _run_grid_logic(self, symbol, current_price):
        """Logic for Grid Strategy execution"""
        from grid_engine import GridStrategy
        balance = 1000.0
        if self.bot.execution and self.bot.client and not self.bot.demo_mode:
            try:
                bal = self.bot.client.get_wallet_balance('USDT')
                if bal > 0: balance = bal * 0.5
            except: pass

        grid = GridStrategy(symbol, balance)
        lower = current_price * 0.98
        upper = current_price * 1.02
        orders = grid.calculate_grid(current_price, lower, upper, grids=6)
        
        if self.bot.execution and self.bot.auto_trade:
             logger.info(f"🕸️ [GRID] Executing {len(orders)} orders for {symbol} range {lower:.2f}-{upper:.2f}")
             self.bot.execution.execute_grid_orders(symbol, orders)
        else:
             logger.info(f"🕸️ [GRID] Simulated {len(orders)} orders for {symbol} range {lower:.2f}-{upper:.2f}")

    def _print_header(self):
        print("""
================================================================================
|                     TRADING AI v2.0 - BYBIT EDITION                          |
|                                                                              |
|  * Multi-Timeframe Confluence (15m + 1h + 4h)                                |
|  * Support/Resistance + Funding Rate + Order Book                           |
|  * Target: 85%+ Win Rate                                                    |
================================================================================
        """)

    def _print_no_signals(self):
        print("""
--------------------------------------------------------------
|  (WAIT)  No signals with probability 85%+                   |
|  This is GOOD - we wait for perfect setups!                 |
--------------------------------------------------------------
        """)

    def _print_stats(self):
        elapsed = (datetime.now() - self.bot.stats['start_time']).total_seconds() / 60
        print(f"\n📊 Сканов: {self.bot.stats['scans']} | Символов: {self.bot.stats['symbols_scanned']} | "
              f"Сигналов: {self.bot.stats['signals_found']} | Исполнено: {self.bot.stats['trades_executed']} | "
              f"Время: {elapsed:.1f} мин\n")

    def _print_final_stats(self):
        elapsed = (datetime.now() - self.bot.stats['start_time']).total_seconds() / 60
        print(f"\n{'='*60}")
        print(f"ИТОГО: {self.bot.stats['scans']} сканов, {self.bot.stats['trades_executed']} сделок за {elapsed:.1f} мин")
        print('='*60)

    def export_signals(self, filepath: str = 'signals_bybit.json'):
        data = [{
            'symbol': s.symbol,
            'type': s.signal_type.value,
            'entry': s.entry_price,
            'probability': s.probability,
            'timestamp': s.timestamp.isoformat()
        } for s in self.bot.signals_history]
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported to {filepath}")

    def run_once(self) -> List[AdvancedSignal]:
        """Однократное сканирование"""
        self._print_header()
        logger.info("Сканирование...")
        start = time.time()
        signals = self.scan_all()
        logger.info(f"Завершено за {time.time()-start:.1f}с")
        if not signals:
            self._print_no_signals()
        self._print_stats()
        return signals
