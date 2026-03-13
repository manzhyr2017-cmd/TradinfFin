"""
GRID BOT 2026 — Configuration
Сеточный бот для Bybit Futures (Мульти-Сканнер)
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from logger import logger

# === Загрузка .env ===
script_dir = Path(__file__).resolve().parent
ENV_PATHS = [
    Path(".env"),
    Path(__file__).parent / ".env",
    Path("d:/Projects/Trading/grid_bot/.env"),
]

for path in ENV_PATHS:
    if os.path.exists(path):
        load_dotenv(path)
        logger.info(f"[GridConfig] Loaded .env from {path}")
        break
else:
    load_dotenv()

# === API BYBIT ===
API_KEY = os.getenv("BYBIT_API_KEY", "dummy_api_key_for_testing_purposes_only")
API_SECRET = os.getenv("BYBIT_API_SECRET", "dummy_api_secret_for_testing_purposes_only_which_is_long")
TESTNET = os.getenv("TESTNET", "False").lower() == "true"
BYBIT_DEMO = os.getenv("BYBIT_DEMO", "False").lower() == "true"

# === TELEGRAM ===
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_CHANNEL = os.getenv("TELEGRAM_CHANNEL")
TG_ADMIN_ID = os.getenv("TELEGRAM_ADMIN_ID")

# === SCANNER & GRID PARAMETERS ===
# AUTO = сканер запускает топ пар, иначе (например ETHUSDT) = фокус на одну.
SYMBOL = os.getenv("GRID_SYMBOL", "AUTO")
CATEGORY = "linear"

AUTO_SCAN_TOP = int(os.getenv("AUTO_SCAN_TOP", "10"))
MAX_CONCURRENT_GRIDS = int(os.getenv("MAX_CONCURRENT_GRIDS", "3"))
MIN_VOLUME_24H = float(os.getenv("MIN_VOLUME_24H", "10000000"))  # 10M
ALLOCATION_PER_GRID = float(os.getenv("ALLOCATION_PER_GRID", "30.0"))  # 30% баланса на сетку

# Границы сетки (0 = авто: ±GRID_RANGE_PCT от текущей цены)
GRID_UPPER = float(os.getenv("GRID_UPPER", "0"))
GRID_LOWER = float(os.getenv("GRID_LOWER", "0"))
GRID_RANGE_PCT = float(os.getenv("GRID_RANGE_PCT", "10.0"))
REBALANCE_MODE = os.getenv("REBALANCE_MODE", "CLOSE_ALL").upper() 

# ATR Adaptive Step
USE_ATR_STEP = os.getenv("USE_ATR_STEP", "True").lower() == "true"
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
ATR_MULTIPLIER = float(os.getenv("ATR_MULTIPLIER", "1.5"))

# Smart Entry & Compounding
RSI_ENTRY_CHECK = os.getenv("RSI_ENTRY_CHECK", "True").lower() == "true"
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
AUTO_COMPOUND = os.getenv("AUTO_COMPOUND", "False").lower() == "true"

# Safety & Funding
MAX_FUNDING_RATE = float(os.getenv("MAX_FUNDING_RATE", "0.005")) 
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "15.0"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))

# Сетка и плечо
GRID_COUNT = int(os.getenv("GRID_COUNT", "10"))
INVESTMENT = float(os.getenv("GRID_INVESTMENT", "0"))
LEVERAGE = int(os.getenv("GRID_LEVERAGE", "3"))
REBALANCE_THRESHOLD = float(os.getenv("REBALANCE_THRESHOLD", "0.8")) 

GRID_MODE = os.getenv("GRID_MODE", "neutral")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "900"))  

# --- NEW: Advanced Features ---
TRAILING_GRID_ENABLED = os.getenv("TRAILING_GRID_ENABLED", "True").lower() == "true"
TRAILING_DEVIATION_PCT = float(os.getenv("TRAILING_DEVIATION_PCT", "1.5")) # Если цена ушла дальше этого % от центра сетки, двигаем её

# Лимиты на диверсификацию (предотвращение захода во все мемы или все гейминг сразу)
MAX_SYMBOLS_PER_SECTOR = int(os.getenv("MAX_SYMBOLS_PER_SECTOR", "2")) 
GRID_INACTIVITY_CLOSE_HOURS = int(os.getenv("GRID_INACTIVITY_CLOSE_HOURS", "24")) # Закрывать сетку через 24ч бездействия

# Защита накопленной прибыли (Trailling Stop-Loss для всей сетки)
PROFIT_TRAIILING_THRESHOLD = float(os.getenv("PROFIT_TRAIILING_THRESHOLD", "5.0")) # Начинаем следить при 5% прибыли
PROFIT_DRAWDOWN_CUTOFF = float(os.getenv("PROFIT_DRAWDOWN_CUTOFF", "20.0")) # Закрываем, если профит упал на 20% от максимума

# --- NEW: VPS Safety Guards ---
MAX_SPREAD_PCT = float(os.getenv("MAX_SPREAD_PCT", "0.3")) # Не входим, если спред > 0.3% (защита от неликвида)
FLASH_CRASH_PROTECTION = os.getenv("FLASH_CRASH_PROTECTION", "True").lower() == "true"
CRASH_THRESHOLD_PCT = float(os.getenv("CRASH_THRESHOLD_PCT", "5.0")) # Если BTC падает более чем на 5% за 15м, пауза entries

STATE_FILE = str(script_dir / "data" / "grid_state.db")

mode = "DEMO" if BYBIT_DEMO else ("TESTNET" if TESTNET else "MAINNET")
if not API_KEY:
    logger.warning(f"[GridConfig] BYBIT_API_KEY NOT FOUND! (Mode: {mode})")
else:
    logger.info(f"[GridConfig] Mode: {mode} | Max Grids: {MAX_CONCURRENT_GRIDS} | Alloc: {ALLOCATION_PER_GRID}%")
