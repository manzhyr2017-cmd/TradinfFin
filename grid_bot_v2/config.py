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
GRID_LEVELS = 10
GRID_STEP_PERCENT = 0.5  # Percentage between levels
BASE_ORDER_QTY = 0.05    # Size of one order in ETH
LEVERAGE = 1             # Leverage for Spot/Margin

# --- Risk & Sizing ---
MAX_DRAWDOWN_PCT = 5.0
USE_DYNAMIC_QTY = True
DYNAMIC_QTY_BALANCE_PCT = 0.5 # % of balance for one level
MIN_ORDER_QTY = 0.001
MAX_ORDER_QTY = 1.0
MAKER_FEE_PCT = float(os.getenv('MAKER_FEE_PCT', 0.02))
VELOCITY_THRESHOLD_PCT = 2.0 # Max price change in 5m
MAX_API_LATENCY_MS = 500
BTC_SYMBOL = "BTCUSDT"

# --- Indicators & Strategy ---
EMA_PERIOD = 200
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
USE_ARBITRAGE = False
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
