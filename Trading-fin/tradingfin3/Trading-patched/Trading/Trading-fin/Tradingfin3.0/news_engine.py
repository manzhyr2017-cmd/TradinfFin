"""
╔══════════════════════════════════════════════════════════════════╗
║                    NEWS ENGINE v2.0                              ║
║         Новостной фильтр + Sentiment Analysis                    ║
║                                                                  ║
║  Приоритет: 🔴 КРИТИЧНЫЙ                                        ║
║  API Sources:                                                    ║
║    - CryptoPanic (основной)                                     ║
║    - CoinGecko (дополнительный, бесплатный)                     ║
║    - Fallback: Fear & Greed Index                                ║
║  Функции:                                                        ║
║    - Sentiment scoring (-1.0 ... +1.0)                           ║
║    - Critical event detection (хаки, делистинги, SEC)           ║
║    - Market-wide fear detection                                  ║
║    - Confluence score contribution (+/- 10 баллов)              ║
╚══════════════════════════════════════════════════════════════════╝
"""

import time
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Попытка импорта requests (если недоступен — fallback)
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.warning("requests не установлен. NewsEngine работает в offline режиме.")


# ═══════════════════════════════════════════════════════════════
# КОНСТАНТЫ И КЛЮЧЕВЫЕ СЛОВА
# ═══════════════════════════════════════════════════════════════

# Критические события — НЕМЕДЛЕННАЯ блокировка торговли
CRITICAL_KEYWORDS = [
    "hack", "hacked", "exploit", "exploited", "stolen",
    "delist", "delisting", "delisted",
    "sec lawsuit", "sec charges", "sec sues",
    "rug pull", "rugpull", "exit scam",
    "bank run", "insolvency", "insolvent", "bankrupt", "bankruptcy",
    "shutdown", "shut down", "cease operations",
    "frozen", "freeze", "freezing assets",
    "ponzi", "fraud", "scam",
    "emergency", "critical vulnerability",
    "51% attack", "double spend",
]

# Негативные ключевые слова — понижение sentiment
NEGATIVE_KEYWORDS = [
    "crash", "dump", "plunge", "plummet", "selloff", "sell-off",
    "bear", "bearish", "decline", "drop", "fall", "falling",
    "regulation", "regulatory", "crackdown", "ban", "restrict",
    "lawsuit", "investigation", "probe", "subpoena",
    "warning", "caution", "risk", "concern", "worry",
    "layoff", "layoffs", "fired", "restructuring",
    "whale dump", "large transfer", "unlock", "token unlock",
    "fud", "fear", "panic", "capitulation",
]

# Позитивные ключевые слова — повышение sentiment
POSITIVE_KEYWORDS = [
    "bull", "bullish", "rally", "surge", "pump", "moon",
    "adoption", "partnership", "integration", "launch",
    "approval", "approved", "etf approved", "spot etf",
    "institutional", "investment", "funding", "raised",
    "upgrade", "mainnet", "milestone", "record", "ath",
    "growth", "growing", "expansion", "expanding",
    "profit", "revenue", "earnings", "positive",
]


@dataclass
class NewsSentiment:
    """Результат анализа новостного сентимента"""
    score: float = 0.0               # -1.0 (крайне негативно) ... +1.0 (крайне позитивно)
    critical_events: List[str] = field(default_factory=list)   # Список критических событий
    positive_count: int = 0
    negative_count: int = 0
    total_articles: int = 0
    fear_greed_index: int = 50       # 0=Extreme Fear ... 100=Extreme Greed
    confidence: float = 0.0           # 0.0-1.0, насколько уверены в оценке
    source: str = ""                  # Откуда данные
    timestamp: float = 0.0
    confluence_points: int = 0        # Баллы для confluence system (-10 ... +10)
    
    @property
    def is_critical(self) -> bool:
        return len(self.critical_events) > 0
    
    @property 
    def is_bearish(self) -> bool:
        return self.score < -0.3
    
    @property
    def is_bullish(self) -> bool:
        return self.score > 0.3
    
    @property
    def should_block_trading(self) -> bool:
        """Должна ли торговля быть заблокирована?"""
        return self.is_critical or self.score < -0.5 or self.fear_greed_index < 15


