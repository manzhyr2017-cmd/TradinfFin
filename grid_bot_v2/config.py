import os
from dotenv import load_dotenv

load_dotenv()

# --- API Configuration ---
BYBIT_API_KEY = os.getenv('BYBIT_API_KEY', 'YOUR_KEY')
BYBIT_API_SECRET = os.getenv('BYBIT_API_SECRET', 'YOUR_SECRET')
BYBIT_DEMO = os.getenv('BYBIT_DEMO', 'false').lower() == 'true'

# --- Bot Configuration ---
SYMBOL = "ETHUSDT"
GRID_LEVELS = 10
GRID_STEP_PERCENT = 0.5  # Percentage between levels
BASE_ORDER_QTY = 0.05    # Size of one order in ETH
LEVERAGE = 1             # Leverage for Spot/Margin

# --- Indicators Configuration ---
EMA_PERIOD = 200
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# --- Telegram Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
# Trading Fees
MAKER_FEE_PCT = float(os.getenv('MAKER_FEE_PCT', 0.02))
