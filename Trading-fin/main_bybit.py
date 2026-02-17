"""
Trading AI v2.0 - Bybit Edition
================================
Полная система с Telegram ботом, Backtesting и Auto-Trading (Модульная версия)

Команды:
    python main_bybit.py scan                    # Однократное сканирование
    python main_bybit.py scan --continuous       # Непрерывный мониторинг
    python main_bybit.py scan --auto-trade       # АВТО-ТОРГОВЛЯ (Осторожно!)
    python main_bybit.py backtest                # Запуск бэктеста
    python main_bybit.py telegram                # Запуск Telegram бота
    python main_bybit.py demo                    # Демо режим
"""

import argparse
import asyncio
import time
import json
import os
import logging
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

# Загрузка env
load_dotenv(override=True)

# Внутренние модули
from mean_reversion_bybit import (
    AdvancedMeanReversionEngine, 
    AdvancedSignal, 
    format_signal,
    UltimateTradingEngine,
    Trade,
    RiskManager,
    PerformanceTracker,
    NewsEngine,
    NewsSentiment
)
from bybit_client import BybitClient, BybitScanner, BybitCategory
from backtesting import Backtester
from execution import ExecutionManager, RiskLimits
from strategies.trend_following import TrendFollowingStrategy
from strategies.breakout import BreakoutStrategy
from strategies.acceleration import AccelerationStrategy
from scalping_engine import UltraScalpingEngine
from new_scalping_engine import NewScalpingEngine
from strategies.deposit_acceleration import DepositAccelerationEngine

# Сервисы (Новая архитектура)
from services.controller_service import BotController
from services.scanner_service import ScannerService
from services.sentiment_service import SentimentService
from services.selector_service import SelectorService
from services.news_service import NewsService
from services.hedge_service import HedgeService
from services.whale_alert_service import WhaleAlertService
from services.ml_service import MLService
from services.strategy_router_service import StrategyRouterService
from services.analytics_service import AnalyticsService
from web_ui.database import db

# Telegram (опционально)
try:
    from telegram_bot import TradingTelegramBot, TelegramConfig, TelegramNotifier, SignalFormatter
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

try:
    from ai_agent import TradingAgent
    AI_AVAILABLE = True