class NewsEngine:
    """
    Движок новостного анализа с несколькими источниками данных.
    
    Использование:
        news = NewsEngine(cryptopanic_key="your_key")
        sentiment = news.get_market_sentiment("BTC")
        
        if sentiment.should_block_trading:
            return None  # Не торгуем
    """

    def __init__(
        self,
        cryptopanic_key: Optional[str] = None,
        cache_ttl_seconds: int = 300,          # Кэш на 5 минут
        request_timeout: int = 10,              # Таймаут запроса
        max_articles: int = 50,                 # Макс. статей для анализа
    ):
        self.cryptopanic_key = cryptopanic_key
        self.cache_ttl = cache_ttl_seconds
        self.timeout = request_timeout
        self.max_articles = max_articles
        
        # Кэш результатов
        self._cache: Dict[str, Tuple[float, NewsSentiment]] = {}
        
        # Статистика
        self.total_requests = 0
        self.cache_hits = 0
        self.api_errors = 0
        
        # Fear & Greed кэш (общий для всех монет)
        self._fear_greed_cache: Optional[Tuple[float, int]] = None
        
        logger.info(
            f"NewsEngine инициализирован: "
            f"CryptoPanic={'✅' if cryptopanic_key else '❌'}, "
            f"cache_ttl={cache_ttl_seconds}s"
        )

    # ═══════════════════════════════════════════════════════════
    # ОСНОВНОЙ МЕТОД
    # ═══════════════════════════════════════════════════════════

    def get_market_sentiment(self, currency: str) -> NewsSentiment:
        """
        Получить sentiment для конкретной монеты.
        
        currency: символ монеты (BTC, ETH, SOL и т.д.)
        
        Возвращает NewsSentiment с оценкой и деталями.
        """
        currency = currency.upper().replace("USDT", "").replace("USD", "")
        
        # Проверка кэша
        cached = self._get_cached(currency)
        if cached:
            self.cache_hits += 1
            return cached
        
        self.total_requests += 1
        sentiment = NewsSentiment(timestamp=time.time(), source="combined")
        
        # 1. CryptoPanic API (основной источник)
        if self.cryptopanic_key and HAS_REQUESTS:
            cp_sentiment = self._fetch_cryptopanic(currency)
            if cp_sentiment:
                sentiment.score = cp_sentiment.score
                sentiment.critical_events = cp_sentiment.critical_events
                sentiment.positive_count = cp_sentiment.positive_count
                sentiment.negative_count = cp_sentiment.negative_count
                sentiment.total_articles = cp_sentiment.total_articles
                sentiment.confidence = cp_sentiment.confidence
                sentiment.source = "cryptopanic"
        
        # 2. Fear & Greed Index (дополнительный)
        if HAS_REQUESTS:
            fg_index = self._fetch_fear_greed()
            if fg_index is not None:
                sentiment.fear_greed_index = fg_index
                
                # Корректируем score на основе F&G
                fg_adjustment = (fg_index - 50) / 200  # -0.25 ... +0.25
                sentiment.score = sentiment.score * 0.7 + fg_adjustment * 0.3
        
        # 3. Если нет API — offline анализ
        if not sentiment.source:
            sentiment.source = "offline"
            sentiment.confidence = 0.1
            # В offline режиме нейтральный sentiment
            sentiment.score = 0.0
        
        # Рассчитываем confluence points
        sentiment.confluence_points = self._calc_confluence_points(sentiment)
        
        # Кэшируем
        self._set_cached(currency, sentiment)
        
        logger.info(
            f"📰 {currency} Sentiment: score={sentiment.score:+.2f}, "
            f"FG={sentiment.fear_greed_index}, "
            f"critical={len(sentiment.critical_events)}, "
            f"confluence={sentiment.confluence_points:+d}"
        )
        
        return sentiment

    def get_market_wide_sentiment(self) -> NewsSentiment:
        """Общий рыночный sentiment (BTC + ETH + общие новости)"""
        btc = self.get_market_sentiment("BTC")
        eth = self.get_market_sentiment("ETH")
        
        combined = NewsSentiment(
            score=(btc.score * 0.6 + eth.score * 0.4),
            critical_events=btc.critical_events + eth.critical_events,
            positive_count=btc.positive_count + eth.positive_count,
            negative_count=btc.negative_count + eth.negative_count,
            total_articles=btc.total_articles + eth.total_articles,
            fear_greed_index=btc.fear_greed_index,  # Общий для рынка
            confidence=max(btc.confidence, eth.confidence),
            source="market_wide",
            timestamp=time.time(),
        )
        combined.confluence_points = self._calc_confluence_points(combined)
        
        return combined

    # ═══════════════════════════════════════════════════════════
    # CRYPTOPANIC API
    # ═══════════════════════════════════════════════════════════

    def _fetch_cryptopanic(self, currency: str) -> Optional[NewsSentiment]:
        """Получение новостей через CryptoPanic API"""
        if not HAS_REQUESTS:
            return None
            
        try:
            url = "https://cryptopanic.com/api/v1/posts/"
            params = {
                "auth_token": self.cryptopanic_key,
                "currencies": currency,
                "filter": "hot",  # Только горячие новости
                "public": "true",
            }
            
            response = requests.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 429:
                logger.warning("CryptoPanic rate limited")
                return None
            
            response.raise_for_status()
            data = response.json()
            
            articles = data.get("results", [])[:self.max_articles]
            
            if not articles:
                return NewsSentiment(confidence=0.2)
            
            return self._analyze_articles(articles, currency)
            
        except requests.exceptions.Timeout:
            logger.warning("CryptoPanic request timed out")
            self.api_errors += 1
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"CryptoPanic error: {e}")
            self.api_errors += 1
            return None
        except Exception as e:
            logger.error(f"CryptoPanic unexpected error: {e}")
            self.api_errors += 1
            return None

    def _analyze_articles(self, articles: list, currency: str) -> NewsSentiment:
        """Анализ массива статей из CryptoPanic"""
        sentiment = NewsSentiment(
            total_articles=len(articles),
            timestamp=time.time(),
            source="cryptopanic",
        )
        
        total_score = 0.0
        
        for article in articles:
            title = article.get("title", "").lower()
            
            # Проверка на критические события
            for keyword in CRITICAL_KEYWORDS:
                if keyword in title:
                    sentiment.critical_events.append(
                        f"[{keyword.upper()}] {article.get('title', 'Unknown')}"
                    )
                    total_score -= 2.0
                    break
            
            # CryptoPanic встроенный sentiment
            votes = article.get("votes", {})
            cp_positive = votes.get("positive", 0)
            cp_negative = votes.get("negative", 0)
            
            if cp_positive > cp_negative:
                total_score += 0.5
                sentiment.positive_count += 1
            elif cp_negative > cp_positive:
                total_score -= 0.5
                sentiment.negative_count += 1
            
            # Дополнительный keyword-based анализ
            neg_hits = sum(1 for kw in NEGATIVE_KEYWORDS if kw in title)
            pos_hits = sum(1 for kw in POSITIVE_KEYWORDS if kw in title)
            
            total_score += pos_hits * 0.3
            total_score -= neg_hits * 0.3
            sentiment.positive_count += pos_hits
            sentiment.negative_count += neg_hits
        
        # Нормализация score в диапазон [-1, 1]
        if len(articles) > 0:
            avg_score = total_score / len(articles)
            sentiment.score = max(-1.0, min(1.0, avg_score))
        
        # Уверенность основана на количестве статей
        sentiment.confidence = min(1.0, len(articles) / 20)
        
        return sentiment

    # ═══════════════════════════════════════════════════════════
    # FEAR & GREED INDEX
    # ═══════════════════════════════════════════════════════════

    def _fetch_fear_greed(self) -> Optional[int]:
        """Получение Fear & Greed Index"""
        # Проверка кэша (обновляем раз в 30 минут)
        if self._fear_greed_cache:
            cache_time, value = self._fear_greed_cache
            if time.time() - cache_time < 1800:  # 30 минут
                return value
        
        if not HAS_REQUESTS:
            return None
        
        try:
            url = "https://api.alternative.me/fng/?limit=1"
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            
            value = int(data["data"][0]["value"])
            self._fear_greed_cache = (time.time(), value)
            
            logger.debug(f"Fear & Greed Index: {value} ({data['data'][0].get('value_classification', '')})")
            return value
            
        except Exception as e:
            logger.warning(f"Fear & Greed fetch error: {e}")
            self.api_errors += 1
            return None

    # ═══════════════════════════════════════════════════════════
    # CONFLUENCE SCORING
    # ═══════════════════════════════════════════════════════════

    def _calc_confluence_points(self, sentiment: NewsSentiment) -> int:
        """
        Рассчёт баллов для confluence system.
        
        Диапазон: -10 ... +10
        
        Логика:
          score < -0.5  → -10 (сильно негативный)
          score < -0.3  → -5
          score < -0.1  → -2
          score 0 ± 0.1 → 0 (нейтральный)
          score > 0.1   → +2
          score > 0.3   → +5
          score > 0.5   → +10 (сильно позитивный)
          
          Fear & Greed < 20 → дополнительно -3
          Fear & Greed > 80 → дополнительно +3
        """
        points = 0
        
        # Основной score
        if sentiment.score < -0.5:
            points = -10
        elif sentiment.score < -0.3:
            points = -5
        elif sentiment.score < -0.1:
            points = -2
        elif sentiment.score > 0.5:
            points = 10
        elif sentiment.score > 0.3:
            points = 5
        elif sentiment.score > 0.1:
            points = 2
        
        # Fear & Greed корректировка
        if sentiment.fear_greed_index < 20:
            points -= 3
        elif sentiment.fear_greed_index > 80:
            points += 3
        
        # Критические события = максимальный негатив
        if sentiment.critical_events:
            points = -10
        
        # Clamp
        return max(-10, min(10, points))

    # ═══════════════════════════════════════════════════════════
    # КЭШИРОВАНИЕ
    # ═══════════════════════════════════════════════════════════

    def _get_cached(self, key: str) -> Optional[NewsSentiment]:
        if key in self._cache:
            cache_time, sentiment = self._cache[key]
            if time.time() - cache_time < self.cache_ttl:
                return sentiment
            del self._cache[key]
        return None

    def _set_cached(self, key: str, sentiment: NewsSentiment):
        self._cache[key] = (time.time(), sentiment)

    def clear_cache(self):
        """Очистка кэша"""
        self._cache.clear()
        self._fear_greed_cache = None

    # ═══════════════════════════════════════════════════════════
    # ОТЧЁТНОСТЬ
    # ═══════════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        return {
            "total_requests": self.total_requests,
            "cache_hits": self.cache_hits,
            "api_errors": self.api_errors,
            "cache_hit_rate": (self.cache_hits / max(1, self.total_requests + self.cache_hits)) * 100,
        }


# ═══════════════════════════════════════════════════════════════
# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Без API ключа — offline mode
    news = NewsEngine()
    
    sentiment = news.get_market_sentiment("BTC")
    print(f"BTC Sentiment: {sentiment.score:+.2f}")
    print(f"Should block: {sentiment.should_block_trading}")
    print(f"Confluence points: {sentiment.confluence_points:+d}")
    
    # С API ключом:
    # news = NewsEngine(cryptopanic_key="YOUR_FREE_KEY")
    # sentiment = news.get_market_sentiment("BTC")
