import logging
import requests
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("SentimentAnalyzer")

@dataclass
class SentimentResult:
    fear_greed_value: int
    sentiment_label: str # "Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed"
    overall_score: float # 0 to 1

class SentimentAnalyzer:
    """
    Анализатор рыночных настроений.
    Использует API Fear & Greed Index и эмуляцию анализа соцсетей.
    """
    
    def __init__(self):
        self.api_url = "https://api.alternative.me/fng/"
        
    def get_sentiment(self) -> Optional[SentimentResult]:
        """Получает текущий индекс страха и жадности."""
        try:
            # Пытаемся получить реальный индекс за последние 24ч
            response = requests.get(self.api_url, timeout=5)
            data = response.json()
            
            if data and 'data' in data:
                val = int(data['data'][0]['value'])
                classification = data['data'][0]['value_classification']
                
                return SentimentResult(
                    fear_greed_value=val,
                    sentiment_label=classification,
                    overall_score=val / 100.0
                )
        except Exception as e:
            log.error(f"Error fetching sentiment: {e}")
            
        # Дефолтные значения при ошибке
        return SentimentResult(50, "Neutral", 0.5)

    def analyze_social_momentum(self) -> float:
        """
        Заглушка для анализа хайпа в Twitter/Telegram.
        В реальности здесь был бы скрапинг или подключение к Lunarcrush/Santiment.
        """
        return 0.5 # Neutral
