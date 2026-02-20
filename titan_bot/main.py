"""
TITAN BOT 2026 - Main Controller (ULTIMATE FINAL)
Центральный запуск и координация всех модулей.
"""

import time
import threading
import logging
from datetime import datetime
from data_engine import DataEngine, RealtimeDataStream
from selector import SymbolSelector
from execution import OrderExecutor
from risk_manager import RiskManager
from order_flow import OrderFlowAnalyzer
from smart_money import SmartMoneyAnalyzer
from mtf_engine import MTFAnalyzer
from composite_engine import CompositeEngine
from telegram_bridge import TitanTelegramBridge
import trade_modes
import config

class TitanBotUltimateFinal:
    """
    Главный оркестратор системы TITAN.
    Управляет многосимвольным сканированием, анализом и исполнением.
    """
    
    def __init__(self, symbol=None):
        self.is_running = False
        self.current_symbol = symbol or config.SYMBOL
        self.symbol_list = [self.current_symbol]
        
        # 1. Загрузка движков
        self.data = DataEngine()
        self.selector = SymbolSelector(self.data)
        self.executor = OrderExecutor(self.data)
        self.risk = RiskManager(self.data)
        self.tg = TitanTelegramBridge()
        
        # 2. Движки анализа
        self.orderflow = OrderFlowAnalyzer()
        self.smc = SmartMoneyAnalyzer()
        self.mtf = MTFAnalyzer()
        self.composite = CompositeEngine()
        
        # 3. Настройки режима
        self.mode_settings = trade_modes.apply_mode(config.TRADE_MODE)
        
        # 4. Потоки данных
        self.stream = None
        self.last_heartbeat = datetime.now()

    def start(self):
        """Запуск торгового цикла"""
        self.is_running = True
        print(f"[TITAN] Запуск {config.TRADE_MODE} в режиме сканирования...")
        
        # Начальный отбор символов
        if config.MULTI_SYMBOL_ENABLED:
            self.symbol_list = self.selector.get_top_symbols(config.MAX_SYMBOLS)
            print(f"[Selector] Отобрано {len(self.symbol_list)} монет.")

        # WebSocket (Один на все символы)
        if config.WEBSOCKET_ENABLED:
            self.stream = RealtimeDataStream()
            self.stream.start(self.symbol_list)
        
        cycle_count = 0
        while self.is_running:
            try:
                # Обновляем топ-монеты раз в 10 циклов
                if config.MULTI_SYMBOL_ENABLED and cycle_count % 10 == 0 and cycle_count > 0:
                    new_symbols = self.selector.get_top_symbols(config.MAX_SYMBOLS)
                    if set(new_symbols) != set(self.symbol_list):
                        print("[Selector] Watchlist updated.")
                        self.symbol_list = new_symbols
                        if self.stream: self.stream.start(self.symbol_list)

                for symbol in self.symbol_list:
                    if not self.is_running: break
                    self.current_symbol = symbol
                    self._process_symbol(symbol)
                    time.sleep(0.5) # Мини-пауза между тикерами
                
                cycle_count += 1
                time.sleep(config.ANALYSIS_INTERVAL)
                
            except Exception as e:
                print(f"[CRITICAL] Error in main loop: {e}")
                time.sleep(10)

    def _process_symbol(self, symbol):
        """Обработка одной монеты"""
        try:
            # 1. Позиции
            self._manage_positions(symbol)
            if self.risk.has_position(symbol):
                return

            # 2. Фильтры
            if not self._pass_pre_checks(symbol):
                return
            
            # 3. Полный анализ
            mtf_signal = self.mtf.analyze(symbol)
            smc_signal = self.smc.analyze(symbol)
            of_signal = self.orderflow.analyze(symbol)
            
            # Считаем балл
            composite = self.composite.calculate(
                symbol=symbol,
                mtf_analysis=mtf_signal,
                smc_signal=smc_signal,
                orderflow_signal=of_signal
            )

            # --- ПРОЗРАЧНЫЙ ЛОГ ---
            score = composite.total_score
            min_score = self.mode_settings['composite_min_score']
            
            # Выводим в консоль статус анализа каждой монеты
            # Только если балл > 10, чтобы не забивать экран мусором
            if abs(score) >= 15:
                status_icon = "🔥" if abs(score) >= min_score else "🔍"
                print(f"{status_icon} [Analysis] {symbol:10} | Score: {score:+.1f} | Need: {min_score}")
            
            # 4. Решение
            if abs(score) >= min_score:
                print(f"💰 [SIGNAL] Target Score Reached for {symbol}! Initiating trade...")
                self._execute_trade(symbol, composite, smc_signal)
                
        except Exception as e:
            # logging.error(f"Error {symbol}: {e}")
            pass

    def _pass_pre_checks(self, symbol):
        """Быстрые проверки"""
        # Session Filter
        if self.mode_settings.get('session_filter', False):
            # Тут могла быть блокировка. Если False - проходим.
            pass
        return True

    def _execute_trade(self, symbol, composite, smc_signal):
        """Вход в позицию"""
        direction = composite.direction
        side = "Buy" if direction == "LONG" else "Sell"
        
        # Получаем данные для входа
        klines = self.data.get_klines(symbol, limit=2)
        if klines is None or klines.empty: return
        current_price = klines['close'].iloc[-1]
        
        # Стоп-лосс (по SMC или ATR)
        sl_price = smc_signal.stop_loss if smc_signal and smc_signal.stop_loss else current_price * 0.99
        tp_price = smc_signal.take_profit if smc_signal and smc_signal.take_profit else current_price * 1.02

        # Расчет объема через риск-менеджер
        pos_size = self.risk.calculate_position_size(
            symbol=symbol,
            stop_loss_price=sl_price,
            risk_percent=self.mode_settings['risk_per_trade']
        )
        
        if not pos_size.is_valid:
            print(f"🛑 [Risk] Trade rejected: {pos_size.rejection_reason}")
            return

        # ИСПОЛНЕНИЕ
        print(f"⚡ [AUTO] Executing {side} on {symbol} @ {current_price}...")
        order = self.executor.place_order(
            symbol=symbol,
            side=side,
            quantity=pos_size.quantity,
            price=current_price,
            stop_loss=sl_price,
            take_profit=tp_price,
            leverage=10
        )
        
        if order.success:
            # Уведомление в ТГ через новый метод
            self.tg.send_signal({
                'symbol': symbol,
                'direction': direction,
                'score': composite.total_score,
                'entry': current_price,
                'sl': sl_price,
                'tp': tp_price,
                'confidence': 0.85,
                'strength': "Aggressive Confluence",
                'recommendation': composite.recommendation
            })

    def _manage_positions(self, symbol):
        """Тут будет логика трейлинга и выхода"""
        pass

    def _shutdown(self):
        print("\n[TITAN] Shutting down...")
        self.is_running = False
        if self.stream: self.stream.stop()

if __name__ == "__main__":
    bot = TitanBotUltimateFinal()
    bot.start()
