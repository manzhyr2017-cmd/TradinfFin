import os
import signal
import subprocess
import sys
import json
import logging
import asyncio
from typing import List, Optional, Dict
import datetime as dt
from datetime import datetime, timedelta
# --- SETUP PATHS FIRST ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.append(PROJECT_ROOT)
CONFIG_FILE = os.path.join(PROJECT_ROOT, "bot_config.json")
LOG_FILE = os.path.join(PROJECT_ROOT, "bot.log")

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Dashboard")

# Import Tradingfin3.0 metrics exporter
try:
    from metrics_exporter import MetricsExporter, TradingMetrics, update_metrics, record_trade
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    logger.info("Metrics exporter not available - Prometheus metrics disabled")

# LOAD ENV VARS EXPLICITLY
from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"), override=True)

# Project Imports moved to local scopes for RAM efficiency

from fastapi import FastAPI, Request, Form, BackgroundTasks, Depends, HTTPException, status, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from jose import JWTError, jwt
from web_ui.database import db, init_db, create_user, get_user, verify_password, get_trades
from services.analytics_service import AnalyticsService

analytics = AnalyticsService(db)
# Auth Config
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-me")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 hours

# Global process and service state
bot_process = None
ai_agent = None
_sentinel_running = False
_services = {}
BOT_START_TIME = None

