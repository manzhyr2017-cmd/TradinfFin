"""
TITAN BOT 2026 - Session Filter
Торгуем только в оптимальное время
"""

from datetime import datetime, time
from enum import Enum
import pytz

class TradingSession(Enum):
    ASIA = "ASIA"           # Tokyo: 00:00-09:00 UTC
    LONDON = "LONDON"       # London: 07:00-16:00 UTC  
    NEW_YORK = "NEW_YORK"   # NY: 13:00-22:00 UTC
    OVERLAP = "OVERLAP"     # London+NY: 13:00-16:00 UTC (лучшее время!)
    DEAD_ZONE = "DEAD_ZONE" # Низкая ликвидность


class SessionFilter:
    """
    Фильтр торговых сессий.
    
    Почему это важно для 20%:
    - OVERLAP (Лондон + Нью-Йорк) = максимальная волатильность и ликвидность
    - DEAD_ZONE = много ложных движений, спреды широкие
    
    Торгуя только в хорошие сессии, ты избегаешь 50% плохих сделок.
    """
    
    def __init__(self):
        self.utc = pytz.UTC
        
        # Определяем сессии (в UTC)
        self.sessions = {
            TradingSession.ASIA: (time(0, 0), time(9, 0)),
            TradingSession.LONDON: (time(7, 0), time(16, 0)),
            TradingSession.NEW_YORK: (time(13, 0), time(22, 0)),
            TradingSession.OVERLAP: (time(13, 0), time(16, 0)),
        }
        
        # Рейтинг сессий для торговли (1-10)
        self.session_quality = {
            TradingSession.OVERLAP: 10,    # Лучшее время
            TradingSession.LONDON: 8,
            TradingSession.NEW_YORK: 8,
            TradingSession.ASIA: 5,        # Меньше волатильности
            TradingSession.DEAD_ZONE: 2,   # Избегать
        }
    
    def get_current_session(self) -> TradingSession:
        """Определяет текущую торговую сессию."""
        now = datetime.now(self.utc).time()
        
        # Проверяем overlap первым (он внутри London и NY)
        if self._is_time_in_range(now, self.sessions[TradingSession.OVERLAP]):
            return TradingSession.OVERLAP
        
        if self._is_time_in_range(now, self.sessions[TradingSession.LONDON]):
            return TradingSession.LONDON
        
        if self._is_time_in_range(now, self.sessions[TradingSession.NEW_YORK]):
            return TradingSession.NEW_YORK
        
        if self._is_time_in_range(now, self.sessions[TradingSession.ASIA]):
            return TradingSession.ASIA
        
        return TradingSession.DEAD_ZONE
    
    def is_good_time_to_trade(self, min_quality: int = 5) -> tuple[bool, str]:
        """
        Проверяет, хорошее ли сейчас время для торговли.
        
        Args:
            min_quality: Минимальный рейтинг сессии (1-10)
            
        Returns:
            (can_trade, reason)
        """
        session = self.get_current_session()
        quality = self.session_quality[session]
        
        if quality >= min_quality:
            return True, f"✅ Сессия {session.value} (качество: {quality}/10)"
        else:
            return False, f"⏳ Сессия {session.value} (качество: {quality}/10) - ждём лучшего времени"
    
    def get_next_good_session(self) -> str:
        """Возвращает время до следующей хорошей сессии."""
        now = datetime.now(self.utc)
        current_hour = now.hour
        
        # Overlap начинается в 13:00 UTC
        if current_hour < 13:
            hours_until = 13 - current_hour
            return f"До OVERLAP: {hours_until} часов"
        elif current_hour >= 22:
            hours_until = 24 - current_hour + 7  # До London
            return f"До LONDON: {hours_until} часов"
        else:
            return "Сейчас хорошее время!"
    
    def _is_time_in_range(self, t: time, time_range: tuple) -> bool:
        """Проверяет, попадает ли время в диапазон."""
        start, end = time_range
        if start <= end:
            return start <= t <= end
        else:  # Переход через полночь
            return t >= start or t <= end
    
    def get_session_stats(self) -> dict:
        """Статистика по сессиям для аналитики."""
        return {
            'current_session': self.get_current_session().value,
            'quality': self.session_quality[self.get_current_session()],
            'utc_time': datetime.now(self.utc).strftime('%H:%M UTC'),
            'recommendation': self.is_good_time_to_trade()[1]
        }
