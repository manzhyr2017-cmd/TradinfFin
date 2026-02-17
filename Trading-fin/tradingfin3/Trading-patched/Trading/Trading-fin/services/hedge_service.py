import asyncio
import logging
from datetime import datetime
from typing import List, Dict

logger = logging.getLogger(__name__)

class HedgeService:
    """
    The Guardian 🛡️
    Protects the portfolio by opening counter-positions (hedges) when exposure is too high.
    Example: If bot has 3 LONGS on Alts, open a small SHORT on BTC to hedge against a market crash.
    """
    
    def __init__(self, execution_manager, bybit_client):
        self.execution = execution_manager
        self.client = bybit_client
        self.is_running = False
        self.active_hedge_symbol = "BTCUSDT"
        self.hedge_status = "Inactive"

    async def start(self, interval_seconds: int = 300):
        """Starts the portfolio monitoring loop (every 5 mins)"""
        self.is_running = True
        logger.info("🛡️ Hedge Service STARTED")
        
        while self.is_running:
            try:
                await self.rebalance_hedges()
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logger.error(f"Hedge Service Error: {e}")
                await asyncio.sleep(60)

    async def rebalance_hedges(self):
        """Analyze current positions and decide if we need a hedge"""
        # Watch-Only Check
        if not self.execution:
            self.hedge_status = "Disabled (Watch-Only)"
            return

        try:
            positions = self.client.get_open_positions()
            if not positions:
                await self._close_existing_hedge()
                return

            longs = [pos for pos in positions if pos['side'] == 'Buy' and pos['symbol'] != self.active_hedge_symbol]
            shorts = [pos for pos in positions if pos['side'] == 'Sell' and pos['symbol'] != self.active_hedge_symbol]
            
            total_long_value = sum(float(pos['size']) * float(pos.get('avgPrice', pos.get('markPrice', 0))) for pos in longs)
            total_short_value = sum(float(pos['size']) * float(pos.get('avgPrice', pos.get('markPrice', 0))) for pos in shorts)
            
            net_exposure = total_long_value - total_short_value
            logger.info(f"📊 Hedge Audit: Longs ${total_long_value:.2f}, Shorts ${total_short_value:.2f}, Net ${net_exposure:.2f}")

            # 1. HEDGE LOGIC: If we are heavily NET LONG on Alts (> $50 exposure)
            if net_exposure > 50:
                await self._open_btc_hedge(side="Sell", value_to_hedge=net_exposure * 0.3)
            # 2. HEDGE LOGIC: If we are heavily NET SHORT on Alts
            elif net_exposure < -50:
                await self._open_btc_hedge(side="Buy", value_to_hedge=abs(net_exposure) * 0.3)
            else:
                # Balanced or low exposure (< 50 USDT net), close hedge
                if abs(net_exposure) < 30: # Added buffer to avoid oscillation
                    await self._close_existing_hedge()
                else:
                    self.hedge_status = f"Waiting (Net ${net_exposure:.1f})"

        except Exception as e:
            logger.error(f"Failed to rebalance hedges: {e}")

    async def _open_btc_hedge(self, side: str, value_to_hedge: float):
        """Opens a small hedge position on BTC"""
        try:
            # Check if hedge already exists
            all_positions = self.client.get_open_positions()
            hedge_pos = next((p for p in all_positions if p['symbol'] == self.active_hedge_symbol), None)
            
            if hedge_pos:
                # Already have a hedge, check if it's the right side
                if hedge_pos['side'] == side:
                    self.hedge_status = f"Active ({side})"
                    return
                else:
                    # Wrong side, close and flip
                    await self._close_existing_hedge()

            # Calculate qty for BTC
            ticker = self.client._request("/v5/market/tickers", {"category": self.client.category.value, "symbol": self.active_hedge_symbol})
            price = float(ticker['list'][0]['lastPrice'])
            qty = value_to_hedge / price
            
            # Round to Bybit precision (BTC usually 0.001)
            qty = round(qty, 3)
            if qty < 0.001: qty = 0.001

            logger.info(f"🛡️ HEDGE: Opening BTC {side} for ${value_to_hedge:.2f} (Portfolio Protection)")
            
            self.client.place_order(
                symbol=self.active_hedge_symbol,
                side=side,
                qty=qty,
                order_type='Market',
                reduce_only=False
            )
            self.hedge_status = f"Active ({side})"
            
        except Exception as e:
            logger.error(f"Failed to open hedge: {e}")

    async def _close_existing_hedge(self):
        """Closes the BTC hedge if it exists"""
        try:
            positions = self.client.get_open_positions()
            hedge_pos = next((p for p in positions if p['symbol'] == self.active_hedge_symbol), None)
            
            if hedge_pos:
                logger.info(f"🛡️ HEDGE: Closing {self.active_hedge_symbol} hedge (Risk safe)")
                close_side = "Sell" if hedge_pos['side'] == "Buy" else "Buy"
                self.client.place_order(
                    symbol=self.active_hedge_symbol,
                    side=close_side,
                    qty=float(hedge_pos['size']),
                    order_type='Market',
                    reduce_only=True
                )
            self.hedge_status = "Inactive"
        except Exception as e:
            logger.error(f"Failed to close hedge: {e}")
