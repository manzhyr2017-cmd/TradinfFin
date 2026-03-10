"""
GRID BOT 2026 — Main Entry Point
Главный файл: запуск, мониторинг, rebalancing, graceful shutdown
"""

import sys
import os
import signal
import time
from datetime import datetime, timedelta

# Добавляем текущую директорию в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import grid_config as cfg
from grid_engine import GridEngine, GridLevel
from grid_executor import GridExecutor
from grid_telegram import GridTelegram
from logger import logger


class GridBot:
    """
    Сеточный бот для Bybit Futures.
    
    Цикл работы:
    1. Получить текущую цену → рассчитать сетку
    2. Выставить Buy ордера ниже цены, Sell выше
    3. Мониторить каждые N секунд:
       - Исполненные ордера → выставить обратный
       - Цена вышла из сетки → rebalance
       - Max drawdown → emergency stop
    4. При остановке → отменить всё, закрыть позиции
    """

    def __init__(self):
        self.executor = GridExecutor()
        self.telegram = GridTelegram()
        self.engine: GridEngine = None
        self.running = False
        self._started_at = datetime.utcnow()
        self._last_heartbeat = datetime.utcnow()
        self._last_funding_check = datetime.utcnow()
        self._active_orders = {}  # order_id → GridLevel

        # Graceful shutdown
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def start(self):
        logger.info("=========================================")
        logger.info(f"🚀 Попытка запуска GridBot для {cfg.SYMBOL}")
        logger.info(f"Investment: ${cfg.INVESTMENT}")
        logger.info(f"Leverage: {cfg.LEVERAGE}x")
        logger.info(f"Mode: {cfg.GRID_MODE}")
        logger.info("=========================================")
        print(f"{'=' * 50}\n")

        # 1. Получаем текущую цену
        price = self.executor.get_price(cfg.SYMBOL)
        if price <= 0:
            logger.error("[GridBot] Не удалось получить цену. Остановка.")
            return

        # 2. Получаем баланс
        balance = self.executor.get_balance()
        base_investment = cfg.INVESTMENT
        if base_investment <= 0:
            investment = balance
        else:
            investment = min(base_investment, balance)
            
        print(f"[GridBot] 💰 Balance: ${balance:.2f}, Target Inv: ${base_investment:.2f}, Actual Inv: ${investment:.2f}")

        if investment < 5:
            print("[GridBot] ❌ Insufficient balance ($5 minimum)")
            return

        # 2.5 Smart Entry Check (RSI)
        if cfg.RSI_ENTRY_CHECK:
            logger.info(f"[GridBot] Проверка RSI (Period={cfg.RSI_PERIOD}) перед входом...")
            while self.running:
                rsi = self.executor.get_rsi(cfg.SYMBOL, cfg.RSI_PERIOD)
                if 30 <= rsi <= 70:
                    logger.info(f"[GridBot] RSI={rsi:.2f} (Нейтрально). Безопасный вход разрешен.")
                    break
                else:
                    status = "Overbought" if rsi > 70 else "Oversold"
                    logger.info(f"[GridBot] RSI={rsi:.2f} ({status}). Ожидание безопасной зоны (30-70)...")
                    time.sleep(cfg.CHECK_INTERVAL)

        # 3. Вычисляем границы сетки
        if cfg.USE_ATR_STEP:
            atr = self.executor.get_atr(cfg.SYMBOL, period=cfg.ATR_PERIOD)
            if atr > 0:
                adaptive_range = (atr * cfg.ATR_MULTIPLIER / price) * 100
                cfg.GRID_RANGE_PCT = round(min(max(adaptive_range, 1.0), 10.0), 2)  # Cap between 1% and 10%
                logger.info(f"[GridBot] ATR={atr:.4f}. Адаптивный шаг стеки установлен: {cfg.GRID_RANGE_PCT}%")

        if cfg.GRID_UPPER > 0 and cfg.GRID_LOWER > 0:
            upper = cfg.GRID_UPPER
            lower = cfg.GRID_LOWER
        else:
            upper = round(price * (1 + cfg.GRID_RANGE_PCT / 100), 4)
            lower = round(price * (1 - cfg.GRID_RANGE_PCT / 100), 4)

        logger.info(f"[GridBot] Текущая цена: {price}")
        logger.info(f"[GridBot] Сетка: {lower:.4f} - {upper:.4f}")
        logger.info(f"[GridBot] Уровней: {cfg.GRID_COUNT}")

        # 4. Инициализируем engine
        self.engine = GridEngine(
            upper=upper,
            lower=lower,
            count=cfg.GRID_COUNT,
            mode=cfg.GRID_MODE
        )
        self.engine.start_balance = balance
        self.engine._started_at = self._started_at.isoformat()

        # 5. Пытаемся восстановить состояние
        old_state = self.engine.load_state(cfg.STATE_FILE)
        if old_state and old_state.symbol == cfg.SYMBOL:
            logger.info(f"[GridBot] 🔄 Restored state: {old_state.total_trades} trades, "
                        f"${old_state.total_profit:+.2f}")
            # Используем восстановленные уровни но пересчитываем ордера
            self.engine.start_balance = old_state.start_balance or balance
            
            if cfg.INVESTMENT > 0 and cfg.AUTO_COMPOUND and self.engine.total_profit > 0:
                investment = min(cfg.INVESTMENT + self.engine.total_profit, balance)
                logger.info(f"[GridBot] 📈 Auto-Compound applied! New Investment: ${investment:.2f}")
        
        # 6. Рассчитываем уровни
        levels = self.engine.calculate_levels(price)
        logger.info(f"[GridBot] 📏 {len(levels)} levels calculated")

        # 7. Получаем symbol info для precision
        sym_info = self.executor.get_symbol_info(cfg.SYMBOL)
        logger.info(f"[GridBot] 📐 Price precision: {sym_info['price_precision']}, "
                    f"Qty step: {sym_info['qty_step']}")

        # 8. Рассчитываем qty
        qty = self.engine.calculate_qty_per_level(
            balance=investment,
            leverage=cfg.LEVERAGE,
            current_price=price,
            qty_step=sym_info['qty_step'],
            min_qty=sym_info['min_qty']
        )
        logger.info(f"[GridBot] 📦 Qty per level: {qty}")

        # Проверяем минимальный нотионал
        notional = qty * price
        if notional < sym_info.get('min_notional', 5):
            logger.error(f"[GridBot] ❌ Order value ${notional:.2f} < min ${sym_info['min_notional']}")
            logger.error("[GridBot] Increase investment or leverage")
            return

        # 9. Устанавливаем плечо
        self.executor.set_leverage(cfg.SYMBOL, cfg.LEVERAGE)

        # 10. Отменяем старые ордера (чистый старт)
        self.executor.cancel_all_orders(cfg.SYMBOL)
        time.sleep(0.5)

        # 11. Выставляем все ордера
        placed = self._place_grid_orders(levels, qty)
        logger.info(f"[GridBot] ✅ Placed {placed}/{len(levels)} orders")

        if placed == 0:
            logger.error("[GridBot] ❌ No orders placed. Check API.")
            return

        # 12. Telegram уведомление
        self.telegram.notify_start(
            symbol=cfg.SYMBOL,
            levels=cfg.GRID_COUNT,
            upper=upper,
            lower=lower,
            qty=qty,
            balance=balance,
            leverage=cfg.LEVERAGE
        )

        # 13. Основной цикл
        self.running = True
        self._main_loop()

    def _place_grid_orders(self, levels: list, qty: float) -> int:
        """Выставляет все ордера сетки"""
        placed = 0
        for level in levels:
            order_id = self.executor.place_limit_order(
                symbol=cfg.SYMBOL,
                side=level.side,
                qty=qty,
                price=level.price
            )
            if order_id:
                level.order_id = order_id
                level.status = "active"
                self._active_orders[order_id] = level
                placed += 1
                time.sleep(0.1)  # Rate limit protection
        return placed

    def _main_loop(self):
        """Основной цикл мониторинга"""
        logger.info(f"\n[GridBot] 🔄 Monitoring started (check every {cfg.CHECK_INTERVAL}s)...")

        while self.running:
            try:
                # 1. Проверяем исполненные ордера
                self._check_fills()

                # 2. Проверяем позицию цены в сетке
                price = self.executor.get_price(cfg.SYMBOL)
                if price > 0 and self.engine.should_rebalance(price, cfg.REBALANCE_THRESHOLD):
                    logger.info(f"[GridBot] ⚠️ Цена {price} вышла из диапазона. Rebalance!")
                    self._do_rebalance(price)
                    continue

                # 3. Проверяем drawdown
                equity = self.executor.get_equity()
                if equity > 0 and self.engine.check_max_drawdown(equity, cfg.MAX_DRAWDOWN_PCT):
                    logger.error(f"[GridBot] 🛑 MAX DRAWDOWN reached! Equity: ${equity:.2f}")
                    self._emergency_stop("Max drawdown exceeded")
                    return

                now = datetime.utcnow()
                
                # 3.5 Проверяем Funding Rate каждые N секунд
                if (now - self._last_funding_check).total_seconds() >= cfg.CHECK_INTERVAL * 6:
                    funding_rate = self.executor.get_funding_rate(cfg.SYMBOL)
                    if abs(funding_rate) >= cfg.MAX_FUNDING_RATE:
                        logger.error(f"[GridBot] 🚨 DANGEROUS FUNDING RATE: {funding_rate*100:.4f}%!")
                        self._emergency_stop(f"Extreme Funding Rate: {funding_rate*100:.4f}%")
                        return
                    self._last_funding_check = now

                # 4. Heartbeat
                if (now - self._last_heartbeat).total_seconds() >= cfg.HEARTBEAT_INTERVAL:
                    self._send_heartbeat(price, equity)
                    self._last_heartbeat = now

                # 5. Сохраняем состояние
                self.engine.save_state(cfg.STATE_FILE, cfg.SYMBOL)

                time.sleep(cfg.CHECK_INTERVAL)

            except KeyboardInterrupt:
                self._handle_shutdown(None, None)
                return
            except Exception as e:
                logger.error(f"[GridBot] Критическая ошибка: {e}")
                time.sleep(cfg.CHECK_INTERVAL * 2)

    def _check_fills(self):
        """
        Проверяет исполненные ордера.
        Для каждого fill → выставляем обратный ордер на соседнем уровне.
        """
        current_orders = self.executor.get_open_orders(cfg.SYMBOL)
        current_ids = {o['order_id'] for o in current_orders}

        # Ищем ордера, которые были активны но пропали (= исполнились)
        filled_ids = set(self._active_orders.keys()) - current_ids

        for oid in filled_ids:
            level = self._active_orders.pop(oid)
            level.status = "filled"
            level.filled_at = datetime.utcnow().isoformat()

            logger.info(f"[GridBot] ✅ FILLED: {level.side} @ {level.price}")

            # Рассчитываем обратный ордер
            opposite = self.engine.get_opposite_level(level)
            if opposite:
                # Выставляем обратный ордер
                new_oid = self.executor.place_limit_order(
                    symbol=cfg.SYMBOL,
                    side=opposite.side,
                    qty=self.engine.qty_per_level,
                    price=opposite.price
                )
                if new_oid:
                    opposite.order_id = new_oid
                    opposite.status = "active"
                    self._active_orders[new_oid] = opposite

                    # Примерный профит = step × qty
                    step = self.engine.get_step_size()
                    approx_profit = step * self.engine.qty_per_level
                    self.engine.record_profit(approx_profit)

                    # Telegram
                    self.telegram.notify_fill(
                        side=level.side,
                        price=level.price,
                        qty=self.engine.qty_per_level,
                        tp_side=opposite.side,
                        tp_price=opposite.price
                    )

                    # Каждые 5 trades — уведомление о прибыли
                    if self.engine.total_trades % 5 == 0:
                        self.telegram.notify_profit(
                            profit=approx_profit,
                            total_profit=self.engine.total_profit,
                            total_trades=self.engine.total_trades
                        )

    def _do_rebalance(self, new_price: float):
        """Перестраивает сетку вокруг новой цены"""
        old_upper, old_lower = self.engine.upper, self.engine.lower
        logger.info(f"[GridBot] 🔄 Rebalancing: price {new_price} outside "
                    f"[{old_lower:.2f} — {old_upper:.2f}]")

        # 1. Отменяем все ордера
        self.executor.cancel_all_orders(cfg.SYMBOL)
        self._active_orders.clear()
        time.sleep(0.5)

        # 2. Обработка старых позиций в зависимости от режима
        if cfg.REBALANCE_MODE.upper() == "CLOSE_ALL":
            logger.info("[GridBot] REBALANCE_MODE=CLOSE_ALL. Закрытие всех позиций...")
            self.executor.close_all_positions(cfg.SYMBOL)
        else:
            logger.info("[GridBot] REBALANCE_MODE=HOLD_POSITION. Позиции сохранены, сетка смещается.")

        # 3. Перестраиваем сетку
        if cfg.USE_ATR_STEP:
            atr = self.executor.get_atr(cfg.SYMBOL, cfg.ATR_PERIOD)
            if atr > 0:
                grid_range = (atr * cfg.ATR_MULTIPLIER) / new_price * 100
                cfg.GRID_RANGE_PCT = max(1.0, min(15.0, grid_range))
                logger.info(f"[GridBot] 📈 Re-calculated ATR Range: {cfg.GRID_RANGE_PCT:.2f}% (ATR: {atr:.4f})")
            self.engine.rebalance(new_price, cfg.GRID_RANGE_PCT)
        else:
            # Сохраняем абсолютную ширину
            self.engine.recenter_grid(new_price)

        # 4. Пересчитываем qty (баланс мог измениться)
        balance = self.executor.get_balance()
        base_investment = cfg.INVESTMENT
        if base_investment <= 0:
            investment = balance
        else:
            if cfg.AUTO_COMPOUND and self.engine.total_profit > 0:
                investment = base_investment + self.engine.total_profit
            else:
                investment = base_investment
        investment = min(investment, balance)
        
        sym_info = self.executor.get_symbol_info(cfg.SYMBOL)
        self.engine.calculate_qty_per_level(
            balance=investment,
            leverage=cfg.LEVERAGE,
            current_price=new_price,
            qty_step=sym_info['qty_step'],
            min_qty=sym_info['min_qty']
        )

        # 5. Выставляем новые ордера
        placed = self._place_grid_orders(self.engine.levels, self.engine.qty_per_level)
        logger.info(f"[GridBot] ✅ Rebalanced: {placed} orders, "
                    f"range [{self.engine.lower:.2f} — {self.engine.upper:.2f}]")

        self.telegram.notify_rebalance(
            new_upper=self.engine.upper,
            new_lower=self.engine.lower,
            reason=f"Price ${new_price:.2f} exited old range"
        )

    def _send_heartbeat(self, price: float, equity: float):
        """Отправка периодического статуса"""
        uptime = datetime.utcnow() - self._started_at
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        uptime_str = f"{hours}h {minutes}m"

        profit = self.engine.total_profit
        trades = self.engine.total_trades
        logger.info(f"[Heartbeat] Price: {price} | Equity: ${equity:.2f} | Profit: ${profit:.4f} | Trades: {trades}")
        
        positions = self.executor.get_positions(cfg.SYMBOL)

        self.telegram.send_status(
            symbol=cfg.SYMBOL,
            price=price,
            upper=self.engine.upper,
            lower=self.engine.lower,
            total_profit=self.engine.total_profit,
            total_trades=self.engine.total_trades,
            balance=equity, # Using equity for balance in heartbeat
            active_orders=len(self._active_orders),
            positions=len(positions),
            uptime=uptime_str
        )

    def _emergency_stop(self, reason: str):
        """Экстренная остановка: отменить всё, закрыть позиции"""
        self.running = False
        logger.error(f"[GridBot] ЭКСТРЕННАЯ ОСТАНОВКА: {reason}")

        self.executor.cancel_all_orders(cfg.SYMBOL)
        time.sleep(0.5)
        self.executor.close_all_positions(cfg.SYMBOL)

        balance = self.executor.get_balance()
        self.engine.save_state(cfg.STATE_FILE, cfg.SYMBOL)

        self.telegram.notify_stop(
            reason=reason,
            total_profit=self.engine.total_profit,
            total_trades=self.engine.total_trades,
            final_balance=balance
        )

    def _handle_shutdown(self, signum, frame):
        """Graceful shutdown по SIGINT/SIGTERM"""
        if not self.running:
            return
        logger.info("\n[GridBot] === ОСТАНОВКА БОТА ===")
        self.running = False

        # Отменяем все ордера
        logger.info(f"[GridBot] Отмена всех ордеров для {cfg.SYMBOL}...")
        self.executor.cancel_all_orders(cfg.SYMBOL)
        time.sleep(0.5)

        # Закрываем позиции
        logger.info(f"[GridBot] Закрытие всех позиций для {cfg.SYMBOL}...")
        self.executor.close_all_positions(cfg.SYMBOL)

        # Сохраняем состояние
        if self.engine:
            self.engine.save_state(cfg.STATE_FILE, cfg.SYMBOL)

        # Итоговый отчёт
        balance = self.executor.get_balance()
        profit = self.engine.total_profit if self.engine else 0
        trades = self.engine.total_trades if self.engine else 0

        logger.info(f"\n{'=' * 50}")
        logger.info(f"  GRID BOT — Session Summary")
        logger.info(f"{'=' * 50}")
        logger.info(f"  Total Profit: ${profit:+.2f}")
        logger.info(f"  Total Trades: {trades}")
        logger.info(f"  Final Balance: ${balance:.2f}")
        logger.info(f"{'=' * 50}\n")

        self.telegram.notify_stop(
            reason="Manual shutdown",
            total_profit=profit,
            total_trades=trades,
            final_balance=balance
        )

        sys.exit(0)


def main():
    """Entry point"""
    print("\n🤖 GRID BOT 2026")
    print(f"Symbol: {cfg.SYMBOL}")
    print(f"Mode: {'DEMO' if cfg.BYBIT_DEMO else ('TESTNET' if cfg.TESTNET else 'LIVE')}")
    print()

    bot = GridBot()
    bot.start()


if __name__ == "__main__":
    main()
