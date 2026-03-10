"""
GRID BOT 2026 — Main Entry Point (Multi-Scanner Version)
Многопоточный сканер рынка: находит волатильные пары, запускает независимые сетки
"""

import sys
import os
import signal
import time
from datetime import datetime, timezone
from typing import Dict, List

# Добавляем текущую директорию в path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Фикс кодировок для Windows (если используется CMD, который работает на cp1251)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import grid_config as cfg
from grid_engine import GridEngine, GridLevel
from grid_executor import GridExecutor
from grid_telegram import GridTelegram
from logger import logger

class GridBotMulti:
    def __init__(self):
        self.executor = GridExecutor()
        self.telegram = GridTelegram()
        
        # symbol -> GridEngine
        self.engines: Dict[str, GridEngine] = {}
        # symbol -> {order_id: GridLevel}
        self.active_orders: Dict[str, Dict[str, GridLevel]] = {}
        
        self.running = False
        self._started_at = datetime.now(timezone.utc).replace(tzinfo=None) # Keep naive for compatibility if needed, but actually we use isoformat
        self._last_heartbeat = datetime.now(timezone.utc).replace(tzinfo=None)
        self._last_funding_check = datetime.now(timezone.utc).replace(tzinfo=None)
        self._last_scan = datetime.min

        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def start(self):
        logger.info("=========================================")
        logger.info(f"GRID BOT 2026 (MULTI-SCANNER) START")
        logger.info(f"Scanner Mode: {'AUTO' if cfg.SYMBOL == 'AUTO' else 'MANUAL (' + cfg.SYMBOL + ')'}")
        logger.info(f"Max Grids: {cfg.MAX_CONCURRENT_GRIDS} | Alloc: {cfg.ALLOCATION_PER_GRID}%")
        logger.info("=========================================")

        # 1. Восстанавливаем состояние старых сеток, если были
        active_symbols = GridEngine.get_active_symbols(cfg.STATE_FILE)
        for sym in active_symbols:
            logger.info(f"[GridBot] Пытаемся восстановить сетку для {sym} из БД...")
            self._start_grid_for_symbol(sym, is_recovery=True)

        # 2. Если режим мануальный (1 пара) и ее почему-то нет — запускаем её.
        if cfg.SYMBOL != "AUTO" and cfg.SYMBOL not in self.engines:
            self._start_grid_for_symbol(cfg.SYMBOL)
            
        self.running = True
        self._main_loop()

    def _start_grid_for_symbol(self, symbol: str, is_recovery: bool = False):
        """Пытается создать и запустить сетку для одной пары"""
        if symbol in self.engines: return

        # 1. Узнаем цену
        price = self.executor.get_price(symbol)
        if price <= 0:
            logger.error(f"[{symbol}] Ошибка получения цены")
            return

        # 2. Сколько выделить баланса?
        total_balance = self.executor.get_balance()
        if cfg.INVESTMENT > 0 and cfg.SYMBOL != "AUTO":
            # Ручной режим с жестко заданной суммой
            target_investment = cfg.INVESTMENT
        else:
            # Аллокация % от баланса
            target_investment = total_balance * (cfg.ALLOCATION_PER_GRID / 100.0)
            
        investment = min(target_investment, total_balance)
        if investment < 5:
            logger.warning(f"[{symbol}] Balance ${investment:.2f} too low (min $5). Не запускаем сетку.")
            return

        # 3. RSI фильтр (только если это новый запуск)
        if not is_recovery and cfg.RSI_ENTRY_CHECK:
            rsi = self.executor.get_rsi(symbol, cfg.RSI_PERIOD)
            if not (30 <= rsi <= 70):
                logger.info(f"[{symbol}] RSI={rsi:.2f} (Не в зоне баланса). Пропускаем вход.")
                return

        # 4. Расчет диапазона (ATR или фиксированный)
        range_pct = cfg.GRID_RANGE_PCT
        if cfg.USE_ATR_STEP:
            atr = self.executor.get_atr(symbol, cfg.ATR_PERIOD)
            if atr > 0:
                calc_range = (atr * cfg.ATR_MULTIPLIER / price) * 100
                range_pct = round(min(max(calc_range, 1.0), 10.0), 2)
                
        upper = round(price * (1 + range_pct / 100), 4)
        lower = round(price * (1 - range_pct / 100), 4)

        # 5. Инит Движка
        engine = GridEngine(symbol=symbol, upper=upper, lower=lower, count=cfg.GRID_COUNT, mode=cfg.GRID_MODE, db_path=cfg.STATE_FILE)
        engine.start_balance = investment
        self.engines[symbol] = engine
        self.active_orders[symbol] = {}

        # 6. Если recovery - грузим
        is_restored = False
        if is_recovery:
            is_restored = engine.load_state()
            if is_restored:
                logger.info(f"[{symbol}] 🔄 Успешно восстановлен. Trades: {engine.total_trades}, PnL: ${engine.total_profit:.2f}")

        # Если не recovery или не удалось восстановить
        if not is_restored:
            levels = engine.calculate_levels(price)
            logger.info(f"[{symbol}] Расчет свежей сетки: {len(levels)} уровней. Шаг: {range_pct}%")

        # 7. Задаем QTY и отправляем ордера
        sym_info = self.executor.get_symbol_info(symbol)
        qty = engine.calculate_qty_per_level(
            balance=investment, leverage=cfg.LEVERAGE, 
            current_price=price, qty_step=sym_info['qty_step'], min_qty=sym_info['min_qty']
        )
        
        notional = qty * price
        if notional < sym_info.get('min_notional', 5):
            logger.warning(f"[{symbol}] Ордер ${notional:.2f} < min ${sym_info['min_notional']}. Отмена.")
            self._remove_grid(symbol)
            return

        self.executor.set_leverage(symbol, cfg.LEVERAGE)
        self.executor.cancel_all_orders(symbol)
        time.sleep(0.5)

        placed = self._place_grid_orders(symbol, engine.levels, qty)
        
        if placed > 0:
            logger.info(f"[{symbol}] Запущена сетка: Выставлено {placed} ордеров")
            if not is_restored:
                self.telegram.notify_start(
                    symbol=symbol, levels=cfg.GRID_COUNT, upper=upper, lower=lower,
                    qty=qty, balance=total_balance, leverage=cfg.LEVERAGE
                )
            # сохраняем
            engine.save_state()
        else:
            logger.error(f"[{symbol}] ❌ Не выставлено ордеров, удаляем сетку.")
            self._remove_grid(symbol)


    def _place_grid_orders(self, symbol: str, levels: list, qty: float) -> int:
        placed = 0
        for level in levels:
            o_id = self.executor.place_limit_order(symbol, level.side, qty, level.price)
            if o_id:
                level.order_id = o_id
                level.status = "active"
                self.active_orders[symbol][o_id] = level
                placed += 1
                time.sleep(0.05) # Небольшая пауза, чтобы не словить Rate Limit
        return placed

    def _remove_grid(self, symbol: str):
        if symbol in self.engines: del self.engines[symbol]
        if symbol in self.active_orders: del self.active_orders[symbol]

    def _main_loop(self):
        logger.info(f"\nМульти-Мониторинг запущен (check every {cfg.CHECK_INTERVAL}s)...")
        while self.running:
            try:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                
                # 1. Сканируем новые пары для входа, если есть свободные слоты
                if cfg.SYMBOL == "AUTO" and len(self.engines) < cfg.MAX_CONCURRENT_GRIDS:
                    # Раз в 5 минут ищем топ волатильных пар
                    if (now - self._last_scan).total_seconds() > 300:
                        logger.info("Поиск лучших волатильных пар (Сканер)....")
                        top_pairs = self.executor.get_top_volatile_pairs(limit=cfg.AUTO_SCAN_TOP, min_volume=cfg.MIN_VOLUME_24H)
                        self._last_scan = now
                        
                        for scan_sym in top_pairs:
                            if len(self.engines) >= cfg.MAX_CONCURRENT_GRIDS: break
                            if scan_sym not in self.engines:
                                logger.info(f"[Сканер] Обнаружена волатильная пара: {scan_sym}, попытка входа...")
                                self._start_grid_for_symbol(scan_sym)

                # 2. Обслуживаем каждую работающую сетку
                for sym in list(self.engines.keys()):
                    engine = self.engines[sym]
                    
                    self._check_fills_for_symbol(sym, engine)
                    
                    price = self.executor.get_price(sym)
                    if price > 0 and engine.should_rebalance(price, cfg.REBALANCE_THRESHOLD):
                        logger.info(f"[{sym}] ⚠️ Цена {price} вышла из диапазона. Rebalance!")
                        self._do_rebalance_for_symbol(sym, engine, price)
                        continue

                # 3. Глобальные проверки (Drawdown)
                equity = self.executor.get_equity()
                has_global_drawdown = False
                
                # Проверим общий drawdown или индивидуальный
                for sym in list(self.engines.keys()):
                    # Если индивидуальная сетка слила больше чем разрешено - рубим ее
                    if self.engines[sym].check_max_drawdown(equity, cfg.MAX_DRAWDOWN_PCT): # TODO: needs individual checking ideally
                        logger.error(f"[{sym}] MAX DRAWDOWN!")
                        self._stop_symbol(sym, "Max Drawdown Exceeded")
                        
                # 4. Проверяем Funding Rate каждые N минут
                if (now - self._last_funding_check).total_seconds() >= 180:
                    for sym in list(self.engines.keys()):
                        fr = self.executor.get_funding_rate(sym)
                        if abs(fr) >= cfg.MAX_FUNDING_RATE:
                            logger.error(f"[{sym}] 🚨 DANGEROUS FUNDING RATE: {fr*100:.4f}%!")
                            self._stop_symbol(sym, f"Extreme Funding: {fr*100:.4f}%")
                    self._last_funding_check = now

                # 5. Heartbeat
                if (now - self._last_heartbeat).total_seconds() >= cfg.HEARTBEAT_INTERVAL:
                    self._send_heartbeat(equity)
                    self._last_heartbeat = now

                # 6. Сохраняемся
                for sym in list(self.engines.keys()):
                    self.engines[sym].save_state()

                time.sleep(cfg.CHECK_INTERVAL)

            except KeyboardInterrupt:
                self._handle_shutdown(None, None)
                return
            except Exception as e:
                logger.error(f"[GridBot] Ошибка главного цикла (Multiscan): {e}")
                time.sleep(cfg.CHECK_INTERVAL * 2)

    def _check_fills_for_symbol(self, symbol: str, engine: GridEngine):
        """Проверяет исполненные ордера текущей пары"""
        current_orders = self.executor.get_open_orders(symbol)
        current_ids = {o['order_id'] for o in current_orders}

        filled_ids = set(self.active_orders[symbol].keys()) - current_ids

        for oid in filled_ids:
            level = self.active_orders[symbol].pop(oid)
            level.status = "filled"
            level.filled_at = datetime.now(timezone.utc).isoformat()

            logger.info(f"[{symbol}] ✅ FILLED: {level.side} @ {level.price}")

            opposite = engine.get_opposite_level(level)
            if opposite:
                new_oid = self.executor.place_limit_order(
                    symbol=symbol, side=opposite.side,
                    qty=engine.qty_per_level, price=opposite.price
                )
                if new_oid:
                    opposite.order_id = new_oid
                    opposite.status = "active"
                    self.active_orders[symbol][new_oid] = opposite

                    step = engine.get_step_size()
                    approx_profit = step * engine.qty_per_level
                    engine.record_profit(approx_profit)

                    self.telegram.notify_fill(
                        side=level.side, price=level.price, qty=engine.qty_per_level,
                        tp_side=opposite.side, tp_price=opposite.price
                    )

                    if engine.total_trades % 5 == 0:
                        self.telegram.notify_profit(
                            profit=approx_profit, total_profit=engine.total_profit, total_trades=engine.total_trades
                        )

    def _do_rebalance_for_symbol(self, symbol: str, engine: GridEngine, new_price: float):
        self.executor.cancel_all_orders(symbol)
        self.active_orders[symbol].clear()
        time.sleep(0.5)

        if cfg.REBALANCE_MODE.upper() == "CLOSE_ALL":
            self.executor.close_all_positions(symbol)

        range_pct = cfg.GRID_RANGE_PCT
        if cfg.USE_ATR_STEP:
            atr = self.executor.get_atr(symbol, cfg.ATR_PERIOD)
            if atr > 0:
                calc_range = (atr * cfg.ATR_MULTIPLIER) / new_price * 100
                range_pct = max(1.0, min(15.0, calc_range))
                
        engine.rebalance(new_price, range_pct)

        balance = self.executor.get_balance()
        target_inv = balance * (cfg.ALLOCATION_PER_GRID / 100.0) if cfg.INVESTMENT <= 0 else cfg.INVESTMENT
        if cfg.AUTO_COMPOUND and engine.total_profit > 0:
            target_inv += engine.total_profit
        
        investment = min(target_inv, balance)

        sym_info = self.executor.get_symbol_info(symbol)
        engine.calculate_qty_per_level(
            balance=investment, leverage=cfg.LEVERAGE,
            current_price=new_price, qty_step=sym_info['qty_step'], min_qty=sym_info['min_qty']
        )

        placed = self._place_grid_orders(symbol, engine.levels, engine.qty_per_level)
        logger.info(f"[{symbol}] ✅ Rebalanced: {placed} orders, range [{engine.lower:.2f} — {engine.upper:.2f}]")

        self.telegram.notify_rebalance(
            new_upper=engine.upper, new_lower=engine.lower,
            reason=f"[{symbol}] Price ${new_price:.2f} exited old range"
        )

    def _send_heartbeat(self, equity: float):
        uptime = datetime.now(timezone.utc).replace(tzinfo=None) - self._started_at
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)
        
        total_pnl = sum(e.total_profit for e in self.engines.values())
        total_trades = sum(e.total_trades for e in self.engines.values())
        
        logger.info(f"[HEARTBEAT] Equ: ${equity:.2f} | PnL: ${total_pnl:.4f} | Grids: {len(self.engines)}/{cfg.MAX_CONCURRENT_GRIDS}")
        
        for sym, eng in self.engines.items():
            logger.info(f" - [{sym}] Pnl: ${eng.total_profit:.2f} ({eng.total_trades} t) | Range: {eng.lower:.2f} - {eng.upper:.2f}")

        # Telegram
        self.telegram.send_status(
            symbol="MULTI-SCANNER",
            price=0,
            upper=0, lower=0,
            total_profit=total_pnl,
            total_trades=total_trades,
            balance=equity,
            active_orders=sum(len(v) for v in self.active_orders.values()),
            positions=len(self.engines),
            uptime=f"{hours}h {minutes}m"
        )

    def _stop_symbol(self, symbol: str, reason: str):
        """Останавливает конкретную сетку"""
        logger.error(f"[{symbol}] 🛑 ЗАКРЫТИЕ СЕТКИ: {reason}")
        self.executor.cancel_all_orders(symbol)
        self.executor.close_all_positions(symbol)
        
        if symbol in self.engines:
            # Сохраняем последнее состояние
            self.engines[symbol].save_state()
            # Удаляем из оперативной памяти 
            # (чтобы она не мешала сканеру брать новые, или скажем удалить её из БД - по идее нам просто не нужно ее больше трекать)
            self._remove_grid(symbol)

    def _handle_shutdown(self, signum, frame):
        if not self.running: return
        self.running = False
        logger.info("\n=== ГЛОБАЛЬНАЯ ОСТАНОВКА БОТА ===")

        for sym in list(self.engines.keys()):
            logger.info(f"[{sym}] Отмена ордеров и позиций...")
            self.executor.cancel_all_orders(sym)
            time.sleep(0.3)
            self.executor.close_all_positions(sym)
            self.engines[sym].save_state()

        eq = self.executor.get_equity()
        total_pnl = sum(e.total_profit for e in self.engines.values())
        total_tr = sum(e.total_trades for e in self.engines.values())
        
        logger.info(f"Final Equity: ${eq:.2f} | Total Profit: ${total_pnl:.2f} | Trades: {total_tr}")
        
        self.telegram.notify_stop(
            reason="Manual multi-shutdown", total_profit=total_pnl, 
            total_trades=total_tr, final_balance=eq
        )
        sys.exit(0)

def main():
    print("\n🤖 GRID BOT 2026 (MULTI-SCANNER)")
    print(f"Server Ready: Monitoring 10 pairs, Max Slots: {cfg.MAX_CONCURRENT_GRIDS}")
    print(f"Allocated Balance per Grid: {cfg.ALLOCATION_PER_GRID}%\n")

    bot = GridBotMulti()
    bot.start()

if __name__ == "__main__":
    main()
