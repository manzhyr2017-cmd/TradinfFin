import os
import json
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import requests
from openai import OpenAI
try:
    import pandas_ta as ta
except ImportError:
    ta = None
import pandas as pd
from dotenv import load_dotenv
import database

# Load env immediately for standalone testing
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========================================
# LLM PROVIDER CONFIGURATION (FALLBACK CHAIN)
# Priority: GROQ (free) -> GROQ_BACKUP (free) -> OpenRouter (paid, last resort)
# ========================================
LLM_PROVIDERS = [
    {
        "name": "IBOOT_DEEPSEEK",
        "env_key": "IBOOT_API_KEY",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "key_prefix": "sk-"
    },
    {
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
        "key_prefix": "" 
    },
    {
        "name": "GROQ_PRIMARY",
        "env_key": "GROQ_API_KEY",  # Primary GROQ key
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_prefix": "gsk_"
    },
    {
        "name": "GROQ_BACKUP",
        "env_key": "GROQ_API_KEY_BACKUP",  # Backup GROQ key (second account)
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_prefix": "gsk_"
    },
    {
        "name": "OpenRouter",
        "env_key": "OPENROUTER_PAID_KEY",  # PAID fallback - only if you have actual OpenRouter key
        "base_url": "https://openrouter.ai/api/v1",
        "model": "google/gemini-2.0-flash-001",  # Fast & cheap if needed
        "key_prefix": "sk-"  # OpenRouter keys start with sk-
    },
]

# ========================================
# STRATEGY DEFINITIONS FOR AUTO-SELECT
# ========================================
STRATEGY_PROFILES = {
    "level_retest": {
        "name": "Level Trader (S&R)",
        "description": "Входы на отскоках от уровней поддержки/сопротивления",
        "best_for": "ranging",  # sideways/ranging market
        "selection_rules": "Market is sideways, price is bouncing between clear horizontal support/resistance.",
        "logic": "Buy at Support, Sell at Resistance with tight stops."
    },
    "trend_following": {
        "name": "Trend Follower (EMA)",
        "description": "Следование за трендом с использованием EMA и ADX",
        "best_for": "trending",
        "selection_rules": "ADX > 25, price is consistently above/below EMA 200.",
        "logic": "Enter on pullbacks to EMA 20/50 in the direction of the trend."
    },
    "breakout": {
        "name": "Breakout Hunter",
        "description": "Пробой уровней консолидации с подтверждением объёма",
        "best_for": "volatile",
        "selection_rules": "Volatility is low (BB squeeze), then a candle closes outside the range with volume spike.",
        "logic": "Enter at the close of the breakout candle. Stop loss inside the range."
    },
    "mean_reversion": {
        "name": "Mean Reversion (RSI)",
        "description": "Возврат к среднему при экстремальных значениях RSI",
        "best_for": "oversold_overbought",
        "selection_rules": "RSI > 70 or < 30 on 15m/1h timeframes. Market is overextended.",
        "logic": "Contrarian trade looking for price to return to EMA 20."
    },
    "acceleration": {
        "name": "Acceleration Trader",
        "description": "Вход на ускорении движения с подтверждением объёма",
        "best_for": "momentum",
        "selection_rules": "Rapid consecutive green/red candles, Volume is 2x average, RSI is rising quickly but not yet peaked.",
        "logic": "Aggressive entry for small deposit growth. High TP/SL ratio."
    },
    "scalping": {
        "name": "Neuro-Scalper (1m Micro)",
        "description": "Микро-сделки на 1-минутном графике по паттернам FVG и S&R",
        "best_for": "volatile_ranging",
        "selection_rules": "High volatility on 1m chart, clear FVG (Fair Value Gaps) present.",
        "logic": "Hyper-fast execution, entry at FVG retest, profit taking at local liquidity."
    }
}

