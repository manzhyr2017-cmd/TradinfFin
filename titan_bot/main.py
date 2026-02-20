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
from multi_timeframe import MTFAnalyzer
from composite_score import CompositeEngine
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
                self.stream.start(self.symbol_list)
            except Exception as e:
                print(f"[Stream] Ошибка WS: {e}")
        
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
                    print(f"🔍 [Scanning] {symbol}...", end="\r")
                    self._process_symbol(symbol)
                    time.sleep(0.5)
                
                cycle_count += 1
                time.sleep(config.ANALYSIS_INTERVAL)
                
            except Exception as e:
                print(f"[CRITICAL] Error in main loop: {e}")
                time.sleep(10)

    def _process_symbol(self, symbol):
        """Обработка одной монеты"""
        try:
            # 1. Позиции
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
            
            # Выводим балл если он хоть сколько-то значимый
            if abs(score) >= 10:
                status_icon = "🔥" if abs(score) >= min_score else "�"
                print(f"{status_icon} [Analysis] {symbol:10} | Score: {score:+.1f} | Need: {min_score}")
            
            # 4. Решение
            if abs(score) >= min_score:
                print(f"💰 [SIGNAL] {symbol} Triggered! Score: {score}")
                self._execute_trade(symbol, composite, smc_signal)
                
        except Exception as e:
            # print(f"Error {symbol}: {e}")
            pass

    def _pass_pre_checks(self, symbol):
        return True

    def _execute_trade(self, symbol, composite, smc_signal):
        direction = composite.direction
        side = "Buy" if direction == "LONG" else "Sell"
        
        klines = self.data.get_klines(symbol, limit=2)
        if klines is None or klines.empty: return
        current_price = klines['close'].iloc[-1]
        
        sl_price = smc_signal.stop_loss if smc_signal and smc_signal.stop_loss else 0
        tp_price = smc_signal.take_profit if smc_signal and smc_signal.take_profit else 0

        pos_size = self.risk.calculate_position_size(
            symbol=symbol,
            stop_loss_price=sl_price,
            risk_percent=self.mode_settings['risk_per_trade']
        )
        
        if not pos_size.is_valid:
            print(f"🛑 [Risk] {symbol} rejected: {pos_size.rejection_reason}")
            return

        print(f"⚡ [AUTO] Executing {side} on {symbol}...")
        order = self.executor.place_order(
            symbol=symbol,
            side=side,
            quantity=pos_size.quantity,
            stop_loss=sl_price,
            take_profit=tp_price
        )
        
        if order.success:
            self.tg.send_signal({
                'symbol': symbol,
                'direction': direction,
                'score': composite.total_score,
                'entry': current_price,
                'sl': sl_price,
                'tp': tp_price,
                'confidence': 0.85,
                'strength': "Aggressive",
                'recommendation': composite.recommendation
            })

    def start_scanner_mode(self):
        self.start()

    def _shutdown(self):
        self.is_running = False

if __name__ == "__main__":
    bot = TitanBotUltimateFinal()
    bot.start()
