import asyncio
import logging
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class NewsService:
    """
    The Sentinel 🛡️
    Detects high-impact news events (CPI, FOMC, etc.) and warns the system to pause trading.
    """
    
    def __init__(self, agent):
        self.agent = agent
        self.events: List[Dict] = []
        self.last_update = None
        self.risk_off_active = False
        self.cryptopanic_key = os.getenv("CRYPTOPANIC_KEY", "35054daf8a39a0d6d1d53f08ce298ab9ba111d4c")
        import requests
        self.requests = requests
        
        # --- LLM-BASED SENTIMENT (Optimized for RAM) ---
        # Removed FinBERT local model to save ~1GB of RAM
        self.sentiment_analyzer = None
        logger.info("🛡️ News Service using LLM-based sentiment (Zero-RAM mode)")

    async def start(self, interval_hours: int = 6):
        """Starts the background news monitoring loop"""
        self.is_running = True
        logger.info(f"🛡️ News Service STARTED (Interval: {interval_hours}h)")
        
        while self.is_running:
            try:
                await self.update_events()
                # Check for immediate danger
                self.check_danger_zone()
                await asyncio.sleep(interval_hours * 3600)
            except Exception as e:
                logger.error(f"News Service Error: {e}")
                await asyncio.sleep(300)

    async def update_events(self):
        """Web search for major economic events and use AI to parse them"""
        if not self.agent.client:
            logger.warning("AI Agent disabled, News Service using empty events.")
            return

        try:
            query = "high impact crypto economic events this week FOMC CPI NFP"
            loop = asyncio.get_running_loop()
            search_res = await loop.run_in_executor(None, lambda: self.agent._search_web(query))
            
            prompt = f"""
            Based on this search result, identify upcoming high-impact economic events that will cause volatility in BTC/Crypto.
            Look for CPI, FOMC, Fed Interest Rate, NFP (Non-Farm Payrolls).
            
            Current Time (UTC): {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}
            
            Search Result:
            {search_res}
            
            RETURN JSON ONLY (List of events):
            {{
                "events": [
                    {{
                        "name": "Event Name",
                        "time_utc": "YYYY-MM-DD HH:MM:00",
                        "severity": "HIGH",
                        "description": "Why it matters"
                    }}
                ]
            }}
            """
            
            messages = [
                {"role": "system", "content": "You are a Financial News Analyst. Extract events into valid JSON."},
                {"role": "user", "content": prompt}
            ]
            
            # Use unified agent method (supports fallback & native Gemini)
            response_text = await loop.run_in_executor(
                None,
                lambda: self.agent._call_llm(
                    messages=messages,
                    response_format={"type": "json_object"}
                )
            )
            
            if not response_text:
                logger.warning("News Service: AI returned no content")
                return

            data = json.loads(response_text)
            self.events = data.get('events', [])
            self.last_update = datetime.now()
            logger.info(f"🛡️ News Service updated: {len(self.events)} high-impact events found.")
            
        except Exception as e:
            logger.error(f"Failed to update news events: {e}")

    def check_danger_zone(self, buffer_minutes: int = 60) -> Optional[Dict]:
        """
        Returns the news event if we are within the 'danger zone' (buffer_minutes before/after).
        """
        now = datetime.utcnow()
        for event in self.events:
            try:
                event_time = datetime.strptime(event['time_utc'], '%Y-%m-%d %H:%M:%S')
                start_danger = event_time - timedelta(minutes=buffer_minutes)
                end_danger = event_time + timedelta(minutes=buffer_minutes // 2) # Shorter tail usually
                
                if start_danger <= now <= end_danger:
                    self.risk_off_active = True
                    return event
            except:
                continue
        
        self.risk_off_active = False
        return None

    def get_upcoming_events(self) -> List[Dict]:
        """Returns future events only"""
        now = datetime.now()
        upcoming = []
        for e in self.events:
            try:
                # Handle both timestamp strings and datetime objects
                e_time = e['time_utc']
                if isinstance(e_time, str):
                    e_time = datetime.strptime(e_time, '%Y-%m-%d %H:%M:%S')
                
                if e_time > now:
                    upcoming.append(e)
            except: pass
        return upcoming

    # --- NEW: SYMBOL SENTIMENT LOGIC ---
    
    async def analyze_sentiment_llm(self, text: str) -> Dict:
        """Analyzes sentiment using the agent's LLM API (Memory-efficient)"""
        try:
            # Ultra-tiny prompt for fast response
            prompt = f"Crypto news sentiment: '{text}'. Return: POSITIVE, NEGATIVE, or NEUTRAL."
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, lambda: self.agent._call_llm([{"role": "user", "content": prompt}]))
            
            label = res.strip().upper() if res else "NEUTRAL"
            score = 0.8 if "POSITIVE" in label else (0.8 if "NEGATIVE" in label else 0.0)
            final_label = "positive" if "POSITIVE" in label else ("negative" if "NEGATIVE" in label else "neutral")
            
            return {"label": final_label, "score": score}
        except Exception as e:
            logger.error(f"LLM Sentiment error: {e}")
            return {"label": "neutral", "score": 0.0}

    def analyze_sentiment(self, text: str) -> Dict:
        # Legacy placeholder, now handled by analyze_sentiment_llm
        return {"label": "neutral", "score": 0.0}

    async def get_symbol_sentiment(self, symbol: str) -> Dict:
        """Fetch and analyze news sentiment for a specific symbol"""
        currency = symbol.replace("USDT", "").replace("USDC", "")
        
        # 1. Try CryptoPanic API First
        if self.cryptopanic_key:
            try:
                logger.info(f"🔎 Fetching CryptoPanic news for {currency}...")
                url = f"https://cryptopanic.com/api/v1/posts/?auth_token={self.cryptopanic_key}&currencies={currency}&kind=news&filter=important"
                
                loop = asyncio.get_running_loop()
                response = await loop.run_in_executor(None, lambda: self.requests.get(url, timeout=10))
                
                if response.status_code == 200:
                    data = response.json()
                    results = data.get('results', [])
                    if results:
                        scores = []
                        for post in results[:7]: # Analyze top 7 news
                            title = post.get('title', '')
                            votes = post.get('votes', {})
                            
                            # Analyze title sentiment via LLM (No local model)
                            res = await self.analyze_sentiment_llm(title)
                            sentiment_score = res['score'] if res['label'] == 'positive' else (-res['score'] if res['label'] == 'negative' else 0.0)
                            
                            # Factor in community votes
                            positive_votes = votes.get('positive', 0) + votes.get('bullish', 0)
                            negative_votes = votes.get('negative', 0) + votes.get('bearish', 0)
                            
                            vote_score = 0
                            if (positive_votes + negative_votes) > 0:
                                vote_score = (positive_votes - negative_votes) / (positive_votes + negative_votes)
                            
                            # Combined score: 70% model, 30% community
                            combined = (sentiment_score * 0.7) + (vote_score * 0.3)
                            scores.append(combined)
                            
                        avg_score = sum(scores) / len(scores) if scores else 0.0
                        label = "positive" if avg_score > 0.15 else ("negative" if avg_score < -0.15 else "neutral")
                        
                        logger.info(f"✅ CryptoPanic Sentiment for {symbol}: {label} ({avg_score:.2f})")
                        return {
                            "score": avg_score,
                            "label": label,
                            "count": len(scores),
                            "source": "CryptoPanic"
                        }
            except Exception as e:
                logger.error(f"CryptoPanic API error for {symbol}: {e}")

        # 2. Fallback to Web Search via Agent
        try:
            query = f"latest {currency} crypto news price prediction sentiment"
            loop = asyncio.get_running_loop()
            news_text = await loop.run_in_executor(None, lambda: self.agent._search_web(query))
            
            if not news_text:
                return {"score": 0.0, "label": "neutral"}
                
            # Analyze chunks of text
            lines = [line for line in news_text.split('\n') if len(line) > 20]
            scores = []
            
            for line in lines[:5]: # Take top 5 snippets
                res = await self.analyze_sentiment_llm(line)
                if res['label'] == 'positive': scores.append(res['score'])
                elif res['label'] == 'negative': scores.append(-res['score'])
                else: scores.append(0.0)
                
            avg_score = sum(scores) / len(scores) if scores else 0.0
            
            return {
                "score": avg_score,
                "label": "positive" if avg_score > 0.2 else ("negative" if avg_score < -0.2 else "neutral"),
                "count": len(scores),
                "source": "WebSearch"
            }
        except Exception as e:
            logger.error(f"Symbol sentiment check failed for {symbol}: {e}")
            return {"score": 0.0, "label": "neutral"}
