import asyncio
import logging
import json
from datetime import datetime
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

class SelectorService:
    """
    The Colonel 🕵️
    Selects the best coins to trade based on Market Metrics + AI Narrative.
    Output: Primary List (Top 10) & Secondary List (Next 10).
    """
    
    def __init__(self, agent, bybit_client):
        self.agent = agent
        self.client = bybit_client
        self.primary_list: List[str] = []   # Shortlist (Active Trading)
        self.secondary_list: List[str] = [] # Longlist (Monitoring)
        self.last_update = None
        self.is_running = False
        self.sector_analysis = "Initializing..."
        
        # Hardcoded safe list in case of API failure
        self.fallback_list = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "DOGEUSDT"]

    async def start(self, interval_hours: int = 1):
        """Starts the background selection loop"""
        self.is_running = True
        logger.info(f"🕵️ Selector Service STARTED (Interval: {interval_hours}h)")
        
        while self.is_running:
            try:
                await self.run_selection_cycle()
                
                # Sleep for interval
                await asyncio.sleep(interval_hours * 3600)
                
            except Exception as e:
                logger.error(f"Selector Loop Error: {e}")
                await asyncio.sleep(300) # Retry in 5 min on error

    async def run_selection_cycle(self):
        """Main selection logic"""
        logger.info("🕵️ Starting Coin Selection Cycle...")
        
        try:
            # 1. Fetch Market Metrics (Top 100 by Volume)
            tickers = await self._fetch_market_data()
            if not tickers:
                logger.warning("No market data fetched. Using previous/fallback list.")
                return

            # 2. AI Sector Analysis
            hot_sectors = await self._analyze_sectors()
            
            # 3. Filter & Rank (Longs vs Shorts)
            self.primary_list, self.secondary_list = self._rank_coins(tickers, hot_sectors)
            
            self.last_update = datetime.now()
            
            logger.info(f"✅ Selection Complete.")
            logger.info(f"🚀 Top 10 LONGS: {self.primary_list}")
            logger.info(f"📉 Top 10 SHORTS: {self.secondary_list}")
            
            # --- SAVE STATE TO FILE FOR UI ---
            try:
                import json
                import os
                state = {}
                state_file = "bot_state.json"
                if os.path.exists(state_file):
                    with open(state_file, 'r') as f:
                        state = json.load(f)
                
                state.update({
                    "top_longs": self.primary_list,
                    "top_shorts": self.secondary_list,
                    "sector_analysis": self.sector_analysis,
                    "selector_last_update": self.last_update.isoformat() if self.last_update else None
                })
                
                with open(state_file, 'w') as f:
                    json.dump(state, f)
            except Exception as e:
                logger.error(f"Failed to save selector state: {e}")
            # ---------------------------------
            
        except Exception as e:
            logger.error(f"Selection Cycle Failed: {e}")

    async def _fetch_market_data(self) -> List[Dict]:
        """Fetches top tickers from Bybit"""
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(None, lambda: self.client._request("/v5/market/tickers", {"category": self.client.category.value}))
            
            if not response or 'list' not in response:
                return []
                
            # Filter USDT pairs only and minimum volume
            data = []
            for t in response['list']:
                if not t['symbol'].endswith('USDT'): continue
                
                vol24 = float(t.get('turnover24h', 0))
                if vol24 < 2_000_000: continue  # Min $2M daily volume
                
                data.append({
                    'symbol': t['symbol'],
                    'price': float(t['lastPrice']),
                    'change24h': float(t['price24hPcnt']) * 100,
                    'turnover24h': vol24
                })
                
            data.sort(key=lambda x: x['turnover24h'], reverse=True)
            return data[:100]  # Top 100 by volume
            
        except Exception as e:
            logger.error(f"Fetch Market Data Error: {e}")
            return []

    async def _analyze_sectors(self) -> List[str]:
        """Asks AI which sectors are trending"""
        
        if not self.agent.client:
            self.sector_analysis = "Focus on High Volume (AI Disabled)"
            return []
            
        try:
            query = "top trending crypto sectors today narrative ai meme rwa gaming"
            loop = asyncio.get_running_loop()
            search_res = await loop.run_in_executor(None, lambda: self.agent._search_web(query))
            
            prompt = f"""
            Analyze Crypto Narratives based on:
            {search_res}
            
            Identify TOP 3 HOT SECTORS (e.g., "AI", "Meme", "Layer2").
            
            RETURN JSON ONLY:
            {{
                "hot_sectors": ["sector1", "sector2", "sector3"],
                "reasoning": "Brief explanation"
            }}
            """
            
            # AI Check
            if not self.agent.client:
                return []

            messages=[
                {"role": "system", "content": "You are a Crypto Narrative Researcher. Output valid JSON."},
                {"role": "user", "content": prompt}
            ]

            response_text = self.agent._call_llm(messages, response_format={"type": "json_object"})
            
            if not response_text:
                return []
            
            import json
            result = json.loads(response_text)
            self.sector_analysis = result.get('reasoning', 'N/A')
            logger.info(f"🕵️ Narrative Analysis: {result}")
            return result.get('hot_sectors', [])
            
        except Exception as e:
            logger.error(f"Sector Analysis Error: {e}")
            return []

    def _rank_coins(self, tickers: List[Dict], hot_sectors: List[str]) -> Tuple[List[str], List[str]]:
        """
        Ranks coins into Top 10 Longs and Top 10 Shorts.
        Ranking Score = Turnover24h * abs(Change24h)
        """
        # Separate Gainers (Longs) and Losers (Shorts)
        gainers = [t for t in tickers if t['change24h'] > 0]
        losers = [t for t in tickers if t['change24h'] < 0]
        
        # Scoring Function: Volatility & Volume
        def relevance_score(t):
             multiplier = 1.0
             # Boost score if sector is hot
             for sector in hot_sectors:
                if sector.lower() in t.get('symbol', '').lower(): multiplier = 1.5
             
             # Score = Volume * Volatility^2 (Prioritize movers)
             return t['turnover24h'] * (abs(t['change24h']) + 0.1) * multiplier

        # Sort both lists by Score (Desc)
        gainers.sort(key=relevance_score, reverse=True)
        losers.sort(key=relevance_score, reverse=True)
        
        # Take Top 10 of each
        top_longs = [t['symbol'] for t in gainers[:10]]
        top_shorts = [t['symbol'] for t in losers[:10]]
        
        # Determine strict top 10 based on regime? 
        # User wants "Most relevant in short, most relevant in long".
        # So we return two distinct lists.
        
        # Ensure Blue Chips are somewhere if market is boring?
        # Actually, let's strictly follow the numbers as requested.
        
        return top_longs, top_shorts

    def get_combined_list(self) -> List[str]:
        """Returns unique list of all selected symbols"""
        return list(set(self.primary_list + self.secondary_list + self.fallback_list))[:25]