except ImportError as e:
    logging.error(f"❌ AI Agent Import Failed: {e}")
    AI_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class TradingBot:
    """Координатор торговой системы"""
    
    def __init__(self, **kwargs):
        self.strategy_name = kwargs.get('strategy', 'mean_reversion')
        self.min_probability = kwargs.get('min_probability', 85)
        
        # Adaptive threshold for scalping (if default 85 is unchanged)
        if self.strategy_name in ["scalping", "new_scalping"] and self.min_probability == 85:
            self.min_probability = 75
            logger.info(f"⚡ Scalping Mode: Tightened adaptive threshold set to {self.min_probability}%")
            
        self.demo_mode = kwargs.get('demo_mode', False)
        self.demo_trading = kwargs.get('demo_trading', False)
        self.category = kwargs.get('category', BybitCategory.LINEAR)
        self.auto_trade = kwargs.get('auto_trade', False)
        self.use_binance_data = kwargs.get('use_binance_data', False)
        
        # 1. Base Setup
        self.analytics_service = AnalyticsService(db)
        self.client = BybitClient(
            category=self.category, 
            testnet=kwargs.get('testnet', False), 
            demo_trading=kwargs.get('demo_trading', False),
            demo_mode=kwargs.get('demo_mode', False),
            api_key=kwargs.get('api_key') or os.getenv('BYBIT_API_KEY'),
            api_secret=kwargs.get('api_secret') or os.getenv('BYBIT_API_SECRET'),
            proxy=kwargs.get('proxy'),
            use_binance_data=self.use_binance_data
        )

        # Get initial equity for Risk Management
        equity = 1000.0
        self.keys_valid = False
        logger.info("💰 Fetching initial equity from API...")
        
        # Если нет валидных API ключей, используем fallback баланс
        if not self.client.has_valid_api:
            logger.info("💰 No valid API keys, using fallback equity: $10000.00")
            equity = 10000.0
        else:
            try:
                val = self.client.get_total_equity()
                logger.info(f"💰 get_total_equity returned: ${val:.2f}")
                if val and val > 0:
                    equity = val
                    self.keys_valid = True
                    logger.info(f"💰 Initial Equity from API: ${equity:.2f}")
                else:
                    logger.warning(f"💰 API returned 0 equity, using fallback: ${equity:.2f}")
            except Exception as e:
                logger.error(f"💰 Failed to fetch equity from API: {e}, using fallback: ${equity:.2f}")
        
        # For demo trading mode, ensure we have a valid equity
        if self.demo_trading and equity <= 0:
            equity = 10000.0
            logger.info(f"💰 Demo trading mode: using default equity ${equity:.2f}")
        
        # For demo mode (fake keys), use default equity
        if self.demo_mode and not self.keys_valid:
            equity = 10000.0
            logger.info(f"💰 Demo mode (fake keys): using default equity ${equity:.2f}")

        # 2. Engine Initialization (Now with Equity and News Key)
        cryptopanic_key = os.getenv('CRYPTOPANIC_KEY')
        
        if self.strategy_name == "trend":
            self.engine = TrendFollowingStrategy()
        elif self.strategy_name == "breakout":
            self.engine = BreakoutStrategy()
        elif self.strategy_name == "acceleration":
            self.engine = AccelerationStrategy()
        elif self.strategy_name == "scalping":
            self.engine = UltraScalpingEngine(min_confluence=self.min_probability, max_risk_pct=0.005)
        elif self.strategy_name == "new_scalping":
            self.engine = NewScalpingEngine(min_confluence=self.min_probability, max_risk_pct=0.01)
        elif self.strategy_name == "deposit_accel":
            self.engine = DepositAccelerationEngine(
                equity=equity,
                min_confluence=self.min_probability if self.min_probability != 85 else 65,
                max_risk_pct=0.02
            )
            logger.info(f"🚀 Deposit Acceleration Engine loaded | Phase auto-detection by balance")
        else:
            # Sniper Mode: Extreme signals only (85%+), R:R 1:4 minimum
            self.engine = UltimateTradingEngine(cryptopanic_key=cryptopanic_key, total_capital=equity, min_confluence=85)

        # 3. Execution Manager (with Tradingfin3.0 components)
        self.execution = None
        if self.client:
            risk_limits = RiskLimits(risk_per_trade_percent=kwargs.get('risk_per_trade', 1.0))
            dry_run = not self.auto_trade or self.demo_mode or (not self.keys_valid)
            
            # V4.1: Initialize Enhanced Tradingfin3.0 components
            from enhanced_risk_manager import EnhancedRiskManager
            from enhanced_performance import EnhancedPerformanceTracker
            from enhanced_news_engine import EnhancedNewsEngine
            
            risk_manager = EnhancedRiskManager(
                total_capital=equity,
                daily_loss_limit=kwargs.get('max_daily_loss', 0.05),  # 5% default
                max_drawdown_limit=kwargs.get('max_drawdown', 0.15),  # 15% default
                max_positions=kwargs.get('max_positions', 200),
                state_file="risk_state.json",
            )
            
            performance_tracker = EnhancedPerformanceTracker(initial_capital=equity)
            
            news_engine = EnhancedNewsEngine(
                cryptopanic_key=cryptopanic_key,
                cache_ttl=300,
            )
            
            try:
                self.execution = ExecutionManager(
                    self.client, 
                    risk_limits, 
                    dry_run=dry_run,
                    analytics=self.analytics_service,
                    risk_manager=risk_manager,
                    performance_tracker=performance_tracker,
                    news_engine=news_engine
                )
            except Exception as e:
                logger.error(f"Execution Manager init failed: {e}")
                self.execution = None

        self.scanner = BybitScanner(
            client=self.client,
            symbols=kwargs.get('symbols'),
            min_volume_24h=kwargs.get('min_volume_24h', 5_000_000),
            max_symbols=kwargs.get('max_symbols') or 100 # Force 100 symbols if not set
        )
            
        # 4. Telegram (Notifier for sending + Bot for receiving/AI chat)
        self.telegram = None
        self.telegram_bot = None  # For receiving messages and AI chat
        self.polling_enabled = not kwargs.get('disable_telegram_polling', False)
        
        if TELEGRAM_AVAILABLE and kwargs.get('telegram_token') and kwargs.get('telegram_channel'):
            self.telegram = TelegramNotifier(kwargs.get('telegram_token'), kwargs.get('telegram_channel'))
            
            # Create TradingTelegramBot for interactive features (polling)
            if self.polling_enabled:
                try:
                    config = TelegramConfig(
                        bot_token=kwargs.get('telegram_token'),
                        channel_gold=kwargs.get('telegram_channel')
                    )
                    self.telegram_bot = TradingTelegramBot(config, controller=None)  # Controller set later
                    logger.info("📱 Telegram Bot (Interactive) configured")
                except Exception as e:
                    logger.error(f"Failed to create TradingTelegramBot: {e}")
            else:
                logger.info("📱 Telegram Polling DISABLED (Main Controller active)")
            
        # 5. State & Stats
        self.signals_history: List[AdvancedSignal] = []
        self.stats = {
            'scans': 0, 'symbols_scanned': 0, 'signals_found': 0,
            'signals_qualified': 0, 'trades_executed': 0, 'start_time': datetime.now()
        }
        self.is_active = True
        self.last_state = {}
        
        # 6. Services
        self.controller = BotController(self)
        self.scanner_service = ScannerService(self)
        self.sentiment_service = None 
        self.selector_service = None
        self.news_service = None
        self.hedge_service = None
        self.whale_service = None
        # TURBO MODE: Re-enabling heavy ML engine (8GB RAM detected)
        from services.ml_service import MLService
        self.ml_service = MLService()
        self.strategy_router = StrategyRouterService(self)
        
        # Save initial state immediately
        self.save_state_to_file()

    def switch_strategy(self, new_strategy: str):
        """Dynamically switches the trading engine"""
        if self.strategy_name == new_strategy:
            return
            
        logger.info(f"🔄 Switching strategy from {self.strategy_name} to {new_strategy}")
        self.strategy_name = new_strategy
        
        if new_strategy == "trend":
            self.engine = TrendFollowingStrategy()
        elif new_strategy == "breakout":
            self.engine = BreakoutStrategy()
        elif new_strategy == "acceleration":
            self.engine = AccelerationStrategy()
        elif new_strategy == "scalping":
            self.engine = UltraScalpingEngine(min_confluence=75)
        elif new_strategy == "new_scalping":
            self.engine = NewScalpingEngine(min_confluence=70)
        elif new_strategy == "deposit_accel":
            self.engine = DepositAccelerationEngine(
                equity=1000, # Fallback, real equity synced in loop
                min_confluence=70
            )
        else:
            self.engine = UltimateTradingEngine(min_confluence=85)


    async def run_continuous_async(self, interval_seconds: int = 30):
        """Непрерывный цикл сканирования"""
        logger.info(f"🔄 Starting continuous scan loop (Interval: {interval_seconds}s)")
        
        # Init AI & Services
        if AI_AVAILABLE:
            if not hasattr(self, 'ai_agent') or self.ai_agent is None:
                self.ai_agent = TradingAgent(self.controller)
                self.sentiment_service = SentimentService(self.ai_agent)
                self.selector_service = SelectorService(self.ai_agent, self.client)
                self.news_service = NewsService(self.ai_agent)
                self.whale_service = WhaleAlertService(self.client, telegram=self.telegram)
                
                # Start Background Loops
                # Start Background Loops (Wrapped to prevent cascading failures)
                services = [
                    (self.sentiment_service.start(interval_hours=0.25), "Sentiment"), # Every 15 min
                    (self.selector_service.start(interval_hours=0.5), "Selector"),   # Every 30 min
                    (self.news_service.start(interval_hours=4), "News"),           # Every 4 hours
                    (self.whale_service.start(interval_seconds=300), "Whale Alerts") # Every 5 min
                ]
                
                for coroutine, name in services:
                    try:
                        asyncio.create_task(coroutine)
                        logger.info(f"✅ Background Service started: {name}")
                    except Exception as e:
                        logger.error(f"❌ Failed to start {name} service: {e}")

                # Start Hedge only if Trading is Active AND Keys Valid
                if self.execution and self.keys_valid:
                    try:
                        self.hedge_service = HedgeService(self.execution, self.client)
                        await asyncio.sleep(2) # STAGGER
                        asyncio.create_task(self.hedge_service.start(interval_seconds=300))
                        logger.info("✅ Hedge Service started")
                    except Exception as e:
                        logger.error(f"❌ Failed to start Hedge service: {e}")
                
                # IMPORTANT: Update execution manager with news service
                if self.execution:
                    self.execution.news_service = self.news_service
                    
                logger.info("🧠 AI Services Started (Sentiment + Selector + News)")
                
                # Start Telegram Bot for AI Chat (Polling)
                if self.telegram_bot:
                    self.telegram_bot.controller = self.controller
                    self.telegram_bot.ai_agent = self.ai_agent
                    try:
                        await asyncio.sleep(2) # STAGGER
                        asyncio.create_task(self.telegram_bot.start())
                        logger.info("📱 Telegram Bot (Interactive) Started")
                    except Exception as e:
                        logger.error(f"Telegram Bot polling failed: {e}")
        
        # Initial state save to fix UI button immediately
        self.save_state_to_file()
        
        # === TELEGRAM STARTUP GREETING ===
        if self.telegram:
            try:
                await self.telegram.send_startup_greeting()
            except Exception as e:
                logger.error(f"Telegram startup greeting failed: {e}")
        
        # Track last hourly report time
        # Force immediate report on startup (requested by user)
        last_hourly_report = 0 
        
        while self.is_active:
            try:
                start_ts = time.time()
                
                # --- SYNC ENGINE RISK WITH EXECUTION ---
                if self.execution and hasattr(self.engine, 'risk_manager'):
                    # Pass current PnL to engine so Circuit Breaker can trigger
                    self.engine.risk_manager.daily_pnl = self.execution.daily_pnl

                # --- VOLATILITY HUNTER (New Scalping Mode Only) ---
                now_ts = time.time()
                if self.strategy_name == "new_scalping" and (now_ts - getattr(self, '_last_symbol_update', 0) > 600):
                    self._last_symbol_update = now_ts # Update immediately 
                    try:
                        logger.info("🌪️ Volatility Hunter: Refreshing top movers (TURBO-20)...")
                        # TURBO: Fetch 20 symbols
                        top_movers = self.client.get_top_volatile_coins(top_n=20, min_volume=10_000_000)
                        new_symbols = [m['symbol'] for m in top_movers]
                        
                        # Keep BTC/ETH/SOL always
                        core = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
                        final_list = list(set(core + new_symbols))
                        
                        self.scanner.symbols = final_list
                        logger.info(f"✅ Active Symbols Updated ({len(final_list)}): {', '.join(final_list)}")
                        import gc
                        gc.collect() # Clean up after symbol refresh
                    except Exception as e:
                        logger.error(f"Failed to update volatile symbols: {e}")

                await self.run_once()
                
                # --- POSITION MAINTENANCE ---
                if self.execution and self.auto_trade:
                    try:
                        self.execution.check_trailing_stop()
                        self.execution.check_time_exits()
                    except Exception as e:
                        logger.error(f"Maintenance task failed: {e}")

                self.save_state_to_file()
                
                # Phase 12: Aggressive Memory Management (Zero-OOM Mode)
                import gc
                gc.collect()
                
                duration = time.time() - start_ts
                
                # === HOURLY TELEGRAM REPORT ===
                if self.telegram and (time.time() - last_hourly_report >= 3600):
                    try:
                        regime = self.sentiment_service.regime if self.sentiment_service else "N/A"
                        strategy = self.strategy_name
                        try:
                            balance = self.client.get_wallet_balance('USDT')
                            # Fallback for demo mode or API issues - use totalEquity if wallet balance is 0
                            if balance <= 0:
                                try:
                                    equity = self.client.get_total_equity()
                                    if equity > 0:
                                        logger.info(f"💰 Using Total Equity as fallback: ${equity:.2f}")
                                        balance = equity
                                except:
                                    pass
                        except:
                            balance = 0.0
                            
                        positions = len(self.client.get_open_positions())
                        top_longs = self.selector_service.primary_list[:5] if self.selector_service and self.selector_service.primary_list else []
                        top_shorts = self.selector_service.secondary_list[:5] if self.selector_service and self.selector_service.secondary_list else []
                        
                        await self.telegram.send_hourly_report(
                            regime=regime,
                            strategy=strategy,
                            balance=balance,
                            positions=positions,
                            top_longs=top_longs,
                            top_shorts=top_shorts
                        )
                        last_hourly_report = time.time()
                    except Exception as e:
                        logger.error(f"Telegram hourly report failed: {e}")
                
                # --- DEPOSIT ACCELERATION: Update equity and positions ---
                if self.strategy_name == "deposit_accel" and hasattr(self.engine, 'update_equity'):
                    try:
                        live_equity = self.client.get_total_equity()
                        if live_equity and live_equity > 0:
                            self.engine.update_equity(live_equity)
                        open_pos = self.client.get_open_positions()
                        if open_pos:
                            self.engine.set_open_positions([p.get('symbol', '') for p in open_pos])
                        else:
                            self.engine.set_open_positions([])
                    except Exception as e:
                        logger.debug(f"Deposit accel equity update failed: {e}")
                
                sleep_time = max(1, interval_seconds - duration)
                logger.debug(f"Scan finished in {duration:.1f}s. Sleeping {sleep_time:.1f}s")
                await asyncio.sleep(sleep_time)
            except Exception as e:
                logger.error(f"Error in continuous loop: {e}")
                await asyncio.sleep(5)

    def save_state_to_file(self):
        """Сохраняет состояние бота в файл для UI"""
        try:
            state = {
                'status': 'running' if self.is_active else 'stopped',
                'pid': os.getpid(),
                'last_update': datetime.now().isoformat(),
                'strategy': self.strategy_name,
                'regime': self.last_state.get('regime', 'Unknown'),
                'sentiment_regime': 'N/A',
                'sentiment_reason': 'Initializing...'
            }
            
            if self.sentiment_service:
                state['sentiment_regime'] = self.sentiment_service.regime
                state['sentiment_reason'] = self.sentiment_service.reasoning
                
            if self.selector_service:
                state['top_longs'] = self.selector_service.primary_list
                state['top_shorts'] = self.selector_service.secondary_list
                
            if self.hedge_service:
                state['hedge_status'] = self.hedge_service.status if hasattr(self.hedge_service, 'status') else self.hedge_service.hedge_status
                
            if self.news_service:
                danger = self.news_service.check_danger_zone()
                state['news_danger'] = danger['name'] if danger else "None"
                
            with open('bot_state.json', 'w') as f:
                json.dump(state, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    async def run_once(self):
        """Одиночный запуск (Async)"""
        try:
            return await self.scanner_service.scan_all()
        except Exception as e:
            logger.error(f"Error in run_once: {e}")
            return []

    def export_signals(self): self.scanner_service.export_signals()

# ============================================================
# CLI COMMANDS
# ============================================================


def load_bot_config():
    """Загружает конфигурацию из JSON файла"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_dir, 'bot_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading config: {e}")
    return {}

def cmd_scan(args):
    # Загружаем конфиг из файла как базу
    file_config = load_bot_config()
    
    # Приоритет: ARGS > ENV > CONFIG FILE
    
    # Для демо-режима используем фейковые ключи ТОЛЬКО если это симуляция (demo_mode)
    # Если это Bybit Demo Trading (demo_trading), используем реальные ключи из конфига
    mode = file_config.get('mode', '')
    if args.demo:
        api_key = "fake_demo_key"
        api_secret = "fake_demo_secret"
        logger.info("💰 Simulation mode: using fake API keys")
    else:
        api_key = os.getenv('BYBIT_API_KEY') or file_config.get('api_key')
        api_secret = os.getenv('BYBIT_API_SECRET') or file_config.get('api_secret')
    
    proxy = os.getenv('HTTP_PROXY') or file_config.get('proxy')
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN') or file_config.get('telegram_token')
    telegram_channel = os.getenv('TELEGRAM_CHANNEL') or file_config.get('telegram_channel')
    
    # Определяем параметры
    # If --all is passed, ignore symbols from config and scan top by volume
    if args.all:
        symbols = None  # Forces BybitScanner to use _get_filtered_symbols()
    else:
        symbols = args.symbols or file_config.get('symbols')
        if not symbols:
            logger.warning("No symbols specified in args or config. Scanning ALL pairs.")
            args.all = True
            symbols = None

    bot = TradingBot(
        symbols=symbols,
        category=BybitCategory.SPOT if args.category == 'spot' else BybitCategory.LINEAR,
        min_volume_24h=0 if args.all else args.min_volume,
        max_symbols=args.max_symbols or file_config.get('max_symbols'),
        min_probability=args.min_probability,
        testnet=args.testnet or (mode == 'paper'), 
        demo_trading=args.demo_trading or (mode in ['demo', 'demo_trading']),
        demo_mode=args.demo or (mode == 'demo'),
        telegram_token=telegram_token,
        telegram_channel=telegram_channel,
        auto_trade=args.auto_trade or file_config.get('auto_trade', False),
         risk_per_trade=args.risk or file_config.get('risk_percent', 1.0),
         proxy=proxy,
         # For demo_trading mode, do NOT use Binance data - use Bybit Demo API directly
         use_binance_data=args.use_binance and not (args.demo_trading or file_config.get('mode') == 'demo_trading'),
         strategy=args.strategy or file_config.get('strategy', 'mean_reversion'),
        api_key=api_key,
        api_secret=api_secret,
        disable_telegram_polling=args.no_telegram_bot
    )
    
    try:
        if args.continuous:
            async def run_async_loop():
                tasks = []
                # tasks.append(asyncio.create_task(bot.run_continuous_async(args.interval))) # Removing duplicate
                
                # Telegram bot is now managed entirely inside TradingBot.run_continuous_async
                # so we don't start it here to avoid Conflict errors.
                
                tasks.append(asyncio.create_task(bot.run_continuous_async(args.interval)))

                try:
                    await asyncio.gather(*tasks)
                except asyncio.CancelledError:
                    pass
            
            try:
                asyncio.run(run_async_loop())
            except KeyboardInterrupt:
                pass
        else:
            # Async run for single scan
            signals = asyncio.run(bot.run_once())
            if signals:
                bot.export_signals()
                
    except Exception as e:
        logger.critical(f"CRITICAL ERROR in cmd_scan: {e}")
        import traceback
        logger.critical(traceback.format_exc())
        # Keep window open if crashed immediately
        import time
        time.sleep(30)

def cmd_backtest(args):
    loader = HistoricalDataLoader()
    if args.data_file:
        df = loader.load_from_csv(args.data_file)
    elif args.days:
        df = loader.fetch_from_bybit(args.symbol, days=args.days)
    else:
        df = loader.generate_synthetic(periods=args.periods)
    
    if args.strategy == 'trend': engine = TrendFollowingStrategy()
    elif args.strategy == 'breakout': engine = BreakoutStrategy()
    else: engine = AdvancedMeanReversionEngine(min_confluence=args.min_confluence, min_rr=args.min_rr)
    
    backtester = Backtester(engine=engine, initial_capital=args.capital, risk_per_trade=args.risk)
    result = backtester.run(df, args.symbol, max_trades=args.max_trades)
    backtester.print_report(result)

def cmd_demo(args):
    logger.info("💰 cmd_demo called")
    # Для демо-режима используем фейковые ключи
    api_key = "fake_demo_key"
    api_secret = "fake_demo_secret"
    logger.info(f"💰 Demo mode: initializing with fake API keys...")
    
    bot = TradingBot(
        demo_mode=True, 
        min_probability=75,
        api_key=api_key,
        api_secret=api_secret
    )
    # Используем asyncio.run для запуска асинхронной функции
    try:
        asyncio.run(bot.run_once())
        logger.info("✅ Demo scan finished successfully")
    except Exception as e:
        logger.error(f"❌ Demo scan failed: {e}")

def cmd_panic(args):
    bot = TradingBot(auto_trade=True)
    if bot.execution:
        res = bot.execution.panic_close_all()
        print(f"✅ Positions Closed: {res['positions_closed']}, Orders Cancelled: {res['orders_cancelled']}")

def main():
    parser = argparse.ArgumentParser(description='Trading AI v2.0 - Bybit Edition')
    subparsers = parser.add_subparsers(dest='command', help='Команды')
    
    scan_parser = subparsers.add_parser('scan', help='Сканирование рынка')
    scan_parser.add_argument('--symbols', '-s', nargs='+', help='Символы')
    scan_parser.add_argument('--all', action='store_true', help='Все пары')
    scan_parser.add_argument('--min-volume', type=float, default=5_000_000)
    scan_parser.add_argument('--max-symbols', type=int)
    scan_parser.add_argument('--continuous', '-c', action='store_true')
    scan_parser.add_argument('--interval', '-i', type=int, default=60)
    scan_parser.add_argument('--strategy', type=str, default='mean_reversion', choices=['mean_reversion', 'trend', 'breakout', 'acceleration', 'auto', 'scalping', 'new_scalping', 'deposit_accel'])
    scan_parser.add_argument('--min-probability', type=int, default=85)
    scan_parser.add_argument('--category', choices=['spot', 'linear'], default='linear')
    scan_parser.add_argument('--testnet', action='store_true')
    scan_parser.add_argument('--demo-trading', action='store_true')
    scan_parser.add_argument('--demo', action='store_true')
    scan_parser.add_argument('--telegram-control', action='store_true')
    scan_parser.add_argument('--auto-trade', action='store_true')
    scan_parser.add_argument('--risk', type=float, default=1.0)
    scan_parser.add_argument('--use-binance', action='store_true')
    scan_parser.add_argument('--no-telegram-bot', action='store_true', help='Disable interactive Telegram bot polling')
    
    bt_parser = subparsers.add_parser('backtest', help='Бэктестинг')
    bt_parser.add_argument('--data-file', '-f')
    bt_parser.add_argument('--days', type=int)
    bt_parser.add_argument('--symbol', default='BTCUSDT')
    bt_parser.add_argument('--strategy', type=str, default='mean_reversion', choices=['mean_reversion', 'trend', 'breakout'])
    bt_parser.add_argument('--periods', type=int, default=10000)
    bt_parser.add_argument('--capital', type=float, default=10000)
    bt_parser.add_argument('--risk', type=float, default=1.0)
    bt_parser.add_argument('--min_confluence', type=int, default=70)
    bt_parser.add_argument('--min_rr', type=float, default=2.5)
    bt_parser.add_argument('--max_trades', type=int, default=100)
    
    subparsers.add_parser('demo', help='Демо режим')
    subparsers.add_parser('panic', help='Экстренное закрытие')

    args = parser.parse_args()
    logger.info(f"Command: {args.command}")
    if args.command == 'scan': cmd_scan(args)
    elif args.command == 'backtest': cmd_backtest(args)
    elif args.command == 'demo': cmd_demo(args)
    elif args.command == 'panic': cmd_panic(args)
    else: parser.print_help()

if __name__ == "__main__":
    main()
