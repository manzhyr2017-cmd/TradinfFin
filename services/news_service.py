import asyncio
import logging
import json
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
        self.is_running = False
        self.risk_off_active = False
        
        # --- NEW: FinBERT Sentiment ---
        self.sentiment_analyzer = None
        try:
            from transformers import pipeline
            import torch
            self.sentiment_analyzer = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                device=0 if torch.cuda.is_available() else -1
            )
            logger.info("✅ News Sentiment (FinBERT) model loaded")
        except Exception as e:
            logger.warning(f"⚠️ FinBERT model load failed: {e}")

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
    
    def analyze_sentiment(self, text: str) -> Dict:
        """Analyzes sentiment of a text string"""
        if not self.sentiment_analyzer:
            return {"label": "neutral", "score": 0.0}
        try:
            result = self.sentiment_analyzer(text[:500])[0]
            return {"label": result['label'].lower(), "score": result['score']}
        except Exception as e:
            logger.error(f"Sentiment analysis error: {e}")
            return {"label": "neutral", "score": 0.0}

    async def get_symbol_sentiment(self, symbol: str) -> Dict:
        """Fetch and analyze news sentiment for a specific symbol"""
        currency = symbol.replace("USDT", "")
        # Use CryptoPanic API if key available, else fallback to web search via Agent
        # For now, let's stick to the Agent search to avoid requiring another API Key immediately
        
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
                res = self.analyze_sentiment(line)
                if res['label'] == 'positive': scores.append(res['score'])
                elif res['label'] == 'negative': scores.append(-res['score'])
                else: scores.append(0.0)
                
            avg_score = sum(scores) / len(scores) if scores else 0.0
            
            return {
                "score": avg_score,
                "label": "positive" if avg_score > 0.2 else ("negative" if avg_score < -0.2 else "neutral"),
                "count": len(scores)
            }
        except Exception as e:
            logger.error(f"Symbol sentiment check failed for {symbol}: {e}")
            return {"score": 0.0, "label": "neutral"}
