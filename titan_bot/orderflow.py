"""
TITAN BOT 2026 - Order Flow Analysis
Анализ потока ордеров, стакана и ленты сделок
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
import config

class MarketPressure(Enum):
    """Давление рынка"""
    STRONG_BUY = "STRONG_BUY"
    WEAK_BUY = "WEAK_BUY"
    NEUTRAL = "NEUTRAL"
    WEAK_SELL = "WEAK_SELL"
    STRONG_SELL = "STRONG_SELL"

class CrowdPosition(Enum):
    """Позиционирование толпы"""
    CROWD_LONG = "CROWD_LONG"       # Толпа в лонгах - опасно для лонга
    CROWD_SHORT = "CROWD_SHORT"     # Толпа в шортах - опасно для шорта
    NEUTRAL = "NEUTRAL"

@dataclass
class OrderFlowSignal:
    """Структура сигнала Order Flow"""
    pressure: MarketPressure
    crowd_position: CrowdPosition
    imbalance: float
    delta_volume: float
    absorption_detected: bool
    spoofing_detected: bool
    large_trades_bias: str  # 'BUY', 'SELL', 'NEUTRAL'
    confidence: float


class OrderFlowAnalyzer:
    """
    Анализатор потока ордеров.
    
    Что анализируем:
    1. Order Book Imbalance - дисбаланс стакана
    2. Delta Volume - разница покупок/продаж по рынку
    3. Absorption - поглощение крупным игроком
    4. Spoofing Detection - обнаружение фейковых стенок
    5. Funding Rate - позиционирование толпы
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        self.orderbook_history = []  # История стакана для детекции спуфинга
        
    def analyze(self, symbol: str = None, realtime_stream=None) -> OrderFlowSignal:
        """
        Полный анализ Order Flow.
        
        Args:
            symbol: Торговая пара
            realtime_stream: RealtimeDataStream для delta volume
            
        Returns:
            OrderFlowSignal с результатами анализа
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        # 1. Получаем данные стакана
        orderbook = self.data.get_orderbook(symbol)
        if orderbook is None:
            return self._empty_signal()
        
        # 2. Анализ дисбаланса стакана
        imbalance = orderbook['imbalance']
        pressure = self._analyze_imbalance(imbalance)
        
        # 3. Delta Volume (если есть WebSocket)
        delta_volume = 0
        if realtime_stream:
            delta_volume = realtime_stream.get_delta_volume(reset=False)
        
        # 4. Детекция поглощения (Absorption)
        absorption = self._detect_absorption(orderbook, delta_volume)
        
        # 5. Детекция спуфинга
        spoofing = self._detect_spoofing(orderbook)
        
        # 6. Анализ крупных сделок
        large_trades_bias = "NEUTRAL"
        if realtime_stream:
            large_trades_bias = self._analyze_large_trades(realtime_stream.get_recent_trades())
        
        # 7. Анализ фандинга (позиционирование толпы)
        funding_data = self.data.get_funding_rate(symbol)
        crowd_position = self._analyze_funding(funding_data)
        
        # 8. Считаем общую уверенность
        confidence = self._calculate_confidence(
            imbalance, delta_volume, absorption, spoofing, crowd_position
        )
        
        return OrderFlowSignal(
            pressure=pressure,
            crowd_position=crowd_position,
            imbalance=imbalance,
            delta_volume=delta_volume,
            absorption_detected=absorption,
            spoofing_detected=spoofing,
            large_trades_bias=large_trades_bias,
            confidence=confidence
        )
    
    def _analyze_imbalance(self, imbalance: float) -> MarketPressure:
        """
        Анализ дисбаланса стакана.
        
        imbalance = bid_volume / (bid_volume + ask_volume)
        > 0.65 = сильное давление покупателей
        < 0.35 = сильное давление продавцов
        """
        if imbalance > 0.70:
            return MarketPressure.STRONG_BUY
        elif imbalance > 0.60:
            return MarketPressure.WEAK_BUY
        elif imbalance < 0.30:
            return MarketPressure.STRONG_SELL
        elif imbalance < 0.40:
            return MarketPressure.WEAK_SELL
        else:
            return MarketPressure.NEUTRAL
    
    def _detect_absorption(self, orderbook: dict, delta_volume: float) -> bool:
        """
        Детекция поглощения (Absorption).
        
        Логика: Если delta_volume сильно положительная (много покупок по рынку),
        но цена не растет - значит, крупный лимитный продавец поглощает все покупки.
        Это медвежий сигнал!
        
        И наоборот: много продаж, но цена не падает = бычье поглощение.
        """
        # Порог для "сильной" дельты (условно)
        delta_threshold = 100  # Подбирается под инструмент
        
        # Получаем последние свечи для проверки движения цены
        klines = self.data.klines_cache.get(config.SYMBOL)
        if klines is None or len(klines) < 5:
            return False
        
        # Изменение цены за последние 5 свечей
        price_change = (klines['close'].iloc[-1] - klines['close'].iloc[-5]) / klines['close'].iloc[-5]
        
        # Поглощение покупок (медвежий сигнал)
        if delta_volume > delta_threshold and price_change < 0.001:
            print("[OrderFlow] ABSORPTION DETECTED: Покупки поглощаются!")
            return True
        
        # Поглощение продаж (бычий сигнал)
        if delta_volume < -delta_threshold and price_change > -0.001:
            print("[OrderFlow] ABSORPTION DETECTED: Продажи поглощаются!")
            return True
        
        return False
    
    def _detect_spoofing(self, orderbook: dict) -> bool:
        """
        Детекция спуфинга (Spoofing).
        
        Спуфинг - это когда крупный игрок выставляет огромную стенку,
        чтобы напугать толпу, а потом быстро убирает её.
        
        Логика: Сохраняем историю стакана и смотрим, появляются/исчезают ли стенки.
        """
        current_walls = {
            'bid_walls': orderbook['bid_walls'].copy() if not orderbook['bid_walls'].empty else pd.DataFrame(),
            'ask_walls': orderbook['ask_walls'].copy() if not orderbook['ask_walls'].empty else pd.DataFrame()
        }
        
        self.orderbook_history.append(current_walls)
        
        # Храним только последние 10 снимков
        if len(self.orderbook_history) > 10:
            self.orderbook_history.pop(0)
        
        # Нужно минимум 5 снимков для анализа
        if len(self.orderbook_history) < 5:
            return False
        
        # Проверяем, исчезла ли крупная стенка
        old_walls = self.orderbook_history[-5]
        
        # Если раньше была крупная стенка на покупку, а сейчас нет
        if not old_walls['bid_walls'].empty and current_walls['bid_walls'].empty:
            print("[OrderFlow] SPOOFING SUSPECTED: Стенка на покупку исчезла!")
            return True
        
        if not old_walls['ask_walls'].empty and current_walls['ask_walls'].empty:
            print("[OrderFlow] SPOOFING SUSPECTED: Стенка на продажу исчезла!")
            return True
        
        return False
    
    def _analyze_large_trades(self, trades: list) -> str:
        """
        Анализ крупных сделок в ленте.
        Крупные игроки оставляют следы.
        """
        if not trades:
            return "NEUTRAL"
        
        df = pd.DataFrame(trades)
        
        # Определяем "крупную" сделку как > 2 стандартных отклонений от среднего
        mean_size = df['size'].mean()
        std_size = df['size'].std()
        threshold = mean_size + 2 * std_size
        
        large_trades = df[df['size'] > threshold]
        
        if large_trades.empty:
            return "NEUTRAL"
        
        buy_volume = large_trades[large_trades['side'] == 'Buy']['size'].sum()
        sell_volume = large_trades[large_trades['side'] == 'Sell']['size'].sum()
        
        if buy_volume > sell_volume * 1.5:
            return "BUY"
        elif sell_volume > buy_volume * 1.5:
            return "SELL"
        
        return "NEUTRAL"
    
    def _analyze_funding(self, funding_data: dict) -> CrowdPosition:
        """
        Анализ Funding Rate.
        
        Высокий положительный фандинг = толпа в лонгах = опасно для лонга.
        Маркет-мейкеры любят брить толпу.
        """
        if funding_data is None:
            return CrowdPosition.NEUTRAL
        
        rate = funding_data['funding_rate']
        
        if rate > config.FUNDING_LONG_THRESHOLD:
            return CrowdPosition.CROWD_LONG
        elif rate < config.FUNDING_SHORT_THRESHOLD:
            return CrowdPosition.CROWD_SHORT
        
        return CrowdPosition.NEUTRAL
    
    def _calculate_confidence(self, imbalance, delta, absorption, spoofing, crowd) -> float:
        """Расчет уверенности в сигнале (0-1)."""
        score = 0.5  # Базовый уровень
        
        # Сильный дисбаланс добавляет уверенности
        if imbalance > 0.65 or imbalance < 0.35:
            score += 0.15
        
        # Поглощение - важный сигнал
        if absorption:
            score += 0.2
        
        # Спуфинг снижает уверенность (рынок манипулируют)
        if spoofing:
            score -= 0.1
        
        # Экстремальный фандинг
        if crowd != CrowdPosition.NEUTRAL:
            score += 0.1
        
        return max(0.0, min(1.0, score))
    
    def _empty_signal(self) -> OrderFlowSignal:
        """Пустой сигнал при ошибке."""
        return OrderFlowSignal(
            pressure=MarketPressure.NEUTRAL,
            crowd_position=CrowdPosition.NEUTRAL,
            imbalance=0.5,
            delta_volume=0,
            absorption_detected=False,
            spoofing_detected=False,
            large_trades_bias="NEUTRAL",
            confidence=0.0
        )
