"""
TITAN BOT 2026 - Fear & Greed Index
Торгуй против толпы!
"""

import requests
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import config

@dataclass
class FearGreedAnalysis:
    """Результат анализа Fear & Greed"""
    value: int                    # 0-100
    classification: str           # 'Extreme Fear', 'Fear', 'Neutral', 'Greed', 'Extreme Greed'
    previous_value: int
    change: int
    trend: str                    # 'IMPROVING', 'WORSENING', 'STABLE'
    contrarian_signal: str        # 'BUY', 'SELL', 'NEUTRAL'
    description: str


class FearGreedAnalyzer:
    """
    Анализатор Fear & Greed Index.
    
    ПОЧЕМУ ЭТО РАБОТАЕТ:
    
    "Be fearful when others are greedy, be greedy when others are fearful"
    — Warren Buffett
    
    ЛОГИКА:
    
    ┌─────────────────┬────────────┬─────────────────────────────────┐
    │ Значение        │ Состояние  │ Действие                        │
    ├─────────────────┼────────────┼─────────────────────────────────┤
    │ 0-20            │ Экстр.страх│ 🟢 ПОКУПАЙ! Все продали         │
    │ 20-40           │ Страх      │ 🟡 Осторожно покупай            │
    │ 40-60           │ Нейтрально │ ➖ Жди сигнала                  │
    │ 60-80           │ Жадность   │ 🟡 Осторожно продавай           │
    │ 80-100          │ Экстр.жадн.│ 🔴 ПРОДАВАЙ! Все купили         │
    └─────────────────┴────────────┴─────────────────────────────────┘
    
    ВАЖНО: Это НЕ timing-инструмент. Это ФИЛЬТР.
    - Не лонгуй при Extreme Greed
    - Не шорти при Extreme Fear
    """
    
    def __init__(self):
        self.api_url = "https://api.alternative.me/fng/"
        self.history = []
    
    def analyze(self) -> FearGreedAnalysis:
        """Получает и анализирует текущий индекс."""
        
        current = self._fetch_current()
        previous = self._fetch_previous()
        
        if current is None:
            return self._empty_analysis()
        
        value = current['value']
        classification = current['classification']
        
        prev_value = previous['value'] if previous else value
        change = value - prev_value
        
        # Тренд
        if change > 5:
            trend = "IMPROVING"  # Становится жаднее (рынок растёт)
        elif change < -5:
            trend = "WORSENING"  # Становится страшнее (рынок падает)
        else:
            trend = "STABLE"
        
        # Контрарный сигнал
        contrarian = self._get_contrarian_signal(value)
        
        # Описание
        description = self._generate_description(value, classification, contrarian)
        
        return FearGreedAnalysis(
            value=value,
            classification=classification,
            previous_value=prev_value,
            change=change,
            trend=trend,
            contrarian_signal=contrarian,
            description=description
        )
    
    def _fetch_current(self) -> Optional[dict]:
        """Получает текущее значение индекса."""
        try:
            # Added timeout for better error handling
            response = requests.get(self.api_url, params={'limit': 1}, timeout=10)
            data = response.json()
            
            if data.get('data'):
                item = data['data'][0]
                return {
                    'value': int(item['value']),
                    'classification': item['value_classification'],
                    'timestamp': datetime.fromtimestamp(int(item['timestamp']))
                }
        except Exception as e:
            print(f"[FearGreed] Error fetching data: {e}")
        
        return None
    
    def _fetch_previous(self) -> Optional[dict]:
        """Получает вчерашнее значение."""
        try:
            response = requests.get(self.api_url, params={'limit': 2}, timeout=10)
            data = response.json()
            
            if data.get('data') and len(data['data']) > 1:
                item = data['data'][1]
                return {
                    'value': int(item['value']),
                    'classification': item['value_classification']
                }
        except:
            pass
        
        return None
    
    def _get_contrarian_signal(self, value: int) -> str:
        """Генерирует контрарный сигнал."""
        
        if value <= 20:
            return "STRONG_BUY"  # Extreme Fear = покупай
        elif value <= 35:
            return "BUY"
        elif value >= 80:
            return "STRONG_SELL"  # Extreme Greed = продавай
        elif value >= 65:
            return "SELL"
        else:
            return "NEUTRAL"
    
    def _generate_description(self, value: int, classification: str, signal: str) -> str:
        """Генерирует описание."""
        
        emoji_map = {
            'Extreme Fear': '😱',
            'Fear': '😰',
            'Neutral': '😐',
            'Greed': '🤑',
            'Extreme Greed': '🚀'
        }
        
        emoji = emoji_map.get(classification, '❓')
        
        if signal == "STRONG_BUY":
            action = "ИДЕАЛЬНОЕ время для покупок! Толпа в панике."
        elif signal == "BUY":
            action = "Хорошее время для покупок. Рынок испуган."
        elif signal == "STRONG_SELL":
            action = "ОПАСНО покупать! Толпа эйфорична. Жди коррекцию."
        elif signal == "SELL":
            action = "Осторожно с покупками. Рынок перегрет."
        else:
            action = "Нейтральное настроение. Смотри на другие индикаторы."
        
        return f"{emoji} Fear & Greed: {value} ({classification}). {action}"
    
    def _empty_analysis(self) -> FearGreedAnalysis:
        """Пустой анализ."""
        return FearGreedAnalysis(
            value=50,
            classification="Unknown",
            previous_value=50,
            change=0,
            trend="UNKNOWN",
            contrarian_signal="NEUTRAL",
            description="Не удалось получить Fear & Greed Index"
        )
    
    def should_avoid_longs(self) -> bool:
        """Проверяет, опасно ли сейчас лонговать."""
        analysis = self.analyze()
        return analysis.value >= 75
    
    def should_avoid_shorts(self) -> bool:
        """Проверяет, опасно ли сейчас шортить."""
        analysis = self.analyze()
        return analysis.value <= 25
