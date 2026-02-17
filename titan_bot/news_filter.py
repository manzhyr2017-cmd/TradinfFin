"""
TITAN BOT 2026 - News & Events Filter
Не торгуй перед CPI/FOMC — это казино!
"""

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional
import config

@dataclass
class EconomicEvent:
    """Экономическое событие"""
    name: str
    datetime: datetime
    impact: str  # 'HIGH', 'MEDIUM', 'LOW'
    currency: str
    forecast: str
    previous: str

@dataclass
class NewsFilterResult:
    """Результат проверки новостей"""
    can_trade: bool
    upcoming_events: List[EconomicEvent]
    nearest_high_impact: Optional[EconomicEvent]
    hours_until_event: float
    risk_level: str  # 'SAFE', 'CAUTION', 'DANGER'
    message: str


class NewsFilter:
    """
    Фильтр экономических событий.
    
    КРИТИЧЕСКИ ВАЖНЫЕ СОБЫТИЯ ДЛЯ КРИПТЫ:
    
    1. FOMC (Fed Meeting) — решение по ставке
       - Волатильность: EXTREME
       - Не торговать: за 2 часа до и 1 час после
    
    2. CPI (Inflation Data)
       - Волатильность: VERY HIGH
       - Не торговать: за 1 час до и 30 мин после
    
    3. NFP (Non-Farm Payrolls)
       - Волатильность: HIGH
       - Обычно в первую пятницу месяца
    
    4. Crypto-specific:
       - ETF решения
       - Крупные разлоки токенов
       - Халвинг BTC
    
    В эти моменты рынок — КАЗИНО. Никакой теханализ не работает.
    """
    
    def __init__(self):
        # Захардкоженное расписание основных событий
        # В реальности — подключить API экономического календаря
        self.scheduled_events = self._load_scheduled_events()
        
        # Время "опасной зоны" вокруг события (в минутах)
        self.danger_zones = {
            'HIGH': {'before': 120, 'after': 60},      # 2 часа до, 1 час после
            'MEDIUM': {'before': 60, 'after': 30},     # 1 час до, 30 мин после
            'LOW': {'before': 30, 'after': 15}
        }
    
    def check(self) -> NewsFilterResult:
        """
        Проверяет, безопасно ли сейчас торговать.
        
        Returns:
            NewsFilterResult с рекомендацией
        """
        now = datetime.utcnow()
        
        # Находим ближайшие события
        upcoming = self._get_upcoming_events(now, hours_ahead=24)
        
        # Проверяем, находимся ли мы в опасной зоне
        in_danger_zone = False
        nearest_high_impact = None
        hours_until = float('inf')
        risk_level = "SAFE"
        
        for event in upcoming:
            time_diff = (event.datetime - now).total_seconds() / 3600  # В часах
            
            # Находим ближайшее HIGH impact событие
            if event.impact == 'HIGH' and (nearest_high_impact is None or time_diff < hours_until):
                nearest_high_impact = event
                hours_until = time_diff
            
            # Проверяем опасную зону
            danger = self.danger_zones.get(event.impact, self.danger_zones['LOW'])
            
            minutes_until = time_diff * 60
            minutes_after = -minutes_until  # Отрицательное = событие прошло
            
            if 0 <= minutes_until <= danger['before']:
                in_danger_zone = True
                risk_level = "DANGER" if event.impact == 'HIGH' else "CAUTION"
            elif 0 <= minutes_after <= danger['after']:
                in_danger_zone = True
                risk_level = "CAUTION"
        
        # Формируем сообщение
        if in_danger_zone:
            msg = f"🚨 ОПАСНАЯ ЗОНА! Событие: {nearest_high_impact.name if nearest_high_impact else 'Unknown'}"
            can_trade = False
        elif hours_until < 4 and nearest_high_impact:
            msg = f"⚠️ Через {hours_until:.1f}ч: {nearest_high_impact.name}. Будь осторожен."
            can_trade = True
            risk_level = "CAUTION"
        else:
            msg = "✅ Нет важных событий в ближайшие часы."
            can_trade = True
        
        return NewsFilterResult(
            can_trade=can_trade,
            upcoming_events=upcoming,
            nearest_high_impact=nearest_high_impact,
            hours_until_event=hours_until if nearest_high_impact else float('inf'),
            risk_level=risk_level,
            message=msg
        )
    
    def _load_scheduled_events(self) -> List[EconomicEvent]:
        """
        Загружает расписание событий.
        
        В реальности здесь должен быть API календаря.
        Пока используем захардкоженные даты.
        """
        # Примерные даты на 2026 год (нужно обновлять!)
        events = []
        
        # FOMC Meetings 2026 (примерные даты)
        fomc_dates = [
            "2026-01-28", "2026-03-18", "2026-05-06", "2026-06-17",
            "2026-07-29", "2026-09-16", "2026-11-04", "2026-12-16"
        ]
        
        for date_str in fomc_dates:
            events.append(EconomicEvent(
                name="FOMC Interest Rate Decision",
                datetime=datetime.strptime(f"{date_str} 18:00", "%Y-%m-%d %H:%M"),
                impact="HIGH",
                currency="USD",
                forecast="",
                previous=""
            ))
        
        # CPI (обычно ~13-15 числа каждого месяца)
        for month in range(1, 13):
            # В реальности даты плавают, это пример
            events.append(EconomicEvent(
                name="US CPI (Inflation)",
                datetime=datetime(2026, month, 13, 12, 30),
                impact="HIGH",
                currency="USD",
                forecast="",
                previous=""
            ))
        
        return events
    
    def _get_upcoming_events(self, now: datetime, hours_ahead: int = 24) -> List[EconomicEvent]:
        """Возвращает события в ближайшие N часов."""
        cutoff = now + timedelta(hours=hours_ahead)
        
        upcoming = []
        for event in self.scheduled_events:
            if now - timedelta(hours=1) <= event.datetime <= cutoff:
                upcoming.append(event)
        
        # Сортируем по времени
        upcoming.sort(key=lambda x: x.datetime)
        
        return upcoming
    
    def add_custom_event(self, name: str, dt: datetime, impact: str = "HIGH"):
        """Добавляет кастомное событие (например, крипто-специфичное)."""
        self.scheduled_events.append(EconomicEvent(
            name=name,
            datetime=dt,
            impact=impact,
            currency="CRYPTO",
            forecast="",
            previous=""
        ))
    
    def get_calendar_report(self, days: int = 7) -> str:
        """Генерирует отчёт календаря на N дней."""
        now = datetime.utcnow()
        events = self._get_upcoming_events(now, hours_ahead=days * 24)
        
        report = f"""
╔══════════════════════════════════════════════════════════╗
║             ECONOMIC CALENDAR (Next {days} days)             ║
╠══════════════════════════════════════════════════════════╣"""
        
        if not events:
            report += "\n║  No major events scheduled                               ║"
        else:
            for event in events:
                impact_icon = "🔴" if event.impact == "HIGH" else "🟡" if event.impact == "MEDIUM" else "🟢"
                date_str = event.datetime.strftime("%b %d %H:%M UTC")
                report += f"\n║  {impact_icon} {date_str} - {event.name[:35]:<35} ║"
        
        report += """
╚══════════════════════════════════════════════════════════╝"""
        
        return report
