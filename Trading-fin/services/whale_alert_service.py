import asyncio
import logging
from datetime import datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class WhaleAlertService:
    """
    Whale Alert Service (Phase 10): 
    Monitors order books for massive liquidity walls and sends alerts.
    Helps detect where 'Smart Money' is placing its bets.
    """
    
    def __init__(self, client, telegram=None):
        self.client = client
        self.telegram = telegram
        self.is_running = False
        self.monitored_symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        self.last_alerts = {} # symbol -> last_alert_price
        self.wall_thresholds = {
            "BTCUSDT": 150.0, # 150 BTC wall
            "ETHUSDT": 2000.0, # 2000 ETH wall
            "SOLUSDT": 10000.0 # 10000 SOL wall
        }

    async def start(self, interval_seconds: int = 600):
        """Check for whales every 10 minutes by default"""
        self.is_running = True
        logger.info(f"🐋 Whale Alert Service STARTED (Interval: {interval_seconds}s)")
        
        while self.is_running:
            try:
                for symbol in self.monitored_symbols:
                    await self.check_symbol_walls(symbol)
                    await asyncio.sleep(2) # Prevent rate limiting
                
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Whale Alert Loop Error: {e}")
                await asyncio.sleep(60)

    async def check_symbol_walls(self, symbol: str):
        """Analyzes orderbook for massive walls"""
        try:
            # We use the raw request for deeper orderbook
            # category='linear' to match perpetuals
            ob = self.client._request('/v5/market/orderbook', {
                'category': self.client.category.value,
                'symbol': symbol,
                'limit': 50
            })
            
            if not ob or 'list' not in ob:
                # API failure or wrong response
                if isinstance(ob, dict) and 'a' in ob:
                    # Some versions return shorter format
                    pass
                else:
                    return

            # Note: Bybit V5 returns {s: symbol, b: [ [price, size], ... ], a: [ [price, size], ... ] }
            bids = ob.get('b', [])
            asks = ob.get('a', [])
            
            threshold = self.wall_thresholds.get(symbol, 100.0)
            
            # Check ASKS (Sell Walls)
            for price_str, size_str in asks:
                price, size = float(price_str), float(size_str)
                if size >= threshold:
                    await self._send_whale_alert(symbol, "SELL WALL", price, size)
                    break # Only one alert per check

            # Check BIDS (Buy Walls)
            for price_str, size_str in bids:
                price, size = float(price_str), float(size_str)
                if size >= threshold:
                    await self._send_whale_alert(symbol, "BUY WALL", price, size)
                    break

        except Exception as e:
            logger.debug(f"Error checking walls for {symbol}: {e}")

    async def _send_whale_alert(self, symbol: str, type: str, price: float, size: float):
        """Sends alert if not already sent for this price lately"""
        alert_key = f"{symbol}_{type}_{round(price, -1)}" # Round to ignore small fluctuations
        
        if alert_key in self.last_alerts:
            # Already alerted for this level recently
            return
            
        self.last_alerts[alert_key] = datetime.now()
        
        # Cleanup old alerts (older than 4 hours)
        now = datetime.now()
        self.last_alerts = {k: v for k, v in self.last_alerts.items() if (now - v).total_seconds() < 14400}

        # Interpret the wall
        interpretation = ""
        action_tip = ""
        
        if "SELL" in type:
            interpretation = "🛑 <b>Сопротивление:</b> Крупный игрок давит цену вниз."
            action_tip = "👀 <i>Возможен отскок вниз (Short) или пробой уровня.</i>"
        else:
            interpretation = "🛡️ <b>Поддержка:</b> Крупный игрок держит уровень."
            action_tip = "👀 <i>Ожидается отскок вверх (Long).</i>"

        emoji = "📗" if "BUY" in type else "📕"
        msg = f"""
🐋 <b>WHALE ALERT: {symbol}</b>
{'═' * 25}

{emoji} <b>Type:</b> {type}
💰 <b>Price:</b> <code>{price:.2f}</code>
📊 <b>Size:</b> <code>{size:.1f}</code> {symbol.replace('USDT', '')}
💎 <b>Total Value:</b> <code>${(price * size) / 1_000_000:.2f}M</code>

{interpretation}
{action_tip}
"""
        logger.info(f"🐋 WHALE ALERT sent for {symbol} at {price}")
        
        if self.telegram:
            try:
                # Use the notifier's bot directly or its send_message method
                # Based on telegram_bot.py, the notifier has send_message or we can use telegram.bot.send_message
                await self.telegram.send_message(msg.strip())
            except Exception as e:
                logger.error(f"Failed to send Whale Alert to Telegram: {e}")
