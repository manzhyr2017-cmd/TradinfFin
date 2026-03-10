"""
GRID BOT 2026 — Configuration
Сеточный бот для Bybit Futures
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from logger import logger

# === Загрузка .env ===
script_dir = Path(__file__).resolve().parent
# Paths to check for .env (priority order)
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

# === GRID PARAMETERS ===
SYMBOL = os.getenv("GRID_SYMBOL", "ETHUSDT")
CATEGORY = "linear"  # Фьючерсы USDT

# Границы сетки (0 = авто-расчёт: ±GRID_RANGE_PCT от текущей цены)
GRID_UPPER = float(os.getenv("GRID_UPPER", "0"))
GRID_LOWER = float(os.getenv("GRID_LOWER", "0"))

# --- Strategy Settings ---
GRID_RANGE_PCT = float(os.getenv("GRID_RANGE_PCT", "10.0"))
REBALANCE_MODE = os.getenv("REBALANCE_MODE", "CLOSE_ALL").upper()  # CLOSE_ALL or HOLD_POSITION

# ATR Adaptive Step
USE_ATR_STEP = os.getenv("USE_ATR_STEP", "True").lower() == "true"
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
ATR_MULTIPLIER = float(os.getenv("ATR_MULTIPLIER", "1.5"))

# Smart Entry & Compounding
RSI_ENTRY_CHECK = os.getenv("RSI_ENTRY_CHECK", "False").lower() == "true"
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
AUTO_COMPOUND = os.getenv("AUTO_COMPOUND", "False").lower() == "true"

# Safety & Funding
MAX_FUNDING_RATE = float(os.getenv("MAX_FUNDING_RATE", "0.005"))  # 0.5% per epoch
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "15.0"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "10"))

# Количество уровней сетки (больше = мельче шаг = больше сделок)
GRID_COUNT = int(os.getenv("GRID_COUNT", "10"))

# Инвестиция (0 = весь доступный баланс)
INVESTMENT = float(os.getenv("GRID_INVESTMENT", "0"))

# Плечо
LEVERAGE = int(os.getenv("GRID_LEVERAGE", "3"))

# === RISK MANAGEMENT ===
MAX_DRAWDOWN_PCT = float(os.getenv("MAX_DRAWDOWN_PCT", "15.0"))  # Стоп при -15%
REBALANCE_THRESHOLD = float(os.getenv("REBALANCE_THRESHOLD", "0.8"))  # Перестроить при 80% выхода

# === GRID MODE ===
# "neutral"    — равномерная сетка вокруг цены
# "long_bias"  — 60% buy уровней, 40% sell (бычий)
# "short_bias" — 40% buy уровней, 60% sell (медвежий)
GRID_MODE = os.getenv("GRID_MODE", "neutral")

# === TIMING ===
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "5"))  # Секунд между проверками
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", "900"))  # 15 мин heartbeat в ТГ

# === STATE ===
STATE_FILE = str(script_dir / "data" / "grid_state.json")

# === Валидация ===
mode = "DEMO" if BYBIT_DEMO else ("TESTNET" if TESTNET else "MAINNET")
if not API_KEY:
    logger.warning(f"[GridConfig] BYBIT_API_KEY NOT FOUND! (Mode: {mode})")
else:
    logger.info(f"[GridConfig] API Key: {API_KEY[:4]}**** | Mode: {mode}")
    logger.info(f"[GridConfig] Symbol: {SYMBOL} | Grid: {GRID_COUNT} levels | Leverage: {LEVERAGE}x")
