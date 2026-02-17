"""
TITAN BOT 2026 - Telegram Bridge
Отправка сигналов и дашбордов в Telegram
"""

import requests
import json
import os
from datetime import datetime
import config

class TitanTelegramBridge:
    """
    Бридж для отправки данных из TitanBot в Telegram.
    Использует прямые HTTP запросы к Telegram Bot API для максимальной скорости и надежности.
    """
    
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.channel = os.getenv("TELEGRAM_CHANNEL")
        self.api_url = f"https://api.telegram.org/bot{self.token}"

    def send_message(self, text: str, parse_mode: str = "HTML"):
        """Отправляет текстовое сообщение"""
        if not self.token or not self.channel:
            return False
            
        try:
            payload = {
                "chat_id": self.channel,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True
            }
            response = requests.post(f"{self.api_url}/sendMessage", json=payload, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"[TelegramBridge] Error: {e}")
            return False

    def send_signal(self, signal_data: dict):
        """
        Форматирует и отправляет сигнал в Telegram.
        signal_data должен содержать: symbol, direction, score, entry, sl, tp, confidence, recommendation
        """
        emoji = "🚀" if signal_data['direction'] == "LONG" else "📉"
        color = "🟢" if signal_data['direction'] == "LONG" else "🔴"
        
        # Визуальная шкала скора
        score = signal_data['score']
        score_bar = self._get_score_bar(score)
        
        msg = f"""
{color} <b>TITAN SIGNAL: {signal_data['symbol']}</b> │ {signal_data['direction']}
{'═' * 30}

<b>TOTAL SCORE:</b> <code>[{score_bar}]</code> <b>{score:+.1f}</b>
<b>Confidence:</b> {signal_data['confidence']*100:.0f}%
<b>Strength:</b> {signal_data['strength']}

{'─' * 30}
💰 <b>Entry:</b> <code>{signal_data['entry']:.4f}</code>
🛑 <b>SL:</b> <code>{signal_data['sl']:.4f}</code>
🎯 <b>TP:</b> <code>{signal_data['tp']:.4f}</code>

{'─' * 30}
💡 <b>Recommendation:</b>
<i>{signal_data['recommendation']}</i>

🤖 <i>TITAN BOT 2026 | ULTIMATE FINAL</i>
"""
        return self.send_message(msg.strip())

    def send_dashboard(self, signal):
        """Отправляет полный дашборд композитного скора"""
        # (Упрощенная версия для ТГ)
        msg = f"📊 <b>TITAN COMPOSITE REPORT</b>\n"
        msg += f"Symbol: <b>{config.SYMBOL}</b>\n"
        msg += f"Score: <b>{signal.total_score:+.1f}</b>\n"
        msg += f"Direction: <b>{signal.direction}</b>\n\n"
        
        for name, value in signal.components.items():
            bar = "🟩" if value > 0.3 else ("🟥" if value < -0.3 else "⬜")
            msg += f"{bar} {name}: {value:+.2f}\n"
            
        msg += f"\n<i>{signal.recommendation}</i>"
        return self.send_message(msg)

    def _get_score_bar(self, score: float) -> str:
        """Визуальная шкала для ТГ"""
        # -100 to 100 map to 10 chars
        normalized = (score + 100) / 200
        pos = int(normalized * 10)
        bar = "─" * pos + "●" + "─" * (9 - pos)
        return bar
