"""
TITAN BOT 2026 - НАСТРОЙКИ ДЛЯ АКТИВНОЙ ТОРГОВЛИ
Версия: AGGRESSIVE MODE
"""

# === API BYBIT ===
# API_KEY = "твой_api_key"  # Keeping existing logic to load from env
# API_SECRET = "твой_api_secret"
TESTNET = True  # Пока тестируем!

# === ТОРГОВЫЕ ПАРЫ ===
# Можно переключать или запускать несколько инстансов
SYMBOL = "ETHUSDT"        # или "BTCUSDT" или "SOLUSDT"
BENCHMARK = "BTCUSDT"
TIMEFRAME = "15"
CATEGORY = "linear"

# === РИСК-МЕНЕДЖМЕНТ ===
INITIAL_DEPOSIT = 300
RISK_PER_TRADE = 0.02     # 2% риска на сделку
MAX_DAILY_LOSS = 0.10     # 10% макс дневной убыток (было 6%)
MIN_RR_RATIO = 2.0        # Risk/Reward 1:2 (было 2.5)
MAX_POSITIONS = 3         # Теперь можем держать 3 позиции (было 1)

# === ФИЛЬТРЫ - ОСЛАБЛЯЕМ! ===

# Session Filter - ОТКЛЮЧАЕМ или ослабляем
SESSION_FILTER_ENABLED = False  # Торгуем 24/7
SESSION_MIN_QUALITY = 3         # Было 6, теперь 3 (почти всегда проходит)

# News Filter - ОСЛАБЛЯЕМ
NEWS_FILTER_ENABLED = True
NEWS_DANGER_HOURS_BEFORE = 1    # Было 2 часа, теперь 1

# Correlation Filter - ОСЛАБЛЯЕМ
CORRELATION_FILTER_ENABLED = True
CORRELATION_MIN_SAFE = 0.3      # Было выше, теперь почти всегда проходит

# BTC Filter - ОСЛАБЛЯЕМ
BTC_FILTER_ENABLED = True
BTC_MIN_CHANGE = -0.02          # Было -0.005, теперь -2% (BTC может падать на 2%)

# === COMPOSITE SCORE - КЛЮЧЕВОЕ! ===
COMPOSITE_STRONG_THRESHOLD = 40   # Было 60, снижаем
COMPOSITE_MODERATE_THRESHOLD = 25 # Было 40, снижаем
COMPOSITE_WEAK_THRESHOLD = 15     # Было 20, снижаем
COMPOSITE_MIN_FOR_ENTRY = 20      # Минимальный скор для входа (было ~40)

# === SMC СИГНАЛЫ - ОСЛАБЛЯЕМ ===
SWING_LOOKBACK = 10              # Было 20, ищем более близкие свинги
SFP_CONFIRMATION_PIPS = 0.0005   # Было 0.001, теперь чувствительнее

# === ORDER FLOW - ОСЛАБЛЯЕМ ===
ORDERBOOK_DEPTH = 25             # Было 50
IMBALANCE_THRESHOLD = 0.55       # Было 0.65, теперь легче пройти

# === MTF - ОСЛАБЛЯЕМ ===
MTF_STRICT_MODE = False          # Не требуем идеального совпадения всех ТФ
MTF_MIN_CONFIDENCE = 0.5         # Было выше

# === COOLDOWN - ОСЛАБЛЯЕМ ===
COOLDOWN_ENABLED = True
COOLDOWN_LOSSES_BEFORE = 3       # Было 2, теперь после 3 убытков
COOLDOWN_SHORT_MINUTES = 15      # Было 30
COOLDOWN_MEDIUM_MINUTES = 60     # Было 120

# === РЕЖИМ ТОРГОВЛИ ===
TRADE_MODE = "AGGRESSIVE"        # "CONSERVATIVE", "MODERATE", "AGGRESSIVE"

# === ТАЙМЕР ===
ANALYSIS_INTERVAL = 30           # Проверяем каждые 30 сек (было 60)
WEBSOCKET_ENABLED = True
