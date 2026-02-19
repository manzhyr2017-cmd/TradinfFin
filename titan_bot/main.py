"""
TITAN BOT 2026 - ULTIMATE FINAL EDITION
Все модули + Composite Score
"""

import time
import sys
from datetime import datetime
import config
import trade_modes

# ВСЕ МОДУЛИ
from data_engine import DataEngine, RealtimeDataStream
from orderflow import OrderFlowAnalyzer
from smart_money import SmartMoneyAnalyzer
from ml_engine import MLEngine
from risk_manager import RiskManager
from executor import OrderExecutor
from trailing_stop import TrailingStopManager
from session_filter import SessionFilter
from analytics import TradingAnalytics
from multi_timeframe import MultiTimeframeAnalyzer
from market_regime import MarketRegimeDetector
from partial_tp import PartialTakeProfitManager
from cooldown import CooldownManager
from open_interest import OpenInterestAnalyzer
from liquidations import LiquidationAnalyzer
from correlations import CorrelationAnalyzer
from news_filter import NewsFilter
from volume_profile import VolumeProfileAnalyzer
from whale_tracker import WhaleTracker
from fear_greed import FearGreedAnalyzer
from composite_score import CompositeScoreEngine
from telegram_bridge import TitanTelegramBridge
from selector import SymbolSelector