# oauth2_scheme defined after lifespan setup
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    print("\n" + "="*50)
    print("[*] SERVER STARTUP - LIFESPAN MODE")
    print("="*50 + "\n")
    
    init_db()
    
    global ai_agent, tg_bot, BOT_START_TIME, bot_process
    
    BOT_START_TIME = datetime.now().isoformat()
    tg_bot = None  # Define early to avoid UnboundLocalError
    bot_process = None
    config = load_config()
    if config.telegram_token:
        try:
            from telegram_bot import TradingTelegramBot, TelegramConfig
            from bybit_client import BybitClient
            
            class AIWebController:
                def __init__(self, telegram_bot_instance=None):
                    self.tg_bot = telegram_bot_instance
                    self._client_instance = None
                
                @property
                def bot(self):
                    # Mock bot object for compatibility
                    return type('obj', (object,), {
                        'client': self.client,
                        'execution': type('obj', (object,), {'execute_signal': lambda s: (True, "OK")})() 
                    })
    
                @property
                def client(self):
                    if not self._client_instance:
                        cfg = load_config()
                        # Determine if we are in demo mode
                        is_demo = cfg.mode in ["demo", "demo_trading"]
                        
                        self._client_instance = BybitClient(
                            api_key=cfg.api_key or "fake", 
                            api_secret=cfg.api_secret or "fake", 
                            proxy=cfg.proxy,
                            demo_mode=is_demo,
                            demo_trading=is_demo
                        )
                    return self._client_instance

                async def get_balance(self):
                    try:
                        bal = float(await asyncio.get_running_loop().run_in_executor(None, self.client.get_wallet_balance))
                        # Fallback for demo mode - use totalEquity if wallet balance is 0
                        if bal <= 0:
                            try:
                                equity = float(await asyncio.get_running_loop().run_in_executor(None, self.client.get_total_equity))
                                if equity > 0:
                                    return equity
                            except:
                                pass
                        return bal
                    except: return 0.0

                async def start_bot(self):
                    global _sentinel_running
                    _sentinel_running = True
                    return {"message": "Sentinel Loop STARTED"}

                async def stop_bot(self):
                    global _sentinel_running
                    _sentinel_running = False
                    return {"message": "Sentinel Loop STOPPED"}

                async def get_regime(self):
                    if _services.get('sentiment'):
                        return _services['sentiment'].regime
                    return "NEUTRAL"

                async def get_status(self):
                    return {
                        "running": _sentinel_running, 
                        "pid": os.getpid(), 
                        "regime": _services.get('sentiment').regime if _services.get('sentiment') else "N/A",
                        "hedge_status": "Status API Check",
                        "news_danger": "Status API Check"
                    }

                async def get_selector_data(self):
                    if _services.get('selector'):
                        return {
                            "longs": _services['selector'].primary_list,
                            "shorts": _services['selector'].secondary_list
                        }
                    return None

                async def send_signal_message(self, data: dict):
                    """Отправка уведомлений и сигналов в Telegram"""
                    try:
                        if not self.tg_bot or not self.tg_bot.app:
                            return
                        
                        if "message" in data and "action" not in data:
                            channel_id = os.getenv("TELEGRAM_CHANNEL")
                            if channel_id:
                                await self.tg_bot.app.bot.send_message(chat_id=channel_id, text=data["message"], parse_mode="HTML")
                            return
                        
                        from mean_reversion_bybit import AdvancedSignal, SignalType, SignalStrength, MarketRegime
                        from telegram_bot import SignalFormatter
                        from datetime import datetime, timedelta
                        
                        sig_type = SignalType.LONG if data.get('action') == "BUY" else SignalType.SHORT
                        
                        def _safe_float(val):
                            try:
                                if isinstance(val, (int, float)): return float(val)
                                if not val: return 0.0
                                cleaned = ''.join(c for c in str(val) if c.isdigit() or c in '.-')
                                return float(cleaned) if cleaned else 0.0
                            except: return 0.0
    
                        entry = _safe_float(data.get('entry'))
                        tp = _safe_float(data.get('tp'))
                        sl = _safe_float(data.get('sl'))
                        
                        signal = AdvancedSignal(
                            symbol=data.get('symbol'),
                            signal_type=sig_type,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit_1=tp,
                            take_profit_2=tp * 1.05,
                            confluence=type('obj', (object,), {
                                'total_score': data.get('confidence', 70),
                                'max_possible': 100,
                                'percentage': data.get('confidence', 70),
                                'get_strength': lambda: SignalStrength.STRONG,
                                'get_breakdown': lambda: "AI Analysis Confluence"
                            })(),
                            probability=data.get('confidence', 70),
                            strength=SignalStrength.STRONG,
                            timeframes_aligned={'1m': True, '15m': True, '1h': True},
                            support_resistance_nearby=None,
                            market_regime=MarketRegime.RANGING_WIDE,
                            risk_reward_ratio=2.0,
                            position_size_percent=1.0,
                            funding_rate=None,
                            funding_interpretation=None,
                            orderbook_imbalance=None,
                            timestamp=datetime.now(),
                            valid_until=datetime.now() + timedelta(hours=4),
                            indicators={},
                            reasoning=[data.get('reason', '')],
                            warnings=[]
                        )
    
                        if signal.entry_price == 0:
                            try:
                                ticker = self.client._request("/v5/market/tickers", {"category": self.client.category.value, "symbol": signal.symbol})
                                signal.entry_price = float(ticker['list'][0]['lastPrice'])
                            except: pass
    
                        await self.tg_bot.send_signal_with_actions(
                            signal,
                            sentiment=data.get('sentiment'),
                            sector=data.get('strategy'),
                            is_executed=data.get('executed', False),
                            order_id=data.get('orderId'),
                            execution_error=data.get('execution_error')
                        )
                    except Exception as e:
                        logger.error(f"Failed to send AI message: {e}")

                async def execute_ai_trade(self, analysis: dict):
                    """Исполнение сделки через ExecutionManager"""
                    try:
                        conf = load_config()
                        if not conf.auto_trade:
                            return {"success": False, "error": "Auto-trade disabled in settings"}

                        from execution import ExecutionManager, RiskLimits
                        from mean_reversion_bybit import AdvancedSignal, SignalType, SignalStrength, MarketRegime
                        from datetime import datetime, timedelta
                        
                        def __safe_float(v, default=0.0):
                            try:
                                if not v: return default
                                cleaned = ''.join(c for c in str(v) if c.isdigit() or c in '.-')
                                return float(cleaned) if cleaned else default
                            except: return default

                        limits = RiskLimits(
                            max_daily_loss_usd=conf.max_daily_loss,
                            risk_per_trade_percent=conf.risk_percent
                        )
                        manager = ExecutionManager(self.client, risk_limits=limits)
                        
                        symbol = analysis.get("symbol")
                        action = analysis.get("action")
                        sig_type = SignalType.LONG if action == "BUY" else SignalType.SHORT
                        
                        entry = __safe_float(analysis.get('entry_price'))
                        tp = __safe_float(analysis.get('take_profit'))
                        sl = __safe_float(analysis.get('stop_loss'))

                        signal = AdvancedSignal(
                            symbol=symbol,
                            signal_type=sig_type,
                            entry_price=entry,
                            stop_loss=sl,
                            take_profit_1=tp,
                            take_profit_2=tp * 1.02,
                            confluence=type('obj', (object,), {
                                'total_score': analysis.get('confidence', 90),
                                'max_possible': 100,
                                'percentage': analysis.get('confidence', 90),
                                'get_strength': lambda: SignalStrength.STRONG,
                                'get_breakdown': lambda: "AI Trade Execution"
                            })(),
                            probability=analysis.get('confidence', 90),
                            strength=SignalStrength.STRONG,
                            timeframes_aligned={'15m': True},
                            support_resistance_nearby=None,
                            market_regime=MarketRegime.RANGING_WIDE,
                            risk_reward_ratio=2.0,
                            position_size_percent=1.0,
                            funding_rate=None,
                            funding_interpretation=None,
                            orderbook_imbalance=None,
                            timestamp=datetime.now(),
                            valid_until=datetime.now() + timedelta(hours=4),
                            indicators={},
                            reasoning=[analysis.get('reasoning', 'AI Web Execution')],
                            warnings=[]
                        )

                        logger.info(f"⚡ AI Agent executing {symbol} {action} via ExecutionManager")
                        res = manager.execute_signal(signal)
                        success, msg = res if isinstance(res, tuple) else (res, "Unknown")
                        
                        if success:
                            return {"success": True, "orderId": "WEB-AI-EXEC", "message": msg}
                        else:
                            return {"success": False, "error": f"Rejected: {msg}"}

                    except Exception as e:
                        logger.error(f"Execution failed: {e}")
                        return {"success": False, "error": str(e)}

                async def execute_pending_signal(self, symbol: str, direction: str):
                    """Ручное исполнение сигнала (через кнопки в Telegram)"""
                    try:
                        ticker = await asyncio.get_running_loop().run_in_executor(
                            None, 
                            lambda: self.client._request("/v5/market/tickers", {"category": self.client.category.value, "symbol": symbol})
                        )
                        price = float(ticker['list'][0]['lastPrice'])
                        
                        sl_mult = 0.98 if direction.upper() == "LONG" else 1.02
                        tp_mult = 1.06 if direction.upper() == "LONG" else 0.94
                        
                        analysis = {
                            "symbol": symbol,
                            "action": "BUY" if direction.upper() == "LONG" else "SELL",
                            "entry_price": price,
                            "take_profit": price * tp_mult,
                            "stop_loss": price * sl_mult,
                            "confidence": 95,
                            "reasoning": "Manual confirmation from Telegram"
                        }
                        res = await self.execute_ai_trade(analysis)
                        if res.get("success"):
                            return f"SUCCESS: {res.get('message')}"
                        return f"REJECTED: {res.get('error')}"
                    except Exception as e:
                        return f"ERROR: {str(e)}"

            # --- SETUP INSTANCES ---
            controller = AIWebController()
            tg_conf = TelegramConfig(bot_token=config.telegram_token)
            tg_bot = TradingTelegramBot(tg_conf, controller=controller)
            controller.tg_bot = tg_bot
            
            await tg_bot.start()
            logger.info("Telegram Bot (Polling) & AI Agent components linked.")
            
            # Init AI Agent (RESTORED for 8GB RAM MODE)
            from ai_agent import TradingAgent
            ai_agent = TradingAgent(controller)
            # ai_agent = None (Disabled standby)
            
            # --- START SERVICES (Phase 5: Global Sentiment & Selector) ---
            try:
                from services.sentiment_service import SentimentService
                from services.selector_service import SelectorService
                
                sentiment = SentimentService(ai_agent)
                selector = SelectorService(ai_agent, controller.client)
                
                _services['sentiment'] = sentiment
                _services['selector'] = selector
                
                # Start background tasks for services
                # OOM PROTECTION: Disabled heavy services on startup
                # asyncio.create_task(sentiment.start(interval_hours=2.0))
                # asyncio.create_task(selector.start(interval_hours=4.0))
                
                logger.info("🌍 Sentiment & 🕵️ Selector Services initialized (STANDBY MODE).")
            except Exception as se:
                logger.error(f"Failed to start base services: {se}")

            # OOM PROTECTION: Disabled autonomous AI cycle
            # asyncio.create_task(ai_agent.run_autonomous_cycle(interval_minutes=15))

        except Exception as e:
            logger.error(f"AI/Telegram Startup failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

    yield
    # Shutdown logic
    if bot_process:
        bot_process.terminate()
    if tg_bot:
        try:
            await tg_bot.app.updater.stop()
            await tg_bot.app.stop()
            await tg_bot.app.shutdown()
        except:
            pass

app = FastAPI(title="Trading Bot Dashboard", lifespan=lifespan)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")




# --- Auth Utils ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    now = dt.datetime.now(dt.timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request):
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        if token.startswith("Bearer "):
            token = token[7:]
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        return username
    except JWTError:
        return None

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Allow public routes
    if request.url.path in ["/login", "/register", "/token", "/auth/login", "/auth/register", "/api/status"]: 
        # /api/status left public for simple heartbeat checks if needed, or remove it
        return await call_next(request)
    
    if request.url.path.startswith("/static"):
        return await call_next(request)
        
    # Check Auth
    user = await get_current_user(request)
    if not user:
        if request.url.path.startswith("/api"):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        else:
            return RedirectResponse(url="/login")
            
    response = await call_next(request)
    return response


# Пути (Moved to top)
# BASE_DIR, PROJECT_ROOT already defined

# Монтирование статики и шаблонов
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Глобальное состояние
bot_process = None
ai_agent = None
BOT_START_TIME = None

# Модели данных

class BotConfig(BaseModel):
    api_key: str = ""
    api_secret: str = ""
    mode: str = "demo"  # demo | real | testnet
    symbols: List[str] = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    risk_percent: float = 1.0
    max_daily_loss: float = 50.0
    stop_loss_atr: float = 2.0
    take_profit_ratio: float = 2.5
    auto_trade: bool = True
    telegram_token: Optional[str] = None
    telegram_channel: Optional[str] = None
    proxy: Optional[str] = None
    min_probability: int = 85
    strategy: str = "mean_reversion" # mean_reversion, trend, breakout
    sentinel_interval: int = 15 # Minutes for AI scan loop
    twa_url: str = "" # Telegram Web App URL
    max_symbols: int = 100

# Загрузка / Сохранение конфига
def load_config() -> BotConfig:
    # 1. Load from DB
    data = db.get_setting("bot_config", {})
    config = BotConfig(**data)
    
    # 2. Fallback to file if DB is empty
    if not data and os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                file_data = json.load(f)
                config = BotConfig(**file_data)
                # Save to DB for future
                db.save_setting("bot_config", config.dict())
        except Exception as e:
            logger.error(f"Error loading config file: {e}")
            
    # 3. Override from Environment (priority)
    if os.getenv("BYBIT_API_KEY"):
        config.api_key = os.getenv("BYBIT_API_KEY")
    if os.getenv("BYBIT_API_SECRET"):
        config.api_secret = os.getenv("BYBIT_API_SECRET")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        config.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if os.getenv("TELEGRAM_CHANNEL"):
        config.telegram_channel = os.getenv("TELEGRAM_CHANNEL")
    if os.getenv("HTTP_PROXY"):
        config.proxy = os.getenv("HTTP_PROXY")
    
    # Force auto_trade to True as requested
    config.auto_trade = True
        
    return config

def save_config(config: BotConfig):
    # CRITICAL: Never save api_key/api_secret to DB or file!
    # They must ONLY come from .env to prevent accidental overwrites
    config_data = config.dict()
    config_data.pop('api_key', None)
    config_data.pop('api_secret', None)
    
    # Save to DB (without API keys)
    db.save_setting("bot_config", config_data)
    # Backup to file (without API keys)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=4)

# API Эндпоинты

# --- Auth Routes ---

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response

import hmac
import hashlib
from urllib.parse import parse_qsl

def validate_twa_data(init_data: str, bot_token: str) -> bool:
    """Валидация данных инициализации Telegram Web App"""
    try:
        vals = dict(parse_qsl(init_data))
        hash_val = vals.pop('hash', None)
        if not hash_val: return False
        
        data_check_string = "\n".join([f"{k}={v}" for k, v in sorted(vals.items())])
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        hmac_val = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return hmac_val == hash_val
    except:
        return False

@app.post("/api/auth/twa")
async def twa_auth(request: Request):
    data = await request.json()
    init_data = data.get("initData")
    
    config = load_config()
    if not validate_twa_data(init_data, config.telegram_token):
        raise HTTPException(status_code=401, detail="Invalid Telegram data")
    
    # Extract user info
    vals = dict(parse_qsl(init_data))
    import json
    user_data = json.loads(vals.get("user", "{}"))
    username = f"tg_{user_data.get('id')}"
    
    # Check if user exists, if not - create with random pass (TWA only)
    if not get_user(username):
        create_user(username, os.urandom(16).hex())
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": username}, expires_delta=access_token_expires)
    
    response = JSONResponse({"status": "ok"})
    response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return response

@app.post("/auth/register")
async def register_user(request: Request, username: str = Form(...), password: str = Form(...)):
    if get_user(username):
        return templates.TemplateResponse("register.html", {"request": request, "error": "Username already exists"})
    
    if create_user(username, password):
        return RedirectResponse(url="/login?registered=true", status_code=302)
    else:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Registration failed"})

@app.post("/auth/login")
async def login_user(request: Request, username: str = Form(...), password: str = Form(...)):
    user = get_user(username)
    if not user or not verify_password(password, user[2]):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user[1]}, expires_delta=access_token_expires
    )
    
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
    return response

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/history")
async def history_page(request: Request):
    return templates.TemplateResponse("history.html", {"request": request})

