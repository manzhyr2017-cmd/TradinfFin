import asyncio
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

class SentimentService:
    """
    The General 🌍
    Analyzes global market sentiment to set the 'Regime'.
    Acts as a filter for the Scanner.
    """
    
    def __init__(self, agent):
        self.agent = agent
        self.regime = "NEUTRAL" # RISK_ON, RISK_OFF, NEUTRAL
        self.reasoning = "Initializing..."
        self.last_update = None
        self.is_running = False
        
    async def start(self, interval_hours: float = 1.0):
        """Starts the background analysis loop"""
        self.is_running = True
        logger.info(f"🌍 Sentiment Service STARTED (Interval: {interval_hours}h)")
        
        while self.is_running:
            try:
                await self.analyze_market()
                
                # Sleep for interval
                await asyncio.sleep(interval_hours * 3600)
                
            except Exception as e:
                logger.error(f"Sentiment Loop Error: {e}")
                await asyncio.sleep(300) # Retry in 5 min on error

    async def analyze_market(self):
        """Queries AI Agent for global sentiment"""
        logger.info("🌍 Analyzing Global Market Sentiment...")
        
        # Check if AI is disabled
        if not self.agent.client:
            self.regime = "RISK_ON" # Default safe mode
            self.reasoning = "AI Disabled (Tech Only Mode)"
            self.allowed_direction = "BOTH"
            self.last_update = datetime.now()
            logger.info("🌍 Sentiment: AI Disabled -> Defaulting to RISK_ON (Trade Both)")
            return

        try:
            # 1. Fetch performance for Divergence Analysis
            ticker_btc = self.agent.controller.bot.client._request("/v5/market/tickers", {"category": self.agent.controller.bot.client.category.value, "symbol": "BTCUSDT"})
            ticker_eth = self.agent.controller.bot.client._request("/v5/market/tickers", {"category": self.agent.controller.bot.client.category.value, "symbol": "ETHUSDT"})
            
            perf_btc = 0.0
            perf_eth = 0.0
            if ticker_btc and 'list' in ticker_btc and ticker_btc['list']:
                t = ticker_btc['list'][0]
                # lastPrice vs prevPrice24h
                last = float(t['lastPrice'])
                prev = float(t['prevPrice24h'])
                perf_btc = (last - prev) / prev * 100
                
            if ticker_eth and 'list' in ticker_eth and ticker_eth['list']:
                t = ticker_eth['list'][0]
                last = float(t['lastPrice'])
                prev = float(t['prevPrice24h'])
                perf_eth = (last - prev) / prev * 100
            
            divergence = perf_eth - perf_btc
            logger.info(f"📊 Market Divergence Check: BTC {perf_btc:+.2f}%, ETH {perf_eth:+.2f}% (Div: {divergence:+.2f}%)")

            # 2. Search for Global Context
            query = "Bitcoin price analysis crypto market sentiment today news regulation sec"
            loop = asyncio.get_running_loop()
            news = await loop.run_in_executor(None, lambda: self.agent._search_web(query))
            
            # 3. Prompt for The General (Simplified 4 Regimes)
            prompt = f"""
            ACT AS 'THE GENERAL' (Macro Analyst).
            Analyze the GLOBAL Crypto Market Context.
            
            Current Performance (24h):
            - BTCUSDT: {perf_btc:+.2f}%
            - ETHUSDT: {perf_eth:+.2f}%
            - ETH/BTC Divergence: {divergence:+.2f}%
            
            News Context:
            {news}
            
            NOTE ON DIVERGENCE:
            If BTC is up but ETH is significantly down (Div < -2%), it's "Liquidity Sucking" - ALTS are dangerous.
            If BTC is down and ETH is crashing harder, it's Panic.
            
            Determine the MARKET REGIME for the next 4-12 hours:
            1. **TREND_UP**: Strong bullish momentum. BTC breaking highs. LONG only.
            2. **TREND_DOWN**: Strong bearish pressure, Crash, Panic sales. SHORT only.
            3. **RISK_ON**: Bullish/Stable sideways. Safe to trade BOTH directions.
            4. **RISK_OFF**: Extreme Uncertainty, Low Volume, or Wild Choppy Volatility (Whipsaw). DANGEROUS. Halt ALL trading.
            
            RETURN JSON ONLY:
            {{
                "regime": "TREND_UP" | "TREND_DOWN" | "RISK_ON" | "RISK_OFF",
                "reasoning": "Brief explanation in Russian (max 1 sentence).",
                "allowed_direction": "LONG_ONLY" | "SHORT_ONLY" | "BOTH" | "NONE",
                "risk_level": 1-10 (1=Safe, 10=Crash)
            }}
            """
            
            messages=[
                {"role": "system", "content": "You are a Macro Analyst. Output valid JSON only."},
                {"role": "user", "content": prompt}
            ]
            
            response_text = self.agent._call_llm(messages, response_format={"type": "json_object"})
            
            if not response_text:
                raise ValueError("AI Agent returned empty response (possibly all rate limits exhausted)")

            import json
            result = json.loads(response_text)
            
            self.regime = result.get('regime', 'RISK_ON')
            self.reasoning = result.get('reasoning', 'Analysis failed')
            self.allowed_direction = result.get('allowed_direction', 'BOTH')
            self.last_update = datetime.now()
            
            logger.info(f"🌍 REGIME UPDATE: {self.regime} | Direction: {self.allowed_direction} | {self.reasoning}")
            
            # --- FORCE UPDATE BOT STATE FILE ---
            try:
                import os
                state = {}
                if os.path.exists("bot_state.json"):
                    with open("bot_state.json", 'r') as f:
                        state = json.load(f)
                
                state.update({
                    "sentiment_regime": self.regime,
                    "sentiment_reason": self.reasoning,
                    "last_update": self.last_update.isoformat()
                })
                
                with open("bot_state.json", 'w') as f:
                    json.dump(state, f)
            except Exception as ex:
                logger.error(f"Failed to update bot_state.json: {ex}")
            # -----------------------------------
            
        except Exception as e:
            logger.error(f"Global Analysis Failed: {e}")
            self.regime = "RISK_ON"
            self.reasoning = f"Error: {str(e)}"
            self.allowed_direction = "BOTH"

    def get_state(self):
        return {
            "regime": self.regime,
            "reasoning": self.reasoning,
            "last_update": self.last_update.isoformat() if self.last_update else None
        }
