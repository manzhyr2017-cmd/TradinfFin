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
from executor import OrderExecutor
from risk_manager import RiskManager
from orderflow import OrderFlowAnalyzer
from smart_money import SmartMoneyAnalyzer
from multi_timeframe import MultiTimeframeAnalyzer
from composite_score import CompositeScoreEngine
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
        
        # 1. Загрузка движков данных
        self.data = DataEngine()
        self.selector = SymbolSelector(self.data)
        self.executor = OrderExecutor(self.data)
        self.risk = RiskManager(self.data)
        self.tg = TitanTelegramBridge()
        
        # 2. Движки анализа (ИСПОЛЬЗУЕМ КОРРЕКТНЫЕ НАЗВАНИЯ КЛАССОВ)
        self.orderflow = OrderFlowAnalyzer(self.data)
        self.smc = SmartMoneyAnalyzer(self.data)
        self.mtf = MultiTimeframeAnalyzer(self.data)
        self.composite = CompositeScoreEngine()
        
        # 3. Настройки режима
        self.mode_settings = trade_modes.apply_mode(config.TRADE_MODE)
        
        # 4. Потоки данных
        self.stream = None

    def start(self):
        """Запуск торгового цикла"""
        self.is_running = True
        print(f"[TITAN] Запуск {config.TRADE_MODE} в режиме сканирования...")
        
        # Начальный отбор символов
        if config.MULTI_SYMBOL_ENABLED:
            try:
                self.symbol_list = self.selector.get_top_symbols(config.MAX_SYMBOLS)
                print(f"[Selector] Отобрано {len(self.symbol_list)} монет.")
            except Exception as e:
                print(f"[Selector] Ошибка отбора: {e}")
                self.symbol_list = [config.SYMBOL]

        # WebSocket
        if config.WEBSOCKET_ENABLED:
            try:
                self.stream = RealtimeDataStream()
                # Мы передаем список всех монет для подписки
                self.stream.start(self.symbol_list)
            except Exception as e:
                print(f"[Stream] WebSocket Error: {e}. Falling back to REST.")
                self.stream = None
        
        cycle_count = 0
        while self.is_running:
            try:
                # Обновляем топ-монеты раз в 10 циклов (~150 сек в агрессивке)
                if config.MULTI_SYMBOL_ENABLED and cycle_count % 10 == 0 and cycle_count > 0:
                    new_symbols = self.selector.get_top_symbols(config.MAX_SYMBOLS)
                    if set(new_symbols) != set(self.symbol_list):
                        print("[Selector] Watchlist updated.")
                        self.symbol_list = new_symbols
                        # Перезапускаем WebSocket на новый список
                        if self.stream: self.stream.start(self.symbol_list)

                for symbol in self.symbol_list:
                    if not self.is_running: break
                    self.current_symbol = symbol
                    print(f"🔍 [Scanning] {symbol:10}...", end="\r")
                    self._process_symbol(symbol)
                    time.sleep(0.5) # Пауза чтобы не перегрузить API
                
                cycle_count += 1
                # Небольшой отдых между полными кругами
                time.sleep(config.ANALYSIS_INTERVAL)
                
            except Exception as e:
                print(f"[CRITICAL] Error in main loop: {e}")
                time.sleep(10)

    def _process_symbol(self, symbol):
        """Обработка одной монеты"""
        try:
            # 1. Если уже есть открытая поза - не ищем новый вход
            if self.risk.has_position(symbol):
                return

            # 2. Быстрые фильтры
            if not self._pass_pre_checks(symbol):
                return
            
            # 3. Полный анализ
            mtf_signal = self.mtf.analyze(symbol)
            smc_signal = self.smc.analyze(symbol)
            # Передаем поток данных в OrderFlow если он есть
            of_signal = self.orderflow.analyze(symbol, realtime_stream=self.stream)
            
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
            
            # Выводим балл если он хоть немного интересен
            if abs(score) >= 15:
                status_icon = "🔥" if abs(score) >= min_score else "🔍"
                print(f"{status_icon} [Analysis] {symbol:10} | Score: {score:+.1f} | Need: {min_score}")
            
            # 4. Решение
            if abs(score) >= min_score:
                print(f"💰 [SIGNAL] {symbol} Triggered! Score: {score:+.1f}. Direction: {composite.direction}")
                self._execute_trade(symbol, composite, smc_signal)
                
        except Exception as e:
            # logging.error(f"Error {symbol}: {e}")
            pass

    def _pass_pre_checks(self, symbol):
        """Убрали лишние блокировки для режима Aggressive"""
        return True

    def _execute_trade(self, symbol, composite, smc_signal):
        """Вход в позицию"""
        direction = composite.direction
        side = "Buy" if direction == "LONG" else "Sell"
        
        # Текущая цена
        klines = self.data.get_klines(symbol, limit=2)
        if klines is None or klines.empty: return
        current_price = klines['close'].iloc[-1]
        
        # Стоп-лосс и Тейк (по приоритету SMC)
        sl_price = smc_signal.stop_loss if smc_signal and smc_signal.stop_loss else 0
        tp_price = smc_signal.take_profit if smc_signal and smc_signal.take_profit else 0

        # Расчет объема через риск-менеджер
        pos_size = self.risk.calculate_position_size(
            symbol=symbol,
            stop_loss_price=sl_price,
            risk_percent=self.mode_settings['risk_per_trade']
        )
        
        if not pos_size.is_valid:
            print(f"🛑 [Risk] {symbol} rejected: {pos_size.rejection_reason}")
            return

        # ИСПОЛНЕНИЕ
        print(f"⚡ [AUTO] Executing {side} on {symbol} @ {current_price}...")
        order = self.executor.place_order(
            symbol=symbol,
            side=side,
            quantity=pos_size.quantity,
            price=current_price,
            stop_loss=sl_price,
            take_profit=tp_price
        )
        
        if order.success:
            # Шлем сигнал в Telegram
            self.tg.send_signal({
                'symbol': symbol,
                'direction': direction,
                'score': composite.total_score,
                'entry': current_price,
                'sl': sl_price,
                'tp': tp_price,
                'confidence': composite.confidence,
                'strength': composite.strength,
                'recommendation': composite.recommendation
            })

    def _shutdown(self):
        self.is_running = False
        if self.stream: self.stream.stop()

if __name__ == "__main__":
    bot = TitanBotUltimateFinal()
    bot.start()
