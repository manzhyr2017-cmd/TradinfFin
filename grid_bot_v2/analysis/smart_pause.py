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
        
        # 1. Спред
        price = self.client.get_price()
        # simplified check
        
        # 2. Дневной убыток
        trades = self.db.get_trades_today()
        # ...
        
        level = PauseLevel.NORMAL
        if health < 0.5:
            level = PauseLevel.HARD_PAUSE
            reasons.append("Health too low")
            
        return PauseDecision(level=level, overall_health=health, reasons=reasons)