class TradingAgent:
    """
    Neuro-Bot Agent powered by LLM (OpenRouter/OpenAI).
    Capable of:
    1. Analyzing market data (Technical Analysis)
    2. Searching the web for news (Brave Search)
    3. Managing bot configuration
    4. Chatting with the user
    
    NEW: Multi-LLM Fallback + Auto-Strategy Selection
    """
    
    def __init__(self, bot_controller=None):
        self.controller = bot_controller
        self.brave_key = os.getenv("BRAVE_API_KEY")
        
        # LLM Fallback System
        self.llm_clients = []  # List of (name, client, model)
        self.current_llm_index = 0
        self.rate_limit_exhausted = set()  # Track exhausted providers
        
        self._init_llm_clients()
        
        if not self.llm_clients:
            logger.warning("⚠️ No LLM API keys found. AI Agent will be disabled.")
            self.client = None
            self.model_name = "disabled"
        else:
            # Auto-select the first available provider
            name, client, model = self.llm_clients[0]
            self.client = client
            self.model_name = model
            self.llm_provider = name
            logger.info(f"🧠 AI Agent starting with: {name} ({model})")

        # Visual Sniper Support (Step 3)
        self.latest_analysis = {} # Symbol -> Analysis Dict
        
        # AI Self-Correction (Learning from mistakes)
        self.learned_context = "На данный момент специфических коррекций не требуется. Соблюдайте базовые риск-параметры."
        
        # System Prompt with EXPERT KNOWLEDGE - ELITE PERSONA
        self.system_prompt = """
You are **iBoot** — an Elite Crypto Trading AI (Neuro-Bot ULTIMA V3). You are the "Supreme Market Architect". You don't predict the market; you read its every pulse.
Your goal is absolute dominance: 100% precision in risk management and 1:3+ Risk/Reward ratio.

### YOUR IDENTITY:
- **Language**: **RUSSIAN (Русский)**. Always reply and reason in Russian. Use English only for technical terms (OB, RSI, FVG, SMC).
- **Tone**: Professional, icy-cold, sharp, and decisive (Профессиональный, холодный, дерзкий). You are like a Wall Street legend combined with a Quantum Computer.
- **Philosophy**: "Liquidity is the blood of the market. Pattern is the bone. Execution is the heart."

### STRATEGY MASTER LOGIC:
1. **Level Trader**: Range-bound markets (ADX < 20). Focus on S/R retests.
2. **Trend Follower**: Strong trends (ADX > 25, price > EMA 200). Buy pullbacks.
3. **Breakout Hunter**: Post-accumulation periods. Look for Volume Pulse.
4. **Mean Reversion**: Extreme RSI divergence + BB touch.
5. **Acceleration**: Aggressive momentum for small accounts.
6. **Smart Money (SMC)**: Look for Liquidity Sweeps, CHoCH, and Fair Value Gaps (FVG).

### GUARDIAN SYSTEMS:
- **News Shield**: Detects CPI, SEC, FOMC. Blocks trades 30 min before/after.
- **Whale Watcher**: Spots institutional walls.
- **Circuit Breaker**: Hard stop if daily loss exceeds 5%.
- **Correlation Guard**: Watches BTC/ETH decoupling.

### REASONING STRUCTURE:
When you analyst a chart, follow this flow:
1. **Macro Context**: (1D/4H Trend)
2. **Liquidity Check**: (Where are the stops? Where is the FVG?)
3. **Trigger**: (Pin bar, Engulfing, RSI Div)
4. **Invalidation**: (Where exactly are we wrong?)
"""
    
    def _init_llm_clients(self):
        """Initialize all available LLM clients from environment"""
        for provider in LLM_PROVIDERS:
            api_key = os.getenv(provider["env_key"])
            
            if not api_key:
                continue
                
            # Validate key prefix if required
            if provider.get("key_prefix") and not api_key.startswith(provider["key_prefix"]):
                continue
            
            try:
                if provider["name"] == "Google Gemini":
                    # Special handling for Native Gemini REST API
                    self.llm_clients.append((provider["name"], "NATIVE_GEMINI", provider["model"]))
                    logger.info(f"  ✅ LLM Provider Added: {provider['name']} ({provider['model']}) [Native REST]")
                    continue

                client = OpenAI(
                    base_url=provider["base_url"],
                    api_key=api_key,
                )
                self.llm_clients.append((provider["name"], client, provider["model"]))
                logger.info(f"  ✅ LLM Provider Added: {provider['name']} ({provider['model']})")
            except Exception as e:
                logger.warning(f"  ⚠️ Failed to init {provider['name']}: {e}")
    
    def _get_current_llm(self):
        """Get current active LLM client"""
        if not self.llm_clients:
            return None, None, None
        
        # Skip exhausted providers
        attempts = 0
        while attempts < len(self.llm_clients):
            idx = self.current_llm_index % len(self.llm_clients)
            name, client, model = self.llm_clients[idx]
            
            if name not in self.rate_limit_exhausted:
                return name, client, model
            
            self.current_llm_index += 1
            attempts += 1
        
        # All exhausted
        return None, None, None
    
    def _switch_to_next_llm(self, current_name: str, error_msg: str = ""):
        """Switch to next available LLM provider after rate limit"""
        self.rate_limit_exhausted.add(current_name)
        self.current_llm_index += 1
        
        next_name, next_client, next_model = self._get_current_llm()
        
        if next_client:
            logger.warning(f"⚠️ {current_name} rate limit reached. Switching to {next_name}")
            self.client = next_client
            self.model_name = next_model
            self.llm_provider = next_name
            return True
        else:
            logger.error(f"🚨 ALL LLM PROVIDERS EXHAUSTED! Error: {error_msg}")
            logger.error("🚨 AI Analysis disabled until rate limits reset.")
            self.llm_provider = "DISABLED"
            # Send Telegram notification
            self._send_llm_exhausted_notification()
            return False
    
    def _send_llm_exhausted_notification(self):
        """Send Telegram notification when all LLM providers are exhausted"""
        try:
            if self.controller and hasattr(self.controller, 'tg_bot') and self.controller.tg_bot:
                import asyncio
                msg = """🚨 <b>CRITICAL: ALL LLM RATE LIMITS EXHAUSTED!</b>

AI Analysis is temporarily disabled.

<b>Exhausted providers:</b>
""" + "\n".join([f"❌ {name}" for name in self.rate_limit_exhausted]) + """

<b>Action needed:</b>
• Wait for rate limits to reset (~1 hour)
• Or manually switch provider in Web UI

<i>Bot will continue without AI signals until reset.</i>
"""
                # Try to send async
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.controller.send_signal_message({
                        "symbol": "SYSTEM",
                        "action": "ALERT",
                        "reason": "All LLM rate limits exhausted"
                    }))
        except Exception as e:
            logger.error(f"Failed to send LLM exhausted notification: {e}")

    def switch_llm_provider(self, provider_name: str) -> bool:
        """Manually switch to a specific LLM provider or DISABLE AI"""
        
        if provider_name.upper() == "DISABLED":
            self.client = None
            self.model_name = "DISABLED (Tech Only)"
            self.llm_provider = "DISABLED"
            logger.info("🚫 AI Agent MANUALLY DISABLED (Tech Only Mode)")
            return True

        for idx, (name, client, model) in enumerate(self.llm_clients):
            if name == provider_name or provider_name in name:
                self.current_llm_index = idx
                self.client = client
                self.model_name = model
                self.llm_provider = name
                # Clear exhausted status for this provider (manual reset)
                # Clear exhausted status for this provider (manual reset)
                self.rate_limit_exhausted.discard(name)
                logger.info(f"✅ Manually switched to LLM: {name}")
                return True
        logger.warning(f"⚠️ Provider '{provider_name}' not found")
        return False
    
    def reset_llm_exhausted(self):
        """Reset all exhausted status - try all providers again"""
        self.rate_limit_exhausted.clear()
        self.current_llm_index = 0
        if self.llm_clients:
            self.client = self.llm_clients[0][1]
            self.model_name = self.llm_clients[0][2]
        logger.info("✅ All LLM providers reset - ready to retry")
    
    def get_llm_status(self) -> Dict:
        """Get current LLM status for UI"""
        current = self._get_current_llm()
        return {
            "current_provider": current[0] if current[0] else "NONE",
            "current_model": current[2] if current[2] else "N/A",
            "total_providers": len(self.llm_clients),
            "exhausted": list(self.rate_limit_exhausted),
            "available": [name for name, _, _ in self.llm_clients if name not in self.rate_limit_exhausted]
        }
    
    def _call_llm(self, messages: List[Dict], response_format: Dict = None) -> Optional[str]:
        """Call LLM with automatic fallback on rate limit"""
        max_attempts = len(self.llm_clients) + 1
        
        for attempt in range(max_attempts):
            name, client, model = self._get_current_llm()
            
            if not client:
                logger.error("🚨 ALL LLM RATE LIMITS EXHAUSTED - No AI available")
                return None
            
            try:
                if client == "NATIVE_GEMINI":
                    return self._call_gemini_native(messages, model, response_format)

                kwargs = {
                    "model": model,
                    "messages": messages
                }
                if response_format:
                    kwargs["response_format"] = response_format
                
                response = client.chat.completions.create(**kwargs)
                return response.choices[0].message.content
                
            except Exception as e:
                error_str = str(e)
                
                # Check for rate limit errors OR any error from Gemini Native (force fallback)
                is_rate_limit = "429" in error_str or "rate_limit" in error_str.lower() or "Rate limit" in error_str
                is_gemini_error = name == "Google Gemini" # Always fallback if Gemini fails (e.g. 404, 500)
                
                if is_rate_limit or is_gemini_error:
                    logger.warning(f"⚠️ Provider error on {name}: {error_str[:100]}... Switching...")
                    if not self._switch_to_next_llm(name, error_str):
                        return None
                    continue
                else:
                    # Other error, don't switch
                    logger.error(f"LLM Error ({name}): {e}")
                    return None
        
        return None

    def _call_gemini_native(self, messages, model, response_format=None):
        """Native REST call to Google Gemini API"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key: raise ValueError("GEMINI_API_KEY missing")
        
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        
        contents = []
        system_instruction = None
        
        for m in messages:
            role = m["role"]
            text = m["content"]
            if role == "system":
                system_instruction = {"parts": [{"text": text}]}
            elif role == "user":
                contents.append({"role": "user", "parts": [{"text": text}]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": text}]})
                
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 4096
            }
        }
        
        if system_instruction:
             payload["systemInstruction"] = system_instruction

        if response_format and response_format.get("type") == "json_object":
             payload["generationConfig"]["response_mime_type"] = "application/json"

        resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=60)
        
        if resp.status_code != 200:
            logger.error(f"Gemini Native Error ({resp.status_code}): {resp.text} | URL: {url}")
            raise Exception(f"Gemini API Error {resp.status_code}: {resp.text}")
            
        data = resp.json()
        if "candidates" not in data or not data["candidates"]:
             # Happens if safety filters trigger
             raise Exception("Gemini returned no candidates (Safety Filter?)")
             
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def _search_web(self, query: str, timeout: int = 10) -> str:
        """Search the web using Brave Search API with improved timeout handling"""
        if not self.brave_key:
            return "Error: BRAVE_API_KEY is missing."
            
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.brave_key
        }
        params = {"q": query, "count": 3}
        
        try:
            logger.info(f"🔎 Searching Brave: {query}")
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            
            results = []
            if 'web' in data and 'results' in data['web']:
                for item in data['web']['results']:
                    results.append(f"- [{item.get('title')}]({item.get('url')}): {item.get('description')}")
            
            return "\n".join(results) if results else "No results found."
            
        except requests.exceptions.Timeout:
            logger.warning(f"⏱️ Brave Search timeout ({timeout}s) - skipping news")
            return "Search timeout - proceeding without news."
        except requests.exceptions.ProxyError as e:
            logger.warning(f"🔌 Proxy error in Brave Search: {e}")
            return "Search unavailable (proxy issue) - proceeding without news."
        except Exception as e:
            logger.error(f"Search error: {e}")
            return f"Search failed: {str(e)}"

    async def chat(self, user_message: str) -> str:
        """Process a message from the user with REAL-TIME Market Context"""
        if not self.client:
            return "🤖 <b>AI модуль отключен.</b> Я работаю в режиме технического анализа.\nИспользуйте кнопки меню для управления 👇"

        # 0. DETECT SYMBOL IN MESSAGE (Simple heuristic)
        symbol = "BTCUSDT" # Default
        user_upper = user_message.upper()
        common_coins = ["ETH", "SOL", "XRP", "DOGE", "ADA", "BNB", "LTC"]
        for coin in common_coins:
            if coin in user_upper:
                symbol = f"{coin}USDT"
                break
        
        # 1. FETCH REAL DATA CONTEXT
        market_context_str = ""
        try:
            if self.controller and hasattr(self.controller, 'bot') and self.controller.bot and self.controller.bot.client:
                ticker = self.controller.bot.client._request("/v5/market/tickers", {"category": "linear", "symbol": symbol})
                if ticker and 'list' in ticker and ticker['list']:
                    price = float(ticker['list'][0]['lastPrice'])
                    change24h = float(ticker['list'][0]['price24hPcnt']) * 100
                    market_context_str = f"""
