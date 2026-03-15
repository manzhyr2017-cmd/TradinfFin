import os
from dotenv import load_dotenv

load_dotenv()

# --- API Configuration ---
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY', 'YOUR_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', 'YOUR_SECRET')
BYBIT_DEMO = os.getenv('BYBIT_DEMO', 'false').lower() == 'true'
API_PROXY = os.getenv('API_PROXY', None) # 'http://user:pass@host:port'
CATEGORY = "linear"

# --- Bot Configuration ---
SYMBOL = "ETHUSDT"
QUOTE_COIN = "USDT"
GRID_LEVEL_COUNT = 15
GRID_STEP_PERCENT = 0.5
GRID_LOWER_PRICE = 1900.0   # НИЖНЯЯ ГРАНИЦА СЕТКИ
GRID_UPPER_PRICE = 2300.0   # ВЕРХНЯЯ ГРАНИЦА СЕТКИ
BASE_ORDER_QTY = 0.02
LEVERAGE = 1

# --- Risk & Sizing ---
STOP_LOSS_PCT = 5.0          # Стоп-лосс от нижней границы
MAX_DRAWDOWN_USDT = 100.0    # Макс. просадка в долларах
DAILY_LOSS_LIMIT_USDT = 50.0  # Дневной лимит убытка
USE_DYNAMIC_QTY = True
DYNAMIC_QTY_BALANCE_PCT = 0.5 
MIN_ORDER_QTY = 0.001
MAX_ORDER_QTY = 1.0
MAKER_FEE_PCT = float(os.getenv('MAKER_FEE_PCT', 0.02))
VELOCITY_THRESHOLD_PCT = 2.0 
MAX_API_LATENCY_MS = 500
BTC_SYMBOL = "BTCUSDT"

# --- Indicators & Strategy ---
EMA_PERIOD = 200
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
USE_ARBITRAGE = False
USE_DELTA_NEUTRAL = False      # Выключим пока для простоты
STATS_INTERVAL_CYCLES = 100

# --- Bybit Specific Optimizations ---
USE_POST_ONLY = True
USE_BATCH_ORDERS = True
CHECK_VIP_STATUS = True
BIT_FEE_DISCOUNT = False 

# --- Auto-Compounding (v4.0) ---
COMPOUND_MODE = "hybrid"       # "qty", "grid", or "hybrid"
MIN_COMPOUND_USDT = 10.0       # Reinvest every $10 profit
INITIAL_CAPITAL = 1000.0       # For ROI calculation

# --- Hybrid Grid + DCA (v4.0) ---
DCA_ENABLED = True
DCA_MAX_LEVELS = 5
DCA_STEP_PCT = 2.0

# --- Infinity Grid (v4.0) ---
INFINITY_MODE = False           # Set True to remove upper bound
INFINITY_TRAILING_PCT = 3.0    # Trail floor 3% below price

# --- Telegram Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