@app.get("/api/status")
async def get_status():
    global bot_process, ai_agent
    
    # Check process status (only bots started via /api/start)
    is_running = bot_process is not None and bot_process.poll() is None
    
    # Read detailed state from file for display (Sentiment, Regime, etc)
    bot_state = {}
    if os.path.exists("bot_state.json"):
        try:
            with open("bot_state.json", 'r') as f:
                bot_state = json.load(f)
        except:
            pass
    
    # Merge with AI Agent's own live data if available
    llm_info = {"provider": "Unknown", "providers_count": 0}
    state = {}
    
    # Try to get live service data first
    if _services.get('sentiment'):
        s_data = _services['sentiment'].get_state()
        state['sentiment_regime'] = s_data.get('regime', 'NEUTRAL')
        state['sentiment_reason'] = s_data.get('reasoning', 'Initializing...')
    else:
        state['sentiment_regime'] = bot_state.get('sentiment_regime', 'N/A')
        state['sentiment_reason'] = bot_state.get('sentiment_reason', 'N/A')

    if ai_agent:
        # LLM detection
        if hasattr(ai_agent, 'get_llm_status'):
            status = ai_agent.get_llm_status()
            llm_info["provider"] = status.get("provider", "Unknown")
            llm_info["providers_count"] = status.get("total_providers", 0)
        elif hasattr(ai_agent, 'llm_clients'):
            llm_info["providers_count"] = len(ai_agent.llm_clients)
            if ai_agent.llm_clients:
                current = ai_agent._get_current_llm()
                if current and current[0]:
                    llm_info["provider"] = current[0]
                    
        # If AI Agent has its own recent findings, prioritize them
        if hasattr(ai_agent, 'learned_context') and ai_agent.learned_context:
             state['learned_context'] = ai_agent.learned_context

    return {
        "status": "running" if is_running else "stopped",
        "running": is_running,
        "config": load_config().model_dump(),
        "pid": bot_process.pid if is_running else None,
        "regime": bot_state.get('regime', 'Unknown'),
        "strategy": bot_state.get('current_strategy', 'N/A'),
        "recommendation": bot_state.get('recommendation', 'N/A'),
        "sentiment_regime": state.get('sentiment_regime', 'N/A'),
        "sentiment_reason": state.get('sentiment_reason', 'N/A'),
        "top_longs": bot_state.get('top_longs', []),
        "top_shorts": bot_state.get('top_shorts', []),
        "llm_provider": llm_info.get("provider", "N/A"),
        "llm_providers_count": llm_info.get("providers_count", 0),
        "start_time": BOT_START_TIME if is_running else None,
        "learned_context": state.get('learned_context', ""),
        "hedge_status": bot_state.get('hedge_status', 'Inactive'),
        "news_danger": bot_state.get('news_danger', 'None')
    }