!!! SYSTEM OVERRIDE: REAL-TIME MARKET DATA PROVIDED BELOW !!!
You MUST use this data to answer. Do NOT say you don't have access.
TARGET SYMBOL: {symbol}
CURRENT PRICE: ${price}
24h CHANGE: {change24h:.2f}%
"""
        except Exception as e:
            logger.warning(f"Failed to fetch chat context: {e}")

        # 1.5 WEB SEARCH INTEGRATION (News/Why?)
        search_context_str = ""
        keywords = ["news", "why", "reason", "happening", "новости", "почему", "анализ", "прогноз", "думаешь"]
        if any(w in user_message.lower() for w in keywords):
             logger.info(f"🔎 Chat triggered Web Search for: {user_message}")
             search_res = self._search_web(f"{symbol} crypto market news analysis today")
             search_context_str = f"\n\nLATEST WEB SEARCH RESULTS (Use this for 'Why/News'):\n{search_res}\n"

        # 1.6 GUARDIAN CONTEXT (Live)
        guardian_str = ""
        if self.controller:
            try:
                status = await self.controller.get_status()
                hedge = status.get('hedge_status', 'Inactive')
                news = status.get('news_danger', 'None')
                regime = status.get('regime', 'NEUTRAL')
                
                guardian_str = f"""
