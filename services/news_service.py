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
        now = datetime.utcnow()
        upcoming = []
        for e in self.events:
            try:
                if datetime.strptime(e['time_utc'], '%Y-%m-%d %H:%M:%S') > now:
                    upcoming.append(e)
            except: pass
        return upcoming
