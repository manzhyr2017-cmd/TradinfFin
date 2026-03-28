import logging
import random
import numpy as np
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger("RLOptimizer")

@dataclass
class GridParams:
    grid_levels: int
    grid_range_pct: float
    qty_multiplier: float = 1.0
    profit_target_pct: float = 1.0

class StateEncoder:
    """Преобразует рыночные данные в вектор состояния для RL."""
    
    @staticmethod
    def encode(
        prices: np.ndarray, 
        volumes: np.ndarray, 
        current_params: GridParams,
        pnl: float,
        balance: float
    ) -> np.ndarray:
        # Упрощенная кодировка: волатильность, тренд, текущий профит
        returns = np.diff(prices) / prices[:-1]
        volatility = np.std(returns) if len(returns) > 0 else 0
        trend = (prices[-1] - prices[0]) / prices[0] if len(prices) > 0 else 0
        
        state = [
            volatility * 100,           # Волатильность в %
            trend * 100,                # Тренд в %
            current_params.grid_levels / 100.0,
            current_params.grid_range_pct / 20.0,
            pnl / max(balance, 1.0),    # Доходность к балансу
        ]
        return np.array(state, dtype=np.float32)

class RLGridOptimizer:
    """
    Reinforcement Learning оптимизатор параметров сетки.
    Использует Q-Learning для подстройки GRID_LEVELS и GRID_RANGE.
    """
    
    def __init__(self, epsilon: float = 0.1, gamma: float = 0.9):
        self.epsilon = epsilon
        self.gamma = gamma
        self.q_table = {} # В реале здесь была бы нейронка или большая таблица
        self.current_params = GridParams(grid_levels=20, grid_range_pct=10.0, qty_multiplier=1.0)
        self.last_action = None
        
    def get_optimal_params(
        self, 
        prices: np.ndarray, 
        volumes: np.ndarray,
        pnl: float,
        balance: float
    ) -> GridParams:
        """Выбирает оптимальные параметры на основе текущего состояния."""
        state = StateEncoder.encode(prices, volumes, self.current_params, pnl, balance)
        state_key = tuple(np.round(state, 1)) # Дискретизация для таблицы
        
        # Epsilon-greedy выбор
        if random.random() < self.epsilon:
            action = self._get_random_action()
        else:
            action = self._get_best_action(state_key)
            
        self.last_action = action
        return self._apply_action(action)

    def record_result(
        self, 
        old_state: np.ndarray, 
        action: int, 
        reward: float, 
        new_state: np.ndarray
    ):
        """Обновляет Q-значения на основе полученного вознаграждения."""
        s = tuple(np.round(old_state, 1))
        s_prime = tuple(np.round(new_state, 1))
        
        old_q = self.q_table.get((s, action), 0.0)
        max_future_q = max([self.q_table.get((s_prime, a), 0.0) for a in range(5)], default=0.0)
        
        # Формула Q-Learning
        new_q = old_q + 0.1 * (reward + self.gamma * max_future_q - old_q)
        self.q_table[(s, action)] = new_q

    def _get_random_action(self) -> int:
        return random.randint(0, 4)

    def _get_best_action(self, state_key) -> int:
        values = [self.q_table.get((state_key, a), 0.0) for a in range(5)]
        return np.argmax(values)

    def _apply_action(self, action: int) -> GridParams:
        # Адаптация текущих параметров
        if action == 1: # Больше уровней
            self.current_params.grid_levels = min(100, self.current_params.grid_levels + 2)
        elif action == 2: # Меньше уровней
            self.current_params.grid_levels = max(5, self.current_params.grid_levels - 2)
        elif action == 3: # Расширить диапазон
            self.current_params.grid_range_pct = min(50.0, self.current_params.grid_range_pct + 0.5)
        elif action == 4: # Сузить диапазон
            self.current_params.grid_range_pct = max(1.0, self.current_params.grid_range_pct - 0.5)
            
        return self.current_params
