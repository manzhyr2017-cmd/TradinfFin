"""
TITAN BOT 2026 - Main Controller (ULTIMATE FINAL v2)
Центральный запуск и координация всех модулей.
Версия 2: Circuit Breakers, Coin Blacklist, Drawdown Protection
"""

import time
import threading
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from data_engine import DataEngine, RealtimeDataStream
from selector import SymbolSelector
from executor import OrderExecutor
from risk_manager import RiskManager
from orderflow import OrderFlowAnalyzer
from smart_money import SmartMoneyAnalyzer
from multi_timeframe import MultiTimeframeAnalyzer
from composite_score import CompositeScoreEngine
from telegram_bridge import TitanTelegramBridge
from database import TitanDatabase
from ml_engine import MLEngine
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
        
        # 1. Загрузка движков данных и БД
        self.data = DataEngine()
        self.db = TitanDatabase()
        self.selector = SymbolSelector(self.data)
        self.executor = OrderExecutor(self.data)
        self.risk = RiskManager(self.data)
        self.tg = TitanTelegramBridge()
        
        # 2. Движки анализа
        self.orderflow = OrderFlowAnalyzer(self.data)
        self.smc = SmartMoneyAnalyzer(self.data)
        self.mtf = MultiTimeframeAnalyzer(self.data)
        self.ml = MLEngine(self.data)
        self.ml.load_model()
        self.composite = CompositeScoreEngine()
        
        # 3. Настройки режима
        self.mode_settings = trade_modes.apply_mode(config.TRADE_MODE)
        
        # 4. Состояние
        self.stream = None
        self.last_status_time = datetime.now()
        self.processed_count = 0

        # 5. CIRCUIT BREAKERS (защита от серийных убытков)
        self.consecutive_losses = 0          # Подряд убытков
        self.daily_pnl = 0.0                 # PNL за текущий день
        self.daily_pnl_reset_date = datetime.now().date()
        self.cooldown_until = None           # Время до которого торговля отключена
        self.coin_losses = defaultdict(list) # {symbol: [datetime убытков]}
        self.coin_cooldown = {}              # {symbol: datetime разблокировки}
        self.last_trade_time = {}            # {symbol: datetime последней сделки}
        self.starting_balance = self.data.get_balance()
        self.trade_count_today = 0

    def start(self):
        """Запуск торгового цикла"""
        self.is_running = True
        print(ASCII_ART)
        print(f"[TITAN] Запуск {config.TRADE_MODE} (Professional Mode)")
        print(f"[Config] Scanning Interval: 3.0 sec per symbol")
        print(f"[Config] Min Score for Entry: {self.mode_settings['composite_min_score']}")
        
        # Фоновый мониторинг БД
        maintenance_thread = threading.Thread(target=self._db_maintenance, daemon=True)
        maintenance_thread.start()

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
                if config.MULTI_SYMBOL_ENABLED and cycle_count % 20 == 0 and cycle_count > 0:
                    self.symbol_list = self.selector.get_top_symbols(config.MAX_SYMBOLS)
                    if self.stream: self.stream.start(self.symbol_list)

                for symbol in self.symbol_list:
                    if not self.is_running: break
                    self.current_symbol = symbol
                    
                    # ПРЯМОЙ ЛОГ АНАЛИЗА
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

    def _check_circuit_breakers(self, symbol) -> str:
        """
        Проверяет все предохранители ПЕРЕД анализом и входом.
        Возвращает причину отказа или пустую строку если всё ОК.
        """
        now = datetime.now()
        
        # 1. Сброс дневного PNL в полночь
        if now.date() != self.daily_pnl_reset_date:
            self.daily_pnl = 0.0
            self.daily_pnl_reset_date = now.date()
            self.trade_count_today = 0
            self.consecutive_losses = 0  # Сброс стрика в новый день
            print(f"🔄 [NEW DAY] Сброс дневных лимитов. Баланс: ${self.data.get_balance():.2f}")
        
        # 2. Cooldown после серии убытков
        if self.cooldown_until and now < self.cooldown_until:
            mins_left = (self.cooldown_until - now).total_seconds() / 60
            return f"COOLDOWN ({mins_left:.0f} мин после {self.consecutive_losses} убытков)"
        elif self.cooldown_until and now >= self.cooldown_until:
            self.cooldown_until = None
            self.consecutive_losses = 0
            print(f"✅ [COOLDOWN OFF] Возобновление торговли")
        
        # 3. Лимит дневного убытка: -5% от стартового баланса дня
        daily_loss_limit = self.starting_balance * 0.05
        if self.daily_pnl < -daily_loss_limit:
            return f"DAILY LOSS LIMIT (${self.daily_pnl:.2f} / -${daily_loss_limit:.2f})"
        
        # 4. Монета в черном списке?
        if symbol in self.coin_cooldown:
            if now < self.coin_cooldown[symbol]:
                return f"COIN BLACKLISTED ({symbol})"
            else:
                del self.coin_cooldown[symbol]
        
        # 5. Cooldown на монету после недавней сделки (30 мин)
        if symbol in self.last_trade_time:
            time_since = (now - self.last_trade_time[symbol]).total_seconds()
            if time_since < 1800:  # 30 минут
                return f"SYMBOL COOLDOWN (traded {time_since/60:.0f}m ago)"
        
        # 6. Лимит сделок в день (макс 30)
        if self.trade_count_today >= 30:
            return f"MAX DAILY TRADES (30)"
        
        return ""
    
    def _register_trade_result(self, symbol, pnl):
        """Обновляет circuit breakers после закрытия сделки."""
        self.daily_pnl += pnl
        
        if pnl < 0:
            self.consecutive_losses += 1
            
            # Запоминаем убыток по монете
            self.coin_losses[symbol].append(datetime.now())
            # Убираем старые (старше 24ч)
            cutoff = datetime.now() - timedelta(hours=24)
            self.coin_losses[symbol] = [t for t in self.coin_losses[symbol] if t > cutoff]
            
            # 2 убытка на одной монете за 24ч → бан на 6 часов
            if len(self.coin_losses[symbol]) >= 2:
                self.coin_cooldown[symbol] = datetime.now() + timedelta(hours=6)
                print(f"� [BLACKLIST] {symbol} заблокирован на 6ч (2+ убытка)")
            
            # 3 убытка подряд → cooldown 2 часа
            cooldown_trigger = self.mode_settings.get('cooldown_after_losses', 3)
            if self.consecutive_losses >= cooldown_trigger:
                self.cooldown_until = datetime.now() + timedelta(hours=2)
                print(f"⏸️ [CIRCUIT BREAKER] {self.consecutive_losses} убытков подряд → пауза 2 часа")
                self.tg.send_message(
                    f"⏸️ <b>CIRCUIT BREAKER</b>\n"
                    f"{self.consecutive_losses} убытков подряд\n"
                    f"Пауза до {self.cooldown_until.strftime('%H:%M')}\n"
                    f"Дневной PNL: ${self.daily_pnl:.2f}"
                )
        else:
            self.consecutive_losses = 0  # Сброс стрика

    def _process_symbol(self, symbol):
        """Обработка одной монеты с детальным выводом"""
        try:
            # CIRCUIT BREAKERS
            cb_reason = self._check_circuit_breakers(symbol)
            if cb_reason:
                # Раз в 100 монет показываем причину для отладки
                if self.processed_count % 100 == 0:
                    print(f"🛡️ {symbol:10} | BLOCKED: {cb_reason}")
                return
            
            if self.risk.has_position(symbol):
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

            # ПРОВЕРКА MTF_STRICT: В режиме разгона или консервативном
            if self.mode_settings.get('mtf_strict', False):
                if composite.direction == 'LONG' and mtf_signal.alignment != 'BULLISH':
                    return
                if composite.direction == 'SHORT' and mtf_signal.alignment != 'BEARISH':
                    return

            score = composite.total_score
            min_score = self.mode_settings['composite_min_score']
            
            # КОРРЕКЦИЯ LONG BIAS: LONGs исторически имеют 25% WR
            # Требуем +10 к порогу для LONGs чтобы выровнять качество
            effective_min = min_score
            if composite.direction == 'LONG':
                effective_min = min_score + 5  # Лонги нужен более сильный скор
            
            # ВИЗУАЛИЗАЦИЯ С УЧЕТОМ НАПРАВЛЕНИЯ
            m_sc = (mtf_signal.confidence * 20) if mtf_signal else 0
            if mtf_signal and mtf_signal.alignment == 'BEARISH': m_sc *= -1
            
            s_sc = (smc_signal.confidence * 20) if smc_signal else 0
            if smc_signal and ('SHORT' in smc_signal.signal_type.value or 'BEARISH' in smc_signal.signal_type.value): s_sc *= -1
            
            o_sc = (of_signal.confidence * 20) if of_signal else 0
            if of_signal and 'SELL' in of_signal.pressure.value: o_sc *= -1
            
            details = f"M:{m_sc:+2.0f} S:{s_sc:+2.0f} O:{o_sc:+2.0f}"
            
            if abs(score) >= effective_min:
                status = "💰 [ENTRY]"
            elif abs(score) >= (min_score / 2):
                status = "🔍 [WATCH]"
            else:
                status = "🔘 [WAIT ]"

            print(f"{status} {symbol:10} | TOTAL: {score:+.1f} | {details} | need {effective_min}")
            
            # Решение
            if abs(score) >= effective_min:
                self._execute_trade(symbol, composite, smc_signal)
                
        except Exception as e:
            # logging.error(f"Error in _process_symbol for {symbol}: {e}")
            pass

    def _execute_trade(self, symbol, composite, smc_signal):
        direction = composite.direction
        side = "Buy" if direction == "LONG" else "Sell"
        
        # Получаем текущую цену и ATR для безопасных уровней
        df = self.data.get_klines(symbol, limit=20)
        if df is None or df.empty: return
        current_price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1] if 'atr' in df.columns else current_price * 0.01

        # ЛОГИКА SL/TP:
        # 1. Сначала пробуем уровни от SMC
        sl_price = smc_signal.stop_loss if smc_signal and smc_signal.stop_loss else 0
        tp_price = smc_signal.take_profit if smc_signal and smc_signal.take_profit else 0
        
        # 2. ПРОВЕРКА НАПРАВЛЕНИЯ: Если уровни SMC противоречат стороне сделки - сбрасываем их
        if side == "Buy":
            if sl_price >= current_price: sl_price = 0
            if tp_price <= current_price: tp_price = 0
        else: # side == "Sell"
            if sl_price <= current_price and sl_price > 0: sl_price = 0
            if tp_price >= current_price and tp_price > 0: tp_price = 0

        # 3. ФОЛЛБЭК НА ATR: Если уровней нет или они некорректны
        if sl_price == 0:
            sl_dist = atr * 1.5
            sl_price = current_price - sl_dist if side == "Buy" else current_price + sl_dist
            
        if tp_price == 0:
            tp_dist = abs(current_price - sl_price) * self.mode_settings.get('min_rr', 2.0)
            tp_price = current_price + tp_dist if side == "Buy" else current_price - tp_dist

        pos_size = self.risk.calculate_position_size(
            entry_price=current_price,
            stop_loss=sl_price,
            symbol=symbol,
            risk_percent=self.mode_settings['risk_per_trade']
        )
        
        if not pos_size.is_valid:
            print(f"🛑 [Risk] {symbol} rejected: {pos_size.rejection_reason}")
            return

        # Получаем признаки для БД
        features = self.ml.get_features_dict(symbol)

        print(f"⚡ [AUTO] Executing {side} on {symbol} @ {current_price}...")
        order = self.executor.place_order(
            symbol=symbol,
            side=side,
            quantity=pos_size.quantity,
            stop_loss=sl_price,
            take_profit=tp_price
        )
        
        if order.success:
            # Сохраняем в БД
            trade_id = order.order_id or f"{symbol}_{int(time.time())}"
            details = {
                'score_total': composite.total_score,
                'mtf': (mtf_sc := composite.components.get('mtf', 0)),
                'smc': composite.components.get('smc', 0),
                'orderflow': composite.components.get('orderflow', 0)
            }
            self.db.record_trade_entry(
                trade_id, symbol, side, current_price, pos_size.quantity, 
                sl_price, tp_price, composite.total_score, details, features
            )
            
            # Обновляем circuit breaker state
            self.last_trade_time[symbol] = datetime.now()
            self.trade_count_today += 1
            
            # Телеграм
            self.tg.send_signal({
                'symbol': symbol, 'direction': direction, 'score': composite.total_score,
                'entry': current_price, 'sl': sl_price, 'tp': tp_price,
                'confidence': composite.confidence, 'strength': composite.strength,
                'recommendation': composite.recommendation
            })

    def _db_maintenance(self):
        """Фоновый процесс мониторинга закрытых сделок"""
        while self.is_running:
            try:
                open_db_trades = self.db.get_open_trades()
                if not open_db_trades:
                    time.sleep(60)
                    continue

                # Получаем все текущие позиции из биржи
                current_positions = self.data.get_positions()
                active_symbols = [p['symbol'] for p in current_positions]

                for trade_id, symbol, side, entry_price, qty in open_db_trades:
                    if symbol not in active_symbols:
                        # Сделка закрыта на бирже! Ищем результат в истории
                        closed_pnl_list = self.data.get_closed_pnl(symbol)
                        if closed_pnl_list:
                            result = closed_pnl_list[0]
                            exit_price = float(result.get('avgExitPrice', 0))
                            pnl = float(result.get('closedPnl', 0))
                            self.db.record_trade_exit(trade_id, exit_price, pnl)
                            
                            # CIRCUIT BREAKER: Обновляем трекер
                            self._register_trade_result(symbol, pnl)
                            
                            icon = '✅' if pnl > 0 else '❌'
                            print(f"{icon} [Closed] {symbol} PNL: ${pnl:+.2f} | Day: ${self.daily_pnl:+.2f} | Streak: {self.consecutive_losses}L")
                            self.db.log_event("Main", f"Closed {symbol} PNL ${pnl:.2f} daily=${self.daily_pnl:.2f}")

                time.sleep(60)
            except Exception as e:
                print(f"[DB Maintenance] Error: {e}")
                time.sleep(60)

    def _send_heartbeat(self):
        self.last_status_time = datetime.now()
        balance = self.data.get_balance()
        msg = (
            f"📡 <b>TITAN HEARTBEAT</b>\n"
            f"Status: <b>ONLINE</b>\n"
            f"Analyzed: <b>{self.processed_count}</b> syms\n"
            f"Mode: <b>{config.TRADE_MODE}</b>\n"
            f"Balance: <b>${balance:.2f}</b>\n"
            f"Day PNL: <b>${self.daily_pnl:+.2f}</b>\n"
            f"Trades Today: <b>{self.trade_count_today}</b>\n"
            f"Loss Streak: <b>{self.consecutive_losses}</b>\n"
            f"Banned Coins: <b>{len(self.coin_cooldown)}</b>"
        )
        self.tg.send_message(msg)

if __name__ == "__main__":
    bot = TitanBotUltimateFinal()
    bot.start()
