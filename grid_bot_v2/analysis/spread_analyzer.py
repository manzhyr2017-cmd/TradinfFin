import logging
from decimal import Decimal
from typing import Dict, Any

log = logging.getLogger("SpreadAnalyzer")

class SpreadAnalyzer:
    """
    Анализирует спред и ликвидность в стакане.
    """
    
    def __init__(self, client):
        self.client = client
        
    def get_current_spread(self) -> Dict[str, Any]:
        """
        Получает текущий bid, ask и рассчитывает спред в процентах.
        """
        try:
            ob = self.client.get_orderbook(limit=1)
            if not ob or not ob.get('b', []) or not ob.get('a', []):
                return {}
                
            bid = Decimal(str(ob['b'][0][0]))
            ask = Decimal(str(ob['a'][0][0]))
            
            spread_usdt = ask - bid
            spread_pct = (spread_usdt / bid) * 100
            
            return {
                "bid": bid,
                "ask": ask,
                "spread_usdt": spread_usdt,
                "spread_pct": spread_pct
            }
        except Exception as e:
            log.error(f"Error calculating spread: {e}")
            return {}

    def get_market_imbalance(self, depth: int = 10) -> float:
        """
        Рассчитывает Order Book Imbalance (OBI).
        0.5 - баланс, >0.5 - больше бидов (buy pressure), <0.5 - больше асков.
        """
        try:
            ob = self.client.get_orderbook(limit=depth)
            if not ob: return 0.5
            
            bid_vol = sum(float(b[1]) for b in ob.get('b', []))
            ask_vol = sum(float(a[1]) for a in ob.get('a', []))
            
            total_vol = bid_vol + ask_vol
            if total_vol == 0: return 0.5
            
            return bid_vol / total_vol
        except Exception as e:
            log.error(f"Error calculating imbalance: {e}")
            return 0.5
