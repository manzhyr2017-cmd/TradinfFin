"""
TITAN BOT 2026 - Open Interest Analysis
Кто заходит в рынок? Кто выходит?
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
from typing import Optional, List
import config

class OISignal(Enum):
    """Сигналы Open Interest"""
    NEW_LONGS = "NEW_LONGS"           # Рост OI + рост цены = новые лонги
    NEW_SHORTS = "NEW_SHORTS"         # Рост OI + падение цены = новые шорты
    LONGS_CLOSING = "LONGS_CLOSING"   # Падение OI + падение цены = лонги закрываются
    SHORTS_CLOSING = "SHORTS_CLOSING" # Падение OI + рост цены = шорты закрываются (SHORT SQUEEZE!)
    NEUTRAL = "NEUTRAL"

@dataclass
class OIAnalysis:
    """Результат анализа Open Interest"""
    current_oi: float
    oi_change_percent: float
    oi_signal: OISignal
    long_short_ratio: float
    top_trader_sentiment: str  # 'LONG', 'SHORT', 'NEUTRAL'
    liquidation_risk: str      # 'HIGH_LONG', 'HIGH_SHORT', 'LOW'
    description: str


class OpenInterestAnalyzer:
    """
    Анализатор Open Interest.
    
    ПОЧЕМУ ЭТО GOLD:
    
    Open Interest = количество открытых контрактов.
    
    Комбинации:
    ┌─────────────┬─────────────┬────────────────────────────────┐
    │ OI          │ Цена        │ Что происходит                 │
    ├─────────────┼─────────────┼────────────────────────────────┤
    │ Растёт ↑    │ Растёт ↑    │ Новые ЛОНГИ заходят            │
    │ Растёт ↑    │ Падает ↓    │ Новые ШОРТЫ заходят            │
    │ Падает ↓    │ Падает ↓    │ ЛОНГИ закрываются (сдаются)    │
    │ Падает ↓    │ Растёт ↑    │ ШОРТЫ закрываются (SQUEEZE!)   │
    └─────────────┴─────────────┴────────────────────────────────┘
    
    SHORT SQUEEZE — самое прибыльное движение!
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        self.oi_history = []
        
    def analyze(self, symbol: str = None) -> OIAnalysis:
        """Полный анализ Open Interest."""
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем данные OI
        oi_data = self._get_open_interest(symbol)
        if oi_data is None:
            return self._empty_analysis()
        
        # Получаем Long/Short Ratio
        ls_ratio = self._get_long_short_ratio(symbol)
        
        # Получаем позиции топ-трейдеров
        top_traders = self._get_top_trader_sentiment(symbol)
        
        # Получаем изменение цены
        price_change = self._get_price_change(symbol)
        
        # Определяем сигнал OI
        oi_signal = self._classify_oi_signal(oi_data, price_change)
        
        # Оцениваем риск ликвидаций
        liq_risk = self._assess_liquidation_risk(ls_ratio, oi_data)
        
        # Формируем описание
        description = self._generate_description(oi_signal, ls_ratio, top_traders)
        
        return OIAnalysis(
            current_oi=oi_data['current'],
            oi_change_percent=oi_data['change_percent'],
            oi_signal=oi_signal,
            long_short_ratio=ls_ratio,
            top_trader_sentiment=top_traders,
            liquidation_risk=liq_risk,
            description=description
        )
    
    def _get_open_interest(self, symbol: str) -> Optional[dict]:
        """Получает данные Open Interest с Bybit."""
        try:
            # Текущий OI
            response = self.data.session.get_tickers(
                category=config.CATEGORY,
                symbol=symbol
            )
            
            if response['retCode'] != 0:
                return None
            
            current_oi = float(response['result']['list'][0]['openInterest'])
            
            # Исторический OI (за последние 24 часа)
            oi_history = self.data.session.get_open_interest(
                category=config.CATEGORY,
                symbol=symbol,
                intervalTime='1h',
                limit=24
            )
            
            if oi_history['retCode'] != 0:
                return None
            
            oi_list = [float(x['openInterest']) for x in oi_history['result']['list']]
            
            if not oi_list:
                return None
            
            oi_24h_ago = oi_list[-1]  # Самый старый
            oi_1h_ago = oi_list[1] if len(oi_list) > 1 else oi_list[0]
            
            change_24h = ((current_oi - oi_24h_ago) / oi_24h_ago) * 100 if oi_24h_ago > 0 else 0
            change_1h = ((current_oi - oi_1h_ago) / oi_1h_ago) * 100 if oi_1h_ago > 0 else 0
            
            return {
                'current': current_oi,
                'oi_1h_ago': oi_1h_ago,
                'oi_24h_ago': oi_24h_ago,
                'change_percent': change_1h,
                'change_24h_percent': change_24h,
                'history': oi_list
            }
            
        except Exception as e:
            print(f"[OI] Error getting OI: {e}")
            return None
    
    def _get_long_short_ratio(self, symbol: str) -> float:
        """
        Получает соотношение Long/Short.
        
        > 1.0 = больше лонгов
        < 1.0 = больше шортов
        """
        try:
            response = self.data.session.get_long_short_ratio(
                category=config.CATEGORY,
                symbol=symbol,
                period='1h',
                limit=1
            )
            
            if response['retCode'] == 0 and response['result']['list']:
                ratio = float(response['result']['list'][0]['buyRatio']) / \
                        float(response['result']['list'][0]['sellRatio'])
                return ratio
            
            return 1.0
            
        except Exception as e:
            print(f"[OI] Error getting L/S ratio: {e}")
            return 1.0
    
    def _get_top_trader_sentiment(self, symbol: str) -> str:
        """Получает настроение топ-трейдеров Bybit."""
        try:
            # Позиции топ-трейдеров
            response = self.data.session.get_long_short_ratio(
                category=config.CATEGORY,
                symbol=symbol,
                period='1h',
                limit=1
            )
            
            if response['retCode'] == 0 and response['result']['list']:
                data = response['result']['list'][0]
                buy_ratio = float(data['buyRatio'])
                sell_ratio = float(data['sellRatio'])
                
                if buy_ratio > 0.55:
                    return "LONG"
                elif sell_ratio > 0.55:
                    return "SHORT"
            
            return "NEUTRAL"
            
        except:
            return "NEUTRAL"
    
    def _get_price_change(self, symbol: str) -> float:
        """Получает изменение цены за последний час."""
        df = self.data.get_klines(symbol, interval='60', limit=2)
        
        if df is None or len(df) < 2:
            return 0
        
        return (df['close'].iloc[-1] - df['close'].iloc[-2]) / df['close'].iloc[-2]
    
    def _classify_oi_signal(self, oi_data: dict, price_change: float) -> OISignal:
        """Классифицирует сигнал OI."""
        oi_change = oi_data['change_percent']
        
        oi_growing = oi_change > 1  # OI вырос более чем на 1%
        oi_falling = oi_change < -1
        price_up = price_change > 0.001
        price_down = price_change < -0.001
        
        if oi_growing and price_up:
            return OISignal.NEW_LONGS
        elif oi_growing and price_down:
            return OISignal.NEW_SHORTS
        elif oi_falling and price_down:
            return OISignal.LONGS_CLOSING
        elif oi_falling and price_up:
            return OISignal.SHORTS_CLOSING  # SQUEEZE!
        else:
            return OISignal.NEUTRAL
    
    def _assess_liquidation_risk(self, ls_ratio: float, oi_data: dict) -> str:
        """
        Оценивает риск каскадных ликвидаций.
        
        Если слишком много лонгов И OI высокий — риск пролива.
        Если слишком много шортов И OI высокий — риск сквиза.
        """
        oi_change_24h = oi_data.get('change_24h_percent', 0)
        
        # Высокий OI = много позиций, которые могут быть ликвидированы
        high_oi = oi_change_24h > 10  # OI вырос на 10%+ за сутки
        
        if ls_ratio > 1.5 and high_oi:
            return "HIGH_LONG"  # Много лонгов — риск пролива вниз
        elif ls_ratio < 0.67 and high_oi:
            return "HIGH_SHORT"  # Много шортов — риск сквиза вверх
        else:
            return "LOW"
    
    def _generate_description(self, signal: OISignal, ls_ratio: float, top_sentiment: str) -> str:
        """Генерирует описание ситуации."""
        descriptions = {
            OISignal.NEW_LONGS: "📈 Новые лонги заходят. Тренд подтверждается.",
            OISignal.NEW_SHORTS: "📉 Новые шорты заходят. Давление продавцов.",
            OISignal.LONGS_CLOSING: "🚪 Лонги закрываются. Возможна капитуляция.",
            OISignal.SHORTS_CLOSING: "🚀 ШОРТЫ ЗАКРЫВАЮТСЯ! Возможен SHORT SQUEEZE!",
            OISignal.NEUTRAL: "➖ OI стабилен. Ждём определённости."
        }
        
        base = descriptions.get(signal, "")
        
        if ls_ratio > 1.5:
            base += f" L/S={ls_ratio:.2f} — перекос в лонги!"
        elif ls_ratio < 0.67:
            base += f" L/S={ls_ratio:.2f} — перекос в шорты!"
        
        return base
    
    def _empty_analysis(self) -> OIAnalysis:
        """Пустой анализ при ошибке."""
        return OIAnalysis(
            current_oi=0,
            oi_change_percent=0,
            oi_signal=OISignal.NEUTRAL,
            long_short_ratio=1.0,
            top_trader_sentiment="NEUTRAL",
            liquidation_risk="LOW",
            description="Ошибка получения данных OI"
        )
    
    def detect_squeeze_potential(self, symbol: str = None) -> dict:
        """
        Детектор потенциального сквиза.
        
        Условия для Short Squeeze:
        1. L/S ratio низкий (много шортов)
        2. Funding отрицательный (шорты платят)
        3. Цена у важного уровня снизу
        4. OI высокий (много позиций для ликвидации)
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        analysis = self.analyze(symbol)
        funding = self.data.get_funding_rate(symbol)
        
        squeeze_score = 0
        reasons = []
        
        # Условие 1: Много шортов
        if analysis.long_short_ratio < 0.8:
            squeeze_score += 25
            reasons.append(f"L/S ratio низкий: {analysis.long_short_ratio:.2f}")
        
        # Условие 2: Funding отрицательный
        if funding and funding['funding_rate'] < -0.005:
            squeeze_score += 25
            reasons.append(f"Funding отрицательный: {funding['funding_rate']*100:.3f}%")
        
        # Условие 3: OI Signal показывает закрытие шортов
        if analysis.oi_signal == OISignal.SHORTS_CLOSING:
            squeeze_score += 30
            reasons.append("Шорты уже закрываются!")
        
        # Условие 4: Высокий OI
        if analysis.oi_change_percent > 5:
            squeeze_score += 20
            reasons.append(f"OI вырос на {analysis.oi_change_percent:.1f}%")
        
        return {
            'squeeze_probability': min(100, squeeze_score),
            'type': 'SHORT_SQUEEZE' if squeeze_score > 50 else 'NONE',
            'reasons': reasons,
            'recommendation': 'LONG' if squeeze_score > 70 else 'WAIT'
        }
