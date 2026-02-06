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

logger = logging.getLogger(__name__)

class ScannerService:
    """Сервис для сканирования рынка и управления циклом мониторинга"""
    
    def __init__(self, bot: 'TradingBot'):
        self.bot = bot
        
    def scan_symbol(self, market_data: MarketData) -> Optional[AdvancedSignal]:
        """Анализирует один символ"""
        if market_data.df_15m.empty or market_data.df_1h.empty:
            return None
        
        if self.bot.strategy_name == "mean_reversion" and market_data.df_4h.empty:
            return None
            
        funding_rate = market_data.funding_rate
        orderbook_imbalance = None
        
        if self.bot.client and not self.bot.demo_mode:
            try:
                ob = self.bot.client.get_orderbook(market_data.symbol)
                orderbook_imbalance = ob.get('imbalance')
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
        elif self.bot.strategy_name == "scalping":
            # Scalping uses 1m klines primarily
            return self.bot.engine.analyze(
                df_15m=market_data.df_1m,
                df_1h=market_data.df_15m, # Fallback 1H to 15m for context if needed
                df_4h=market_data.df_1h,   # Fallback 4H to 1H
                symbol=market_data.symbol,
                funding_rate=funding_rate,
                orderbook_imbalance=orderbook_imbalance,
                is_scalping=True
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
            
            if allowed == "NONE":
                logger.warning(f"⛔ Market is RISK_OFF ({self.bot.sentiment_service.reasoning}). Trading HALTED.")
                return []
            
            if regime == "RISK_OFF" and allowed != "BOTH":
                 logger.info(f"⚠️ Market Regime: {regime} | Allowed: {allowed}")

        self.bot.stats['scans'] += 1
        signals = []
        
        if self.bot.demo_mode:
            return self._demo_scan()
        
        # 2. FETCH MARKET DATA
        market_data_list = await self.bot.scanner.scan_all_async()
        self.bot.stats['symbols_scanned'] += len(market_data_list)
        
        loop = asyncio.get_running_loop()
        
        for market_data in market_data_list:
            signal = self.scan_symbol(market_data)
            
            if signal:
                self.bot.stats['signals_found'] += 1
                
                if signal.probability >= self.bot.min_probability:
                    # --- ADVANCED SENTIMENT FILTER (Allowed Direction) ---
                    if hasattr(self.bot, 'sentiment_service'):
                        allowed = getattr(self.bot.sentiment_service, 'allowed_direction', 'BOTH')
                        from mean_reversion_bybit import SignalType
                        
                        reject = False
                        if allowed == "LONG_ONLY" and signal.signal_type != SignalType.LONG:
                            reject = True
                        elif allowed == "SHORT_ONLY" and signal.signal_type != SignalType.SHORT:
                            reject = True
                        elif allowed == "NONE":
                            reject = True
                            
                        if reject:
                            logger.info(f"⏭️ Skipping {signal.symbol} {signal.signal_type.value} - Market Regime: {allowed}")
                            continue

                    # --- NEW: ML & NEWS SENTIMENT FILTERS ---
                    
                    # 1. ML Validation
                    if hasattr(self.bot, 'ml_service') and self.bot.ml_service and self.bot.ml_service.is_ready:
                        # We need full df for ML. self.bot.client.get_klines can be used if not in market_data
                        # For simplicity, we assume market_data might not have full df history
                        # We fetch if needed
                        try:
                            ml_res = self.bot.ml_service.predict(market_data.get('df_15m'))
                            prediction = ml_res['prediction']
                            confidence = ml_res['confidence']
                            
                            logger.info(f"🤖 ML Check for {signal.symbol}: Pred {prediction:+.4f}, Conf {confidence:.2f}")
                            
                            # Filter: ML must agree with direction (prediction > 0 for LONG, < 0 for SHORT)
                            from mean_reversion_bybit import SignalType
                            if (signal.signal_type == SignalType.LONG and prediction < 0.001) or \
                               (signal.signal_type == SignalType.SHORT and prediction > -0.001):
                                if confidence > 0.7: # Only reject if ML is confident
                                    logger.info(f"⏭️ ML REJECTED {signal.symbol} {signal.signal_type.value} (Prediction disagreement)")
                                    continue
                            
                            signal.reasoning.append(f"🤖 ML: Pred {prediction:+.4f} (Conf: {confidence:.2f})")
                        except Exception as e:
                            logger.error(f"ML check failed: {e}")

                    # 2. News Sentiment (Symbol Specific)
                    if hasattr(self.bot, 'news_service') and self.bot.news_service:
                        news_res = await self.bot.news_service.get_symbol_sentiment(signal.symbol)
                        logger.info(f"📰 News Sentiment for {signal.symbol}: {news_res['label']} (Score: {news_res['score']:.2f})")
                        
                        # Filter: Don't trade if sentiment is contrary and strong
                        from mean_reversion_bybit import SignalType
                        if (signal.signal_type == SignalType.LONG and news_res['score'] < -0.4) or \
                           (signal.signal_type == SignalType.SHORT and news_res['score'] > 0.4):
                            logger.info(f"⏭️ NEWS REJECTED {signal.symbol} {signal.signal_type.value} (Sentiment contradiction)")
                            continue
                            
                        signal.reasoning.append(f"📰 News: {news_res['label']} ({news_res['score']:.2f})")

                    signals.append(signal)
                    self.bot.signals_history.append(signal)
                    self.bot.stats['signals_qualified'] += 1
                    
                    logger.info(f"🎯 Signal Identified: {signal.symbol} {signal.signal_type.value} ({signal.probability}%)")
                    
                    # 3. EXECUTION LOGIC
                    execution_success = False
                    order_id = None
                    
                    if self.bot.execution and self.bot.auto_trade:
                        logger.info(f"⚙️ AUTO-TRADE: Executing {signal.symbol}...")
                        try:
                            # Use execute_signal_async if available, else run in executor
                            # Use execute_signal_async if available, else run in executor
                            if hasattr(self.bot.execution, 'execute_signal_async'):
                                res = await self.bot.execution.execute_signal_async(signal)
                            else:
                                res = await loop.run_in_executor(None, lambda: self.bot.execution.execute_signal(signal))
                            
                            # execute_signal returns (success, message)
                            execution_success, exec_msg = res if isinstance(res, tuple) else (res, "Unknown")
                            
                            if execution_success:
                                self.bot.stats['trades_executed'] += 1
                                logger.info(f"✅ AUTO-TRADE SUCCESS: {signal.symbol} - {exec_msg}")
                            else:
                                logger.warning(f"❌ AUTO-TRADE REJECTED for {signal.symbol}: {exec_msg}")
                        except Exception as e:
                            logger.error(f"❌ AUTO-TRADE FAILED for {signal.symbol}: {e}")
                    
                    # 4. TELEGRAM NOTIFICATION
                    if hasattr(self.bot, 'telegram_bot') and self.bot.telegram_bot:
                        sentiment = self.bot.sentiment_service.regime if self.bot.sentiment_service else None
                        sector = self.bot.selector_service.get_symbol_sector(signal.symbol) if self.bot.selector_service else None
                        
                        # Send with appropriate buttons/status
                        await self.bot.telegram_bot.send_signal_with_actions(
                            signal, 
                            sentiment=sentiment, 
                            sector=sector,
                            is_executed=execution_success,
                            order_id=exec_msg if execution_success else None
                        )
                    elif self.bot.telegram:
                         # Fallback to simple notifier
                         await self.bot.telegram.send(signal)
        
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
