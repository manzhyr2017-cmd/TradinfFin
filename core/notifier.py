import requests
import logging
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger("Notifier")

class TelegramNotifier:
    """
    Класс для отправки уведомлений в Telegram.
    """
    
    def __init__(self, token: str = TELEGRAM_BOT_TOKEN, chat_id: str = TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
        
    def send_message(self, message: str):
        if not self.enabled:
            log.warning("Telegram configuration missing. Skipping notification.")
            return
            
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception as e:
            log.error(f"Error sending Telegram message: {e}")

    def send(self, message: str):
        """Псевдоним для совместимости."""
        self.send_message(message)

    def send_alert(self, message: str):
        """Псевдоним для экстренных уведомлений."""
        self.send_message(f"🚨 <b>ALERT</b>\n{message}")

def send_telegram_message(message: str):
    """Функция-обертка для обратной совместимости."""
    notifier = TelegramNotifier()
    notifier.send_message(message)
