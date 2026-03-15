"""
═══════════════════════════════════════════════════════════════════
  GRID BOT v2.0 — Orchestrated by Master Brain
  ═══════════════════════════════════════════════════════════════
"""

import time
import logging
import signal
import sys
from brain.master_brain import MasterBrain
import config

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("grid_bot.log", encoding="utf-8")
    ]
)

log = logging.getLogger("Main")

class GridBotApp:
    def __init__(self):
        self.brain = MasterBrain()
        self.running = True
        
        # Регистрация сигналов для корректного завершения
        signal.signal(signal.SIGINT, self.handle_exit)
        signal.signal(signal.SIGTERM, self.handle_exit)

    def handle_exit(self, signum, frame):
        log.info(f"Завершение работы (сигнал {signum})...")
        self.running = False
        self.brain.stop()
        sys.exit(0)

    def run(self):
        log.info("🚀 Запуск приложения Grid Bot v2...")
        self.brain.start()
        
        # Первоначальная проверка и размещение сетки (если нужно)
        # decide() без аргументов запускает _periodic_check
        self.brain.decide()
        
        while self.running:
            try:
                # Основной цикл принятия решений (периодический аудит)
                # Частота аудита регулируется здесь, 
                # но основные события (fills) приходят через WebSockets.
                decision = self.brain.decide()
                
                # Логируем если есть важные заметки
                if decision.notes:
                    for note in decision.notes:
                        log.debug(f"Brain Note: {note}")
                
                time.sleep(30) # Пауза между периодическими проверками
                
            except Exception as e:
                log.error(f"Ошибка в основном цикле: {e}", exc_info=True)
                time.sleep(10)

if __name__ == "__main__":
    bot = GridBotApp()
    bot.run()
