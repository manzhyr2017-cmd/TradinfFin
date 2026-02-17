#!/usr/bin/env python3
"""
Trading Bot Log Monitor
=======================
Скрипт для автоматической проверки логов бота и отправки уведомлений в Telegram
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict

# Настройки
LOG_FILE = "bot.log"
STATE_FILE = "bot_monitor_state.json"
CHECK_INTERVAL = 60  # секунд
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8339069750:AAGMYLCZ9bfovVb57fmB3vAZ_M7ePHbl2zo")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "-1003842003511")

# Уровни логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BotMonitor:
    """Монитор для проверки логов бота"""
    
    def __init__(self, log_file: str = LOG_FILE):
        self.log_file = log_file
        self.last_position = 0
        self.last_state = self._load_state()
        self.telegram_sent = set()  # Уже отправленные уведомления
        
    def _load_state(self) -> Dict:
        """Загрузить состояние из файла"""
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {"last_check": None, "trades_opened": 0, "errors": 0}
    
    def _save_state(self):
        """Сохранить состояние в файл"""
        self.last_state["last_check"] = datetime.now().isoformat()
        with open(STATE_FILE, 'w') as f:
            json.dump(self.last_state, f, indent=2)
    
    def _get_new_logs(self) -> List[str]:
        """Получить новые строки из логов"""
        if not os.path.exists(self.log_file):
            return []
        
        try:
            with open(self.log_file, 'r') as f:
                f.seek(self.last_position)
                new_lines = f.readlines()
                self.last_position = f.tell()
                return new_lines
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            return []
    
    def _parse_log_line(self, line: str) -> Optional[Dict]:
        """Разобрать строку лога"""
        line = line.strip()
        if not line:
            return None
        
        # Ищем ключевые слова
        keywords = {
            'LONG': 'LONG',
            'SHORT': 'SHORT',
            'Entry': 'Entry',
            'TP': 'Take Profit',
            'SL': 'Stop Loss',
            'Position': 'Position',
            'Order': 'Order',
            'Error': 'Error',
            'Warning': 'Warning',
            'Info': 'Info'
        }
        
        for keyword, category in keywords.items():
            if keyword in line:
                return {
                    "timestamp": datetime.now().isoformat(),
                    "line": line,
                    "category": category,
                    "keyword": keyword
                }
        return None
    
    def _send_telegram(self, message: str):
        """Отправить уведомление в Telegram"""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL:
            logger.warning("Telegram not configured")
            return
        
        # В реальном скрипте здесь будет вызов Telegram API
        # Для теста просто логируем
        logger.info(f"Telegram message: {message}")
    
    def check_logs(self):
        """Проверить логи и отправить уведомления"""
        new_logs = self._get_new_logs()
        
        for line in new_logs:
            parsed = self._parse_log_line(line)
            if not parsed:
                continue
            
            # Обработка различных типов сообщений
            if parsed['keyword'] == 'LONG' or parsed['keyword'] == 'SHORT':
                if 'Исполнение сигнала' in line:
                    self.last_state["trades_opened"] += 1
                    self._send_telegram(f"🚀 Открыта сделка: {line}")
            
            elif parsed['keyword'] == 'Error':
                self.last_state["errors"] += 1
                if line not in self.telegram_sent:
                    self.telegram_sent.add(line)
                    self._send_telegram(f"❌ Ошибка: {line}")
            
            elif parsed['keyword'] == 'Warning':
                if line not in self.telegram_sent:
                    self.telegram_sent.add(line)
                    self._send_telegram(f"⚠️ Предупреждение: {line}")
            
            elif parsed['keyword'] == 'Order':
                if 'отправлен успешно' in line:
                    self._send_telegram(f"✅ Ордер отправлен: {line}")
        
        self._save_state()
    
    def check_bot_status(self) -> bool:
        """Проверить статус процесса бота"""
        try:
            import subprocess
            result = subprocess.run(
                ['pgrep', '-f', 'main_bybit.py'],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except:
            return False
    
    def run(self):
        """Запустить мониторинг"""
        logger.info("🚀 Запуск мониторинга бота")
        
        while True:
            try:
                # Проверить статус бота
                if not self.check_bot_status():
                    logger.warning("⚠️ Бот не запущен!")
                    self._send_telegram("⚠️ Бот остановлен! Проверьте логи.")
                    time.sleep(300)  # Ждать 5 минут перед повторной проверкой
                    continue
                
                # Проверить логи
                self.check_logs()
                
                # Ждать следующую проверку
                time.sleep(CHECK_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("🛑 Мониторинг остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка мониторинга: {e}")
                time.sleep(60)


def main():
    """Главная функция"""
    monitor = BotMonitor()
    monitor.run()


if __name__ == "__main__":
    main()
