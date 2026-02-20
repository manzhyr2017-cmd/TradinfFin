import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Пытаемся найти .env в текущей папке или в папке со скриптом
current_dir = Path(os.getcwd())
script_dir = Path(__file__).resolve().parent
env_paths = [current_dir / ".env", script_dir / ".env", current_dir.parent / ".env"]

env_loaded = False
for path in env_paths:
    if path.exists():
        load_dotenv(path)
        print(f"[Config] Loaded .env from {path}")
        env_loaded = True
        break

if not env_loaded:
    # Запасной вариант - стандартный поиск
    load_dotenv()

# === API BYBIT ===
# Принудительно перечитываем, если нужно
load_dotenv(override=True)

API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
TESTNET_STR = os.getenv("TESTNET", "False").lower()
TESTNET = TESTNET_STR == "true"
BYBIT_DEMO = os.getenv("BYBIT_DEMO", "False").lower() == "true"

# Валидация
mode = "DEMO" if BYBIT_DEMO else ("TESTNET" if TESTNET else "MAINNET")
if not API_KEY:
    print(f"⚠️ [Config] WARNING: BYBIT_API_KEY NOT FOUND! (Mode: {mode})")
else:
    print(f"✅ [Config] BYBIT_API_KEY loaded: {API_KEY[:4]}**** (Mode: {mode})")

if not API_SECRET or API_SECRET == "your_secret":
    print("⚠️ WARNING: BYBIT_API_SECRET NOT FOUND!")


# === ТОРГОВЫЕ ПАРАМЕТРЫ ===
SYMBOL = "ETHUSDT"           # Дефолтная пара
BENCHMARK = "BTCUSDT"        # На что смотрим как на индикатор рынка
MULTI_SYMBOL_ENABLED = True  # Сканировать несколько монет
MAX_SYMBOLS = 10             # Сколько монет в топе перебирать
TIMEFRAME = "15"             # Таймфрейм в минутах
CATEGORY = "linear"          # linear = фьючерсы USDT

# === ТЕКУЩИЙ РЕЖИМ ТОРГОВЛИ ===
TRADE_MODE = "AGGRESSIVE"    # "CONSERVATIVE", "MODERATE", "AGGRESSIVE", "SCALPER"

# === РИСК-МЕНЕДЖМЕНТ ===
INITIAL_DEPOSIT = 300        # Начальный депозит
RISK_PER_TRADE = 0.02        # Риск на сделку (2%)
MAX_DAILY_LOSS = 0.10        # Макс. дневная потеря (было 6%, теперь 10% для агрессивного)
MIN_RR_RATIO = 2.0           # Минимальный Risk/Reward (было 2.5, теперь 2.0)
MAX_POSITIONS = 3            # Макс. одновременных позиций (было 1, теперь 3)

# === ФИЛЬТРЫ - НАСТРОЙКИ ДЛЯ AGGRESSIVE ===
SESSION_FILTER_ENABLED = False  # Отключаем для агрессивного режима
SESSION_MIN_QUALITY = 2         # Почти любое время (было 5)

NEWS_FILTER_ENABLED = True
NEWS_DANGER_HOURS_BEFORE = 1    # Было 2, теперь 1
CORRELATION_FILTER_ENABLED = True
CORRELATION_MIN_SAFE = 0.3      # Ослаблено (было 0.5)

# === COMPOSITE SCORE - КЛЮЧЕВОЕ! ===
COMPOSITE_MIN_FOR_ENTRY = 35      # Минимальный скор для входа (был 30)
COMPOSITE_STRONG_THRESHOLD = 45   # Скор для СИЛЬНОГО сигнала (был 35)
COMPOSITE_MODERATE_THRESHOLD = 35 # Скор для умеренного сигнала (был 30)
MTF_STRICT_MODE = False          # Не требуем идеального совпадения всех ТФ

# === ORDER FLOW ===
ORDERBOOK_DEPTH = 25         # Глубина стакана (было 50)
IMBALANCE_THRESHOLD = 0.55   # Порог дисбаланса (было 0.65)
VOLUME_SPIKE_MULT = 2.0      # Было 2.5

# === FUNDING ===
FUNDING_LONG_THRESHOLD = 0.02    # Ослаблено
FUNDING_SHORT_THRESHOLD = -0.01  # Ослаблено

# === SMC (Smart Money Concepts) ===
SWING_LOOKBACK = 15          # Было 20
SFP_CONFIRMATION_PIPS = 0.0005 # Было 0.001

# === MACHINE LEARNING ===
ML_MODEL_PATH = "models/titan_model.pkl"
ML_TRAINING_DAYS = 30        # Дней данных для обучения
ML_CONFIDENCE_THRESHOLD = 0.6 # Было 0.7

# === ТАЙМЕРЫ ===
ANALYSIS_INTERVAL = 30       # Секунд между анализами (было 60)
WEBSOCKET_ENABLED = True     # Использовать WebSocket для реалтайма
