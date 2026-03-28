import logging
from typing import Dict, Any

log = logging.getLogger("ABTesting")

class ABTestEngine:
    """
    Система A/B тестирования стратегий.
    Разделяет торговый капитал между Группой А и Группой Б.
    """
    
    def __init__(self):
        self.tests = {}
        
    def create_test(self, name: str, params_a: Dict, params_b: Dict):
        log.info(f"AB: Starting test '{name}'...")
        self.tests[name] = {
            "a": {"params": params_a, "pnl": 0.0},
            "b": {"params": params_b, "pnl": 0.0}
        }

    def record_pnl(self, test_name: str, group: str, pnl: float):
        if test_name in self.tests:
            self.tests[test_name][group.lower()]["pnl"] += pnl