@app.post("/api/config")
async def update_config(config: BotConfig):
    # Load existing to preserve hidden fields (e.g. max_symbols)
    existing = load_config()
    
    # Merge existing into new config if field is missing or empty
    # But since BotConfig has defaults, we should rather update existing with new
    
    # Create dict from existing and update with non-None values from new
    new_data = config.model_dump(exclude_unset=True)
    existing_data = existing.model_dump()
    
    existing_data.update(new_data)
    
    # Re-create config object
    final_config = BotConfig(**existing_data)

    # Preserve PROXY if not provided by UI explicitly (though above merge handles it)
    if not final_config.proxy and existing.proxy:
        final_config.proxy = existing.proxy
        
    save_config(final_config)
    return {"status": "ok", "message": "Config saved"}

@app.get("/api/scan")
async def scan_market():
    """Запускает однократное сканирование"""
    config = load_config()
    
    # Формируем команду
    cmd = [sys.executable, "main_bybit.py", "scan"]
    
    if config.symbols:
        cmd.extend(["--symbols"] + config.symbols)
        
    if config.mode in ["demo", "testnet", "demo_trading"]:
        cmd.append("--demo")
        cmd.append("--use-binance")
        
    if config.strategy:
        cmd.extend(["--strategy", config.strategy])
        
    # Inject Env
    env = os.environ.copy()
    if config.api_key: env["BYBIT_API_KEY"] = config.api_key
    if config.api_secret: env["BYBIT_API_SECRET"] = config.api_secret
    if config.telegram_token: env["TELEGRAM_BOT_TOKEN"] = config.telegram_token
    if config.telegram_channel: env["TELEGRAM_CHANNEL"] = config.telegram_channel
    if config.proxy: 
        env["HTTP_PROXY"] = config.proxy
        env["HTTPS_PROXY"] = config.proxy

    try:
        # Run sync process
        result = subprocess.run(
            cmd, 
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            env=env
        )
        
        if result.returncode != 0:
            logger.error(f"Scan failed: {result.stderr}")
            return {"status": "error", "message": "Scan process failed", "details": result.stderr}
            
        # Parse output file if exists
        # Scanner saves to 'signals_bybit.json' by default if run_once finds signals
        # But if no signals, file might be old or not created.
        # Ideally main_bybit.py always saves or we parse stdout.
        # Check stdout for "No signals"
        
        output_file = os.path.join(PROJECT_ROOT, "signals_bybit.json")
        results = []
        if os.path.exists(output_file):
            try:
                # Check modification time to ensure it's fresh (within 1 min)
                mtime = os.path.getmtime(output_file)
                if datetime.now().timestamp() - mtime < 60:
                    with open(output_file, 'r') as f:
                        data = json.load(f)
                        # Transform to expected format
                        # Expected by UI: { symbol, type, strength, score }
                        for s in data:
                             results.append({
                                 "symbol": s['symbol'],
                                 "type": s['type'],
                                 "strength": "STRONG", # approximated
                                 "score": s['probability']
                             })
            except Exception as e:
                logger.error(f"Error reading signals file: {e}")

        return {"status": "ok", "results": results}
        
    except Exception as e:
        logger.error(f"Scan exception: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/balance")