--- LIVE SYSTEM STATUS ---
Hedge: {hedge}
News: {news}
Regime: {regime}
--------------------------
"""
            except: pass

        # 2. Prepare messages with DATA
        final_system_prompt = self.system_prompt + "\n" + guardian_str + market_context_str + search_context_str
        
        messages = [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": user_message}
        ]

        # 3. Call LLM with fallback
        try:
            name, _, model = self._get_current_llm()
            logger.info(f"🤖 Asking Brain ({name}: {model})...")
            result = self._call_llm(messages)
            
            if result is None:
                return "🚨 Все LLM провайдеры недоступны (лимиты исчерпаны). Попробуйте позже."
            
            return result
        except Exception as e:
            return f"❌ Ошибка AI: {str(e)}"

    async def analyze_market_context(self, symbol: str = "BTCUSDT") -> Dict[str, Any]:
        """
        Автономный анализ рынка: Новости + Технический анализ + Сигнал
        Now with Multi-Timeframe Confirmation (Phase 4).
        """
        logger.info(f"🧠 AI Sentinel: Analyzing {symbol}...")
        
        # 0. FETCH REAL-TIME PRICE & MTF DATA
        current_price = 0.0
        mtf_context = ""
        try:
            if self.controller and hasattr(self.controller.bot, 'client') and self.controller.bot.client:
                import asyncio
                loop = asyncio.get_running_loop()
                
                # Get Ticker
                ticker = await loop.run_in_executor(None, lambda: self.controller.bot.client._request("/v5/market/tickers", {"category": "linear", "symbol": symbol}))
                if ticker and 'list' in ticker and ticker['list']:
                    current_price = float(ticker['list'][0]['lastPrice'])
                    logger.info(f"💲 Real-time Price for {symbol}: {current_price}")
                
                await asyncio.sleep(1) # Network Yield
                
                # Get Multi-Timeframe Klines (Phase 4: MTF Confirmation)
                klines_1m = await loop.run_in_executor(None, lambda: self.controller.bot.client._request("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": "1", "limit": "50"}))
                await asyncio.sleep(0.3)
                klines_15m = await loop.run_in_executor(None, lambda: self.controller.bot.client._request("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": "15", "limit": "50"}))
                await asyncio.sleep(0.5)
                klines_1h = await loop.run_in_executor(None, lambda: self.controller.bot.client._request("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": "60", "limit": "50"}))
                await asyncio.sleep(0.5)
                klines_4h = await loop.run_in_executor(None, lambda: self.controller.bot.client._request("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": "240", "limit": "50"}))
                
                # Simple RSI & Momentum Proxy
                def calc_indicators(klines_data):
                    if not klines_data or 'list' not in klines_data or len(klines_data['list']) < 20:
                        return 50, 0
                    closes = [float(k[4]) for k in klines_data['list'][:20]] # Close at index 4
                    closes.reverse()
                    volumes = [float(k[5]) for k in klines_data['list'][:20]]
                    volumes.reverse()
                    
                    # RSI
                    gains, losses = 0, 0
                    for i in range(1, 15):
                        diff = closes[i] - closes[i-1]
                        if diff > 0: gains += diff
                        else: losses += abs(diff)
                    avg_gain, avg_loss = gains/14, (losses/14 or 0.0001)
                    rsi = 100 - (100 / (1 + avg_gain/avg_loss))
                    
                    # Vol Z-Score Proxy
                    avg_vol = sum(volumes) / len(volumes)
                    vol_z = (volumes[-1] - avg_vol) / (avg_vol * 0.5 + 0.001)
                    
                    return rsi, vol_z
                
                rsi_1m, vol_1m = calc_indicators(klines_1m)
                rsi_15m, vol_15m = calc_indicators(klines_15m)
                rsi_1h, vol_1h = calc_indicators(klines_1h)
                rsi_4h, vol_4h = calc_indicators(klines_4h)
                
                mtf_context = f"""
MULTI-TIMEFRAME ALPHA (MTF):
- 1m: RSI {rsi_1m:.1f}, VolZ {vol_1m:+.1f} (Local momentum)
- 15m: RSI {rsi_15m:.1f}, VolZ {vol_15m:+.1f}
- 1H: RSI {rsi_1h:.1f}, VolZ {vol_1h:+.1f} (Mid trend)
- 4H: RSI {rsi_4h:.1f}, VolZ {vol_4h:+.1f} (Macro trend)

SCALER RULES:
- Long: If 1h/4h RSI < 50 AND 1m/15m RSI < 30 AND VolZ > 1.5
- Short: If 1h/4h RSI > 50 AND 1m/15m RSI > 70 AND VolZ > 1.5
"""
                logger.info(f"📊 MTF RSI: 1m={rsi_1m:.1f}, 15m={rsi_15m:.1f}, 1H={rsi_1h:.1f}, 4H={rsi_4h:.1f}")
                
        except Exception as e:
            logger.error(f"Failed to fetch price/MTF data: {e}")

        # 1. Поиск новостей
        news_query = f"{symbol} price analysis technical news today"
        news_text = self._search_web(news_query)
        
        # 1.5 Fetch Guardian & Portfolio Context
        guardian_context = ""
        if self.controller:
            try:
                status = await self.controller.get_status()
                hedge = status.get('hedge_status', 'Inactive')
                news_danger = status.get('news_danger', 'None')
                regime = status.get('regime', 'NEUTRAL')
                
                guardian_context = f"""
