"""
TITAN BOT 2026 - ULTIMATE FINAL EDITION
Все модули + Composite Score
"""

import time
import sys
from datetime import datetime
import config

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


class TitanBotUltimateFinal:
    """Финальная версия со всеми модулями."""
    
    def __init__(self):
        self._print_banner()
        
        # Базовые модули
        self.data = DataEngine()
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
        
        print(f"[TITAN] Запуск ULTIMATE FINAL... Symbol: {config.SYMBOL}")
        
        if config.WEBSOCKET_ENABLED:
            self.stream = RealtimeDataStream()
            self.stream.start(config.SYMBOL)
            time.sleep(2)
        
        while self.is_running:
            try:
                self._main_loop()
                time.sleep(config.ANALYSIS_INTERVAL)
            except KeyboardInterrupt:
                self._shutdown()
                break
            except Exception as e:
                print(f"[TITAN] ❌ Error: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(10)
    
    def _main_loop(self):
        """Главный цикл."""
        print(f"\n{'='*70}")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ANALYSIS CYCLE")
        print('='*70)
        
        # ══════════════════════════════════════════
        # ФИЛЬТРЫ (быстрая проверка)
        # ══════════════════════════════════════════
        
        if not self._pass_filters():
            self._manage_positions()
            return
        
        # ══════════════════════════════════════════
        # СБОР ВСЕХ ДАННЫХ
        # ══════════════════════════════════════════
        print("[Analysis] Собираю разведданные...")
        
        mtf_analysis = self.mtf.analyze()
        smc_signal = self.smc.analyze()
        of_signal = self.orderflow.analyze(config.SYMBOL, self.stream)
        regime = self.regime.analyze()
        oi = self.oi.analyze()
        vp = self.volume_profile.analyze()
        whale = self.whale.analyze()
        fg = self.fear_greed.analyze()
        corr = self.correlations.analyze()
        
        # ══════════════════════════════════════════
        # COMPOSITE SCORE
        # ══════════════════════════════════════════
        
        composite_signal = self.composite.calculate(
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
             self.telegram.send_dashboard(composite_signal)
        
        # ══════════════════════════════════════════
        # РЕШЕНИЕ
        # ══════════════════════════════════════════
        
        if composite_signal.direction != "NEUTRAL" and composite_signal.strength in ["STRONG", "MODERATE"]:
            self._execute_trade(composite_signal, smc_signal, regime)
        else:
            # Если нет входа, просто мониторим позиции
            self._manage_positions()
    
    def _pass_filters(self) -> bool:
        """Проверяет все фильтры."""
        
        # Cooldown
        cooldown = self.cooldown.can_trade()
        if cooldown.is_active:
            print(f"[Filter] ⏸️ Cooldown: {cooldown.message}")
            return False
        
        # Session
        can_trade, msg = self.session.is_good_time_to_trade()
        if not can_trade:
            print(f"[Filter] 🕐 Session: {msg}")
            return False
        
        # News
        news = self.news.check()
        if not news.can_trade:
            print(f"[Filter] 📰 News: {news.message}")
            return False
        
        # Risk limits
        risk = self.risk.check_risk_limits()
        if not risk.can_trade:
            print(f"[Filter] 💰 Risk: {risk.reason}")
            return False
        
        print("[Filter] ✅ Все фильтры пройдены")
        return True
    
    def _execute_trade(self, composite, smc_signal, regime):
        """Исполняет сделку."""
        
        if smc_signal is None:
            print("[Trade]Нет точки входа от SMC")
            return
        
        # Рассчитываем размер позиции
        base_position = self.risk.calculate_position_size(
            entry_price=smc_signal.entry_price,
            stop_loss=smc_signal.stop_loss
        )
        
        if not base_position.is_valid:
            print(f"[Trade] ❌ {base_position.rejection_reason}")
            return
        
        # Применяем модификаторы
        final_qty = base_position.quantity * composite.position_size_modifier * regime.position_size_multiplier
        final_qty = round(final_qty, 3)
        
        if final_qty * smc_signal.entry_price < 5:
            print("[Trade] ❌ Позиция слишком мала")
            return

        # Вход
        side = 'Buy' if composite.direction == 'LONG' else 'Sell'
        
        print(f"\n{'🚀'*30}")
        print(f"[TRADE] {composite.direction} | Score: {composite.total_score}")
        print(f"  Entry: {smc_signal.entry_price:.4f}")
        print(f"  SL: {smc_signal.stop_loss:.4f}")
        print(f"  Qty: {final_qty}")
        print(f"  Confidence: {composite.confidence*100:.0f}%")
        print(f"{'🚀'*30}\n")
        
        result = self.executor.place_order(
            symbol=config.SYMBOL,
            side=side,
            quantity=final_qty,
            price=smc_signal.entry_price,
            stop_loss=smc_signal.stop_loss
        )
        
        if result.success:
            # Регистрируем для управления
            df = self.data.get_klines(config.SYMBOL, limit=20)
            atr = df['atr'].iloc[-1] if (df is not None and not df.empty) else smc_signal.entry_price * 0.01
            
            self.trailing.register_position(
                symbol=config.SYMBOL,
                side=composite.direction,
                entry_price=smc_signal.entry_price,
                initial_stop=smc_signal.stop_loss,
                atr=atr
            )
            
            self.partial_tp.register_position(
                symbol=config.SYMBOL,
                side=composite.direction,
                entry_price=smc_signal.entry_price,
                stop_loss=smc_signal.stop_loss,
                quantity=final_qty
            )
            
            # Уведомление в ТГ об исполнении
            self.telegram.send_signal({
                'symbol': config.SYMBOL,
                'direction': composite.direction,
                'score': composite.total_score,
                'entry': smc_signal.entry_price,
                'sl': smc_signal.stop_loss,
                'tp': smc_signal.take_profit_1,
                'confidence': composite.confidence,
                'strength': composite.strength,
                'recommendation': composite.recommendation
            })
            
            print(f"[TRADE] ✅ Order executed successfully. Order ID: {result.order_id}")
    
    def _manage_positions(self):
        """Управляет открытыми позициями."""
        positions = self.data.get_positions(config.SYMBOL)
        
        if not positions:
            return
        
        ticker = self.data.get_funding_rate(config.SYMBOL)
        if ticker:
            current_price = ticker['last_price']
            self.trailing.update(config.SYMBOL, current_price)
            self.partial_tp.check_and_execute(config.SYMBOL, current_price)
    
    def _shutdown(self):
        """Завершение работы."""
        self.is_running = False
        print("\n" + "="*70)
        print("TITAN BOT SHUTTING DOWN")
        print("="*70)
        if self.stream: self.stream.stop()
        self.analytics.print_report(30)


if __name__ == "__main__":
    bot = TitanBotUltimateFinal()
    
    print("\nTITAN ULTIMATE FINAL MENU:")
    print("  1. Start Live/Demo Bot")
    print("  2. Run Analysis Once")
    print("  3. Exit")
    
    choice = input("\nSelect: ").strip()
    
    if choice == "1":
        bot.start()
    elif choice == "2":
        bot._main_loop()
    else:
        print("Goodbye!")