class TitanBotUltimateFinal:
    """Финальная версия со всеми модулями."""
    
    def __init__(self, symbol=None):
        self.symbol_list = [symbol] if symbol else [config.SYMBOL]
        self.current_symbol = self.symbol_list[0]
        self._print_banner()
        
        # Применяем режим торговли из конфига
        self.mode_settings = trade_modes.apply_mode(config.TRADE_MODE)
        
        # Базовые модули
        self.data = DataEngine()
        self.selector = SymbolSelector(self.data)
        self.executor = OrderExecutor(self.data)
        self.risk = RiskManager(self.data)
        
        # Аналитические модули
        self.mtf = MultiTimeframeAnalyzer(self.data)
        self.smc = SmartMoneyAnalyzer(self.data)
        self.orderflow = OrderFlowAnalyzer(self.data)
        self.regime = MarketRegimeDetector(self.data)
        self.oi = OpenInterestAnalyzer(self.data)
        self.liquidations = LiquidationAnalyzer(self.data)
        self.correlations = CorrelationAnalyzer(self.data)
        self.volume_profile = VolumeProfileAnalyzer(self.data)
        self.whale = WhaleTracker()
        self.fear_greed = FearGreedAnalyzer()
        
        # Фильтры
        self.session = SessionFilter()
        self.news = NewsFilter()
        self.cooldown = CooldownManager()
        
        # Управление позициями
        self.trailing = TrailingStopManager(self.executor)
        self.partial_tp = PartialTakeProfitManager(self.executor)
        
        # Аналитика
        self.analytics = TradingAnalytics()
        
        # ГЛАВНОЕ: Композитный скоринг
        self.composite = CompositeScoreEngine()
        self.telegram = TitanTelegramBridge()
        
        # Состояние
        self.is_running = False
        self.stream = None
        
        print("🚀 TITAN BOT ULTIMATE FINAL загружен!")

    def _print_banner(self):
        print("""
╔═══════════════════════════════════════════════════════════╗
║                                                           ║
║   ████████╗██╗████████╗ █████╗ ███╗   ██╗               ║
║   ╚══██╔══╝██║╚══██╔══╝██╔══██╗████╗  ██║               ║
║      ██║   ██║   ██║   ███████║██╔██╗ ██║               ║
║      ██║   ██║   ██║   ██╔══██║██║╚██╗██║               ║
║      ██║   ██║   ██║   ██║  ██║██║ ╚████║               ║
║      ╚═╝   ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝               ║
║                                                           ║
║              BOT 2026 - ULTIMATE FINAL                   ║
║                  "One Score to Rule Them All"             ║
║                                                           ║
╚═══════════════════════════════════════════════════════════╝
        """)
    
    def start(self):
        """Запуск бота."""
        self.is_running = True
        
        print(f"[TITAN] Ожидание сброса лимитов Bybit (10 сек)...")
        time.sleep(10)
        print(f"[TITAN] Запуск ULTIMATE FINAL в режиме сканирования...")
        
        # Первичный подбор символов (только ОДИН раз здесь)
        if config.MULTI_SYMBOL_ENABLED:
            self.symbol_list = self.selector.get_top_symbols(config.MAX_SYMBOLS)
        
        if config.WEBSOCKET_ENABLED:
            self.stream = RealtimeDataStream()
            # Подписываемся сразу на весь список!
            self.stream.start(self.symbol_list)
            time.sleep(5)
        
        cycle_count = 0
        while self.is_running:
            try:
                # Раз в 5 циклов (примерно каждые 15-20 мин) обновляем список топов
                if config.MULTI_SYMBOL_ENABLED and cycle_count % 5 == 0 and cycle_count > 0:
                    new_symbols = self.selector.get_top_symbols(10)
                    if new_symbols != self.symbol_list:
                        self.symbol_list = new_symbols
                        # Если список сменился, перезапускаем WS
                        if self.stream:
                            if self.stream.ws: self.stream.ws.exit()
                            self.stream.ws = None
                            self.stream.start(self.symbol_list)
                
                for symbol in self.symbol_list:
                    self.current_symbol = symbol
                    self._main_loop(symbol)
                    
                    # Пауза 3 секунды между монетами по просьбе юзера
                    time.sleep(3)
                
                cycle_count += 1
                
            except KeyboardInterrupt:
                self._shutdown()
                break
            except Exception as e:
                print(f"[TITAN] ❌ Error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(10)
    
    def _main_loop(self, symbol):
        """Главный цикл для конкретной монеты."""
        print(f"\n{'='*70}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ANALYSIS CYCLE - {symbol}")
        print('='*70)
        
        # ══════════════════════════════════════════
        # ФИЛЬТРЫ (быстрая проверка)
        # ══════════════════════════════════════════
        
        pass_filters, filter_msg = self._pass_filters(symbol)
        if not pass_filters:
            # Если сигнал сильный, но фильтры не пустили - логгируем почему
            print(f"[{symbol}] ⏭️ Trade skipped by filter: {filter_msg}")
            self._manage_positions(symbol)
            return
        
        # ══════════════════════════════════════════
        # СБОР ВСЕХ ДАННЫХ
        # ══════════════════════════════════════════
        print(f"[{symbol}] Собираю разведданные...")
        
        mtf_analysis = self.mtf.analyze(symbol)
        smc_signal = self.smc.analyze(symbol)
        of_signal = self.orderflow.analyze(symbol, self.stream)
        regime = self.regime.analyze(symbol)
        oi = self.oi.analyze(symbol)
        vp = self.volume_profile.analyze(symbol)
        whale = self.whale.analyze(symbol)
        fg = self.fear_greed.analyze()
        corr = self.correlations.analyze(symbol)
        
        # ══════════════════════════════════════════
        # COMPOSITE SCORE
        # ══════════════════════════════════════════
        
        composite_signal = self.composite.calculate(
            symbol=symbol,
            mtf_analysis=mtf_analysis,
            smc_signal=smc_signal,
            orderflow_signal=of_signal,
            volume_profile=vp,
            oi_analysis=oi,
            regime_analysis=regime,
            whale_analysis=whale,
            fear_greed=fg,
            correlation_analysis=corr
        )
        
        # Выводим дашборд
        self.composite.print_dashboard(composite_signal)
        
        # Отправляем в ТГ если сигнал сильный
        if abs(composite_signal.total_score) > 40:
             self.telegram.send_dashboard(composite_signal, symbol)
        
        # ══════════════════════════════════════════
        # РЕШЕНИЕ
        # ══════════════════════════════════════════
        
        if composite_signal.direction != "NEUTRAL" and composite_signal.strength in ["STRONG", "MODERATE"]:
            self._execute_trade(symbol, composite_signal, smc_signal, regime)
        else:
            # Если нет входа, просто мониторим позиции
            self._manage_positions(symbol)
    
    def _pass_filters(self, symbol) -> bool:
        """Проверяет все фильтры."""
        
        # Cooldown
        cooldown = self.cooldown.can_trade()
        if cooldown.is_active:
            return False, f"Cooldown: {cooldown.message}"
        
        # Session
        if self.mode_settings.get("session_filter", True):
            can_trade, msg = self.session.is_good_time_to_trade(
                min_quality=self.mode_settings.get("session_min_quality", 5)
            )
            if not can_trade:
                return False, f"Session: {msg}"
        else:
            print("[Filter] 🕐 Session: IGNORED (Aggressive Mode)")
        
        # News
        if self.mode_settings.get("news_filter", True):
            news = self.news.check()
            if not news.can_trade:
                return False, f"News: {news.message}"
        
        # Risk limits
        risk = self.risk.check_risk_limits()
        if not risk.can_trade:
            return False, f"Risk: {risk.reason}"
        
        print("[Filter] ✅ Все фильтры пройдены")
        return True, "OK"
    
    def _execute_trade(self, symbol, composite, smc_signal, regime):
        """Исполняет сделку."""
        
        # Если нет сигнала от SMC, но сигнал ОЧЕНЬ сильный - заходим по рынку
        is_very_strong = composite.total_score >= 40
        
        if smc_signal is None:
            if is_very_strong:
                print(f"[Trade] {symbol}: SMC не дал точку, но Score {composite.total_score} > 40. ВХОДИМ ПО РЫНКУ!")
                # Создаем фейковый сигнал для входа по рынку
                ticker = self.data.session.get_tickers(category=config.CATEGORY, symbol=symbol)
                current_price = float(ticker['result']['list'][0]['lastPrice'])
                
                # Примерный стоп 1% для рыночного входа
                sl_dist = current_price * 0.01
                sl = current_price - sl_dist if composite.direction == 'LONG' else current_price + sl_dist
                
                from smart_money import SMCSignal, SMCSignalType
                smc_signal = SMCSignal(
                    signal_type=SMCSignalType.NO_SIGNAL,
                    entry_price=current_price,
                    stop_loss=sl,
                    take_profit=current_price + (sl_dist * 2),
                    liquidity_level=current_price,
                    confidence=0.5,
                    description="Market Entry (High Score)"
                )
            else:
                print(f"[Trade] {symbol}: ❌ Нет точки входа от SMC и Score ({composite.total_score}) недостаточно высокий для входа по рынку")
                return
        
        # Определяем тип ордера
        order_type = "Market" if is_very_strong else "Limit"
        
        # Рассчитываем размер позиции
        base_position = self.risk.calculate_position_size(
            entry_price=smc_signal.entry_price,
            stop_loss=smc_signal.stop_loss
        )
        
        if not base_position.is_valid:
            error_msg = f"Rejection: {base_position.rejection_reason}"
            print(f"[Trade] {symbol}: ❌ {error_msg}")
            # Уведомляем в ТГ если сигнал был очень сильный
            if is_very_strong:
                self.telegram.send_message(f"⚠️ <b>SKIP TRADE {symbol}</b>\nScore: {composite.total_score}\nReason: {base_position.rejection_reason}")
            return
        
        # Применяем модификаторы
        final_qty = base_position.quantity * composite.position_size_modifier * regime.position_size_multiplier
        final_qty = self.risk._round_quantity(final_qty, symbol)
        
        if final_qty * smc_signal.entry_price < 5:
            print(f"[Trade] {symbol}: ❌ Позиция слишком мала")
            return
 
        # Вход
        side = 'Buy' if composite.direction == 'LONG' else 'Sell'
        
        print(f"\n{'🚀'*30}")
        print(f"[TRADE] {symbol} | {composite.direction} | Score: {composite.total_score}")
        print(f"  Entry: {smc_signal.entry_price:.4f}")
        print(f"  SL: {smc_signal.stop_loss:.4f}")
        print(f"  Qty: {final_qty}")
        print(f"  Confidence: {composite.confidence*100:.0f}%")
        print(f"{'🚀'*30}\n")
        
        result = self.executor.place_order(
            symbol=symbol,
            side=side,
            quantity=final_qty,
            price=smc_signal.entry_price,
            stop_loss=smc_signal.stop_loss,
            order_type=order_type
        )
        
        if result.success:
            # Регистрируем для управления
            df = self.data.get_klines(symbol, limit=20)
            atr = df['atr'].iloc[-1] if (df is not None and not df.empty) else smc_signal.entry_price * 0.01
            
            self.trailing.register_position(
                symbol=symbol,
                side=composite.direction,
                entry_price=smc_signal.entry_price,
                initial_stop=smc_signal.stop_loss,
                atr=atr
            )
            
            self.partial_tp.register_position(
                symbol=symbol,
                side=composite.direction,
                entry_price=smc_signal.entry_price,
                stop_loss=smc_signal.stop_loss,
                quantity=final_qty
            )
            
            # Уведомление в ТГ об исполнении
            self.telegram.send_signal({
                'symbol': symbol,
                'direction': composite.direction,
                'score': composite.total_score,
                'entry': smc_signal.entry_price,
                'sl': smc_signal.stop_loss,
                'tp': smc_signal.take_profit_1,
                'confidence': composite.confidence,
                'strength': composite.strength,
                'recommendation': composite.recommendation
            })
            
            print(f"[TRADE] ✅ Order executed successfully. Symbol: {symbol}, Order ID: {result.order_id}")
    
    def _manage_positions(self, symbol):
        """Управляет открытыми позициями."""
        positions = self.data.get_positions(symbol)
        
        if not positions:
            return
        
        ticker = self.data.get_funding_rate(symbol)
        if ticker:
            current_price = ticker['last_price']
            self.trailing.update(symbol, current_price)
            self.partial_tp.check_and_execute(symbol, current_price)
    
    def _shutdown(self):
        """Завершение работы."""
        self.is_running = False
        print("\n" + "="*70)
        print("TITAN BOT SHUTTING DOWN")
        print("="*70)
        if self.stream: self.stream.stop()
        self.analytics.print_report(30)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--mode", type=str, choices=["bot", "scan"], default="bot")
    args = parser.parse_args()
    
    bot = TitanBotUltimateFinal(symbol=args.symbol)
    
    if args.mode == "bot":
        bot.start()
    else:
        bot._main_loop()
