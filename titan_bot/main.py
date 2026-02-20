"""
TITAN BOT 2026 - Main Controller (ULTIMATE FINAL)
Центральный запуск и координация всех модулей.
"""

import time
import threading
import logging
from datetime import datetime, timedelta
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

ASCII_ART = """
████████╗██╗████████╗ █████╗ ███╗   ██╗
╚══██╔══╝██║╚══██╔══╝██╔══██╗████╗  ██║
   ██║   ██║   ██║   ███████║██╔██╗ ██║
   ██║   ██║   ██║   ██╔══██║██║╚██╗██║
   ██║   ██║   ██║   ██║  ██║██║ ╚████║
   ╚═╝   ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═══╝
      TITAN BOT 2026 | ULTIMATE TRADING
"""

class TitanBotUltimateFinal:
    """
    Главный оркестратор системы TITAN.
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
        
        # 2. Движки анализа
        self.orderflow = OrderFlowAnalyzer(self.data)
        self.smc = SmartMoneyAnalyzer(self.data)
        self.mtf = MultiTimeframeAnalyzer(self.data)
        self.composite = CompositeScoreEngine()
        
        # 3. Настройки режима
        self.mode_settings = trade_modes.apply_mode(config.TRADE_MODE)
        
        # 4. Состояние
        self.stream = None
        self.last_status_time = datetime.now()
        self.processed_count = 0

    def start(self):
        """Запуск торгового цикла"""
        self.is_running = True
        print(ASCII_ART)
        print(f"[TITAN] Запуск {config.TRADE_MODE} (Professional Mode)")
        print(f"[Config] Scanning Interval: 3.0 sec per symbol")
        print(f"[Config] Min Score for Entry: {self.mode_settings['composite_min_score']}")
        
        # Начальный отбор символов
        if config.MULTI_SYMBOL_ENABLED:
            try:
                self.symbol_list = self.selector.get_top_symbols(config.MAX_SYMBOLS)
                print(f"[Selector] Отобрано {len(self.symbol_list)} монет по волатильности.")
            except Exception as e:
                print(f"[Selector] Ошибка отбора: {e}")
                self.symbol_list = [config.SYMBOL]

        # WebSocket
        if config.WEBSOCKET_ENABLED:
            try:
                self.stream = RealtimeDataStream()
                self.stream.start(self.symbol_list)
            except Exception as e:
                print(f"[Stream] WebSocket Error: {e}")
        
        cycle_count = 0
        while self.is_running:
            try:
                # Обновляем топ-монеты
                if config.MULTI_SYMBOL_ENABLED and cycle_count % 10 == 0 and cycle_count > 0:
                    self.symbol_list = self.selector.get_top_symbols(config.MAX_SYMBOLS)
                    if self.stream: self.stream.start(self.symbol_list)

                for symbol in self.symbol_list:
                    if not self.is_running: break
                    self.current_symbol = symbol
                    
                    # ПРЯМОЙ ЛОГ АНАЛИЗА (Мгновенно!)
                    start_time = time.time()
                    self._process_symbol(symbol)
                    self.processed_count += 1
                    
                    # Принудительная пауза 3 секунды
                    time.sleep(3.0)
                
                cycle_count += 1
                # Отчет в ТГ раз в полчаса
                if (datetime.now() - self.last_status_time) > timedelta(minutes=30):
                    self._send_heartbeat()
                
                time.sleep(config.ANALYSIS_INTERVAL)
                
            except Exception as e:
                print(f"[CRITICAL] Error in main loop: {e}")
                time.sleep(10)

    def _process_symbol(self, symbol):
        """Обработка одной монеты с детальным выводом"""
        try:
            if self.risk.has_position(symbol):
                print(f"📊 [Active] {symbol:10} | Skipping (Position exists)")
                return

            # Сбор данных и анализ
            mtf_signal = self.mtf.analyze(symbol)
            smc_signal = self.smc.analyze(symbol)
            of_signal = self.orderflow.analyze(symbol, realtime_stream=self.stream)
            
            # Композитный балл
            composite = self.composite.calculate(
                symbol=symbol,
                mtf_analysis=mtf_signal,
                smc_signal=smc_signal,
                orderflow_signal=of_signal
            )

            score = composite.total_score
            min_score = self.mode_settings['composite_min_score']
            
            # ВИЗУАЛИЗАЦИЯ ДЛЯ ТЕРМИНАЛА
            # [MTF +10 | SMC +15 | OF +5]
            details = f"M:{mtf_signal.confidence*20:+2.0f} S:{smc_signal.confidence*20:+2.0f} O:{of_signal.confidence*20:+2.0f}"
            
            if abs(score) >= min_score:
                status = "� [ENTRY]"
            elif abs(score) >= (min_score / 2):
                status = "🔍 [WATCH]"
            else:
                status = "🔘 [WAIT ]"

            print(f"{status} {symbol:10} | TOTAL: {score:+.1f} | {details} | need {min_score}")
            
            # Решение
            if abs(score) >= min_score:
                self._execute_trade(symbol, composite, smc_signal)
                
        except Exception as e:
            print(f"⚠️ [Error] {symbol}: {e}")

    def _send_heartbeat(self):
        self.last_status_time = datetime.now()
        msg = (
            f"📡 <b>TITAN HEARTBEAT</b>\n"
            f"Status: <b>ONLINE</b>\n"
            f"Analyzed: <b>{self.processed_count}</b> syms\n"
            f"Mode: <b>{config.TRADE_MODE}</b>"
        )
        self.tg.send_message(msg)

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

        print(f"⚡ [AUTO] Executing {side} on {symbol} @ {current_price}...")
        order = self.executor.place_order(
            symbol=symbol,
            side=side,
            quantity=pos_size.quantity,
            stop_loss=sl_price,
            take_profit=tp_price
        )
        
        if order.success:
            self.tg.send_signal({
                'symbol': symbol, 'direction': direction, 'score': composite.total_score,
                'entry': current_price, 'sl': sl_price, 'tp': tp_price,
                'confidence': composite.confidence, 'strength': composite.strength,
                'recommendation': composite.recommendation
            })

if __name__ == "__main__":
    bot = TitanBotUltimateFinal()
    bot.start()
