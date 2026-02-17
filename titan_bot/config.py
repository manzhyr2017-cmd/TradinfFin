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
API_KEY = os.getenv("BYBIT_API_KEY")
API_SECRET = os.getenv("BYBIT_API_SECRET")
TESTNET_STR = os.getenv("TESTNET", "False").lower()
TESTNET = TESTNET_STR == "true"

# Валидация
if not API_KEY or API_KEY == "your_key":
    print("⚠️ WARNING: BYBIT_API_KEY NOT FOUND! Check your .env file.")
else:
    print(f"✅ BYBIT_API_KEY loaded: {API_KEY[:4]}****")

if not API_SECRET or API_SECRET == "your_secret":
    print("⚠️ WARNING: BYBIT_API_SECRET NOT FOUND!")


# === ТОРГОВЫЕ ПАРАМЕТРЫ ===
SYMBOL = "ETHUSDT"           # Что торгуем
BENCHMARK = "BTCUSDT"        # На что смотрим как на индикатор рынка
TIMEFRAME = "15"             # Таймфрейм в минутах
CATEGORY = "linear"          # linear = фьючерсы USDT

# === РИСК-МЕНЕДЖМЕНТ ===
INITIAL_DEPOSIT = 300        # Начальный депозит
RISK_PER_TRADE = 0.02        # Риск на сделку (2%)
MAX_DAILY_LOSS = 0.06        # Макс. дневная потеря (6% = стоп на день)
MIN_RR_RATIO = 2.5           # Минимальный Risk/Reward (1:2.5)
MAX_POSITIONS = 1            # Макс. одновременных позиций

# === ORDER FLOW ===
ORDERBOOK_DEPTH = 50         # Глубина стакана для анализа
IMBALANCE_THRESHOLD = 0.65   # Порог дисбаланса (65% = сильная стенка)
VOLUME_SPIKE_MULT = 2.5      # Множитель для детекции аномального объема

# === FUNDING ===
FUNDING_LONG_THRESHOLD = 0.01    # Выше = толпа в лонгах (опасно для лонга)
FUNDING_SHORT_THRESHOLD = -0.005 # Ниже = толпа в шортах (опасно для шорта)

# === SMC (Smart Money Concepts) ===
SWING_LOOKBACK = 20          # Свечей назад для поиска swing high/low
SFP_CONFIRMATION_PIPS = 0.001 # Минимальный прокол уровня (0.1%)

# === MACHINE LEARNING ===
ML_MODEL_PATH = "models/titan_model.pkl"
ML_TRAINING_DAYS = 30        # Дней данных для обучения
ML_CONFIDENCE_THRESHOLD = 0.7 # Минимальная уверенность модели

# === ТАЙМЕРЫ ===
ANALYSIS_INTERVAL = 60       # Секунд между анализами (для REST API)
WEBSOCKET_ENABLED = True     # Использовать WebSocket для реалтайма