async def get_real_balance():
    """Fetches real balance from Bybit API"""
    config = load_config()
    
    if not config.api_key or not config.api_secret:
        return {"balance": 0, "error": "API keys not configured"}
    
    try:
        from bybit_client import BybitClient, BybitCategory
        
        client = BybitClient(
            api_key=config.api_key,
            api_secret=config.api_secret,
            # mode="testnet" -> Bybit Testnet environment
            # mode="demo_trading" -> Bybit Unified Demo (Mock) environment
            testnet=(config.mode == "testnet"),
            demo_trading=(config.mode in ["demo", "demo_trading"]), 
            proxy=config.proxy or os.getenv('HTTP_PROXY')
        )
        
        # Try wallet balance first, fallback to totalEquity for demo mode
        balance = client.get_wallet_balance('USDT')
        if balance <= 0:
            try:
                equity = client.get_total_equity()
                if equity > 0:
                    balance = equity
            except:
                pass
        positions = client.get_open_positions()
        
        # Calculate unrealized PnL
        unrealized_pnl = sum(float(p.get('unrealisedPnl', 0)) for p in positions)
        
        return {
            "balance": round(balance, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_equity": round(balance + unrealized_pnl, 2),
            "open_positions": len(positions),
            "positions": positions,
            "mode": config.mode
        }
    except Exception as e:
        logger.error(f"Balance fetch error: {e}")
        return {"balance": 0, "error": str(e)}

@app.post("/api/start")
async def start_bot():
    global bot_process, BOT_START_TIME
    
    if bot_process is not None and bot_process.poll() is None:
        return {"status": "error", "message": "Бот уже запущен"}

    # Set start time
    BOT_START_TIME = datetime.utcnow().isoformat() + "Z"
    
    config = load_config()
    
    # Cross-platform process cleanup
    if os.name == 'nt':
        cmd_cleanup = ["powershell", "-Command", "Get-Process python | Where-Object { $_.Id -ne $PID } | Stop-Process -Force"]
    else:
        cmd_cleanup = ["pkill", "-9", "-f", "main_bybit.py"]
    
    try:
        subprocess.run(cmd_cleanup, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except:
        pass
        
    cmd = [sys.executable, "main_bybit.py", "scan", "--continuous", "--no-telegram-bot"]
    
    if config.symbols:
        cmd.extend(["--symbols"] + config.symbols)
    
    if config.mode == "testnet":
        # Force sim mode for testnet too since blocked
        cmd.append("--demo") 
        cmd.append("--use-binance")
        
    if config.mode in ["demo", "demo_trading"]:
        cmd.append("--demo-trading") # Use Bybit Demo API
        # cmd.append("--demo") # Do NOT enable simulation mode (dry-run)
        # cmd.append("--use-binance") # Do NOT force Binance data

    if config.auto_trade:
         cmd.append("--auto-trade")
         cmd.extend(["--risk", str(config.risk_percent)])
    
    if config.strategy:
        cmd.extend(["--strategy", config.strategy])
    
    # Pass max_symbols for dynamic scanning (default 100)
    cmd.extend(["--max-symbols", "100"])
    cmd.append("--all")  # Scan all pairs (filtered by volume)
    
    # Установка переменных окружения
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Disable buffering
    if config.api_key:
        env["BYBIT_API_KEY"] = config.api_key
    if config.api_secret:
        env["BYBIT_API_SECRET"] = config.api_secret
        
    if config.telegram_token:
        env["TELEGRAM_BOT_TOKEN"] = config.telegram_token
    if config.telegram_channel:
        env["TELEGRAM_CHANNEL"] = config.telegram_channel
        
    if config.proxy:
        env["HTTP_PROXY"] = config.proxy
        env["HTTPS_PROXY"] = config.proxy
    
    # Запуск процесса БЕЗ КОНСОЛИ (в фоне)
    # Логи идут в файл bot.log
    try:
        log_out = open(LOG_FILE, "a", encoding='utf-8')
        # Use creationflags only on Windows
        popen_kwargs = {
            "cwd": PROJECT_ROOT,
            "stdout": log_out,
            "stderr": log_out,
            "env": env
        }
        if os.name == 'nt':
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        bot_process = subprocess.Popen(cmd, **popen_kwargs)
        return {"status": "ok", "message": "Бот запущен", "pid": bot_process.pid}
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/stop")
async def stop_bot():
    global bot_process
    
    if bot_process is None or bot_process.poll() is not None:
        return {"status": "warning", "message": "Бот не запущен"}
    
    try:
        bot_process.terminate()
        # Ждем немного и если не умер - убиваем
        try:
            bot_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            bot_process.kill()
            
        bot_process = None
        return {"status": "ok", "message": "Бот остановлен"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/analytics")
async def get_analytics():
    """Возвращает метрики эффективности"""
    metrics = analytics.calculate_metrics()
    equity = analytics.get_equity_curve()
    return {
        "metrics": metrics,
        "equity_curve": equity
    }

@app.get("/api/export/trades")
async def export_trades():
    """Экспорт сделок в CSV"""
    import tempfile
    from fastapi.responses import FileResponse
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        analytics.export_trades_csv(tmp.name)
        return FileResponse(
            path=tmp.name, 
            filename=f"trades_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            media_type='text/csv'
        )

@app.get("/api/logs")
async def get_logs():
    """Читает последние 100 строк лога"""
    if not os.path.exists(LOG_FILE):
        return {"logs": []}
        
    try:
        with open(LOG_FILE, "r", encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
            return {"logs": lines[-100:]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {e}"]}

# ============================================
# LLM PROVIDER MANAGEMENT ENDPOINTS
# ============================================

@app.get("/api/llm/status")
async def get_llm_status():
    """Get current LLM provider status"""
    global ai_agent
    if ai_agent and hasattr(ai_agent, 'get_llm_status'):
        return ai_agent.get_llm_status()
    return {
        "current_provider": "Unknown",
        "current_model": "N/A", 
        "total_providers": 0,
        "exhausted": [],
        "available": []
    }

@app.post("/api/llm/switch")
async def switch_llm_provider(provider: str):
    """Manually switch to a specific LLM provider"""
    global ai_agent
    if not ai_agent or not hasattr(ai_agent, 'switch_llm_provider'):
        return {"status": "error", "message": "AI Agent not initialized"}
    
    success = ai_agent.switch_llm_provider(provider)
    if success:
        return {"status": "ok", "message": f"Switched to {provider}"}
    return {"status": "error", "message": f"Provider '{provider}' not found"}

@app.post("/api/llm/reset")
async def reset_llm_providers():
    """Reset all exhausted LLM providers - try again"""
    global ai_agent
    if ai_agent:
        ai_agent.rate_limit_exhausted.clear()
        ai_agent.current_llm_index = 0
        return {"status": "ok", "message": "LLM providers reset"}
    return {"status": "error", "message": "Agent not active"}

@app.post("/api/ai/learn")
async def force_ai_learning():
    """Force the AI to analyze past trades and update its strategy immediately"""
    global ai_agent
    if not ai_agent:
        return {"status": "error", "message": "AI Agent not initialized"}
    
    try:
        # Run the self-correction logic (async mode)
        # Note: perform_self_correction updates self.learned_context internally
        await ai_agent.perform_self_correction()
        
        return {
            "status": "ok", 
            "message": "AI self-learning completed", 
            "new_context": ai_agent.learned_context
        }
    except Exception as e:
        logger.error(f"Force learning failed: {e}")
        return {"status": "error", "message": str(e)}
    if not ai_agent or not hasattr(ai_agent, 'reset_llm_exhausted'):
        return {"status": "error", "message": "AI Agent not initialized"}
    
    ai_agent.reset_llm_exhausted()
    return {"status": "ok", "message": "All LLM providers reset"}

# /api/panic endpoint removed

@app.post("/api/history/sync")
async def sync_history():
    """Manually trigger history sync from Bybit"""
    try:
        from trade_logger import get_trade_logger
        from bybit_client import BybitClient
        
        config = load_config()
        # Use simple client to fetch history
        client = BybitClient(
            api_key=config.api_key, 
            api_secret=config.api_secret, 
            proxy=config.proxy
        )
        t_logger = get_trade_logger()
        
        # 1. Fetch Closed PnL
        closed_trades = client.get_closed_pnl(limit=50)
        
        count = 0
        for trade in closed_trades:
             # Parse and log
             try:
                 data = {
                     'symbol': trade['symbol'],
                     'side': trade['side'],
                     'entry_price': float(trade.get('avgEntryPrice', 0)),
                     'exit_price': float(trade.get('avgExitPrice', 0)),
                     'pnl': float(trade.get('closedPnl', 0)),
                     'exit_time': int(trade.get('createdTime', 0)), # Closed time
                     'qty': float(trade.get('closedSize', 0)),
                     'order_id': trade.get('orderId')
                 }
                 t_logger.sync_external_trade(data)
                 count += 1
             except Exception as ex:
                 logger.error(f"Error parsing trade {trade}: {ex}")
                 
        return {"status": "ok", "synced": count}
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/history")
async def get_history():
    """Возвращает историю сделок из БД"""
    trades = get_trades(limit=100)
    return {"trades": trades}

@app.get("/api/stats")
async def get_stats():
    """Возвращает общую статистику"""
    from web_ui.database import get_trade_stats
    stats = get_trade_stats()
    return stats

@app.get("/api/equity")
async def get_equity_curve():
    """Returns equity curve data for charting"""
    try:
        from trade_logger import get_trade_logger
        logger_instance = get_trade_logger()
        trades = logger_instance.get_recent_trades(limit=50)
        
        # Build cumulative PnL
        equity = 100.0  # Starting balance
        curve = [{"date": "Start", "value": equity}]
        
        for trade in reversed(trades):  # Oldest first
            if trade.get('pnl') is not None:
                equity += trade['pnl']
                curve.append({
                    "date": trade['timestamp'][:10] if trade.get('timestamp') else "?",
                    "value": round(equity, 2),
                    "symbol": trade.get('symbol', '?'),
                    "pnl": trade.get('pnl', 0)
                })
        
        return {"curve": curve, "current": round(equity, 2)}
    except Exception as e:
        return {"curve": [], "current": 100, "error": str(e)}

@app.get("/api/analytics/advanced")
async def get_advanced_analytics():
    """Advanced portfolio metrics"""
    from web_ui.database import db
    with db._get_connection() as conn:
        c = conn.cursor()
        # Fetch all closed trades
        c.execute("SELECT pnl FROM trades WHERE status != 'OPEN'")
        pnls = [row[0] for row in c.fetchall() if row[0] is not None]
    
    if not pnls:
        return {"profit_factor": 0, "avg_win": 0, "avg_loss": 0, "expectancy": 0}
        
    wins = [p for p in pnls if p > 0]
    losses = [abs(p) for p in pnls if p < 0]
    
    sum_wins = sum(wins)
    sum_losses = sum(losses)
    
    profit_factor = (sum_wins / sum_losses) if sum_losses > 0 else (sum_wins if sum_wins > 0 else 0)
    avg_win = (sum_wins / len(wins)) if wins else 0
    avg_loss = (sum_losses / len(losses)) if losses else 0
    
    # Expectancy = (Win% * AvgWin) - (Loss% * AvgLoss)
    win_rate = len(wins) / len(pnls)
    loss_rate = 1 - win_rate
    expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
    
    return {
        "profit_factor": round(profit_factor, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "expectancy": round(expectancy, 2),
        "total_trades": len(pnls)
    }



@app.get("/api/klines")
async def get_klines(symbol: str = "BTCUSDT", interval: str = "15m"):
    """Получает данные для графика"""
    config = load_config()
    client = BybitClient(proxy=config.proxy)
    try:
        # Fetch last 200 candles
        # Note: category from config would be better, but LINEAR is safe for perps
        # Use get_klines (plural)
        df = client.get_klines(symbol, interval, limit=200)
        if df.empty:
            return []
        
        result = []
        for _, row in df.iterrows():
            result.append({
                "time": int(row['time'].timestamp()),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close'])
            })
        return result
    except Exception as e:
        logger.error(f"Error fetching klines: {e}")

@app.get("/api/analysis/latest")
async def get_latest_analysis(symbol: str = "BTCUSDT"):
    """Visual Sniper: возвращает последний анализ для отрисовки линий на графике"""
    if not ai_agent:
        return {}
    return ai_agent.latest_analysis.get(symbol, {})

@app.get("/api/ai/learnings")
async def get_ai_learnings():
    """Возвращает текущий контекст самообучения бота"""
    if not ai_agent:
        return {"learned_context": "AI Agent disabled"}
    return {"learned_context": ai_agent.learned_context}

@app.get("/api/active_symbols")
async def get_active_symbols():
    """Получает список торгуемых пар для графика"""
    config = load_config()
    return config.symbols

class ChatRequest(BaseModel):
    message: str

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
    """Эндпоинт для общения с Neuro-Bot через Web UI"""
    if not ai_agent:
        return {"response": "🧠 Мозг не подключен (ошибка инициализации или нет ключа)."}
    
    try:
        # Run in threadpool to not block async loop (requests/openai are sync usually, unless async client)
        # ai_agent.chat uses sync OpenAI client? Yes.
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, ai_agent.chat, req.message)
        return {"response": response}
    except Exception as e:
        logger.error(f"Chat API error: {e}")
        return {"response": f"Error: {str(e)}"}

# Запуск сервера
# Запуск сервера
@app.get("/api/active_symbols")
async def get_active_symbols():
    """Return list of symbols for chart selection"""
    config = load_config()
    return config.symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

if __name__ == "__main__":
    import uvicorn
    import atexit
    import time
    
    # === SINGLE INSTANCE ENFORCER ===
    def kill_existing_instances():
        """
        Гарантированно убивает все процессы, связанные с этим ботом и портом 8000.
        """
        import subprocess
        import os
        import platform
        import time
        current_pid = os.getpid()
        print(f"[*] Cleaning up old processes (Current PID: {current_pid})...")
        
        system = platform.system()
        try:
            if system == "Windows":
                ps_cmd = (
                    f"Get-Process python -ErrorAction SilentlyContinue | "
                    f"Where-Object {{ $_.CommandLine -like '*server.py*'-or $_.CommandLine -like '*main_bybit.py*' }} | "
                    f"Where-Object {{ $_.Id -ne {current_pid} }} | "
                    f"Stop-Process -Force -ErrorAction SilentlyContinue"
                )
                subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
            else:
                # Linux: МНОГОУРОВНЕВАЯ ОЧИСТКА
                # 1. Пробуем через lsof (если есть) убить всё на порту 8000
                subprocess.run("lsof -ti:8000 | xargs kill -9 2>/dev/null", shell=True)
                
                # 2. Пробуем fuser (старый способ)
                subprocess.run("fuser -k 8000/tcp 2>/dev/null", shell=True)
                
                # 3. Убиваем по имени скрипта
                subprocess.run(f"pkill -9 -f 'server.py' --exclude {current_pid} 2>/dev/null", shell=True)
                subprocess.run(f"pkill -9 -f 'uvicorn' --exclude {current_pid} 2>/dev/null", shell=True)
                
                # 4. Если установлена psutil - используем её для точечного удара
                try:
                    import psutil
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                        try:
                            # Если в команде есть server.py и это не мы
                            if proc.info['pid'] != current_pid:
                                cmdline = " ".join(proc.info['cmdline'] or [])
                                if 'server.py' in cmdline or '8000' in cmdline:
                                    print(f"[!] Killing zombie process {proc.info['pid']} ({proc.info['name']})")
                                    proc.kill()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            continue
                except ImportError:
                    pass
            
            # Даем системе время освободить порт
            time.sleep(1)
            print("[+] Old processes cleaned (if any).")
        except Exception as e:
            print(f"[!] Error during cleanup: {e}")

    # Запускаем зачистку ПЕРЕД всем остальным
    kill_existing_instances()
    
    # PID File (для справки, но не основной механизм теперь)
    PID_FILE = "server.pid"
    with open(PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    # Создаем папку логов
    if not os.path.exists("logs"):
        os.makedirs("logs", exist_ok=True)
    
    print(f"[*] Server started (PID: {os.getpid()})")
    print(f"[!] Single Instance Mode Active")
    
    # Запуск Uvicorn
    # Используем порт 8000 как стандарт, чтобы не путаться
    config = uvicorn.Config(app=app, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)
    server.run()