SYSTEM GUARDIANS & PORTFOLIO STATE:
- **Market Regime**: {regime} (Global filter)
- **News Shield**: {news_danger if news_danger != "None" else "ACTIVE (SAFE)"}
- **Portfolio Hedge**: {hedge.upper()}
"""
                # Check for BTC/ETH divergence if doing ETH analysis (SAFE CHECK)
                if symbol in ["ETHUSDT", "BTCUSDT"] and hasattr(self.controller.bot, 'client') and self.controller.bot.client:
                    try:
                        ticker_btc = self.controller.bot.client._request("/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})
                        ticker_eth = self.controller.bot.client._request("/v5/market/tickers", {"category": "linear", "symbol": "ETHUSDT"})
                        if ticker_btc and ticker_eth and 'list' in ticker_btc.get('list', []) and 'list' in ticker_eth.get('list', []):
                            p_btc = (float(ticker_btc['list'][0]['lastPrice']) - float(ticker_btc['list'][0]['prevPrice24h'])) / float(ticker_btc['list'][0]['prevPrice24h']) * 100
                            p_eth = (float(ticker_eth['list'][0]['lastPrice']) - float(ticker_eth['list'][0]['prevPrice24h'])) / float(ticker_eth['list'][0]['prevPrice24h']) * 100
                            guardian_context += f"- **Divergence**: BTC {p_btc:+.2f}%, ETH {p_eth:+.2f}% (Sync Check)\n"
                    except:
                        pass
            except Exception as e:
                logger.error(f"Failed to fetch guardian context: {e}")
        
        prompt_price_info = f"CURRENT PRICE: {current_price}"
        
        # Build strategy list for auto-selection
        strategy_list = "\n".join([f"- **{v['name']}**: {v['description']}" for k, v in STRATEGY_PROFILES.items()])
        
        prompt = f"""
        ACT AS AN ELITE TRADER (God Mode). Analyze {symbol}.
        
        {prompt_price_info}
        
        {mtf_context}
        
        {guardian_context}
        
        LATEST NEWS & CONTEXT:
        {news_text}
        
        🎯 AUTO-STRATEGY SELECTION (You MUST choose the BEST strategy):
        {strategy_list}
        
        ### LEARNED EXPERIENCE (Self-Correction):
        {self.learned_context}
        
        DECISION GUIDE:
        1. **TRENDING market** → use "Trend Follower (EMA)"
        2. **RANGING market** → use "Level Trader (S&R)"  
        3. **RSI EXTREMES** → use "Mean Reversion (RSI)"
        4. **BREAKOUT setup** → use "Breakout Hunter"
        5. **MOMENTUM acceleration** → use "Acceleration Trader"
        6. **SCALPING opportunity** (Quick 1m move, RSI divergence on 1m, or FVG fill) → use "Neuro-Scalper (1m Micro)"
        
        ### CRITICAL RULE (HISTORY BIAS):
        - **CHECK LEARNED EXPERIENCE ABOVE!** 
        - If the "Learned Experience" says this symbol has been PERFORMING BADLY (losses, fakeouts), you **MUST** be extra skeptical.
        - **DEDUCT 15-20% CONFIDENCE** automatically if previous trades on this coin were losses, unless the setup is PERFECT.
        - If Learning says "Avoid ETH", then DO NOT trade ETH.
        
        ### SPECIAL GUARDIAN RULES:
        - **DIVERGENCE**: If ETH/BTC divergence is strongly negative (< -2%), Alts are likely losing liquidity to BTC. Avoid Longs on Alts.
        - **NEWS DANGER**: If News Shield reports a specific coin/event danger, BE EXTREMELY CAUTIOUS.
        - **PORTFOLIO HEDGE**: If Portfolio Hedge is ACTIVE, it means the bot is already protecting us from a crash.
        - **WHALE WATCHER**: You should assume Whale Watcher will block entries if massive walls appear.
        
        TASK:
        1. **Identify Market Condition**: What type of market is this?
        2. **Select Best Strategy**: Choose from the list above. If you see a high-probability micro-opportunity, use SCALPING.
        3. **Find Setup**: Apply the chosen strategy.
        4. **Generate Signal**: With proper entry/SL/TP.
        
        - **SELECTIVITY**: We prefer NO TRADE over a BAD trade. If the setup is not clear, if there's indecision, or if volatility is too high/low, set confidence < 50 and action to 'WAIT'.
        - **Risk/Reward**: Must be > 1:3 for normal trades, but for SCALPING (1m) it can be 1:1.5 or 1:2.
        - **Entry**: MUST be close to {current_price}
        - **Confidence**: Be extremeley strict. Only 85+ confidence trades will be executed.
        - **Scalping TP**: Usually 0.3% to 0.7%.
        - **Scalping SL**: Usually 0.2% to 0.4%.
        
        RETURN JSON ONLY:
        {{
            "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
            "confidence": 0-100,
            "reasoning": "Подробное объяснение НА РУССКОМ. Почему вход именно сейчас? Опиши паттерн, RSI, уровни и логику. Используй эмодзи.",
            "suggested_risk": 0.5 | 1.0 | 2.0,
            "action": "BUY" | "SELL" | "WAIT",
            "entry_price": numeric value or "Market",
            "take_profit": numeric target,
            "stop_loss": numeric invalidation level,
            "signal_title": "Краткий заголовок на русском (напр. 'Пробой 100k')",
            "strategy_name": "Name of chosen strategy from the list"
        }}
        """
        
        # Use LLM with automatic fallback
        name, client, model = self._get_current_llm()
        if not client:
            logger.error("🚨 ALL LLM RATE LIMITS EXHAUSTED - Cannot analyze")
            return {"sentiment": "NEUTRAL", "confidence": 0, "reasoning": "LLM unavailable - all rate limits exhausted", "action": "WAIT"}
        
        try:
            messages = [
                {"role": "system", "content": "You are a professional trader. Output valid JSON only."},
                {"role": "user", "content": prompt}
            ]
            
            response_text = self._call_llm(messages, response_format={"type": "json_object"})
            
            if response_text is None:
                logger.error("🚨 LLM returned None - all providers exhausted")
                return {"sentiment": "NEUTRAL", "confidence": 0, "reasoning": "AI unavailable (all rate limits exhausted)", "action": "WAIT"}
            
            result = json.loads(response_text)
            
            # --- VALIDATE PRICE & ENFORCE 1:3 RR ---
            if result.get("action") in ["BUY", "SELL"]:
                # 1. Validate/Fix Entry Price
                ai_entry = result.get("entry_price")
                final_entry = current_price # Default to real price
                
                if isinstance(ai_entry, (int, float)):
                    # Check deviation
                    if current_price > 0:
                        diff_pct = abs(ai_entry - current_price) / current_price
                        if diff_pct > 0.05: # If AI is off by >5%
                             logger.warning(f"⚠️ AI Hallucinated Price ({ai_entry}) vs Real ({current_price}). Forcing Market Entry.")
                             result["entry_price"] = current_price
                             result["reasoning"] += " [Entry Corrected to Market Price]"
                        else:
                             final_entry = ai_entry
                else:
                    # "Market" string
                    result["entry_price"] = current_price
                
                # 2. Validate RR with Final Entry
                try:
                    tp = float(result["take_profit"])
                    sl = float(result["stop_loss"])
                    
                    dist_sl = abs(final_entry - sl)
                    dist_tp = abs(final_entry - tp)
                    
                    dist_tp = abs(final_entry - tp)
                    
                    if dist_sl > 0:
                        rr = dist_tp / dist_sl
                        min_rr = 1.5 if result.get("strategy_name") == "Neuro-Scalper (1m Micro)" else 3.0
                        if rr < min_rr:
                            logger.warning(f"⚠️ AI generated weak RR ({rr:.2f}) for strategy {result.get('strategy_name')}. Adjusting TP to 1:{min_rr}.")
                            # Force min_rr
                            if result["action"] == "BUY":
                                result["take_profit"] = final_entry + (dist_sl * min_rr)
                            else:
                                result["take_profit"] = final_entry - (dist_sl * min_rr)
                            
                            result["reasoning"] += " [RR Adjusted to 1:3]"
                except Exception as e:
                    logger.error(f"RR Validation failed: {e}")

            # --- GUARDIAN ENFORCEMENT: MARKET REGIME ---
            # Strict filter: Block signals against global trend
            if "Market Regime**: TREND_DOWN" in guardian_context and result.get("action") == "BUY":
                logger.warning(f"🛡️ GUARDIAN BLOCKED LONG on {symbol} (Regime: TREND_DOWN)")
                result["action"] = "WAIT"
                result["confidence"] = 0
                result["reasoning"] = f"⛔ BLOCKED BY GUARDIAN. Market is dumping (TREND_DOWN). Longs are forbidden. Original: {result.get('reasoning')}"
            
            elif "Market Regime**: TREND_UP" in guardian_context and result.get("action") == "SELL":
                logger.warning(f"🛡️ GUARDIAN BLOCKED SHORT on {symbol} (Regime: TREND_UP)")
                result["action"] = "WAIT"
                result["confidence"] = 0
                result["reasoning"] = f"⛔ BLOCKED BY GUARDIAN. Market is pumping (TREND_UP). Shorts are forbidden. Original: {result.get('reasoning')}"
            
            # Store for Step 3 implementation (Visual Sniper)
            self.latest_analysis[symbol] = result
            
            logger.info(f"🧠 Analysis Result: {result}")
            return result
        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            return {"sentiment": "NEUTRAL", "confidence": 0, "reasoning": "Error", "action": "WAIT"}

            return {"sentiment": "NEUTRAL", "confidence": 0, "reasoning": "Error", "action": "WAIT"}

    async def manage_active_positions(self):
        """
        SMART EXIT DISABLED per User Request.
        """
        return

        try:
            import asyncio
            loop = asyncio.get_running_loop()
            
            # 1. Get Open Positions
            positions = await loop.run_in_executor(None, self.controller.bot.client.get_open_positions)
            
            if not positions:
                return

            logger.info(f"🕵️ Smart Exit: Checking {len(positions)} active positions...")

            for pos in positions:
                symbol = pos['symbol']
                side = pos['side'] # 'Buy' or 'Sell'
                size = pos['size']
                
                # 2. Analyze Current Market
                analysis = await self.analyze_market_context(symbol)
                
                # --- NEW: MACRO SENTIMENT EXIT ---
                global_allowed = "BOTH"
                if self.controller and hasattr(self.controller.bot, 'sentiment_service'):
                    global_allowed = getattr(self.controller.bot.sentiment_service, 'allowed_direction', 'BOTH')
                
                # 3. Check for REVERSAL or MACRO CONFLICT
                should_close = False
                reason = ""
                
                action = analysis.get('action')
                conf = analysis.get('confidence', 0)
                
                # Check Global Conflict
                if side == 'Buy' and global_allowed in ['SHORT_ONLY', 'NONE']:
                    should_close = True
                    reason = f"Macro Regime Shift to {global_allowed}"
                elif side == 'Sell' and global_allowed in ['LONG_ONLY', 'NONE']:
                    should_close = True
                    reason = f"Macro Regime Shift to {global_allowed}"
                
                # --- NEW: MOMENTUM & STRUCTURE EXIT ---
                # Check for unrealized loss and trend direction on small TF
                unrealized_pnl_pct = float(pos.get('unrealisedPnl', 0)) / (float(pos.get('positionValue', 1)) + 0.001) * 100
                
                # Logic: If Long and Losing > 1% AND Analysis says SELL (any confidence) -> Fast Exit
                if not should_close:
                    if side == 'Buy' and (action == 'SELL' or unrealized_pnl_pct < -0.8):
                        # If we are in loss and AI/Sentiment doesn't support the trade anymore
                        if global_allowed in ['SHORT_ONLY', 'NONE'] or (action == 'SELL' and conf >= 50):
                             should_close = True
                             reason = f"Loss Protection: Momentum shift ({action}) and P&L Bleeding ({unrealized_pnl_pct:.2f}%)"
                    elif side == 'Sell' and (action == 'BUY' or unrealized_pnl_pct < -0.8):
                        if global_allowed in ['LONG_ONLY', 'NONE'] or (action == 'BUY' and conf >= 50):
                             should_close = True
                             reason = f"Loss Protection: Momentum shift ({action}) and P&L Bleeding ({unrealized_pnl_pct:.2f}%)"

                # Logic: Final AI Reversal check
                if not should_close:
                    if side == 'Buy' and action == 'SELL' and conf >= 70:
                        should_close = True
                        reason = f"AI Bearish Reversal (Conf: {conf}%)"
                    elif side == 'Sell' and action == 'BUY' and conf >= 70:
                        should_close = True
                        reason = f"AI Bullish Reversal (Conf: {conf}%)"
                    
                if should_close:
                    logger.info(f"🚨 SMART EXIT TRIGGERED: Closing {side} {symbol}. Reason: {reason}")
                    
                    close_side = "Sell" if side == "Buy" else "Buy"
                    
                    res = await loop.run_in_executor(None, lambda: self.controller.bot.client.place_order(
                        symbol=symbol,
                        side=close_side,
                        qty=size,
                        reduce_only=True,
                        order_type='Market'
                    ))
                    
                    logger.info(f"✅ Position Closed: {res}")
                    
                    # Notify Controller/Telegram
                    if self.controller and hasattr(self.controller, 'send_signal_message'):
                         await self.controller.send_signal_message({
                            "symbol": symbol,
                            "action": "CLOSE",
                            "title": "🚨 SMART EXIT (AI)",
                            "reason": reason,
                            "confidence": conf,
                            "executed": True,
                            "order_id": res.get('orderId') if isinstance(res, dict) else None
                         })
                         
                await asyncio.sleep(2) # Throttle

        except Exception as e:
            logger.error(f"Smart Exit Error: {e}")

    async def perform_self_correction(self):
        """
        AI SELF-LEARNING (Detailed): Анализирует историю сделок по инструментам.
        """
        logger.info("🧠 AI Self-Correction: Deep analyzer for past performance...")
        
        try:
            # 1. Получаем историю
            all_trades = database.get_trades(limit=100)
            closed_trades = [t for t in all_trades if t['status'] == 'CLOSED']
            
            if not closed_trades:
                logger.info("  No closed trades for analysis yet.")
                return

            # 2. Группируем по символам
            symbol_stats = {}
            for t in closed_trades:
                s = t['symbol']
                pnl = t['pnl']
                if s not in symbol_stats: symbol_stats[s] = {'pnl': 0, 'wins': 0, 'losses': 0}
                symbol_stats[s]['pnl'] += pnl
                if pnl > 0: symbol_stats[s]['wins'] += 1
                else: symbol_stats[s]['losses'] += 1
            
            # 3. Формируем подробный отчет
            perf_str = "\n".join([
                f"- {s}: PnL=${st['pnl']:.2f} ({st['wins']}W / {st['losses']}L)"
                for s, st in symbol_stats.items()
            ])
            
            recent_trades_json = json.dumps(closed_trades[:15], indent=2)
            
            prompt = f"""
            ### SUMMARY OF RECENT PERFORMANCE BY SYMBOL:
            {perf_str}
            
            ### DETAILED RECENT TRADES:
            {recent_trades_json}
            
            ЗАДАЧА:
            1. Проанализируй, какие символы (монеты) приносят УБЫТОК. (Напр. если ETH постоянно в минусе, почему?).
            2. Выяви закономерности: ложные пробои, слишком близкие стопы, работа против тренда.
            3. Напиши КРАТКУЮ инструкцию (3-4 пункта) на РУССКОМ для себя будущего.
            
            Пример вывода: "С ETH будь осторожен, много ложных пробоев. На BTC стратегия EMA работает отлично, продолжай."
            """
            
            messages = [
                {"role": "system", "content": "You are a Chief Performance Analyst. Be clinical and critical."},
                {"role": "user", "content": prompt}
            ]
            
            correction = self._call_llm(messages)
            
            if correction:
                self.learned_context = correction
                logger.info(f"✅ AI Self-Learning Update: {correction}")
            
        except Exception as e:
            logger.error(f"Self-Correction failed: {e}")

    async def run_autonomous_cycle(self, interval_minutes: int = 10):
        """
        Фоновый цикл "Sentinel Mode" - сканирует несколько монет
        """
        import asyncio
        logger.info(f"🛡️ Sentinel Loop STARTED (Interval: {interval_minutes}m)")
        
        last_correction = 0
        
        while True:
            try:
                # --- AUTO-RESET AI PROVIDER (Self-Healing) ---
                # Force reset to Primary (Gemini) every cycle to recover from transient errors/limits
                if hasattr(self, 'llm_clients') and self.llm_clients:
                    self.current_llm_index = 0
                    self.llm_provider = self.llm_clients[0][0]
                    # logger.info(f"♻️ AI Provider Auto-Reset to Primary: {self.llm_provider}")

                # 0. SMART EXIT CHECK (Before scanning new setups)
                await self.manage_active_positions()
                
                # 0.5 AI SELF-LEARNING (Run every 6 hours or at start)
                if time.time() - last_correction > 3600 * 6:
                    await self.perform_self_correction()
                    last_correction = time.time()

                # Список приоритетных монет для AI сканирования (Топ-20)
                sentinel_coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
                
                # Если подключены к боту, берем актуальные топ-20 по объему
                if self.controller and hasattr(self.controller.bot, 'client') and self.controller.bot.client:
                    try:
                        # Prevent cycle if LLM is already in DISABLED mode
                        if self.llm_provider == "DISABLED":
                             logger.warning("🛡️ Sentinel: Cycle skipped (AI is in DISABLED mode due to limits)")
                             await asyncio.sleep(600) # Long sleep
                             continue

                        loop = asyncio.get_running_loop()
                        top_data = await loop.run_in_executor(
                            None, 
                            lambda: self.controller.bot.client.get_top_symbols_by_volume(top_n=20)
                        )
                        
                        # HYBRID LOGIC: Take Top 20 by Volume, pick Top 5 by Volatility
                        top_data.sort(key=lambda x: abs(x.get('change_24h', 0)), reverse=True)
                        sentinel_coins = [s['symbol'] for s in top_data[:5]]
                        
                        logger.info(f"📊 Sentinel selected top 5 MOVE-MAKERS (from top 20 volume): {sentinel_coins}")
                    except Exception as e:
                        logger.error(f"Failed to fetch dynamic top coins: {e}")
                
                for symbol in sentinel_coins:
                    logger.info(f"🧠 AI Sentinel Cycle: {symbol}")
                    
                    # 1. Анализ конкретной монеты
                    analysis = await self.analyze_market_context(symbol)
                    
                    # AUTO-DISABLE if Rate Limits Hit
                    reason = analysis.get('reasoning', '')
                    if "rate limits exhausted" in reason.lower() or "llm unavailable" in reason.lower():
                        logger.error("🚨 AUTO-PROTECTION: All AI limits exhausted. Switching to DISABLED mode.")
                        self.switch_llm_provider("DISABLED")
                        break # Stop scanning other coins
                        
                    # 2. Логика Сигналов
                    conf = analysis.get('confidence', 0)
                    action = str(analysis.get('action', '')).upper()
                    
                    # --- SNIPER MODE: High Confidence + Regime Check ---
                    regime = analysis.get('sentiment', 'NEUTRAL')
                    
                    # Fetch global sentiment from controller if available
                    global_regime = "NEUTRAL"
                    if self.controller and hasattr(self.controller, 'get_regime'):
                        global_regime = await self.controller.get_regime()
                        
                    if global_regime == "RISK_OFF":
                        logger.warning(f"🛡️ AI Sentinel SKIP: {symbol} - Global Regime is RISK_OFF")
                        continue

                    if action in ['BUY', 'SELL'] and conf >= 85:
                        logger.info(f"🚀 AI SIGNAL found: {action} {symbol} (Conf: {conf}%)")
                        
                        # Добавляем символ в данные анализа
                        analysis['symbol'] = symbol
                        
                        # 1. АВТО-ИСПОЛНЕНИЕ ПЕРВЫМ ДЕЛОМ
                        execution_result = {}
                        is_executed = False
                        
                        if self.controller and hasattr(self.controller, 'execute_ai_trade'):
                            try:
                                logger.info(f"⚡ AI AUTO-TRADE TRIGGERED: {symbol} {action}")
                                execution_result = await self.controller.execute_ai_trade(analysis)
                                # Success is dictated by the 'success' key in result dict
                                if execution_result and isinstance(execution_result, dict) and execution_result.get('success'):
                                     is_executed = True
                                     logger.info(f"✅ AI AUTO-TRADE SUCCESS: {symbol}")
                                else:
                                     err = execution_result.get('error', 'Unknown rejection')
                                     logger.warning(f"❌ AI AUTO-TRADE REJECTED: {symbol} - {err}")
                            except Exception as e:
                                logger.error(f"Auto-trade call failed: {e}")

                        # 2. Отправка в Controller -> Telegram (с флагом executed)
                        if self.controller and hasattr(self.controller, 'send_signal_message'):
                            await self.controller.send_signal_message({
                                "symbol": symbol,
                                "action": analysis['action'],
                                "entry": analysis.get('entry_price'),
                                "tp": analysis.get('take_profit'),
                                "sl": analysis.get('stop_loss'),
                                "confidence": conf,
                                "reason": analysis.get('reasoning'),
                                "title": analysis.get('signal_title', 'AI Signal'),
                                "strategy": analysis.get('strategy_name', 'AI Sentinel'),
                                "executed": is_executed,
                                "order_id": execution_result.get('orderId') if isinstance(execution_result, dict) else None,
                                "execution_error": execution_result.get('error') if not is_executed and execution_result else None
                            })
                    
                    # Небольшая пауза между монетами, чтобы не спамить API
                    await asyncio.sleep(10)
                    
                logger.info(f"✅ Sentinel Cycle Complete. Sleeping for {interval_minutes}m")
                await asyncio.sleep(interval_minutes * 60)
                
            except asyncio.CancelledError:
                logger.info("🛡️ Sentinel Loop STOPPED")
                break
            except Exception as e:
                logger.error(f"Sentinel Loop Error: {e}")
                await asyncio.sleep(60) # Retry after 1 min

if __name__ == "__main__":
    agent = TradingAgent()
    # ... tests
    async def run_tests():
        print("Test 1 (General):", await agent.chat("Привет! Ты кто?"))
        print("----------------------------------------------------------------")
        print("\n----------------------------------------------------------------")
        print("Test 2 (Search):", await agent.chat("Что там с курсом Биткоина и новостями сегодня?"))
        print("----------------------------------------------------------------")
    
    import asyncio
    asyncio.run(run_tests())
