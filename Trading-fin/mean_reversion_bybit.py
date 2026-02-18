"""
Advanced Mean Reversion Engine v2.0 - Bybit Edition
====================================================
Цель: 85%+ Win Rate через Multi-Factor Confluence

ИНТЕГРАЦИЯ С BYBIT:
+ Funding Rate анализ (экстремумы = разворот)
+ Open Interest анализ
+ Order Book Imbalance

CONFLUENCE FACTORS (100 баллов максимум):
1. RSI экстремумы (0-25)
2. Bollinger Bands position (0-15)
3. Multi-Timeframe alignment (0-25)
4. Support/Resistance proximity (0-15)
5. Volume spike (0-10)
6. MACD divergence (0-10)
7. Funding Rate (0-10) - НОВОЕ
8. Order Book Imbalance (0-5) - НОВОЕ
9. Additional oscillators (0-10)

Минимальный score для входа: 70/100
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
from datetime import datetime, timedelta
import logging
import requests
import json
import os
from collections import deque

# Import config (added for Titan Bot modes)
try:
    import config
except ImportError:
    config = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# ENUMS & DATA CLASSES
# ============================================================

class SignalType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_SIGNAL = "NO_SIGNAL"


class SignalStrength(Enum):
    WEAK = "WEAK"           # 60-70% probability
    MODERATE = "MODERATE"   # 70-80% probability  
    STRONG = "STRONG"       # 80-85% probability
    EXTREME = "EXTREME"     # 85%+ probability


class MarketRegime(Enum):
    STRONG_TREND_UP = "STRONG_TREND_UP"
    WEAK_TREND_UP = "WEAK_TREND_UP"
    RANGING_NARROW = "RANGING_NARROW"
    RANGING_WIDE = "RANGING_WIDE"
    WEAK_TREND_DOWN = "WEAK_TREND_DOWN"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    VOLATILE_CHAOS = "VOLATILE_CHAOS"
    NEUTRAL = "NEUTRAL"


@dataclass
class SupportResistanceLevel:
    price: float
    strength: int
    level_type: str  # 'support' или 'resistance'
    timeframe: str
    last_touch: datetime


class StrategyType(Enum):
    MEAN_REVERSION = "MEAN_REVERSION"
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    GRID = "GRID"
    SCALPING = "SCALPING"


@dataclass
class Trade:
    """Trade record для Performance Tracker"""
    entry_time: datetime
    exit_time: Optional[datetime] = None
    symbol: str = ""
    strategy: StrategyType = StrategyType.MEAN_REVERSION
    signal_type: SignalType = SignalType.LONG
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    confluence_score: float = 0.0
    is_winner: bool = False
    exit_reason: str = ""


@dataclass
class ConfluenceScore:
    """
    Enhanced Confluence Score System v2.0
    max_possible = 145 (was 100/135)
    
    Breakdown:
    - RSI:          0-25    | Основной осциллятор
    - BB:           0-15    | Bollinger Bands position
    - MTF:          0-25    | Multi-timeframe alignment
    - S/R:          0-15    | Support/Resistance proximity
    - Volume:       0-10    | Volume spike confirmation
    - MACD:         0-10    | MACD divergence/convergence
    - Funding:      0-10    | Bybit funding rate
    - OrderBook:    0-5     | Order book imbalance
    - Oscillators:  0-10    | Extra (Williams %R, CCI, etc)
    - Fibonacci:    0-15    | Fib level proximity (БОНУС)
    - Supertrend:   0-10    | Trend confirmation (БОНУС)
    - News:         0-10    | News sentiment (НОВЫЙ!)
    ─────────────────────────────────────
    ИТОГО:        0-145   ← ПРАВИЛЬНЫЙ МАКСИМУМ!
    """
    total_score: int = 0
    max_possible: int = 145  # ИСПРАВЛЕНО! Было 100/135!
    
    # Детализация по факторам
    rsi_score: int = 0
    bb_score: int = 0
    mtf_score: int = 0
    sr_score: int = 0
    volume_score: int = 0
    macd_score: int = 0
    funding_score: int = 0
    orderbook_score: int = 0
    oscillators_score: int = 0
    fibonacci_score: int = 0  # БОНУС
    supertrend_score: int = 0  # БОНУС
    news_score: int = 0  # НОВЫЙ!
    
    factors: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    
    def add_factor(self, name: str, score: int, max_score: int):
        self.factors[name] = (score, max_score)
        self.total_score += score
        
        # Map names to fields for breakdown
        if 'RSI' in name: self.rsi_score = score
        elif 'Bollinger' in name: self.bb_score = score
        elif 'Timeframe' in name: self.mtf_score = score
        elif 'Support' in name: self.sr_score = score
        elif 'Volume' in name: self.volume_score = score
        elif 'MACD' in name: self.macd_score = score
        elif 'Funding' in name: self.funding_score = score
        elif 'Order' in name: self.orderbook_score = score
        elif 'Oscillators' in name: self.oscillators_score = score
        elif 'Fibonacci' in name: self.fibonacci_score = score
        elif 'Supertrend' in name: self.supertrend_score = score
        elif 'News' in name: self.news_score = score
    
    def recalculate_total(self):
        """Пересчёт total_score из компонентов"""
        self.total_score = (
            self.rsi_score + self.bb_score + self.mtf_score +
            self.sr_score + self.volume_score + self.macd_score +
            self.funding_score + self.orderbook_score + self.oscillators_score +
            self.fibonacci_score + self.supertrend_score + self.news_score
        )
    
    @property
    def percentage(self) -> float:
        return (self.total_score / self.max_possible) * 100 if self.max_possible > 0 else 0
    
    def get_strength(self) -> SignalStrength:
        if config and hasattr(config, "TRADE_MODE"):
            # Dynamic thresholds based on config
            pct = self.total_score # Use raw score if user config uses raw score, but user config has thresholds like 40, 25, 15 which are low for pct.
            # User config says: COMPOSITE_STRONG_THRESHOLD = 40. 
            # Original code used percentage.
            # Convert config thresholds to percentage if needed, OR use total_score.
            # The user's config comments say "Было 60, снижаем". 60/145 is ~41%.
            # "COMPOSITE_STRONG_THRESHOLD = 40". 40/145 is ~27%.
            # Let's assume user thresholds are RAW SCORES because max_possible is 145.
            
            score = self.total_score
            
            if score >= getattr(config, 'COMPOSITE_STRONG_THRESHOLD', 40):
                return SignalStrength.EXTREME # Or STRONG? User says "STRONG_THRESHOLD = 40"
            elif score >= getattr(config, 'COMPOSITE_MODERATE_THRESHOLD', 25):
                return SignalStrength.STRONG # Mapping moderate threshold to strong signal for aggressive?
            elif score >= getattr(config, 'COMPOSITE_WEAK_THRESHOLD', 15):
                return SignalStrength.MODERATE
            elif score >= getattr(config, 'COMPOSITE_MIN_FOR_ENTRY', 10):
                return SignalStrength.WEAK
            else:
                return SignalStrength.WEAK # Fallback
        else:
            # Fallback to original percentage based logic
            pct = self.percentage
            if pct >= 80:
                return SignalStrength.EXTREME
            elif pct >= 65:
                return SignalStrength.STRONG
            elif pct >= 50:
                return SignalStrength.MODERATE
            elif pct >= 35:
                return SignalStrength.WEAK
            else:
                return SignalStrength.WEAK
    
    def get_breakdown(self) -> str:
        """Возвращает детальную разбивку по факторам"""
        return (
            f"RSI:{self.rsi_score}/25 | BB:{self.bb_score}/15 | "
            f"MTF:{self.mtf_score}/25 | S/R:{self.sr_score}/15 | "
            f"Vol:{self.volume_score}/10 | MACD:{self.macd_score}/10 | "
            f"Fund:{self.funding_score}/10 | OB:{self.orderbook_score}/5 | "
            f"Osc:{self.oscillators_score}/10 | Fib:{self.fibonacci_score}/15 | "
            f"ST:{self.supertrend_score}/10 | News:{self.news_score}/10 | "
            f"TOTAL: {self.total_score}/{self.max_possible} ({self.percentage:.1f}%) [{self.get_strength().value}]"
        )


# ============================================================
# ULTIMATE MODULES
# ============================================================

# ============================================================
# ENHANCED NEWS ENGINE v2.0
# ============================================================

import time
from dataclasses import dataclass, field


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

    def __init__(
        self,
        cryptopanic_key: Optional[str] = None,
        cache_ttl_seconds: int = 300,          # Кэш на 5 минут
        request_timeout: int = 10,              # Таймаут запроса
        max_articles: int = 50,                 # Макс. статей для анализа
        use_finbert: bool = False,              # Совместимость
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
        if self.cryptopanic_key:
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
            for keyword in self.CRITICAL_KEYWORDS:
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
            neg_hits = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in title)
            pos_hits = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in title)
            
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


# ============================================================
# ENHANCED RISK MANAGER + CIRCUIT BREAKER v2.0
# ============================================================

from enum import Enum
import json
import time


class RiskLevel(Enum):
    """Уровни риска системы"""
    NORMAL = "normal"           # Всё в порядке
    ELEVATED = "elevated"       # Повышенный - уменьшаем позиции
    HIGH = "high"               # Высокий - только закрытие позиций
    CRITICAL = "critical"       # Критический - СТОП торговли
    EMERGENCY = "emergency"     # Экстренный - закрыть ВСЁ


class CircuitBreakerState(Enum):
    """Состояния Circuit Breaker"""
    CLOSED = "closed"           # Нормальная работа
    HALF_OPEN = "half_open"     # Тестовый режим (малые позиции)
    OPEN = "open"               # Торговля остановлена


@dataclass
class TradeRecord:
    """Запись о сделке для отслеживания"""
    symbol: str
    side: str               # "long" / "short"
    entry_price: float
    exit_price: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    position_size: float = 0.0
    timestamp: float = 0.0
    is_win: bool = False
    duration_seconds: int = 0
    confluence_score: float = 0.0


@dataclass
class DailyStats:
    """Ежедневная статистика"""
    date: str = ""
    total_pnl: float = 0.0
    total_pnl_percent: float = 0.0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    max_win: float = 0.0
    max_loss: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0


class RiskManager:
    """
    Комплексный менеджер рисков с Circuit Breaker.
    
    Основные функции:
    1. Circuit Breaker - остановка торговли при превышении лимита потерь
    2. Drawdown Protection - защита от глубокой просадки
    3. Position Limits (макс. количество позиций)
    4. Cooldown после серии убытков
    5. Volatility Filter
    """

    def __init__(
        self,
        total_capital: float,
        daily_loss_limit: float = 0.05,        # 5% макс. дневной убыток
        max_drawdown_limit: float = 0.15,       # 15% макс. просадка от пика
        max_positions: int = 3,                  # макс. одновременных позиций
        max_consecutive_losses: int = 5,         # макс. серия убытков подряд
        cooldown_minutes: int = 60,              # пауза после серии убытков
        max_position_pct: float = 0.10,          # макс. % капитала на позицию
        volatility_pause_multiplier: float = 3.0,
        state_file: str = "risk_state.json",
    ):
        # === Капитал ===
        self.total_capital = total_capital
        self.initial_capital = total_capital
        self.peak_capital = total_capital
        
        # === Лимиты ===
        self.daily_loss_limit = daily_loss_limit
        self.max_drawdown_limit = max_drawdown_limit
        self.max_positions = max_positions
        self.max_consecutive_losses = max_consecutive_losses
        self.cooldown_minutes = cooldown_minutes
        self.max_position_pct = max_position_pct
        self.volatility_pause_multiplier = volatility_pause_multiplier
        
        # === Состояние ===
        self.circuit_breaker_state = CircuitBreakerState.CLOSED
        self.risk_level = RiskLevel.NORMAL
        self.current_positions: Dict[str, dict] = {}
        self.daily_stats = DailyStats(date=self._today())
        self.trade_history: List[TradeRecord] = []
        self.consecutive_losses = 0
        self.cooldown_until: Optional[datetime] = None
        self.last_reset_date: str = self._today()
        
        # === Persistence ===
        self.state_file = state_file
        self._load_state()
        
        logger.info(
            f"RiskManager инициализирован: capital=${total_capital}, "
            f"daily_limit={daily_loss_limit*100}%, max_dd={max_drawdown_limit*100}%, "
            f"max_positions={max_positions}"
        )

    # ═══════════════════════════════════════════════════════════
    # ОСНОВНЫЕ ПРОВЕРКИ (вызывать перед каждой сделкой)
    # ═══════════════════════════════════════════════════════════

    def can_open_trade(self, symbol: str, position_size_usd: float, 
                       current_volatility: float = 0.0, 
                       normal_volatility: float = 0.0) -> Tuple[bool, str]:
        """
        Главная проверка: можно ли открыть сделку?
        
        Возвращает (True/False, причина_отказа)
        """
        # 1. Проверка даты (сброс дневных счётчиков)
        self._check_daily_reset()
        
        # 2. Circuit Breaker
        if self.circuit_breaker_state == CircuitBreakerState.OPEN:
            return False, f"🚫 CIRCUIT BREAKER ACTIVE! Торговля остановлена до завтра."
        
        # 3. Cooldown после серии убытков
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            remaining = (self.cooldown_until - datetime.now()).seconds // 60
            return False, f"⏸️ Cooldown активен. Осталось {remaining} мин."
        
        # 4. Максимальная просадка
        current_dd = self._current_drawdown()
        if current_dd >= self.max_drawdown_limit:
            self._activate_circuit_breaker("MAX_DRAWDOWN")
            return False, f"🔴 Max drawdown {current_dd*100:.1f}% >= {self.max_drawdown_limit*100}%!"
        
        # 5. Дневной лимит убытков
        daily_loss_pct = abs(min(0, self.daily_stats.total_pnl)) / self.total_capital
        if daily_loss_pct >= self.daily_loss_limit:
            self._activate_circuit_breaker("DAILY_LOSS_LIMIT")
            return False, f"🔴 Daily loss {daily_loss_pct*100:.1f}% >= {self.daily_loss_limit*100}%!"
        
        # 6. Максимум позиций
        if len(self.current_positions) >= self.max_positions:
            return False, f"⚠️ Max positions ({self.max_positions}) reached."
        
        # 7. Дубликат символа
        if symbol in self.current_positions:
            return False, f"⚠️ Already in position for {symbol}."
        
        # 8. Размер позиции
        max_allowed = self.total_capital * self.max_position_pct
        if position_size_usd > max_allowed:
            return False, f"⚠️ Position ${position_size_usd:.0f} > max ${max_allowed:.0f}"
        
        # 9. Фильтр волатильности
        if current_volatility > 0 and normal_volatility > 0:
            vol_ratio = current_volatility / normal_volatility
            if vol_ratio > self.volatility_pause_multiplier:
                return False, (
                    f"🌪️ Extreme volatility! Ratio {vol_ratio:.1f}x "
                    f"> {self.volatility_pause_multiplier}x normal"
                )
        
        # 10. Half-open mode (после восстановления)
        if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            max_half = self.total_capital * self.max_position_pct * 0.5
            if position_size_usd > max_half:
                return False, f"⚠️ Half-open mode: max ${max_half:.0f}"
        
        # 11. Приближение к дневному лимиту — уменьшаем exposure
        if daily_loss_pct >= self.daily_loss_limit * 0.7:
            logger.warning(
                f"⚠️ Approaching daily limit: {daily_loss_pct*100:.1f}% "
                f"of {self.daily_loss_limit*100}%"
            )
        
        return True, "✅ Trade allowed"

    # ═══════════════════════════════════════════════════════════
    # УПРАВЛЕНИЕ ПОЗИЦИЯМИ
    # ═══════════════════════════════════════════════════════════

    def register_position(self, symbol: str, side: str, entry_price: float, 
                         position_size: float, confluence_score: float = 0.0):
        """Регистрация открытой позиции"""
        self.current_positions[symbol] = {
            "side": side,
            "entry_price": entry_price,
            "position_size": position_size,
            "confluence_score": confluence_score,
            "timestamp": time.time(),
        }
        logger.info(f"📊 Position registered: {symbol} {side} @ {entry_price}")
        self._save_state()

    def close_position(self, symbol: str, exit_price: float, pnl: float):
        """Закрытие позиции и обновление статистики"""
        if symbol not in self.current_positions:
            logger.warning(f"Position {symbol} not found")
            return
        
        pos = self.current_positions.pop(symbol)
        pnl_pct = pnl / (pos["position_size"] * pos["entry_price"]) if pos["entry_price"] else 0
        
        # Создаём запись
        record = TradeRecord(
            symbol=symbol,
            side=pos["side"],
            entry_price=pos["entry_price"],
            exit_price=exit_price,
            pnl=pnl,
            pnl_percent=pnl_pct,
            position_size=pos["position_size"],
            timestamp=time.time(),
            is_win=pnl > 0,
            duration_seconds=int(time.time() - pos["timestamp"]),
            confluence_score=pos.get("confluence_score", 0),
        )
        self.trade_history.append(record)
        
        # Обновляем дневную статистику
        self._update_daily_stats(record)
        
        # Обновляем капитал
        self.total_capital += pnl
        if self.total_capital > self.peak_capital:
            self.peak_capital = self.total_capital
        
        # Обновляем серию убытков
        if pnl < 0:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.max_consecutive_losses:
                self._activate_cooldown()
        else:
            self.consecutive_losses = 0
        
        # Проверяем risk level
        self._update_risk_level()
        
        logger.info(
            f"{'✅' if pnl > 0 else '❌'} {symbol} closed: "
            f"PnL=${pnl:.2f} ({pnl_pct*100:.2f}%) | "
            f"Capital=${self.total_capital:.2f} | "
            f"DD={self._current_drawdown()*100:.1f}%"
        )
        
        self._save_state()

    # ═══════════════════════════════════════════════════════════
    # POSITION SIZING (с учётом текущего риска)
    # ═══════════════════════════════════════════════════════════

    def get_adjusted_position_size(self, base_size_pct: float) -> float:
        """
        Корректировка размера позиции с учётом текущего уровня риска.
        
        base_size_pct: базовый % от капитала (напр. 0.02 = 2%)
        Возвращает: скорректированный % от капитала
        """
        multiplier = 1.0
        
        # Уменьшаем при повышенном риске
        if self.risk_level == RiskLevel.ELEVATED:
            multiplier = 0.5
        elif self.risk_level == RiskLevel.HIGH:
            multiplier = 0.25
        elif self.risk_level in (RiskLevel.CRITICAL, RiskLevel.EMERGENCY):
            multiplier = 0.0
        
        # Уменьшаем при приближении к дневному лимиту
        daily_loss_pct = abs(min(0, self.daily_stats.total_pnl)) / self.total_capital
        if daily_loss_pct > self.daily_loss_limit * 0.5:
            remaining_ratio = 1.0 - (daily_loss_pct / self.daily_loss_limit)
            multiplier *= max(0.1, remaining_ratio)
        
        # Half-open mode
        if self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            multiplier *= 0.5
        
        # Уменьшаем после серии убытков (даже до cooldown)
        if self.consecutive_losses >= 2:
            loss_penalty = max(0.3, 1.0 - (self.consecutive_losses * 0.15))
            multiplier *= loss_penalty
        
        adjusted = base_size_pct * multiplier
        
        # Не превышаем максимум
        adjusted = min(adjusted, self.max_position_pct)
        
        return adjusted

    # ═══════════════════════════════════════════════════════════
    # CIRCUIT BREAKER
    # ═══════════════════════════════════════════════════════════

    def _activate_circuit_breaker(self, reason: str):
        """Активация Circuit Breaker — ПОЛНАЯ ОСТАНОВКА"""
        self.circuit_breaker_state = CircuitBreakerState.OPEN
        self.risk_level = RiskLevel.CRITICAL
        
        logger.critical(
            f"🚨🚨🚨 CIRCUIT BREAKER ACTIVATED! Reason: {reason} | "
            f"Daily PnL: ${self.daily_stats.total_pnl:.2f} | "
            f"Capital: ${self.total_capital:.2f} | "
            f"Drawdown: {self._current_drawdown()*100:.1f}%"
        )
        
        self._save_state()

    def _activate_cooldown(self):
        """Активация паузы после серии убытков"""
        self.cooldown_until = datetime.now() + timedelta(minutes=self.cooldown_minutes)
        logger.warning(
            f"⏸️ Cooldown activated: {self.consecutive_losses} consecutive losses. "
            f"Pausing until {self.cooldown_until.strftime('%H:%M')}"
        )

    def reset_circuit_breaker(self, force: bool = False):
        """Сброс Circuit Breaker (вручную или автоматически)"""
        if force or self._today() != self.last_reset_date:
            self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
            self.risk_level = RiskLevel.ELEVATED
            logger.info("🔄 Circuit Breaker reset to HALF_OPEN")
            self._save_state()

    # ═══════════════════════════════════════════════════════════
    # ВНУТРЕННИЕ МЕТОДЫ
    # ═══════════════════════════════════════════════════════════

    def _current_drawdown(self) -> float:
        """Текущая просадка от пика"""
        if self.peak_capital <= 0:
            return 0
        return (self.peak_capital - self.total_capital) / self.peak_capital

    def _update_daily_stats(self, record: TradeRecord):
        """Обновление дневной статистики"""
        self.daily_stats.total_pnl += record.pnl
        self.daily_stats.total_pnl_percent = self.daily_stats.total_pnl / self.total_capital
        self.daily_stats.trades_count += 1
        
        if record.is_win:
            self.daily_stats.wins += 1
            self.daily_stats.max_win = max(self.daily_stats.max_win, record.pnl)
        else:
            self.daily_stats.losses += 1
            self.daily_stats.max_loss = min(self.daily_stats.max_loss, record.pnl)
            self.daily_stats.consecutive_losses += 1
            self.daily_stats.max_consecutive_losses = max(
                self.daily_stats.max_consecutive_losses,
                self.daily_stats.consecutive_losses
            )
        
        if record.is_win:
            self.daily_stats.consecutive_losses = 0

    def _update_risk_level(self):
        """Обновление уровня риска"""
        dd = self._current_drawdown()
        daily_loss = abs(min(0, self.daily_stats.total_pnl)) / self.total_capital
        
        if dd >= self.max_drawdown_limit or daily_loss >= self.daily_loss_limit:
            self.risk_level = RiskLevel.CRITICAL
        elif dd >= self.max_drawdown_limit * 0.7 or daily_loss >= self.daily_loss_limit * 0.7:
            self.risk_level = RiskLevel.HIGH
        elif dd >= self.max_drawdown_limit * 0.4 or daily_loss >= self.daily_loss_limit * 0.4:
            self.risk_level = RiskLevel.ELEVATED
        else:
            self.risk_level = RiskLevel.NORMAL

    def _check_daily_reset(self):
        """Проверка и сброс дневных счётчиков"""
        today = self._today()
        if today != self.last_reset_date:
            logger.info(f"📅 New day: resetting daily stats. Previous: {self.daily_stats}")
            self.daily_stats = DailyStats(date=today)
            self.last_reset_date = today
            
            # Автоматический сброс CB на следующий день
            if self.circuit_breaker_state == CircuitBreakerState.OPEN:
                self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
                self.risk_level = RiskLevel.ELEVATED
                logger.info("🔄 Circuit Breaker auto-reset to HALF_OPEN (new day)")

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    # ═══════════════════════════════════════════════════════════
    # PERSISTENCE (сохранение/загрузка состояния)
    # ═══════════════════════════════════════════════════════════

    def _save_state(self):
        """Сохранение состояния на диск"""
        state = {
            "total_capital": self.total_capital,
            "peak_capital": self.peak_capital,
            "circuit_breaker_state": self.circuit_breaker_state.value,
            "risk_level": self.risk_level.value,
            "consecutive_losses": self.consecutive_losses,
            "last_reset_date": self.last_reset_date,
            "daily_stats": {
                "date": self.daily_stats.date,
                "total_pnl": self.daily_stats.total_pnl,
                "trades_count": self.daily_stats.trades_count,
                "wins": self.daily_stats.wins,
                "losses": self.daily_stats.losses,
            },
            "current_positions": self.current_positions,
        }
        try:
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save risk state: {e}")

    def _load_state(self):
        """Загрузка состояния с диска"""
        if not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            self.total_capital = state.get("total_capital", self.total_capital)
            self.peak_capital = state.get("peak_capital", self.peak_capital)
            self.circuit_breaker_state = CircuitBreakerState(
                state.get("circuit_breaker_state", "closed")
            )
            self.risk_level = RiskLevel(state.get("risk_level", "normal"))
            self.consecutive_losses = state.get("consecutive_losses", 0)
            self.last_reset_date = state.get("last_reset_date", self._today())
            logger.info(f"Risk state loaded: CB={self.circuit_breaker_state.value}")
        except Exception as e:
            logger.error(f"Failed to load risk state: {e}")

    # ═══════════════════════════════════════════════════════════
    # ОТЧЁТНОСТЬ
    # ═══════════════════════════════════════════════════════════

    def get_status_report(self) -> dict:
        """Полный отчёт о состоянии рисков"""
        return {
            "capital": {
                "current": self.total_capital,
                "initial": self.initial_capital,
                "peak": self.peak_capital,
                "total_pnl": self.total_capital - self.initial_capital,
                "total_pnl_pct": (self.total_capital - self.initial_capital) / self.initial_capital * 100,
            },
            "risk": {
                "level": self.risk_level.value,
                "circuit_breaker": self.circuit_breaker_state.value,
                "drawdown_pct": self._current_drawdown() * 100,
                "max_drawdown_limit": self.max_drawdown_limit * 100,
            },
            "daily": {
                "date": self.daily_stats.date,
                "pnl": self.daily_stats.total_pnl,
                "trades": self.daily_stats.trades_count,
                "wins": self.daily_stats.wins,
                "losses": self.daily_stats.losses,
                "win_rate": (self.daily_stats.wins / self.daily_stats.trades_count * 100) 
                           if self.daily_stats.trades_count > 0 else 0,
            },
            "positions": {
                "count": len(self.current_positions),
                "max": self.max_positions,
                "symbols": list(self.current_positions.keys()),
            },
            "consecutive_losses": self.consecutive_losses,
        }


# ============================================================
# ENHANCED PERFORMANCE TRACKER v2.0
# ============================================================

import math


@dataclass
class TradeEntry:
    """Запись о сделке"""
    id: str = ""
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    position_size: float = 0.0
    pnl: float = 0.0
    pnl_percent: float = 0.0
    is_win: bool = False
    entry_time: str = ""
    exit_time: str = ""
    duration_seconds: int = 0
    confluence_score: float = 0.0
    market_regime: str = ""
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_reason: str = ""  # "tp", "sl", "signal", "manual", "circuit_breaker"


class PerformanceTracker:
    """
    Полный трекер производительности торгового бота.
    
    Отслеживает:
    - Win rate, profit factor, Sharpe ratio
    - Max drawdown, avg drawdown
    - Equity curve
    - Per-symbol, per-regime, per-timeframe статистика
    - Best/worst trades
    - Streak analysis
    """

    def __init__(self, initial_capital: float = 10000, history_file: str = "trade_history.json"):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        self.history_file = history_file
        
        self.trades: List[TradeEntry] = []
        self.equity_curve: List[Tuple[str, float]] = [(datetime.now().isoformat(), initial_capital)]
        
        # Загрузка истории
        self._load_history()

    def add_trade(self, trade: dict):
        """
        Добавить завершённую сделку.
        
        trade = {
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 100000,
            "exit_price": 101500,
            "position_size": 0.005,
            "pnl": 7.5,
            "confluence_score": 85,
            "market_regime": "ranging_narrow",
            "stop_loss": 99000,
            "take_profit": 102000,
            "exit_reason": "tp",
            "duration_seconds": 3600,
        }
        """
        entry = TradeEntry(
            id=f"T{len(self.trades)+1:06d}",
            symbol=trade.get("symbol", ""),
            side=trade.get("side", ""),
            entry_price=trade.get("entry_price", 0),
            exit_price=trade.get("exit_price", 0),
            position_size=trade.get("position_size", 0),
            pnl=trade.get("pnl", 0),
            pnl_percent=trade.get("pnl_percent", 0),
            is_win=trade.get("pnl", 0) > 0,
            entry_time=trade.get("entry_time", ""),
            exit_time=trade.get("exit_time", datetime.now().isoformat()),
            duration_seconds=trade.get("duration_seconds", 0),
            confluence_score=trade.get("confluence_score", 0),
            market_regime=trade.get("market_regime", ""),
            stop_loss=trade.get("stop_loss", 0),
            take_profit=trade.get("take_profit", 0),
            exit_reason=trade.get("exit_reason", ""),
        )
        
        self.trades.append(entry)
        self.current_capital += entry.pnl
        
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        
        self.equity_curve.append((datetime.now().isoformat(), self.current_capital))
        
        self._save_history()

    def get_statistics(self, last_n: Optional[int] = None) -> dict:
        """
        Полная статистика. last_n = только последние N сделок.
        """
        trades = self.trades[-last_n:] if last_n else self.trades
        
        if not trades:
            return {"error": "No trades yet"}
        
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        
        total_profit = sum(t.pnl for t in wins)
        total_loss = abs(sum(t.pnl for t in losses))
        
        # === Базовые метрики ===
        stats = {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(trades) * 100,
            "total_pnl": sum(t.pnl for t in trades),
            "total_pnl_pct": (self.current_capital - self.initial_capital) / self.initial_capital * 100,
        }
        
        # === Profit Factor ===
        stats["profit_factor"] = total_profit / total_loss if total_loss > 0 else float('inf')
        
        # === Средние значения ===
        stats["avg_win"] = total_profit / len(wins) if wins else 0
        stats["avg_loss"] = total_loss / len(losses) if losses else 0
        stats["avg_pnl"] = sum(t.pnl for t in trades) / len(trades)
        stats["avg_win_pct"] = sum(t.pnl_percent for t in wins) / len(wins) * 100 if wins else 0
        stats["avg_loss_pct"] = sum(t.pnl_percent for t in losses) / len(losses) * 100 if losses else 0
        
        # === Лучшие/Худшие ===
        stats["best_trade"] = max(t.pnl for t in trades) if trades else 0
        stats["worst_trade"] = min(t.pnl for t in trades) if trades else 0
        
        # === Reward/Risk Ratio ===
        stats["reward_risk_ratio"] = stats["avg_win"] / stats["avg_loss"] if stats["avg_loss"] > 0 else 0
        
        # === Drawdown ===
        stats["max_drawdown_pct"] = self._calc_max_drawdown(trades) * 100
        stats["current_drawdown_pct"] = ((self.peak_capital - self.current_capital) / self.peak_capital * 100) if self.peak_capital > 0 else 0
        
        # === Sharpe Ratio (упрощённый) ===
        stats["sharpe_ratio"] = self._calc_sharpe(trades)
        
        # === Серии ===
        stats["max_consecutive_wins"] = self._max_streak(trades, True)
        stats["max_consecutive_losses"] = self._max_streak(trades, False)
        
        # === Средняя длительность ===
        durations = [t.duration_seconds for t in trades if t.duration_seconds > 0]
        stats["avg_duration_minutes"] = sum(durations) / len(durations) / 60 if durations else 0
        
        # === Капитал ===
        stats["capital"] = {
            "initial": self.initial_capital,
            "current": self.current_capital,
            "peak": self.peak_capital,
        }
        
        return stats

    def get_per_symbol_stats(self) -> Dict[str, dict]:
        """Статистика по символам"""
        symbols: Dict[str, list] = {}
        for t in self.trades:
            symbols.setdefault(t.symbol, []).append(t)
        
        result = {}
        for symbol, trades in symbols.items():
            wins = [t for t in trades if t.is_win]
            result[symbol] = {
                "trades": len(trades),
                "win_rate": len(wins) / len(trades) * 100 if trades else 0,
                "total_pnl": sum(t.pnl for t in trades),
                "avg_pnl": sum(t.pnl for t in trades) / len(trades),
            }
        
        return result

    def get_per_regime_stats(self) -> Dict[str, dict]:
        """Статистика по рыночным режимам"""
        regimes: Dict[str, list] = {}
        for t in self.trades:
            if t.market_regime:
                regimes.setdefault(t.market_regime, []).append(t)
        
        result = {}
        for regime, trades in regimes.items():
            wins = [t for t in trades if t.is_win]
            result[regime] = {
                "trades": len(trades),
                "win_rate": len(wins) / len(trades) * 100 if trades else 0,
                "total_pnl": sum(t.pnl for t in trades),
            }
        
        return result

    def get_kelly_input(self) -> list:
        """Подготовка данных для Kelly Calculator"""
        return [
            {
                "pnl": t.pnl,
                "pnl_percent": t.pnl_percent,
                "is_win": t.is_win,
            }
            for t in self.trades
        ]

    # === Internal Methods ===

    def _calc_max_drawdown(self, trades: list) -> float:
        """Расчёт максимальной просадки"""
        peak = self.initial_capital
        max_dd = 0
        capital = self.initial_capital
        
        for t in trades:
            capital += t.pnl
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        
        return max_dd

    def _calc_sharpe(self, trades: list, risk_free_rate: float = 0.0) -> float:
        """Упрощённый Sharpe Ratio"""
        if len(trades) < 2:
            return 0
        
        returns = [t.pnl_percent for t in trades]
        avg_return = sum(returns) / len(returns)
        
        variance = sum((r - avg_return) ** 2 for r in returns) / (len(returns) - 1)
        std_dev = math.sqrt(variance) if variance > 0 else 0.001
        
        # Аннуализированный (предполагаем ~250 торговых дней)
        sharpe = (avg_return - risk_free_rate) / std_dev * math.sqrt(250)
        return round(sharpe, 2)

    @staticmethod
    def _max_streak(trades: list, is_win: bool) -> int:
        """Максимальная серия побед/поражений"""
        max_streak = 0
        current = 0
        for t in trades:
            if t.is_win == is_win:
                current += 1
                max_streak = max(max_streak, current)
            else:
                current = 0
        return max_streak

    def print_report(self):
        """Красивый вывод отчёта"""
        stats = self.get_statistics()
        if "error" in stats:
            print(f"⚠️ {stats['error']}")
            return
        
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║               PERFORMANCE REPORT                             ║
╠══════════════════════════════════════════════════════════════╣
║ Total Trades:     {stats['total_trades']:>6}                                   
║ Win Rate:         {stats['win_rate']:>6.1f}%  (W:{stats['wins']} L:{stats['losses']})          
║ Profit Factor:    {stats['profit_factor']:>6.2f}                                   
║ Sharpe Ratio:     {stats['sharpe_ratio']:>6.2f}                                   
║ R/R Ratio:        {stats['reward_risk_ratio']:>6.2f}                                   
╠══════════════════════════════════════════════════════════════╣
║ Total PnL:        ${stats['total_pnl']:>+10.2f}  ({stats['total_pnl_pct']:+.1f}%)        
║ Avg Win:          ${stats['avg_win']:>+10.2f}  ({stats['avg_win_pct']:+.1f}%)        
║ Avg Loss:         ${stats['avg_loss']:>10.2f}  ({stats['avg_loss_pct']:.1f}%)         
║ Best Trade:       ${stats['best_trade']:>+10.2f}                          
║ Worst Trade:      ${stats['worst_trade']:>+10.2f}                          
╠══════════════════════════════════════════════════════════════╣
║ Max Drawdown:     {stats['max_drawdown_pct']:>6.1f}%                                  
║ Current DD:       {stats['current_drawdown_pct']:>6.1f}%                                  
║ Max Win Streak:   {stats['max_consecutive_wins']:>6}                                   
║ Max Loss Streak:  {stats['max_consecutive_losses']:>6}                                   
║ Avg Duration:     {stats['avg_duration_minutes']:>6.0f} min                                
╠══════════════════════════════════════════════════════════════╣
║ Capital: ${stats['capital']['initial']:,.0f} → ${stats['capital']['current']:,.0f} (Peak: ${stats['capital']['peak']:,.0f})
╚══════════════════════════════════════════════════════════════╝
""")

    # === Persistence ===

    def _save_history(self):
        try:
            data = {
                "initial_capital": self.initial_capital,
                "current_capital": self.current_capital,
                "peak_capital": self.peak_capital,
                "trades": [
                    {
                        "id": t.id,
                        "symbol": t.symbol,
                        "side": t.side,
                        "entry_price": t.entry_price,
                        "exit_price": t.exit_price,
                        "position_size": t.position_size,
                        "pnl": t.pnl,
                        "pnl_percent": t.pnl_percent,
                        "is_win": t.is_win,
                        "entry_time": t.entry_time,
                        "exit_time": t.exit_time,
                        "duration_seconds": t.duration_seconds,
                        "confluence_score": t.confluence_score,
                        "market_regime": t.market_regime,
                        "exit_reason": t.exit_reason,
                    }
                    for t in self.trades
                ],
            }
            with open(self.history_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save trade history: {e}")

    def _load_history(self):
        if not os.path.exists(self.history_file):
            return
        try:
            with open(self.history_file, "r") as f:
                data = json.load(f)
            self.initial_capital = data.get("initial_capital", self.initial_capital)
            self.current_capital = data.get("current_capital", self.initial_capital)
            self.peak_capital = data.get("peak_capital", self.initial_capital)
            
            for t in data.get("trades", []):
                entry = TradeEntry(
                    id=t["id"],
                    symbol=t["symbol"],
                    side=t["side"],
                    entry_price=t["entry_price"],
                    exit_price=t["exit_price"],
                    position_size=t["position_size"],
                    pnl=t["pnl"],
                    pnl_percent=t["pnl_percent"],
                    is_win=t["is_win"],
                    entry_time=t["entry_time"],
                    exit_time=t["exit_time"],
                    duration_seconds=t["duration_seconds"],
                    confluence_score=t["confluence_score"],
                    market_regime=t["market_regime"],
                    exit_reason=t["exit_reason"],
                )
                self.trades.append(entry)
            
            logger.info(f"Trade history loaded: {len(self.trades)} trades")
        except Exception as e:
            logger.error(f"Failed to load trade history: {e}")


@dataclass
class AdvancedSignal:
    signal_type: SignalType
    symbol: str
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    
    confluence: ConfluenceScore = field(default_factory=lambda: ConfluenceScore())
    probability: int = 50
    strength: SignalStrength = SignalStrength.MODERATE
    
    timeframes_aligned: Dict[str, bool] = field(default_factory=dict)
    support_resistance_nearby: Optional[SupportResistanceLevel] = None
    market_regime: MarketRegime = MarketRegime.NEUTRAL
    
    risk_reward_ratio: float = 2.0
    position_size_percent: float = 1.0
    
    # Bybit специфичные данные
    funding_rate: Optional[float] = 0.0
    funding_interpretation: Optional[str] = "Neutral"
    orderbook_imbalance: Optional[float] = 0.0
    
    timestamp: datetime = field(default_factory=lambda: datetime.now())
    valid_until: datetime = field(default_factory=lambda: datetime.now() + timedelta(hours=4))
    
    indicators: Dict[str, Any] = field(default_factory=dict)
    reasoning: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Тюнинг стратегии (Фаза 5)
    time_exit_bars: int = 24  # Максимальное удержание (например, 24 свечи по 15м = 6 часов)


# ============================================================
# TECHNICAL INDICATORS
# ============================================================

class TechnicalIndicators:
    """Набор технических индикаторов"""
    
    @staticmethod
    def sma(data: pd.Series, period: int) -> pd.Series:
        return data.rolling(window=period).mean()
    
    @staticmethod
    def ema(data: pd.Series, period: int) -> pd.Series:
        return data.ewm(span=period, adjust=False).mean()
    
    @staticmethod
    def rsi(data: pd.Series, period: int = 14) -> pd.Series:
        delta = data.diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    @staticmethod
    def stochastic_rsi(data: pd.Series, rsi_period: int = 14, stoch_period: int = 14) -> Tuple[pd.Series, pd.Series]:
        rsi = TechnicalIndicators.rsi(data, rsi_period)
        stoch_rsi = (rsi - rsi.rolling(stoch_period).min()) / \
                    (rsi.rolling(stoch_period).max() - rsi.rolling(stoch_period).min())
        k = stoch_rsi * 100
        d = k.rolling(3).mean()
        return k, d
    
    @staticmethod
    def bollinger_bands(data: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        middle = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        upper = middle + (std * std_dev)
        lower = middle - (std * std_dev)
        return upper, middle, lower
    
    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.rolling(window=period).mean()
    
    @staticmethod
    def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
        
        atr_val = TechnicalIndicators.atr(high, low, close, period)
        
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr_val)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr_val)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx_val = dx.rolling(window=period).mean()
        
        return adx_val, plus_di, minus_di
    
    @staticmethod
    def macd(data: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = data.ewm(span=fast, adjust=False).mean()
        ema_slow = data.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    @staticmethod
    def williams_r(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()
        return -100 * (highest_high - close) / (highest_high - lowest_low)
    
    @staticmethod
    def cci(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
        tp = (high + low + close) / 3
        sma = tp.rolling(window=period).mean()
        mad = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean())
        return (tp - sma) / (0.015 * mad)
    
        mfr = positive_mf / negative_mf
        return 100 - (100 / (1 + mfr))

    @staticmethod
    def fibonacci_levels(high: pd.Series, low: pd.Series, lookback: int = 50) -> Dict[str, float]:
        """
        Calculate Fibonacci Retracement levels from recent swing high/low.
        Returns dict with levels: 0.236, 0.382, 0.5, 0.618, 0.786
        """
        recent_high = high.tail(lookback).max()
        recent_low = low.tail(lookback).min()
        diff = recent_high - recent_low
        
        return {
            'high': recent_high,
            'low': recent_low,
            '0.236': recent_high - (diff * 0.236),
            '0.382': recent_high - (diff * 0.382),
            '0.5': recent_high - (diff * 0.5),
            '0.618': recent_high - (diff * 0.618),
            '0.786': recent_high - (diff * 0.786),
        }
    
    @staticmethod
    def supertrend(high: pd.Series, low: pd.Series, close: pd.Series, 
                   period: int = 10, multiplier: float = 3.0) -> Tuple[pd.Series, pd.Series]:
        """
        Supertrend indicator.
        Returns (supertrend_line, direction) where direction is 1 for bullish, -1 for bearish.
        """
        atr = TechnicalIndicators.atr(high, low, close, period)
        
        hl2 = (high + low) / 2
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)
        
        supertrend = pd.Series(index=close.index, dtype=float)
        direction = pd.Series(index=close.index, dtype=float)
        
        # Initialize
        supertrend.iloc[0] = upper_band.iloc[0]
        direction.iloc[0] = 1
        
        for i in range(1, len(close)):
            if close.iloc[i] > upper_band.iloc[i-1]:
                supertrend.iloc[i] = lower_band.iloc[i]
                direction.iloc[i] = 1  # Bullish
            elif close.iloc[i] < lower_band.iloc[i-1]:
                supertrend.iloc[i] = upper_band.iloc[i]
                direction.iloc[i] = -1  # Bearish
            else:
                supertrend.iloc[i] = supertrend.iloc[i-1]
                direction.iloc[i] = direction.iloc[i-1]
                
                # Adjust bands
                if direction.iloc[i] == 1 and lower_band.iloc[i] < supertrend.iloc[i-1]:
                    supertrend.iloc[i] = supertrend.iloc[i-1]
                elif direction.iloc[i] == -1 and upper_band.iloc[i] > supertrend.iloc[i-1]:
                    supertrend.iloc[i] = supertrend.iloc[i-1]
        
        return supertrend, direction

    @staticmethod
    def zscore(data: pd.Series, period: int = 20) -> pd.Series:
        mean = data.rolling(window=period).mean()
        std = data.rolling(window=period).std()
        return (data - mean) / std


# ============================================================
# SUPPORT/RESISTANCE DETECTOR
# ============================================================

class SupportResistanceDetector:
    
    def __init__(self, lookback: int = 100, tolerance: float = 0.002):
        self.lookback = lookback
        self.tolerance = tolerance
    
    def find_levels(self, df: pd.DataFrame) -> List[SupportResistanceLevel]:
        levels = []
        data = df.tail(self.lookback).copy()
        
        highs = data['high'].values
        lows = data['low'].values
        closes = data['close'].values
        
        # Локальные максимумы
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
               highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                price = highs[i]
                strength = self._count_touches(closes, price)
                if strength >= 2:
                    levels.append(SupportResistanceLevel(
                        price=price,
                        strength=strength,
                        level_type='resistance',
                        timeframe=df.attrs.get('timeframe', '15m'),
                        last_touch=datetime.now()
                    ))
        
        # Локальные минимумы
        for i in range(2, len(lows) - 2):
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and \
               lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                price = lows[i]
                strength = self._count_touches(closes, price)
                if strength >= 2:
                    levels.append(SupportResistanceLevel(
                        price=price,
                        strength=strength,
                        level_type='support',
                        timeframe=df.attrs.get('timeframe', '15m'),
                        last_touch=datetime.now()
                    ))
        
        levels.sort(key=lambda x: x.strength, reverse=True)
        return self._merge_close_levels(levels)
    
    def _count_touches(self, prices: np.ndarray, level: float) -> int:
        tolerance_abs = level * self.tolerance
        return sum(1 for price in prices if abs(price - level) <= tolerance_abs)
    
    def _merge_close_levels(self, levels: List[SupportResistanceLevel], threshold: float = 0.005) -> List[SupportResistanceLevel]:
        if not levels:
            return []
        
        merged = [levels[0]]
        for level in levels[1:]:
            is_close = False
            for existing in merged:
                if abs(level.price - existing.price) / existing.price < threshold:
                    existing.strength += level.strength
                    is_close = True
                    break
            if not is_close:
                merged.append(level)
        return merged
    
    def find_nearest(self, levels: List[SupportResistanceLevel], price: float, direction: str) -> Optional[SupportResistanceLevel]:
        if direction == 'below':
            candidates = [l for l in levels if l.price < price and l.level_type == 'support']
            return max(candidates, key=lambda x: x.price) if candidates else None
        else:
            candidates = [l for l in levels if l.price > price and l.level_type == 'resistance']
            return min(candidates, key=lambda x: x.price) if candidates else None


# ============================================================
# ENHANCED S/R DETECTOR (Dynamic ATR Tolerance)
# ============================================================

class EnhancedSRDetector:
    """
    Улучшенный детектор S/R уровней.
    
    Ключевое изменение: tolerance = f(ATR) вместо фиксированных 0.2%
    """

    def __init__(
        self, 
        lookback: int = 100, 
        atr_multiplier: float = 0.5,
        min_tolerance: float = 0.001,
        max_tolerance: float = 0.01,
        min_touches: int = 2,
    ):
        self.lookback = lookback
        self.atr_multiplier = atr_multiplier
        self.min_tolerance = min_tolerance
        self.max_tolerance = max_tolerance
        self.min_touches = min_touches

    def find_levels(self, highs, lows, closes, atr_value: float = 0.0) -> dict:
        """
        Найти S/R уровни с динамическим tolerance.
        
        highs, lows, closes: массивы/списки цен
        atr_value: текущий ATR
        """
        if len(closes) < 10:
            return {"support_levels": [], "resistance_levels": [], "sr_score": 0}
        
        # Берём последние lookback баров
        h = list(highs[-self.lookback:])
        l = list(lows[-self.lookback:])
        c = list(closes[-self.lookback:])
        current_price = c[-1]
        
        # Dynamic tolerance
        if atr_value <= 0:
            atr_value = self._simple_atr(h, l, c)
        
        tolerance = (atr_value / current_price) * self.atr_multiplier
        tolerance = max(self.min_tolerance, min(self.max_tolerance, tolerance))
        
        # Pivot points
        potential = []
        for i in range(2, len(h) - 2):
            if h[i] > h[i-1] and h[i] > h[i-2] and h[i] > h[i+1] and h[i] > h[i+2]:
                potential.append(h[i])
            if l[i] < l[i-1] and l[i] < l[i-2] and l[i] < l[i+1] and l[i] < l[i+2]:
                potential.append(l[i])
        
        # Merge close levels
        merged = self._merge(potential, atr_value)
        
        # Count touches
        strong = []
        for level in merged:
            touches = sum(
                1 for i in range(len(h))
                if abs(h[i] - level) / level < tolerance or
                   abs(l[i] - level) / level < tolerance
            )
            if touches >= self.min_touches:
                strong.append((level, touches))
        
        strong.sort(key=lambda x: x[1], reverse=True)
        
        supports = sorted([lv for lv, t in strong if lv < current_price], reverse=True)[:5]
        resistances = sorted([lv for lv, t in strong if lv >= current_price])[:5]
        
        nearest_s = supports[0] if supports else current_price * 0.98
        nearest_r = resistances[0] if resistances else current_price * 1.02
        
        # S/R score (0-15)
        sr_score = self._calc_score(current_price, nearest_s, nearest_r, tolerance)
        
        return {
            "support_levels": supports,
            "resistance_levels": resistances,
            "nearest_support": nearest_s,
            "nearest_resistance": nearest_r,
            "tolerance": tolerance,
            "tolerance_pct": tolerance * 100,
            "sr_score": sr_score,
        }

    def _calc_score(self, price, support, resistance, tolerance) -> int:
        min_dist = min(abs(price - support), abs(resistance - price)) / price
        if min_dist < tolerance * 0.5: return 15
        elif min_dist < tolerance: return 12
        elif min_dist < tolerance * 2: return 8
        elif min_dist < tolerance * 3: return 5
        return 2

    @staticmethod
    def _merge(levels, distance):
        if not levels:
            return []
        levels = sorted(levels)
        merged = [levels[0]]
        for lv in levels[1:]:
            if abs(lv - merged[-1]) <= distance:
                merged[-1] = (merged[-1] + lv) / 2
            else:
                merged.append(lv)
        return merged

    @staticmethod
    def _simple_atr(highs, lows, closes, period=14):
        trs = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        if len(trs) < period:
            return sum(trs) / len(trs) if trs else 0
        return sum(trs[-period:]) / period


# ============================================================
# KELLY CRITERION POSITION SIZER
# ============================================================

class KellyPositionSizer:
    """
    Оптимальный размер позиции на основе формулы Келли.
    
    Kelly % = (W * R - L) / R
    где:
        W = win rate
        R = avg_win / avg_loss (reward/risk ratio)
        L = 1 - W (loss rate)
    
    Используем Conservative Kelly (25-50% от полного Келли)
    для защиты от overfitting и вариации.
    
    Также учитываем:
    - Confluence score (сила сигнала)
    - Текущую волатильность
    - Drawdown state
    """

    def __init__(
        self,
        kelly_fraction: float = 0.25,       # Используем 25% от Келли (conservative)
        min_position_pct: float = 0.005,     # Минимум 0.5% капитала
        max_position_pct: float = 0.10,      # Максимум 10% капитала
        min_trades_for_kelly: int = 30,      # Минимум сделок для расчёта
        default_position_pct: float = 0.02,  # Дефолтный размер до накопления статистики
        lookback_trades: int = 100,          # Окно расчёта (последние N сделок)
    ):
        self.kelly_fraction = kelly_fraction
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.min_trades = min_trades_for_kelly
        self.default_pct = default_position_pct
        self.lookback = lookback_trades
        
        logger.info(
            f"KellyPositionSizer: fraction={kelly_fraction}, "
            f"range=[{min_position_pct*100}%-{max_position_pct*100}%], "
            f"min_trades={min_trades_for_kelly}"
        )

    def calculate(
        self,
        trades: list,
        confluence_score: float = 0.0,       # 0-100 (процент от max)
        current_volatility: float = 0.0,     # Текущий ATR %
        normal_volatility: float = 0.0,      # Нормальный ATR %
        drawdown_pct: float = 0.0,           # Текущая просадка %
    ) -> dict:
        """
        Рассчитать оптимальный размер позиции.
        
        trades: список сделок [{pnl, is_win, pnl_percent}, ...]
        
        Возвращает:
        {
            "position_pct": float,       # Рекомендуемый % от капитала
            "kelly_raw": float,          # Полный Kelly %
            "kelly_adjusted": float,     # Kelly * fraction
            "win_rate": float,
            "reward_risk_ratio": float,
            "method": str,               # "kelly" / "default" / "reduced"
        }
        """
        result = {
            "position_pct": self.default_pct,
            "kelly_raw": 0.0,
            "kelly_adjusted": 0.0,
            "win_rate": 0.0,
            "reward_risk_ratio": 0.0,
            "method": "default",
            "adjustments": [],
        }
        
        # Фильтруем последние N сделок
        recent = trades[-self.lookback:] if len(trades) > self.lookback else trades
        
        if len(recent) < self.min_trades:
            result["method"] = "default"
            result["adjustments"].append(
                f"Недостаточно сделок ({len(recent)}/{self.min_trades}), используем default {self.default_pct*100:.1f}%"
            )
            # Но всё равно применяем корректировки
            result["position_pct"] = self._apply_adjustments(
                self.default_pct, confluence_score, 
                current_volatility, normal_volatility, drawdown_pct
            )
            return result
        
        # === Рассчёт Kelly ===
        wins = [t for t in recent if t.get("is_win", t.get("pnl", 0) > 0)]
        losses = [t for t in recent if not t.get("is_win", t.get("pnl", 0) > 0)]
        
        win_rate = len(wins) / len(recent)
        loss_rate = 1 - win_rate
        
        avg_win = abs(sum(t.get("pnl_percent", t.get("pnl", 0)) for t in wins) / max(1, len(wins)))
        avg_loss = abs(sum(t.get("pnl_percent", t.get("pnl", 0)) for t in losses) / max(1, len(losses)))
        
        if avg_loss == 0:
            avg_loss = 0.001  # Предотвращаем деление на ноль
        
        reward_risk = avg_win / avg_loss
        
        # Kelly Formula: K = (W * R - L) / R
        kelly_raw = (win_rate * reward_risk - loss_rate) / reward_risk
        kelly_adjusted = kelly_raw * self.kelly_fraction
        
        result["win_rate"] = win_rate
        result["reward_risk_ratio"] = reward_risk
        result["kelly_raw"] = kelly_raw
        result["kelly_adjusted"] = kelly_adjusted
        result["method"] = "kelly"
        
        # Если Kelly отрицательный — не торговать
        if kelly_raw <= 0:
            result["position_pct"] = 0
            result["method"] = "kelly_negative"
            result["adjustments"].append("⚠️ Kelly < 0: стратегия убыточна!")
            return result
        
        # Применяем корректировки
        base_pct = max(self.min_position_pct, min(self.max_position_pct, kelly_adjusted))
        result["position_pct"] = self._apply_adjustments(
            base_pct, confluence_score, current_volatility, normal_volatility, drawdown_pct
        )
        
        logger.info(
            f"Kelly: WR={win_rate:.1%}, R/R={reward_risk:.2f}, "
            f"raw={kelly_raw:.3f}, adj={kelly_adjusted:.3f}, "
            f"final={result['position_pct']:.3f} ({result['position_pct']*100:.1f}%)"
        )
        
        return result

    def _apply_adjustments(
        self, base_pct: float, confluence: float,
        vol: float, normal_vol: float, dd: float
    ) -> float:
        """Корректировки размера позиции"""
        adjusted = base_pct
        
        # 1. Confluence score boost/penalty
        if confluence > 0:
            # 80-100% confluence → 1.0-1.5x boost
            # 60-80% → 0.8-1.0x
            # <60% → 0.5-0.8x
            if confluence >= 80:
                adjusted *= 1.0 + (confluence - 80) / 40  # max 1.5x
            elif confluence >= 60:
                adjusted *= 0.8 + (confluence - 60) / 100  # 0.8-1.0x
            else:
                adjusted *= 0.5 + confluence / 200  # 0.5-0.8x
        
        # 2. Volatility adjustment (higher vol → smaller position)
        if vol > 0 and normal_vol > 0:
            vol_ratio = vol / normal_vol
            if vol_ratio > 1.5:
                vol_penalty = 1.0 / vol_ratio
                adjusted *= max(0.3, vol_penalty)
        
        # 3. Drawdown adjustment (deeper DD → smaller position)
        if dd > 0:
            # 0-5% DD → 1.0x
            # 5-10% DD → 0.5-1.0x
            # >10% DD → 0.25-0.5x
            if dd > 0.10:
                adjusted *= 0.25
            elif dd > 0.05:
                adjusted *= 0.5 + (0.10 - dd) * 10  # Linear 0.5-1.0
        
        # Clamp
        return max(self.min_position_pct, min(self.max_position_pct, adjusted))


# ============================================================
# MULTI-TIMEFRAME ANALYZER
# ============================================================

class MultiTimeframeAnalyzer:
    
    def __init__(self):
        self.ind = TechnicalIndicators()
    
    def analyze_timeframe(self, df: pd.DataFrame) -> Dict[str, Any]:
        if len(df) < 50:
            return {'valid': False}
        
        df = df.copy()
        df['rsi'] = self.ind.rsi(df['close'])
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = self.ind.bollinger_bands(df['close'])
        df['adx'], df['plus_di'], df['minus_di'] = self.ind.adx(df['high'], df['low'], df['close'])
        df['macd'], df['macd_signal'], df['macd_hist'] = self.ind.macd(df['close'])
        df['ema_200'] = self.ind.ema(df['close'], 200)
        df['vol_zscore'] = self.ind.zscore(df['volume'], 20)
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        return {
            'valid': True,
            'rsi': current['rsi'],
            'rsi_oversold': current['rsi'] < 30,
            'rsi_overbought': current['rsi'] > 70,
            'rsi_extreme_oversold': current['rsi'] < 20,
            'rsi_extreme_overbought': current['rsi'] > 80,
            'below_bb_lower': current['close'] < current['bb_lower'],
            'above_bb_upper': current['close'] > current['bb_upper'],
            'bb_position': (current['close'] - current['bb_lower']) / (current['bb_upper'] - current['bb_lower']),
            'adx': current['adx'],
            'trend_strength': 'strong' if current['adx'] > 25 else 'weak',
            'trend_direction': 'up' if current['plus_di'] > current['minus_di'] else 'down',
            'macd_bearish': current['macd_hist'] < prev['macd_hist'],
            'macd_bullish': current['macd_hist'] > prev['macd_hist'],
            'price': current['close'],
            'rsi_slope': current['rsi'] - prev['rsi'],
            'ema_dist': (current['close'] - current['ema_200']) / current['ema_200'] * 100 if 'ema_200' in current else 0,
            'bb_width': (current['bb_upper'] - current['bb_lower']) / current['bb_middle'] if 'bb_middle' in current else 0,
            'vol_zscore': current['vol_zscore'] if 'vol_zscore' in current else 0
        }
    
    def check_alignment(self, tf_15m: Dict, tf_1h: Dict, tf_4h: Dict, direction: str) -> Dict[str, Any]:
        if not all([tf_15m.get('valid'), tf_1h.get('valid'), tf_4h.get('valid')]):
            return {'aligned': False, 'score': 0, 'details': {}}
        
        score = 0
        details = {}
        
        if direction == 'LONG':
            # AGGRESSIVE MODE BONUS
            if config and getattr(config, 'TRADE_MODE', '') == 'AGGRESSIVE':
                score += 15
                details['AGGRESSIVE'] = "🚀 Aggressive Bonus +15"

            if tf_15m['rsi_oversold']:
                score += 20
                details['15m_rsi'] = f"✅ RSI={tf_15m['rsi']:.1f} < 30"
            if tf_15m['rsi_extreme_oversold']:
                score += 10
                details['15m_extreme'] = f"✅ RSI < 20 (экстремум)"
            if tf_15m['below_bb_lower']:
                score += 10
                details['15m_bb'] = "✅ Ниже BB Lower"
            
            if tf_1h['rsi'] < 40:
                score += 15
                details['1h_rsi'] = f"✅ 1H RSI={tf_1h['rsi']:.1f} < 40"
            if tf_1h['rsi'] < 30:
                score += 10
                details['1h_oversold'] = f"✅ 1H перепродан"
            if tf_1h['trend_strength'] == 'weak':
                score += 10
                details['1h_trend'] = f"✅ 1H тренд слабый"
            
            if tf_4h['rsi'] < 50:
                score += 10
                details['4h_rsi'] = f"✅ 4H RSI < 50"
            if tf_4h['adx'] < 30:
                score += 10
                details['4h_adx'] = f"✅ 4H нет сильного тренда"
            if tf_4h['macd_bullish']:
                score += 5
                details['4h_macd'] = "✅ 4H MACD вверх"
        
        else:  # SHORT
            # AGGRESSIVE MODE BONUS
            if config and getattr(config, 'TRADE_MODE', '') == 'AGGRESSIVE':
                score += 15
                details['AGGRESSIVE'] = "🚀 Aggressive Bonus +15"
                
            if tf_15m['rsi_overbought']:
                score += 20
                details['15m_rsi'] = f"✅ RSI={tf_15m['rsi']:.1f} > 70"
            if tf_15m['rsi_extreme_overbought']:
                score += 10
                details['15m_extreme'] = f"✅ RSI > 80 (экстремум)"
            if tf_15m['above_bb_upper']:
                score += 10
                details['15m_bb'] = "✅ Выше BB Upper"
            
            if tf_1h['rsi'] > 60:
                score += 15
                details['1h_rsi'] = f"✅ 1H RSI={tf_1h['rsi']:.1f} > 60"
            if tf_1h['rsi'] > 70:
                score += 10
                details['1h_overbought'] = f"✅ 1H перекуплен"
            if tf_1h['trend_strength'] == 'weak':
                score += 10
                details['1h_trend'] = f"✅ 1H тренд слабый"
            
            if tf_4h['rsi'] > 50:
                score += 10
                details['4h_rsi'] = f"✅ 4H RSI > 50"
            if tf_4h['adx'] < 30:
                score += 10
                details['4h_adx'] = f"✅ 4H нет сильного тренда"
            if tf_4h['macd_bearish']:
                score += 5
                details['4h_macd'] = "✅ 4H MACD вниз"
        
        return {'aligned': score >= 50, 'score': score, 'details': details}


# ============================================================
# MAIN ENGINE
# ============================================================

class AdvancedMeanReversionEngine:
    """
    Продвинутый Mean Reversion движок для Bybit
    
    Дополнительные факторы:
    - Funding Rate (для perpetual)
    - Order Book Imbalance
    """
    
    def __init__(self, min_confluence: int = 85, min_rr: float = 4.5):
        """
        Sniper Mode: min_confluence=85 (Extreme only), min_rr=4.0 (1:4 minimum)
        """
        self.ind = TechnicalIndicators()
        self.sr_detector = SupportResistanceDetector()
        self.mtf_analyzer = MultiTimeframeAnalyzer()
        self.min_confluence = min_confluence
        self.min_rr = min_rr
        
        # AI Integration
        try:
            from ai_engine import AIEngine
            self.ai = AIEngine()
        except ImportError:
            self.ai = None
    
    def analyze(
        self,
        df_15m: pd.DataFrame,
        df_1h: pd.DataFrame,
        df_4h: pd.DataFrame,
        symbol: str,
        funding_rate: Optional[float] = None,
        orderbook_imbalance: Optional[float] = None,
        is_scalping: bool = False
    ) -> Optional[AdvancedSignal]:
        """
        Главный метод анализа
        
        Args:
            df_15m, df_1h, df_4h: Данные по таймфреймам (В режиме Scalping df_15m = df_1m)
            symbol: Торговая пара
            funding_rate: Funding rate с Bybit (для perpetual)
            orderbook_imbalance: Дисбаланс стакана
            is_scalping: Режим скальпинга
        """
        
        # В режиме скальпинга нам нужно меньше истории
        min_len = 50 if is_scalping else 100
        if len(df_15m) < min_len:
            return None
        
        if not is_scalping and (len(df_1h) < 50 or len(df_4h) < 50):
            return None
            
        # 0. Фильтр волатильности (ATR Filter)
        # Не торгуем если цена "стоит" (ATR < 0.2% от цены)
        current_price = df_15m['close'].iloc[-1]
        atr = self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1]
        atr_pct = (atr / current_price) * 100
        
        if atr_pct < 0.2:
            # In AGGRESSIVE mode, we might allow lower volatility
            if config and getattr(config, 'TRADE_MODE', '') == 'AGGRESSIVE':
                 pass # Allow low vol in aggressive
            else:
                logger.debug(f"{symbol}: Low Volatility (ATR {atr_pct:.2f}%) - SKIP")
                return None
        
        # Режим рынка
        if is_scalping:
            regime = MarketRegime.RANGING_WIDE # Default for scalping
        else:
            regime = self.detect_regime(df_4h)
            
            # In AGGRESSIVE mode, we trade ALL regimes except maybe CHAOS
            if config and getattr(config, 'TRADE_MODE', '') == 'AGGRESSIVE':
                if regime == MarketRegime.VOLATILE_CHAOS:
                     logger.debug(f"{symbol}: CHAOS - skip even in aggressive")
                     return None
            else:
                if regime in [MarketRegime.STRONG_TREND_UP, MarketRegime.STRONG_TREND_DOWN, MarketRegime.VOLATILE_CHAOS]:
                    logger.debug(f"{symbol}: {regime.value} - пропуск")
                    return None
        
        # Анализ таймфреймов
        tf_15m = self.mtf_analyzer.analyze_timeframe(df_15m)
        
        if is_scalping:
            # В скальпинге мы смотрим только на 1м (который передан в df_15m)
            # Заглушки для старших ТФ
            tf_1h = tf_15m.copy() 
            tf_4h = tf_15m.copy()
        else:
            tf_1h = self.mtf_analyzer.analyze_timeframe(df_1h)
            tf_4h = self.mtf_analyzer.analyze_timeframe(df_4h)
        
        # Проверка LONG
        long_signal = self._check_long(
            df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
            funding_rate, orderbook_imbalance
        )
        if long_signal and long_signal.confluence.percentage >= self.min_confluence:
            # AI Check
            if self.ai:
                try:
                    ai_prob = self.ai.predict_success_probability(long_signal.indicators)
                    long_signal.indicators['ai_score'] = ai_prob
                    long_signal.reasoning.append(f"🤖 AI Score: {ai_prob*100:.1f}%")
                    # Filter weak AI signals
                    if ai_prob < 0.6:
                         logger.info(f"AI rejected LONG {symbol} (prob {ai_prob:.2f})")
                         return None
                except Exception as e:
                    logger.warning(f"⚠️ AI Check Failed (Rate Limit?): {e}. Proceeding with technical signal.")
                    long_signal.reasoning.append("⚠️ AI недоступен (Tech Only)")

            return long_signal
        
        # Проверка SHORT
        short_signal = self._check_short(
            df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
            funding_rate, orderbook_imbalance
        )
        if short_signal and short_signal.confluence.percentage >= self.min_confluence:
             # AI Check
            if self.ai:
                try:
                    ai_prob = self.ai.predict_success_probability(short_signal.indicators)
                    short_signal.indicators['ai_score'] = ai_prob
                    short_signal.reasoning.append(f"🤖 AI Score: {ai_prob*100:.1f}%")
                    if ai_prob < 0.6:
                         logger.info(f"AI rejected SHORT {symbol} (prob {ai_prob:.2f})")
                         return None
                except Exception as e:
                    logger.warning(f"⚠️ AI Check Failed (Rate Limit?): {e}. Proceeding with technical signal.")
                    short_signal.reasoning.append("⚠️ AI недоступен (Tech Only)")

            return short_signal
        
        return None
    
    def detect_regime(self, df: pd.DataFrame) -> MarketRegime:
        df = df.copy()
        df['adx'], df['plus_di'], df['minus_di'] = self.ind.adx(df['high'], df['low'], df['close'])
        df['atr'] = self.ind.atr(df['high'], df['low'], df['close'])
        
        current = df.iloc[-1]
        avg_atr = df['atr'].tail(20).mean()
        volatility_ratio = current['atr'] / avg_atr if avg_atr > 0 else 1
        
        if volatility_ratio > 2.0:
            return MarketRegime.VOLATILE_CHAOS
        
        adx = current['adx']
        trend_up = current['plus_di'] > current['minus_di']
        
        if adx > 40:
            return MarketRegime.STRONG_TREND_UP if trend_up else MarketRegime.STRONG_TREND_DOWN
        elif adx > 25:
            return MarketRegime.WEAK_TREND_UP if trend_up else MarketRegime.WEAK_TREND_DOWN
        else:
            try:
                bb_upper, bb_middle, bb_lower = self.ind.bollinger_bands(df['close'])
                bb_width = (bb_upper.iloc[-1] - bb_lower.iloc[-1]) / bb_middle.iloc[-1]
                return MarketRegime.RANGING_NARROW if bb_width < 0.04 else MarketRegime.RANGING_WIDE
            except Exception:
                 return MarketRegime.RANGING_WIDE
    
    def _check_long(
        self, df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
        funding_rate, orderbook_imbalance
    ) -> Optional[AdvancedSignal]:
        
        # Dynamic RSI Thresholds
        adx = tf_15m.get('adx', 0)
        rsi_limit = 25 if adx > 30 else 30

        # === TREND GUARDIAN (Block counter-trend entries) ===
        price = tf_15m['price']
        
        # Long Safeguard
        if tf_1h.get('valid'):
            # If price is below 1H EMA 200 AND trend is strong down, BLOCK LONG
            # (ema_dist is (price - ema200) / ema200 * 100)
            is_bearish_macro = tf_1h.get('ema_dist', 0) < -0.5 and tf_1h.get('trend_direction') == 'down'
            
            if is_bearish_macro:
                # Relax for AGGRESSIVE mode (low min_confluence)
                rsi_block_threshold = 15 if self.min_confluence >= 50 else 30
                if tf_15m['rsi'] > rsi_block_threshold:
                    logger.debug(f"{symbol}: Blocked LONG by Trend Guardian (Bearish Macro)")
                    return None

        # Обязательные условия
        if tf_15m['rsi'] > rsi_limit or not tf_15m.get('below_bb_lower'):
            return None
        
        confluence = ConfluenceScore()
        reasoning = []
        warnings = []
        
        current = df_15m.iloc[-1]
        
        # === RSI (0-25) ===
        rsi = tf_15m['rsi']
        if rsi < 15:
            confluence.add_factor('RSI', 25, 25)
            reasoning.append(f"🔥 RSI={rsi:.1f} ЭКСТРЕМУМ")
        # === RSI (0-20) ===
        rsi = tf_15m['rsi']
        if rsi < 15:
            confluence.add_factor('RSI', 20, 20)
            reasoning.append(f"🔥 RSI={rsi:.1f} ЭКСТРЕМУМ")
        elif rsi < 25:
            confluence.add_factor('RSI', 15, 20)
            reasoning.append(f"RSI={rsi:.1f} перепродан")
        else:
            confluence.add_factor('RSI', 5, 20)
        
        # === Bollinger Bands (0-15) ===
        bb_pos = tf_15m['bb_position']
        if bb_pos < -0.1:
            confluence.add_factor('Bollinger Bands', 15, 15)
            reasoning.append("📉 Цена ниже BB Lower")
        elif bb_pos < 0:
            confluence.add_factor('Bollinger Bands', 10, 15)
        
        # === MTF Alignment (0-20) ===
        mtf = self.mtf_analyzer.check_alignment(tf_15m, tf_1h, tf_4h, 'LONG')
        mtf_score = min(mtf['score'] // 5, 20)
        confluence.add_factor('Multi-Timeframe', mtf_score, 20)
        for detail in mtf['details'].values():
            reasoning.append(detail)
        
        # === Support/Resistance (0-15) ===
        sr_levels = self.sr_detector.find_levels(df_15m)
        nearest_support = self.sr_detector.find_nearest(sr_levels, current['close'], 'below')
        
        # Dynamic ATR Tolerance for Levels
        atr_val = float(self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1])
        level_tolerance = atr_val * 0.3
        
        if nearest_support:
            dist = abs(current['close'] - nearest_support.price)
            if dist < level_tolerance:
                confluence.add_factor('Support/Resistance', 15, 15)
                reasoning.append(f"🎯 У сильной поддержки ${nearest_support.price:,.2f}")
            elif dist < level_tolerance * 2:
                confluence.add_factor('Support/Resistance', 10, 15)
                reasoning.append(f"Близко к поддержке ${nearest_support.price:,.2f}")
        
        # === Volume (0-10) ===
        df_15m_copy = df_15m.copy()
        df_15m_copy['vol_ma'] = df_15m_copy['volume'].rolling(20).mean()
        vol_ratio = current['volume'] / df_15m_copy['vol_ma'].iloc[-1] if df_15m_copy['vol_ma'].iloc[-1] > 0 else 1
        
        if vol_ratio > 2.0:
            confluence.add_factor('Volume', 10, 10)
            reasoning.append(f"📊 Всплеск объёма ({vol_ratio:.1f}x)")
        elif vol_ratio > 1.5:
            confluence.add_factor('Volume', 7, 10)
        
        # === MACD (0-10) ===
        df_15m_copy['macd'], df_15m_copy['macd_signal'], df_15m_copy['macd_hist'] = self.ind.macd(df_15m_copy['close'])
        macd_turning = df_15m_copy['macd_hist'].iloc[-1] > df_15m_copy['macd_hist'].iloc[-2]
        
        if macd_turning:
            confluence.add_factor('MACD', 10, 10)
            reasoning.append("📈 MACD разворачивается вверх")
        
        # === Funding Rate (0-10) ===
        funding_interpretation = None
        if funding_rate is not None:
            if funding_rate < -0.001:
                confluence.add_factor('Funding Rate', 10, 10)
                reasoning.append(f"🔥 Экстремальный SHORT BIAS ({funding_rate*100:.3f}%)")
                funding_interpretation = "EXTREME_SHORT_BIAS"
            elif funding_rate < -0.0005:
                confluence.add_factor('Funding Rate', 7, 10)
                funding_interpretation = "HIGH_SHORT_BIAS"
        
        # === Order Book (0-5) ===
        if orderbook_imbalance is not None:
            if orderbook_imbalance > 1.5:
                confluence.add_factor('Order Book', 5, 5)
                reasoning.append(f"📗 Перевес покупателей {orderbook_imbalance:.2f}x")
            elif orderbook_imbalance > 1.2:
                confluence.add_factor('Order Book', 3, 5)
        
        # === Extra Oscillators (0-10) ===
        stoch_k, _ = self.ind.stochastic_rsi(df_15m['close'])
        williams = self.ind.williams_r(df_15m['high'], df_15m['low'], df_15m['close'])
        extra_score = 0
        if stoch_k.iloc[-1] < 20: extra_score += 5
        if williams.iloc[-1] < -80: extra_score += 5
        confluence.add_factor('Extra Oscillators', extra_score, 10)
        
        # === Fibonacci Entry Zone (0-10) ===
        fib_levels = self.ind.fibonacci_levels(df_15m['high'], df_15m['low'])
        fib_score = 0
        price = current['close']
        fib_tolerance = atr_val * 0.4
        
        if abs(price - fib_levels['0.618']) < fib_tolerance:
            fib_score = 10
            reasoning.append(f"🎯 Золотое сечение Фибо 0.618 (${fib_levels['0.618']:.2f})")
        elif abs(price - fib_levels['0.786']) < fib_tolerance:
            fib_score = 8
        elif abs(price - fib_levels['0.5']) < fib_tolerance:
            fib_score = 5
        confluence.add_factor('Fibonacci', fib_score, 10)
        
        # === Supertrend (0-10) ===
        _, st_dir = self.ind.supertrend(df_15m['high'], df_15m['low'], df_15m['close'])
        if st_dir.iloc[-1] == 1:
            confluence.add_factor('Supertrend', 10, 10)
            reasoning.append("📈 Supertrend подтверждает LONG")
        else:
            confluence.add_factor('Supertrend', 0, 10)
            warnings.append("⚠️ Против Supertrend")
        
        # === Проверка минимального score ===
        if confluence.percentage < self.min_confluence:
            return None
        
        # === Entry/SL/TP (Dynamic Phase 5) ===
        entry = float(current['close'])
        atr_val = float(self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1])
        
        # Динамический множитель SL в зависимости от режима
        # В волатильном боковике даем больше "воздуха"
        sl_multiplier = 2.5 if regime == MarketRegime.RANGING_WIDE else 2.0
        stop_loss = entry - (sl_multiplier * atr_val)
        
        if nearest_support:
            sl_sr = nearest_support.price - (0.5 * atr_val)
            stop_loss = max(stop_loss, sl_sr) # Не ставим стоп слишком далеко от S/R
        
        df_15m_copy['bb_upper'], df_15m_copy['bb_middle'], df_15m_copy['bb_lower'] = self.ind.bollinger_bands(df_15m_copy['close'])
        
        # Динамический TP (Фаза 5)
        # 1. Если ADX растет, значит тренд усиливается -> держим до BB Upper
        # 2. Если BB Width большой (высокая волатильность) -> ставим цели более агрессивно
        
        adx_current = tf_15m.get('adx', 0)
        adx_prev = df_15m_copy['adx'].iloc[-2]
        bb_width = tf_15m.get('bb_width', 0)
        
        adx_growing = adx_current > adx_prev
        
        if adx_growing or bb_width > 0.05:
             # Агрессивный выход
             take_profit_1 = float(df_15m_copy['bb_upper'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_upper'].iloc[-1]) * 1.015
        else:
             # Консервативный выход (возврат к среднему)
             take_profit_1 = float(df_15m_copy['bb_middle'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_upper'].iloc[-1])
        
        risk = entry - stop_loss
        reward = take_profit_1 - entry
        
        if risk <= 0 or (reward / risk) < self.min_rr:
            logger.debug(f"{symbol}: LONG RR too low ({reward/risk:.2f})")
            return None
        
        # Warnings
        if regime == MarketRegime.WEAK_TREND_DOWN:
            warnings.append("⚠️ Слабый нисходящий тренд")
        
        probability = self._calc_probability(confluence)
        
        return AdvancedSignal(
            signal_type=SignalType.LONG,
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confluence=confluence,
            probability=probability,
            strength=confluence.get_strength(),
            timeframes_aligned={'15m': True, '1h': mtf['score'] >= 30, '4h': mtf['score'] >= 50},
            support_resistance_nearby=nearest_support,
            market_regime=regime,
            risk_reward_ratio=round(reward / risk, 2),
            position_size_percent=self._calc_position_size(probability),
            funding_rate=funding_rate,
            funding_interpretation=funding_interpretation,
            orderbook_imbalance=orderbook_imbalance,
            timestamp=datetime.now(),
            valid_until=datetime.now() + timedelta(hours=4),
            indicators={
                'rsi_15m': tf_15m['rsi'],
                'rsi_1h': tf_1h.get('rsi', 50),
                'rsi_4h': tf_4h.get('rsi'),
                'bb_position': bb_pos,
                'vol_ratio': vol_ratio,
                'atr_pct': (atr_val / entry) * 100 if entry > 0 else 0,
                'trend_adx': tf_15m.get('adx', 0),
                'funding_rate': funding_rate or 0,
                'hour_of_day': datetime.now().hour,
                'rsi_slope': tf_15m.get('rsi_slope', 0),
                'ema_dist': tf_15m.get('ema_dist', 0),
                'bb_width': tf_15m.get('bb_width', 0),
                'vol_zscore': tf_15m.get('vol_zscore', 0)
            },
            reasoning=reasoning,
            warnings=warnings
        )
    
    def _check_short(
        self, df_15m, tf_15m, tf_1h, tf_4h, symbol, regime,
        funding_rate, orderbook_imbalance
    ) -> Optional[AdvancedSignal]:
        """Зеркальная логика для SHORT"""
        
        # Dynamic RSI Thresholds
        adx = tf_15m.get('adx', 0)
        rsi_limit = 75 if adx > 30 else 70

        # === TREND GUARDIAN (Block counter-trend entries) ===
        if tf_1h.get('valid'):
            # If price is above 1H EMA 200 AND trend is strong up, BLOCK SHORT
            is_bullish_macro = tf_1h.get('ema_dist', 0) > 0.5 and tf_1h.get('trend_direction') == 'up'
            
            if is_bullish_macro:
                # Relax for AGGRESSIVE mode (low min_confluence)
                rsi_block_threshold = 85 if self.min_confluence >= 50 else 70
                if tf_15m['rsi'] < rsi_block_threshold:
                    logger.debug(f"{symbol}: Blocked SHORT by Trend Guardian (Bullish Macro)")
                    return None
        
        confluence = ConfluenceScore()
        reasoning = []
        warnings = []
        
        current = df_15m.iloc[-1]
        atr_val = float(self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1])
        
        # RSI
        rsi = tf_15m['rsi']
        if rsi > 85:
            confluence.add_factor('RSI', 25, 25)
            reasoning.append(f"🔥 RSI={rsi:.1f} ЭКСТРЕМУМ")
        elif rsi > 80:
            confluence.add_factor('RSI', 20, 25)
            reasoning.append(f"RSI={rsi:.1f} сильно перекуплен")
        elif rsi > 75:
            confluence.add_factor('RSI', 15, 25)
            reasoning.append(f"RSI={rsi:.1f} перекуплен")
        else:
            confluence.add_factor('RSI', 10, 25)
        
        # BB
        bb_pos = tf_15m['bb_position']
        if bb_pos > 1.1:
            confluence.add_factor('Bollinger Bands', 15, 15)
            reasoning.append("Сильно выше BB Upper")
        elif bb_pos > 1.0:
            confluence.add_factor('Bollinger Bands', 10, 15)
            reasoning.append("Выше BB Upper")
        
        # MTF
        mtf = self.mtf_analyzer.check_alignment(tf_15m, tf_1h, tf_4h, 'SHORT')
        mtf_score = min(mtf['score'] // 4, 25)
        confluence.add_factor('Multi-Timeframe', mtf_score, 25)
        for detail in mtf['details'].values():
            reasoning.append(detail)
        
        # S/R
        sr_levels = self.sr_detector.find_levels(df_15m)
        nearest_support = self.sr_detector.find_nearest(sr_levels, current['close'], 'below')
        
        for level in sr_levels:
            if level.level_type == 'resistance':
                dist = abs(current['close'] - level.price) / current['close']
                if dist < 0.005:
                    confluence.add_factor('Support/Resistance', 15, 15)
                    reasoning.append(f"🎯 У сопротивления ${level.price:,.2f}")
                    break
                elif dist < 0.01:
                    confluence.add_factor('Support/Resistance', 10, 15)
                    break
        
        # Volume
        df_15m_copy = df_15m.copy()
        df_15m_copy['vol_ma'] = df_15m_copy['volume'].rolling(20).mean()
        vol_ratio = current['volume'] / df_15m_copy['vol_ma'].iloc[-1] if df_15m_copy['vol_ma'].iloc[-1] > 0 else 1
        
        # Calculate ADX for DataFrame (Required for Dynamic TP)
        df_15m_copy['adx'] = self.ind.adx(df_15m_copy['high'], df_15m_copy['low'], df_15m_copy['close'])[0]
        
        if vol_ratio > 2.0:
            confluence.add_factor('Volume', 10, 10)
            reasoning.append(f"📊 Объём {vol_ratio:.1f}x")
        elif vol_ratio > 1.5:
            confluence.add_factor('Volume', 7, 10)
        
        # MACD
        df_15m_copy['macd'], _, df_15m_copy['macd_hist'] = self.ind.macd(df_15m_copy['close'])
        if df_15m_copy['macd_hist'].iloc[-1] < df_15m_copy['macd_hist'].iloc[-2]:
            confluence.add_factor('MACD', 8, 10)
            reasoning.append("MACD разворачивается вниз")
        
        # Funding Rate (для SHORT: много лонгов = хорошо)
        funding_interpretation = None
        if funding_rate is not None:
            if funding_rate > 0.001:
                confluence.add_factor('Funding Rate', 10, 10)
                reasoning.append(f"🔥 Funding={funding_rate*100:.3f}% ЭКСТРЕМУМ LONG")
                funding_interpretation = "EXTREME_LONG_BIAS"
            elif funding_rate > 0.0005:
                confluence.add_factor('Funding Rate', 7, 10)
                reasoning.append(f"Funding={funding_rate*100:.3f}% много лонгов")
                funding_interpretation = "HIGH_LONG_BIAS"
            elif funding_rate > 0:
                confluence.add_factor('Funding Rate', 4, 10)
                funding_interpretation = "SLIGHT_LONG_BIAS"
        
        # Order Book (для SHORT: больше продавцов = хорошо)
        if orderbook_imbalance is not None:
            if orderbook_imbalance < 0.67:
                confluence.add_factor('Order Book', 5, 5)
                reasoning.append(f"📕 Стакан: продавцы {1/orderbook_imbalance:.2f}x")
            elif orderbook_imbalance < 0.83:
                confluence.add_factor('Order Book', 3, 5)
        
        # === Extra Oscillators (0-10) ===
        stoch_k, _ = self.ind.stochastic_rsi(df_15m['close'])
        williams = self.ind.williams_r(df_15m['high'], df_15m['low'], df_15m['close'])
        extra_score = 0
        if stoch_k.iloc[-1] > 80: extra_score += 5
        if williams.iloc[-1] > -20: extra_score += 5
        confluence.add_factor('Extra Oscillators', extra_score, 10)

        # === Fibonacci Entry Zone (0-10) ===
        fib_levels = self.ind.fibonacci_levels(df_15m['high'], df_15m['low'])
        fib_score = 0
        price = current['close']
        fib_tolerance = atr_val * 0.4
        
        if abs(price - fib_levels['0.618']) < fib_tolerance:
            fib_score = 10
            reasoning.append(f"🎯 Золотое сечение Фибо 0.618 (${fib_levels['0.618']:.2f})")
        elif abs(price - fib_levels['0.786']) < fib_tolerance:
            fib_score = 8
        elif abs(price - fib_levels['0.5']) < fib_tolerance:
            fib_score = 5
        confluence.add_factor('Fibonacci', fib_score, 10)
        
        # === Supertrend (0-10) ===
        _, st_dir = self.ind.supertrend(df_15m['high'], df_15m['low'], df_15m['close'])
        if st_dir.iloc[-1] == -1:
            confluence.add_factor('Supertrend', 10, 10)
            reasoning.append("📉 Supertrend подтверждает SHORT")
        else:
            confluence.add_factor('Supertrend', 0, 10)
            warnings.append("⚠️ Против Supertrend")
        
        if confluence.percentage < self.min_confluence:
            return None
        
        # === Entry/SL/TP (Dynamic Phase 5) ===
        entry = float(current['close'])
        atr_val = float(self.ind.atr(df_15m['high'], df_15m['low'], df_15m['close']).iloc[-1])
        
        # Динамический множитель SL
        sl_multiplier = 2.5 if regime == MarketRegime.RANGING_WIDE else 2.0
        stop_loss = entry + (sl_multiplier * atr_val)
        
        # Calculate Bollinger Bands (Moved up for TP calculation)
        df_15m_copy['bb_upper'], df_15m_copy['bb_middle'], df_15m_copy['bb_lower'] = self.ind.bollinger_bands(df_15m_copy['close'])
        
        # Динамический TP (Фаза 5)
        adx_current = tf_15m.get('adx', 0)
        adx_prev = df_15m_copy['adx'].iloc[-2]
        bb_width = tf_15m.get('bb_width', 0)
        
        adx_growing = adx_current > adx_prev
        
        if adx_growing or bb_width > 0.05:
             # Агрессивный выход (до нижней границы)
             take_profit_1 = float(df_15m_copy['bb_lower'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_lower'].iloc[-1]) * 0.985
        else:
             # Консервативный выход (до средней)
             take_profit_1 = float(df_15m_copy['bb_middle'].iloc[-1])
             take_profit_2 = float(df_15m_copy['bb_lower'].iloc[-1])
             
        risk = stop_loss - entry
        reward = entry - take_profit_1
        
        if risk <= 0 or (reward / risk) < self.min_rr:
            logger.debug(f"{symbol}: SHORT RR too low ({reward/risk:.2f})")
            return None
        
        if regime == MarketRegime.WEAK_TREND_UP:
            warnings.append("⚠️ Слабый восходящий тренд")
        
        probability = self._calc_probability(confluence)
        
        return AdvancedSignal(
            signal_type=SignalType.SHORT,
            symbol=symbol,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confluence=confluence,
            probability=probability,
            strength=confluence.get_strength(),
            timeframes_aligned={'15m': True, '1h': mtf['score'] >= 30, '4h': mtf['score'] >= 50},
            support_resistance_nearby=nearest_support,
            market_regime=regime,
            risk_reward_ratio=round(reward / risk, 2),
            position_size_percent=self._calc_position_size(probability),
            funding_rate=funding_rate,
            funding_interpretation=funding_interpretation,
            orderbook_imbalance=orderbook_imbalance,
            timestamp=datetime.now(),
            valid_until=datetime.now() + timedelta(hours=4),
            indicators={
                'rsi_15m': tf_15m['rsi'],
                'rsi_1h': tf_1h.get('rsi', 50),
                'rsi_4h': tf_4h.get('rsi', 50),
                'bb_position': bb_pos,
                'vol_ratio': vol_ratio,
                'atr_pct': (atr_val / entry) * 100 if entry > 0 else 0,
                'trend_adx': tf_15m.get('adx', 0),
                'funding_rate': funding_rate or 0,
                'hour_of_day': datetime.now().hour,
                'rsi_slope': tf_15m.get('rsi_slope', 0),
                'ema_dist': tf_15m.get('ema_dist', 0),
                'bb_width': tf_15m.get('bb_width', 0),
                'vol_zscore': tf_15m.get('vol_zscore', 0)
            },
            reasoning=reasoning,
            warnings=warnings
        )
    
    def _calc_probability(self, confluence: ConfluenceScore) -> int:
        score = confluence.percentage
        if score >= 95:
            return min(92, int(85 + (score - 95) * 0.7))
        elif score >= 85:
            return int(85 + (score - 85) * 0.5)
        elif score >= 75:
            return int(80 + (score - 75) * 0.5)
        elif score >= 70:
            return int(75 + (score - 70) * 1.0)
        else:
            return int(60 + score * 0.2)
    
    def _calc_position_size(self, probability: int) -> float:
        if probability >= 90:
            return 2.0
        elif probability >= 85:
            return 1.5
        elif probability >= 80:
            return 1.0
        else:
            return 0.5


# ============================================================
# SIGNAL FORMATTER
# ============================================================

def format_signal(signal: AdvancedSignal, balance: float = 100) -> str:
    """Форматирует сигнал для отображения"""
    
    emoji = '🟢' if signal.signal_type == SignalType.LONG else '🔴'
    direction = 'LONG' if signal.signal_type == SignalType.LONG else 'SHORT'
    
    if signal.signal_type == SignalType.LONG:
        sl_pct = (signal.entry_price - signal.stop_loss) / signal.entry_price * 100
        tp1_pct = (signal.take_profit_1 - signal.entry_price) / signal.entry_price * 100
        tp2_pct = (signal.take_profit_2 - signal.entry_price) / signal.entry_price * 100
    else:
        sl_pct = (signal.stop_loss - signal.entry_price) / signal.entry_price * 100
        tp1_pct = (signal.entry_price - signal.take_profit_1) / signal.entry_price * 100
        tp2_pct = (signal.entry_price - signal.take_profit_2) / signal.entry_price * 100
    
    risk_amount = balance * (signal.position_size_percent / 100)
    position_usd = risk_amount / (sl_pct / 100) if sl_pct > 0 else 0
    
    output = f"""
{'═'*65}
{emoji} {signal.symbol} │ {direction} │ {signal.strength.value} {emoji}
{'═'*65}

📊 CONFLUENCE: {signal.confluence.percentage:.0f}/100
{signal.confluence.get_breakdown()}

🎯 ВЕРОЯТНОСТЬ: {signal.probability}%

{'─'*65}
💰 ВХОД:     ${signal.entry_price:,.4f}
🎯 ЦЕЛЬ 1:   ${signal.take_profit_1:,.4f}  (+{tp1_pct:.2f}%)
🎯 ЦЕЛЬ 2:   ${signal.take_profit_2:,.4f}  (+{tp2_pct:.2f}%)
🛑 СТОП:     ${signal.stop_loss:,.4f}  (-{sl_pct:.2f}%)
⚖️ R:R:      1:{signal.risk_reward_ratio}

{'─'*65}
✅ ПРИЧИНЫ:
"""
    
    for reason in signal.reasoning:
        output += f"   • {reason}\n"
    
    if signal.funding_rate is not None:
        output += f"\n📈 BYBIT DATA:\n"
        output += f"   Funding Rate: {signal.funding_rate*100:.4f}% ({signal.funding_interpretation})\n"
        if signal.orderbook_imbalance:
            output += f"   Order Book: {signal.orderbook_imbalance:.2f}x\n"
    
    if signal.warnings:
        output += f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ:\n"
        for w in signal.warnings:
            output += f"   {w}\n"
    
    output += f"""
{'─'*65}
📐 ТАЙМФРЕЙМЫ: 15m {'✅' if signal.timeframes_aligned['15m'] else '❌'} │ 1h {'✅' if signal.timeframes_aligned['1h'] else '❌'} │ 4h {'✅' if signal.timeframes_aligned['4h'] else '❌'}
📈 РЕЖИМ: {signal.market_regime.value}

{'─'*65}
💼 ДЛЯ ${balance:.0f} (риск {signal.position_size_percent}%):
   Размер: ${position_usd:.2f}
   Риск: ${risk_amount:.2f}

⏰ Действителен до: {signal.valid_until.strftime('%H:%M')}
{'═'*65}
"""
    
    return output


# ============================================================
# TEST
# ============================================================

def generate_test_data(periods: int = 500) -> pd.DataFrame:
    np.random.seed(42)
    base = 50000
    noise = np.random.randn(periods) * 0.01
    mean_rev = np.zeros(periods)
    for i in range(1, periods):
        mean_rev[i] = mean_rev[i-1] * 0.95 + noise[i]
    prices = base * (1 + mean_rev)
    
    return pd.DataFrame({
        'time': pd.date_range(start='2024-01-01', periods=periods, freq='15min'),
        'open': prices,
        'high': prices * (1 + np.abs(np.random.randn(periods)) * 0.003),
        'low': prices * (1 - np.abs(np.random.randn(periods)) * 0.003),
        'close': prices * (1 + np.random.randn(periods) * 0.002),
        'volume': np.random.randint(100, 1000, periods) * 1000
    })


# ============================================================
# 🔥 ULTIMATE TRADING ENGINE (10/10!)
# ============================================================

class UltimateTradingEngine:
    """
    Ultimate Trading Engine v3.0
    
    Объединяет:
    - Продвинутый Mean Reversion движок
    - Momentum стратегию
    - Фильтр новостей (FinBERT)
    - Circuit Breaker & Kelly Sizing
    """
    def __init__(self, cryptopanic_key: str = None, total_capital: float = 10000, min_confluence: int = 75):
        self.mr_engine = AdvancedMeanReversionEngine(min_confluence=min_confluence)
        # Use torch check for FinBERT
        use_finbert = False
        try:
             import torch
             use_finbert = torch.cuda.is_available()
        except: pass
        
        # V4.1: Use Enhanced News Engine (drop-in replacement with confluence points)
        from enhanced_news_engine import EnhancedNewsEngine
        self.news_engine = EnhancedNewsEngine(
            cryptopanic_key=cryptopanic_key or os.getenv('CRYPTOPANIC_KEY'),
            cache_ttl=300,
        )
        # V4.1: Use Enhanced Risk Manager (drop-in replacement with full circuit breaker)
        from enhanced_risk_manager import EnhancedRiskManager
        self.risk_manager = EnhancedRiskManager(
            total_capital=total_capital,
            daily_loss_limit=0.05,
            max_drawdown_limit=0.15,
            max_positions=5,
            state_file="risk_state.json",
        )
        # V4.1: Use Enhanced Performance Tracker (drop-in replacement with Kelly sizing)
        from enhanced_performance import EnhancedPerformanceTracker
        self.performance_tracker = EnhancedPerformanceTracker(initial_capital=total_capital)
        
    def analyze(self, df_15m, df_1h, df_4h, symbol, funding_rate=None, orderbook_imbalance=None) -> Optional[AdvancedSignal]:
        # 1. Circuit Breaker & Limits
        if self.risk_manager.check_circuit_breaker():
            logger.warning(f"🚨 {symbol}: Circuit Breaker ACTIVE - Trading Paused")
            return None
        
        # 2. News Sentiment Filter
        news_bonus = 0
        if hasattr(self.news_engine, 'cryptopanic_key') and self.news_engine.cryptopanic_key:
            currency = symbol.replace("USDT", "").replace("USDC", "")[:3]
            news = self.news_engine.get_market_sentiment(currency)
            
            if news.get('critical_events'):
                logger.warning(f"🛑 {symbol}: Critical news detected!")
                return None
                
            if news.get('score', 0) < -0.5:
                return None
            
            # V4.1: Use confluence points from EnhancedNewsEngine
            cp = news.get('confluence_points', 0)
            if cp > 0:
                news_bonus = min(cp * 2, 15)   # Positive: up to +15 
            elif cp < 0:
                news_bonus = max(cp * 2, -10)  # Negative: down to -10

        # 3. Market Regime & Strategy Routing
        ind = TechnicalIndicators()
        adx, _, _ = ind.adx(df_4h['high'], df_4h['low'], df_4h['close'])
        current_adx = adx.iloc[-1]
        
        # Bollinger Width for Breakout detection
        bb_upper, _, bb_lower = ind.bollinger_bands(df_1h['close'])
        bb_width = (bb_upper - bb_lower) / bb_upper
        
        if current_adx > 30:
            # TRENDING: Use Momentum
            signal = self._analyze_momentum(df_15m, symbol)
            strategy_name = "Momentum (Trend)"
        elif bb_width.iloc[-1] < 0.02:
            # SQUEEZE: Use Breakout
            signal = self._analyze_breakout(df_15m, symbol)
            strategy_name = "Breakout Hunter"
        else:
            # RANGING: Use Mean Reversion
            signal = self.mr_engine.analyze(df_15m, df_1h, df_4h, symbol, funding_rate, orderbook_imbalance)
            strategy_name = "Mean Reversion"
            
        if not signal: return None
        
        # 4. Integrate News Bonus
        if news_bonus > 0:
            signal.confluence.add_factor("News Alpha", news_bonus, 15)
            signal.reasoning.append(f"📰 News Alpha Alignment (+{news_bonus})")

        # 5. Kelly position sizing
        stats = self.performance_tracker.get_stats()
        if stats.get('total_trades', 0) >= 10:
            win_rate = stats['win_rate']
            p_ratio = stats['avg_win'] / stats['avg_loss'] if stats['avg_loss'] > 0 else 2.0
            k_pct = max(0.01, min(((win_rate * p_ratio - (1 - win_rate)) / p_ratio) * 0.25, 0.03))
            signal.position_size_percent = k_pct * 100
        
        return signal

    def _analyze_momentum(self, df, symbol) -> Optional[AdvancedSignal]:
        """EMA Momentum Cross + ADX Confirmation"""
        ind = TechnicalIndicators()
        ema9 = ind.ema(df['close'], 9)
        ema21 = ind.ema(df['close'], 21)
        adx, plus_di, minus_di = ind.adx(df['high'], df['low'], df['close'])
        
        curr = df.iloc[-1]
        if ema9.iloc[-1] > ema21.iloc[-1] and plus_di.iloc[-1] > minus_di.iloc[-1] and adx.iloc[-1] > 25:
            conf = ConfluenceScore(max_possible=135)
            conf.add_factor("Momentum Trend", 40, 40)
            conf.add_factor("ADX Power", 30, 30)
            entry = float(curr['close'])
            atr = ind.atr(df['high'], df['low'], df['close']).iloc[-1]
            return AdvancedSignal(
                signal_type=SignalType.LONG, symbol=symbol, entry_price=entry,
                stop_loss=entry - 2.5*atr, take_profit_1=entry + 3.5*atr,
                take_profit_2=entry + 6*atr, confluence=conf, probability=78,
                market_regime=MarketRegime.STRONG_TREND_UP, reasoning=["Momentum: EMA Cross + ADX > 25"]
            )
        return None

    def _analyze_breakout(self, df, symbol) -> Optional[AdvancedSignal]:
        """Volatility Squeeze Breakout"""
        ind = TechnicalIndicators()
        upper, mid, lower = ind.bollinger_bands(df['close'])
        curr = df.iloc[-1]
        
        if curr['close'] > upper.iloc[-1] and curr['volume'] > df['volume'].rolling(20).mean().iloc[-1] * 1.5:
            conf = ConfluenceScore(max_possible=135)
            conf.add_factor("BB Breakout", 50, 50)
            conf.add_factor("Volume Spike", 30, 30)
            entry = float(curr['close'])
            return AdvancedSignal(
                signal_type=SignalType.LONG, symbol=symbol, entry_price=entry,
                stop_loss=mid.iloc[-1], take_profit_1=entry + (entry - mid.iloc[-1]) * 2,
                take_profit_2=entry + (entry - mid.iloc[-1]) * 4, confluence=conf,
                probability=72, market_regime=MarketRegime.VOLATILE_BREAKOUT,
                reasoning=["Breakout: Price closed above BB Upper with Volume"]
            )
        return None

    def record_trade(self, trade: Trade):
        self.performance_tracker.add_trade(trade)
        self.risk_manager.daily_pnl += trade.pnl
        self.risk_manager.total_capital += trade.pnl


if __name__ == "__main__":
    print("Testing Advanced Mean Reversion Engine (Bybit Edition)...")
    
    engine = AdvancedMeanReversionEngine(min_confluence=70)
    
    df_15m = generate_test_data(500)
    df_1h = df_15m.iloc[::4].reset_index(drop=True)
    df_4h = df_15m.iloc[::16].reset_index(drop=True)
    
    signal = engine.analyze(
        df_15m, df_1h, df_4h, 'BTCUSDT',
        funding_rate=-0.0008,  # Симулируем экстремальный short bias
        orderbook_imbalance=1.6
    )
    
    if signal:
        print(format_signal(signal, balance=500))
    else:
        print("Нет сигналов с достаточным confluence score")
