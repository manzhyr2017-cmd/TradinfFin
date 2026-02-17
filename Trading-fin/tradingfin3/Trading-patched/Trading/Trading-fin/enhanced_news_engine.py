"""
╔══════════════════════════════════════════════════════════════════════╗
║          ENHANCED NEWS ENGINE v2.0                                   ║
║     Drop-in замена NewsEngine из mean_reversion_bybit.py             ║
║                                                                      ║
║  Улучшения:                                                         ║
║    + Fear & Greed Index (дополнительный источник)                    ║
║    + Кэширование с TTL (избежание rate limit)                       ║
║    + Critical Event Detector (расширенный)                          ║
║    + Confluence integration (±10 баллов)                            ║
║    + Market-wide sentiment                                          ║
║    + Graceful fallback (работает без API ключа)                     ║
║                                                                      ║
║  Совместим с UltimateTradingEngine.analyze()                        ║
║                                                                      ║
║  Приоритет: 🔴 КРИТИЧНЫЙ                                            ║
╚══════════════════════════════════════════════════════════════════════╝

ИНТЕГРАЦИЯ:
    # В mean_reversion_bybit.py заменить существующий NewsEngine:
    from enhanced_news_engine import EnhancedNewsEngine
    
    # В UltimateTradingEngine.__init__:
    self.news_engine = EnhancedNewsEngine(
        cryptopanic_key=os.getenv('CRYPTOPANIC_KEY'),
        cache_ttl=300
    )
    
    # Всё остальное API совместимо — get_market_sentiment() работает так же
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class NewsSentiment:
    """Результат анализа новостей"""
    score: float = 0.0                    # -1.0 (bearish) .. +1.0 (bullish)
    news_count: int = 0
    critical_events: List[str] = None
    sentiment_label: str = "Neutral"
    fear_greed_index: int = 50            # 0=Extreme Fear .. 100=Extreme Greed
    fear_greed_label: str = "Neutral"
    confluence_points: int = 0            # -10 .. +10 для confluence system
    should_block_trading: bool = False
    source: str = "none"

    def __post_init__(self):
        if self.critical_events is None:
            self.critical_events = []


# ═══════════════════════════════════════════════════════════════
# ENHANCED NEWS ENGINE
# ═══════════════════════════════════════════════════════════════

class EnhancedNewsEngine:
    """
    Улучшенный движок новостей. Drop-in замена для NewsEngine.
    
    API совместимость:
        - get_market_sentiment(currency) → dict (как старый)
        - _is_critical_event(text) → bool (как старый)
        - _analyze_text(text) → float (как старый)
    
    Новые методы:
        - get_enhanced_sentiment(currency) → NewsSentiment
        - get_fear_greed() → dict
        - get_market_wide_sentiment() → NewsSentiment
    """

    # Расширенные критические keywords
    CRITICAL_KEYWORDS = [
        # Хаки и эксплоиты
        'hack', 'hacked', 'exploit', 'vulnerability', 'breach', 'stolen',
        'compromised', 'drained', 'flash loan', 'reentrancy',
        # Делистинг и приостановка
        'delist', 'delisting', 'suspend', 'suspended', 'halt', 'halted',
        'withdrawal disabled', 'deposits paused',
        # Регулирование
        'sec', 'lawsuit', 'fraud', 'investigation', 'subpoena',
        'regulation', 'banned', 'illegal', 'enforcement',
        # Банкротство
        'bankruptcy', 'insolvent', 'collapse', 'liquidation', 'default',
        # Другое критичное
        'rug pull', 'scam', 'ponzi', 'exit scam', 'emergency', 'critical',
    ]

    POSITIVE_KEYWORDS = [
        'bull', 'bullish', 'pump', 'surge', 'rally', 'profit', 'buy',
        'growth', 'listing', 'launch', 'partnership', 'adoption',
        'upgrade', 'milestone', 'record', 'breakout', 'institutional',
        'etf', 'approval', 'integration',
    ]

    NEGATIVE_KEYWORDS = [
        'bear', 'bearish', 'dump', 'crash', 'fall', 'loss', 'sell',
        'scam', 'drop', 'decline', 'plunge', 'slump', 'correction',
        'fear', 'panic', 'warning', 'risk', 'concern', 'uncertainty',
    ]

    def __init__(
        self,
        cryptopanic_key: Optional[str] = None,
        cache_ttl: int = 300,               # 5 минут кэш
        use_finbert: bool = False,           # Совместимость (игнорируем)
    ):
        self.api_key = cryptopanic_key or ""
        self.base_url = "https://cryptopanic.com/api/v1"
        self.cache: Dict[str, dict] = {}
        self.cache_ttl = cache_ttl
        self.use_finbert = False             # FinBERT отключён (слишком тяжёлый)
        self.sentiment_model = None

        # Статистика
        self._total_requests = 0
        self._cache_hits = 0
        self._errors = 0

        if self.api_key:
            logger.info("✅ EnhancedNewsEngine: CryptoPanic key configured")
        else:
            logger.info("ℹ️  EnhancedNewsEngine: No API key (offline mode)")

    # ═══════════════════════════════════════════════════════════
    # ГЛАВНЫЙ МЕТОД (совместимость со старым API)
    # ═══════════════════════════════════════════════════════════

    def get_market_sentiment(self, currency: str) -> Dict[str, Any]:
        """
        Совместимость с существующим NewsEngine.get_market_sentiment()
        
        Returns: dict с полями score, news_count, critical_events, sentiment_label
        """
        result = self.get_enhanced_sentiment(currency)
        return {
            'score': result.score,
            'news_count': result.news_count,
            'critical_events': result.critical_events,
            'sentiment_label': result.sentiment_label,
            'fear_greed_index': result.fear_greed_index,
            'confluence_points': result.confluence_points,
            'should_block_trading': result.should_block_trading,
        }

    # ═══════════════════════════════════════════════════════════
    # РАСШИРЕННЫЙ АНАЛИЗ
    # ═══════════════════════════════════════════════════════════

    def get_enhanced_sentiment(self, currency: str) -> NewsSentiment:
        """
        Полный анализ с кэшированием.
        
        Объединяет:
        1. CryptoPanic (новости по монете)
        2. Fear & Greed Index (общий рынок)
        """
        self._total_requests += 1

        # Проверяем кэш
        cache_key = f"sentiment_{currency.upper()}"
        cached = self._get_cache(cache_key)
        if cached:
            self._cache_hits += 1
            return cached

        result = NewsSentiment()

        # 1. CryptoPanic
        if self.api_key and HAS_REQUESTS:
            cp_result = self._fetch_cryptopanic(currency)
            result.score = cp_result.get('score', 0.0)
            result.news_count = cp_result.get('news_count', 0)
            result.critical_events = cp_result.get('critical_events', [])
            result.source = "cryptopanic"

        # 2. Fear & Greed Index
        if HAS_REQUESTS:
            fg = self._fetch_fear_greed()
            result.fear_greed_index = fg.get('value', 50)
            result.fear_greed_label = fg.get('label', 'Neutral')

        # 3. Расчёт confluence points и block decision
        result.confluence_points = self._calc_confluence_points(result)
        result.should_block_trading = self._should_block(result)
        result.sentiment_label = self._label_sentiment(result.score)

        # Кэшируем
        self._set_cache(cache_key, result)

        return result

    def get_market_wide_sentiment(self) -> NewsSentiment:
        """Общее настроение рынка (без привязки к монете)"""
        return self.get_enhanced_sentiment("BTC")  # BTC = proxy для рынка

    # ═══════════════════════════════════════════════════════════
    # ИСТОЧНИКИ ДАННЫХ
    # ═══════════════════════════════════════════════════════════

    def _fetch_cryptopanic(self, currency: str) -> dict:
        """Получает новости из CryptoPanic"""
        try:
            url = f"{self.base_url}/posts/"
            params = {
                'auth_token': self.api_key,
                'currencies': currency.upper(),
                'kind': 'news',
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
            }

            response = requests.get(url, params=params, headers=headers, timeout=10)

            if response.status_code == 404:
                return {'score': 0.0, 'news_count': 0, 'critical_events': []}

            if response.status_code != 200:
                logger.warning(f"CryptoPanic HTTP {response.status_code}")
                return {'score': 0.0, 'news_count': 0, 'critical_events': []}

            if not response.text.strip():
                return {'score': 0.0, 'news_count': 0, 'critical_events': []}

            data = response.json()
            news = data.get('results', [])[:20]

            sentiments = []
            critical_events = []

            for item in news:
                title = item.get('title', '')

                if self._is_critical_event(title):
                    critical_events.append(title[:100])

                score = self._analyze_text(title)
                sentiments.append(score)

            avg_score = sum(sentiments) / len(sentiments) if sentiments else 0.0

            return {
                'score': float(avg_score),
                'news_count': len(news),
                'critical_events': critical_events,
            }

        except requests.exceptions.Timeout:
            logger.warning("CryptoPanic timeout")
        except Exception as e:
            self._errors += 1
            logger.error(f"CryptoPanic error: {e}")

        return {'score': 0.0, 'news_count': 0, 'critical_events': []}

    def _fetch_fear_greed(self) -> dict:
        """Fear & Greed Index от alternative.me"""
        cache_key = "fear_greed_global"
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        try:
            response = requests.get(
                "https://api.alternative.me/fng/?limit=1",
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                item = data.get('data', [{}])[0]
                result = {
                    'value': int(item.get('value', 50)),
                    'label': item.get('value_classification', 'Neutral'),
                }
                self._set_cache(cache_key, result)
                return result
        except Exception as e:
            logger.debug(f"Fear & Greed unavailable: {e}")

        return {'value': 50, 'label': 'Neutral'}

    # ═══════════════════════════════════════════════════════════
    # АНАЛИЗ ТЕКСТА (совместимость + расширение)
    # ═══════════════════════════════════════════════════════════

    def _is_critical_event(self, text: str) -> bool:
        """Совместимость с оригинальным _is_critical_event()"""
        text_lower = text.lower()
        return any(kw in text_lower for kw in self.CRITICAL_KEYWORDS)

    def _analyze_text(self, text: str) -> float:
        """Совместимость с оригинальным _analyze_text()"""
        text_lower = text.lower()

        pos = sum(1 for w in self.POSITIVE_KEYWORDS if w in text_lower)
        neg = sum(1 for w in self.NEGATIVE_KEYWORDS if w in text_lower)

        total = pos + neg
        if total == 0:
            return 0.0

        return (pos - neg) / total

    # ═══════════════════════════════════════════════════════════
    # ЛОГИКА РЕШЕНИЙ
    # ═══════════════════════════════════════════════════════════

    def _calc_confluence_points(self, sentiment: NewsSentiment) -> int:
        """
        Рассчитывает очки для confluence system.
        
        -10 (крайне негативный) ... 0 (нейтральный) ... +10 (крайне позитивный)
        """
        points = 0

        # Новостной score (-5 .. +5)
        if sentiment.score > 0.5:
            points += 5
        elif sentiment.score > 0.2:
            points += 3
        elif sentiment.score < -0.5:
            points -= 5
        elif sentiment.score < -0.2:
            points -= 3

        # Fear & Greed (-5 .. +5)
        fg = sentiment.fear_greed_index
        if fg >= 75:        # Extreme Greed → осторожно для LONG
            points -= 2     # Против толпы
        elif fg >= 55:      # Greed
            points += 2
        elif fg <= 25:      # Extreme Fear → хорошо для LONG
            points += 5     # Против толпы (mean reversion!)
        elif fg <= 40:      # Fear
            points += 3

        # Critical events override
        if sentiment.critical_events:
            points = -10

        return max(-10, min(10, points))

    def _should_block(self, sentiment: NewsSentiment) -> bool:
        """Нужно ли блокировать торговлю?"""
        # Критические события → СТОП
        if sentiment.critical_events:
            return True

        # Extreme negative sentiment
        if sentiment.score < -0.6:
            return True

        # Extreme Fear + negative news → СТОП
        if sentiment.fear_greed_index < 15 and sentiment.score < -0.3:
            return True

        return False

    def _label_sentiment(self, score: float) -> str:
        if score > 0.3:
            return "Bullish"
        elif score < -0.3:
            return "Bearish"
        return "Neutral"

    # ═══════════════════════════════════════════════════════════
    # КЭШИРОВАНИЕ
    # ═══════════════════════════════════════════════════════════

    def _get_cache(self, key: str):
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry['ts'] < self.cache_ttl:
                return entry['data']
            del self.cache[key]
        return None

    def _set_cache(self, key: str, data):
        self.cache[key] = {'data': data, 'ts': time.time()}

    # ═══════════════════════════════════════════════════════════
    # СТАТИСТИКА
    # ═══════════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        return {
            'total_requests': self._total_requests,
            'cache_hits': self._cache_hits,
            'cache_hit_rate': (self._cache_hits / max(1, self._total_requests)) * 100,
            'errors': self._errors,
            'has_api_key': bool(self.api_key),
        }
