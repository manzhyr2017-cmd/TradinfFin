"""
TITAN BOT 2026 - Main Controller (ULTIMATE FINAL v2)
Центральный запуск и координация всех модулей.
Версия 2: Circuit Breakers, Coin Blacklist, Drawdown Protection
"""

import time
import threading
import logging
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from data_engine import DataEngine, RealtimeDataStream
from selector import SymbolSelector
from executor import OrderExecutor
from risk_manager import RiskManager
from orderflow import OrderFlowAnalyzer
from smart_money import SmartMoneyAnalyzer
from multi_timeframe import MultiTimeframeAnalyzer
from composite_score import CompositeScoreEngine
from volume_profile import VolumeProfileAnalyzer
from open_interest import OpenInterestAnalyzer
from market_regime import MarketRegimeDetector
from whale_tracker import WhaleTracker
from fear_greed import FearGreedAnalyzer
from correlations import CorrelationAnalyzer
from trailing_stop import TrailingStopManager
from partial_tp import PartialTakeProfitManager
from session_filter import SessionFilter
from news_filter import NewsFilter
from telegram_bridge import TitanTelegramBridge
from database import TitanDatabase
from ml_engine import MLEngine
import trade_modes
import config

# PROBATION LIST (Ранее черный список)
# Монеты, которые показывали 0% WR. Мы больше их не блочим, но логируем их отдельно.
PROBATION_LIST = {
    'RAVEUSDT',   # 12 trades, 0% WR, -$147
    'LAUSDT',     # 11 trades, 0% WR, -$65
    'ZROUSDT',    # 8 trades, 0% WR, -$46
    'AGLDUSDT',   # 4 trades, 0% WR, -$34
    'ENSOUSDT',   # 5 trades, 0% WR, -$32
    'SENTUSDT',   # 3 trades, 0% WR, -$19  (v8)
    'SKRUSDT',    # 3 trades, 0% WR, -$17  (v8)
    'SOMIUSDT',   # 3 trades, 0% WR, -$15  (v8)
    'ETHUSDT',    # 7 trades, 0% WR, -$53  (v9)
}

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
        
        # 2. Движки анализа (ВСЕ 9 компонентов)
        self.orderflow = OrderFlowAnalyzer(self.data)
        self.smc = SmartMoneyAnalyzer(self.data)
        self.mtf = MultiTimeframeAnalyzer(self.data)
        self.volume_profile = VolumeProfileAnalyzer(self.data)
        self.oi = OpenInterestAnalyzer(self.data)
        self.regime = MarketRegimeDetector(self.data)
        self.whale = WhaleTracker()
        self.fear_greed = FearGreedAnalyzer()
        self.correlation = CorrelationAnalyzer(self.data)
        self.ml = MLEngine(self.data)
        self.ml.load_model()
        self.composite = CompositeScoreEngine()
        
        # 3. Trailing Stop + Partial TP (v6)
        self.trailing = TrailingStopManager(self.executor)
        self.partial_tp = PartialTakeProfitManager(self.executor)
        self.session_filter = SessionFilter()
        self.news_filter = NewsFilter()
        
        # 4. Настройки режима
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
        print(f"[Config] Scanning Interval: 3.0 sec per symbol | Symbols: {len(self.symbol_list)}")
        print(f"[Config] Mode: {config.TRADE_MODE} | Min Score: {self.mode_settings['composite_min_score']}")
        if self.mode_settings.get('mtf_strict'):
            print(f"[Config] MTF STRICT: ENABLED")
        
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

                # TRAILING STOP UPDATE: проверяем ВСЕ активные позиции
                try:
                    for pos in self.data.get_positions():
                        sym = pos['symbol']
                        price = float(pos.get('markPrice', 0))
                        if price > 0:
                            self.trailing.update(sym, price)
                            self.partial_tp.check_and_execute(sym, price)
                except:
                    pass

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
        
        # 0. PROBATION LIST (Больше не блокируем, просто помечаем в логах)
        # Если монета в PROBATION_LIST, мы продолжаем анализ.
        pass
        
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
            
            # 2 убытка на одной монете за 24ч → бан на 1 час (v8: было 6ч — лишнее с time filter)
            if len(self.coin_losses[symbol]) >= 2:
                self.coin_cooldown[symbol] = datetime.now() + timedelta(hours=1)
                print(f"🚫 [COOLDOWN] {symbol} пауза 1ч (2+ убытка)")
            
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
            
            
            # DAY FILTER: Sun=10% WR(-$71), Wed=21% WR(-$145)
            TOXIC_DAYS = {2, 6}  # 2=Wednesday, 6=Sunday
            current_day = datetime.now(timezone.utc).weekday()
            if current_day in TOXIC_DAYS:
                if self.processed_count % 200 == 0:
                    day_names = {2: 'WED', 6: 'SUN'}
                    print(f"📅 TOXIC DAY {day_names.get(current_day, '?')} — торговля заблокирована")
                return
            
            if self.risk.has_position(symbol):
                return
            
            # SESSION FILTER: Режимы MODERATE/ACCEL требуют хорошую сессию
            if self.mode_settings.get('session_filter', False):
                min_q = self.mode_settings.get('session_min_quality', 5)
                can_trade, reason = self.session_filter.is_good_time_to_trade(min_q)
                if not can_trade:
                    if self.processed_count % 200 == 0:
                        print(f"🕑 {reason}")
                    return
            
            # NEWS FILTER: Не торгуем перед FOMC/CPI
            if self.mode_settings.get('news_filter', False):
                try:
                    news = self.news_filter.check()
                    if not news.can_trade:
                        if self.processed_count % 200 == 0:
                            print(f"📰 {news.message}")
                        return
                except:
                    pass  # Не блокируем если апи календаря недоступен

            # Сбор данных и анализ — ВСЕ 9 компонентов
            mtf_signal = self.mtf.analyze(symbol)
            smc_signal = self.smc.analyze(symbol)
            of_signal = self.orderflow.analyze(symbol, realtime_stream=self.stream)
            
            # Дополнительные компоненты (v5: подключены)
            try:
                vp_signal = self.volume_profile.analyze(symbol)
            except:
                vp_signal = None
            try:
                oi_signal = self.oi.analyze(symbol)
            except:
                oi_signal = None
            try:
                regime_signal = self.regime.analyze(symbol)
            except:
                regime_signal = None
            try:
                whale_signal = self.whale.analyze()
            except:
                whale_signal = None
            try:
                fg_signal = self.fear_greed.analyze()
            except:
                fg_signal = None
            try:
                corr_signal = self.correlation.analyze(symbol)
            except:
                corr_signal = None
            
            # Композитный балл — ВСЕ 9
            composite = self.composite.calculate(
                symbol=symbol,
                mtf_analysis=mtf_signal,
                smc_signal=smc_signal,
                orderflow_signal=of_signal,
                volume_profile=vp_signal,
                oi_analysis=oi_signal,
                regime_analysis=regime_signal,
                whale_analysis=whale_signal,
                fear_greed=fg_signal,
                correlation_analysis=corr_signal
            )

            # ПРОВЕРКА MTF_STRICT: В режиме разгона или консервативном
            if self.mode_settings.get('mtf_strict', False):
                if composite.direction == 'LONG' and mtf_signal.alignment != 'BULLISH':
                    return
                if composite.direction == 'SHORT' and mtf_signal.alignment != 'BEARISH':
                    return

            score = composite.total_score
            min_score = self.mode_settings['composite_min_score']
            
            # КОРРЕКЦИЯ LONG BIAS: LONGs = 25% WR, R:R 1:1.38 (убыточно)
            # SHORTs = 34% WR, R:R 1:2.01 (прибыльно)
            # Требуем +8 к порогу для LONGs
            effective_min = min_score
            if composite.direction == 'LONG':
                effective_min = min_score + 8  # Данные: LONGs нужен значительно более сильный скор
            
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

            if symbol in PROBATION_LIST:
                status += "[PROBATION]"

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

        # 3. ФУНДАМЕНТАЛЬНОЕ ИСПРАВЛЕНИЕ СТОПА (Причина сливов):
        # SMC-движок давал экстремально тесные стопы (0.2 ATR).
        # Из-за этого происходило 2 вещи:
        # A) Выбивало любым случайным шумом/тенью свечи
        # Б) Trailing Stop включал "Безубыток" при профите +1R (что равнялось смешным 0.2 ATR), и цена тут же его сбивала.
        # Решение: Ставим ЖЕСТКИЙ минимум для стопа в 2.0 ATR. Даём сделке дышать.
        min_sl_dist = atr * 2.0
        current_sl_dist = abs(current_price - sl_price) if sl_price > 0 else 0
        
        if sl_price == 0 or current_sl_dist < min_sl_dist:
            sl_dist = min_sl_dist
            sl_price = current_price - sl_dist if side == "Buy" else current_price + sl_dist
            
        # 4. Жёстко пересчитываем TP от финального правильного стопа
        actual_sl_dist = abs(current_price - sl_price)
        target_rr = self.mode_settings.get('min_rr', 2.0)
        tp_dist = actual_sl_dist * target_rr
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
            
            # Регистрируем в Trailing Stop + Partial TP
            try:
                direction_str = 'LONG' if side == 'Buy' else 'SHORT'
                self.trailing.register_position(
                    symbol=symbol, side=direction_str,
                    entry_price=current_price, initial_stop=sl_price, atr=atr
                )
                self.partial_tp.register_position(
                    symbol=symbol, side=direction_str,
                    entry_price=current_price, stop_loss=sl_price,
                    quantity=pos_size.quantity
                )
            except Exception as e:
                print(f"[TrailingStop/PartialTP] Register error: {e}")
            
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
                            
                            # Убираем из Trailing/PartialTP
                            self.trailing.remove_position(symbol)
                            self.partial_tp.remove_position(symbol)
                            
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
