import logging
import config
from enum import Enum
from dataclasses import dataclass, field
from typing import List

log = logging.getLogger("SmartPause")

class PauseLevel(Enum):
    NORMAL = 0
    SOFT_PAUSE = 1
    HARD_PAUSE = 2
    EMERGENCY_STOP = 3

@dataclass
class PauseDecision:
    level: PauseLevel
    overall_health: float
    qty_multiplier: float = 1.0
    reasons: List[str] = field(default_factory=list)

class SmartPauseEngine:
    """
    Движок интеллектуальной паузы.
    Оценивает 8 метрик здоровья рынка и бота.
    """
    
    def __init__(self, client, db):
        self.client = client
        self.db = db
        
    def evaluate(self) -> PauseDecision:
        """Проверяет, не пора ли сделать паузу."""
        reasons = []
        health = 1.0
        qty_mult = 1.0
        
        # 1. Спред (если спред > 0.5%, снижаем активность)
        try:
            ob = self.client.get_orderbook(limit=2)
            if ob and ob.get('b') and ob.get('a'):
                bid = float(ob['b'][0][0])
                ask = float(ob['a'][0][0])
                spread_pct = (ask - bid) / bid * 100
                if spread_pct > 0.5:
                    health -= 0.2
                    qty_mult *= 0.5
                    reasons.append(f"Wide spread: {spread_pct:.2f}%")
        except Exception as e:
            log.warning(f"PauseEngine spread check failed: {e}")

        # 2. Дневной убыток (если убыток > 70% от лимита, мягкая пауза)
        try:
            today_trades = self.db.get_trades_today()
            daily_pnl = sum(float(t.get("profit_usdt", 0)) for t in today_trades)
            limit = float(config.DAILY_LOSS_LIMIT_USDT)
            if daily_pnl < -limit * 0.7:
                health -= 0.3
                qty_mult *= 0.5
                reasons.append(f"Near daily loss limit: {daily_pnl:.2f} USDT")
        except Exception as e:
            log.warning(f"PauseEngine PnL check failed: {e}")

        # 3. Режим паузы
        level = PauseLevel.NORMAL
        if health <= 0.3:
            level = PauseLevel.HARD_PAUSE
        elif health <= 0.7:
            level = PauseLevel.SOFT_PAUSE
            
        return PauseDecision(
            level=level, 
            overall_health=max(0.0, health), 
            qty_multiplier=qty_mult, 
            reasons=reasons
        )
