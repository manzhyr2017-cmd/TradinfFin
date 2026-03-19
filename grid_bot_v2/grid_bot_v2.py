"""
═══════════════════════════════════════════════════════
  GRID BOT v4.0 — Bulletproof WebSocket & Master Brain
═══════════════════════════════════════════════════════
"""

import time
import signal
import sys
import logging

import config
from brain.master_brain import MasterBrain
from core.websocket_manager import WebSocketManager

# Проверяем, что в конфиге есть необходимые константы
if not hasattr(config, 'LOG_FILE'): config.LOG_FILE = "grid_bot.log"
if not hasattr(config, 'POLL_INTERVAL_SEC'): config.POLL_INTERVAL_SEC = 2.0
if not hasattr(config, 'RETRY_DELAY_SEC'): config.RETRY_DELAY_SEC = 5.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("GridBot")


def main():
    brain = MasterBrain()
    ws_manager = WebSocketManager()
    running = True

    # ── Signal handler ────────────────────────────────
    def stop_signal_handler(sig, frame):
        nonlocal running
        running = False
        log.info("⛔ Получен сигнал остановки...")

    signal.signal(signal.SIGINT, stop_signal_handler)
    signal.signal(signal.SIGTERM, stop_signal_handler)

    # ── WebSocket callback для fill ───────────────────
    def on_fill(order_data: dict):
        """Вызывается при исполнении ордера."""
        try:
            side = order_data.get("side", "")
            avg_price = order_data.get("avgPrice", "0")
            qty = order_data.get("qty", "0")
            oid = order_data.get("orderId", "")
            
            # Определяем level_index из orderLinkId (если он там есть)
            # Формат: SYMBOL-LVL-INDEX-TIMESTAMP
            link_id = order_data.get("orderLinkId", "")
            level_idx = 0
            if "-LVL-" in link_id:
                try:
                    # Разделяем по -LVL- и берем следующую часть, затем делим по - и берем индекс
                    parts = link_id.split("-LVL-")
                    if len(parts) > 1:
                        level_idx = int(parts[1].split("-")[0])
                except (ValueError, IndexError):
                    pass

            # Передаём в мозг для принятия мер (размещение ответного ордера)
            brain.decide_and_act(
                filled_order_id=oid,
                filled_side=side,
                filled_price=float(avg_price) if avg_price != "0" and avg_price else 0,
                filled_qty=float(qty) if qty else 0,
                filled_profit=0,
                filled_level_index=level_idx,
            )
        except Exception as e:
            log.error(f"Fill handler error: {e}", exc_info=True)

    # ── Запуск ────────────────────────────────────────
    log.info("🚀 " + "═" * 55)
    log.info("🚀  GRID BOT v5.0 — ЗАПУСК (x10 Leverage)")
    log.info("🚀 " + "═" * 55)

    # ① Стартуем системы
    ws_manager.start()
    brain.start()
    ws_manager.on_order_fill(on_fill)

    # ② Ждём подключения
    for attempt in range(10):
        if ws_manager.is_healthy:
            break
        log.info(f"⏳ Ожидание WS подключения... ({attempt+1}/10)")
        time.sleep(2)

    if not ws_manager.is_healthy:
        log.warning("❌ WS не подключился за 20 секунд. Продолжаем в режиме Polling.")

    # ③ Первоначальный снимок и размещение сетки (если нет ордеров)
    try:
        snap = brain._level2_read_market()
        mode = brain._level3_select_mode(snap)
        
        # Проверяем, есть ли уже ордера. Если нет - ставим сетку.
        open_orders = brain.client.get_open_orders()
        if not open_orders:
            log.info("🌱 Сетка пуста. Размещаем начальные ордера...")
            brain._place_initial_grid(snap, mode)
        
        banner = f"""
        {'='*40}
           GRID BOT v5.0 - PROFITABILITY UPGRADE
        {'='*40}
        Symbol:    {config.SYMBOL}
        Leverage:  {config.LEVERAGE}x (Target 10x)
        Grid Size: {config.GRID_LEVEL_COUNT} levels
        Step:      {config.GRID_STEP_PERCENT}%
        Risk:      Max Drawdown ${config.MAX_DRAWDOWN_USDT}
        {'='*40}
        """
        print(banner)
        
        # 0. Установка плеча при старте
        brain.client.set_leverage(symbol=config.SYMBOL, leverage=config.LEVERAGE)
        
        brain.notifier.send_alert(
            f"🚀 Grid Bot v4.0 запущен!\n"
            f"Символ: {config.SYMBOL}\n"
            f"Режим: {mode.value}\n"
            f"Баланс: {float(brain.client.get_balance()):.2f} USDT"
        )
    except Exception as e:
        log.error(f"Initial setup error: {e}")

    # ④ Основной цикл
    cycle = 0
    last_ws_health_check = time.time()
    last_stats_log = time.time()

    try:
        while running:
            cycle += 1
            try:
                # 1. Периодический аудит мозга (проверка условий, RSI, ML и т.д.)
                brain.decide_and_act()

                # 2. Проверка здоровья WS и fallback-опрос
                if time.time() - last_ws_health_check > 30:
                    last_ws_health_check = time.time()
                    if not ws_manager.is_healthy:
                        log.warning("⚠️ WS нездоров — принудительный опрос через REST API")
                        brain._check_orders_rest()

                # 3. Периодический лог статистики в чат
                if time.time() - last_stats_log > 3600: # Раз в час
                    last_stats_log = time.time()
                    profit = brain.db.get_total_profit()
                    brain.notifier.send_message(f"📊 Статистика за час:\nПрофит: {float(profit):.4f} USDT")

                time.sleep(config.POLL_INTERVAL_SEC)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log.error(f"Ошибка в основном цикле: {e}", exc_info=True)
                time.sleep(config.RETRY_DELAY_SEC)

    finally:
        # ⑤ Грациозное завершение
        log.info("🛑 Остановка приложения...")
        ws_manager.stop()
        brain.stop()
        
        # Опционально: отмена ордеров при выходе (обычно не нужно для грида)
        # if input("Отменить все ордера? (y/n): ") == "y":
        #    brain.client.cancel_all()
        
        try:
            if hasattr(brain, 'db'):
                brain.db.close()
        except: pass
        
        brain.notifier.send_alert("🛑 Бот остановлен администратором")
        log.info("👋 Бот полностью остановлен. Удачи!")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.critical(f"Критическая ошибка запуска: {e}", exc_info=True)
        sys.exit(1)
