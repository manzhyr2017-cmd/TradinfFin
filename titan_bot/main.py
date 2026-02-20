"""
TITAN BOT 2026 - ULTIMATE FINAL EDITION
Все модули + Composite Score + Smart Money + Order Flow + ML
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
from news_filter import NewsFilter
from multi_timeframe import MultiTimeframeAnalyzer
from correlations import CorrelationAnalyzer
from market_regime import MarketRegimeDetector
from open_interest import OpenInterestAnalyzer
from liquidations import LiquidationAnalyzer
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
        
        # Управление позициями
        self.trailing = TrailingStopManager(self.executor)
        
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
        
        print(f"[TITAN] Ожидание сброса лимитов Bybit (5 сек)...")
        time.sleep(5)
        print(f"[TITAN] Запуск ULTIMATE FINAL в режиме сканирования...")
        
        # Первичный подбор символов (только ОДИН раз здесь)
        if config.MULTI_SYMBOL_ENABLED:
            # Запрашиваем нужное количество монет
            count = config.MAX_SYMBOLS
            self.symbol_list = self.selector.get_top_symbols(count)
        
        # Инициализация WebSocket
        if config.WEBSOCKET_ENABLED:
            self.stream = RealtimeDataStream()
            self.stream.symbol_list = self.symbol_list # Важно передать список
            self.stream.start(self.symbol_list)
            time.sleep(3)
        
        # Восстановление позиций (если бот перезагрузился)
        self._recover_tracked_positions()
        
        cycle_count = 0
        while self.is_running:
            try:
                # Проверка WebSocket (реконнект если упал)
                if config.WEBSOCKET_ENABLED:
                    if not self.stream or not self.stream.ws:
                        print("[TITAN] Реинициализация WebSocket...")
                        self.stream = RealtimeDataStream()
                        self.stream.start(self.symbol_list)
                
                # Обновление списка топ монет (раз в 10 циклов)
                if config.MULTI_SYMBOL_ENABLED and cycle_count % 10 == 0 and cycle_count > 0:
                    new_symbols = self.selector.get_top_symbols(config.MAX_SYMBOLS)
                    
                    # Если список изменился, обновляем подписку
                    if set(new_symbols) != set(self.symbol_list):
                        print(f"[TITAN] Обновление списка монет ({len(new_symbols)} шт)...")
                        self.symbol_list = new_symbols
                        
                        if self.stream and self.stream.ws:
                            self.stream.ws.exit()
                            self.stream = RealtimeDataStream()
                            self.stream.start(self.symbol_list)

                # === ГЛАВНЫЙ ЦИКЛ ПО ВСЕМ МОНЕТАМ ===
                for symbol in self.symbol_list:
                    if not self.is_running: break
                    
                    self.current_symbol = symbol
                    self._process_symbol(symbol)
                    
                    # Пауза между монетами, чтобы не спамить (1 сек достаточно если есть WS)
                    time.sleep(1)
                
                cycle_count += 1
                # Пауза между полными кругами
                time.sleep(config.ANALYSIS_INTERVAL)
                
            except KeyboardInterrupt:
                self._shutdown()
                break
            except Exception as e:
                print(f"[CRITICAL] Ошибка в главном цикле: {e}")
                time.sleep(10)

    def _process_symbol(self, symbol):
        """Обработка одной монеты"""
        try:
            # 1. Сначала управляем позициями (трейлинг, закрытие)
            self._manage_positions(symbol)
            
            # 2. Если уже есть поза - не ищем новый вход (для простоты пока так)
            if self.risk.has_position(symbol):
                return

            # 3. Анализ (Composite Score)
            # Сначала проверяем фильтры "на берегу", чтобы не грузить CPU
            if not self._pass_pre_checks(symbol):
                return
            
            # Полный анализ
            mtf_signal = self.mtf.analyze(symbol)
            smc_signal = self.smc.analyze(symbol)
            of_signal = self.orderflow.analyze(symbol)
            if config.WEBSOCKET_ENABLED and self.stream:
                # Добавляем данные из стрима в OF
                of_signal = self.orderflow.enrich_with_stream(of_signal, self.stream.get_data(symbol))

            # Считаем итоговый балл
            composite = self.composite.calculate(
                symbol=symbol,
                mtf_analysis=mtf_signal,
                smc_signal=smc_signal,
                orderflow_signal=of_signal
            )

            # 4. Решение
            min_score = self.mode_settings['composite_min_score']
            if abs(composite.total_score) >= min_score:
                self._execute_trade(symbol, composite, smc_signal)
                
        except Exception as e:
            # Логируем, но не падаем
            # print(f"Error processing {symbol}: {e}")
            pass

    def _pass_pre_checks(self, symbol):
        """Быстрые проверки перед тяжелым анализом"""
        # 1. Session Filter
        if self.mode_settings['session_filter']:
            if not self.session.is_active(symbol, min_quality=self.mode_settings['session_min_quality']):
                return False
                
        # 2. News Filter
        if self.mode_settings['news_filter']:
             if self.news.is_danger_zone(symbol):
                 return False
                 
        return True

    def _execute_trade(self, symbol, composite, smc_signal):
        """Вход в сделку"""
        direction = composite.direction # "LONG" / "SHORT"
        
        # 1. Расчет риска
        # Если есть SMC сигнал c уровнем стопа - используем его
        stop_loss_price = None
        if smc_signal and smc_signal.stop_loss:
            stop_loss_price = smc_signal.stop_loss
            
        pos_size = self.risk.calculate_position_size(
            symbol=symbol, 
            stop_loss_price=stop_loss_price,
            risk_percent=self.mode_settings['risk_per_trade']
        )
        
        if not pos_size.is_valid:
            print(f"[Risk] Отказ: {pos_size.rejection_reason}")
            return

        # 2. Отправка ордера
        order = self.executor.place_order(
            symbol=symbol,
            side="Buy" if direction == "LONG" else "Sell",
            qty=pos_size.quantity,
            stop_loss=pos_size.risk_amount, # Тут надо передать цену, а не сумму. Поправим в executor
            take_profit=smc_signal.take_profit if smc_signal else None
        )
        
        if order:
            # 3. Уведомление
            self.telegram.send_signal({
                'symbol': symbol,
                'direction': direction,
                'score': composite.total_score,
                'entry': composite.entry_price,
                'sl': stop_loss_price,
                'tp': smc_signal.take_profit if smc_signal else 0,
                'confidence': composite.confidence,
                'recommendation': composite.recommendation,
                'strength': 'STRONG' if abs(composite.total_score) > 45 else 'MODERATE'
            })

    def _manage_positions(self, symbol):
        """Трейлинг стоп и мониторинг"""
        self.trailing.update(symbol)
        
    def _recover_tracked_positions(self):
        """Восстановление после перезапуска"""
        # TODO: Реализовать чтение ордеров с биржи
        pass

    def _shutdown(self):
        self.is_running = False
        print("🛑 TITAN BOT STOPPED.")

if __name__ == "__main__":
    bot = TitanBotUltimateFinal()
    bot.start()
