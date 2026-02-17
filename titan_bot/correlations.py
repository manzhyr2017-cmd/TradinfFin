"""
TITAN BOT 2026 - Correlation Analysis
Не торгуй альту, когда BTC решает куда идти!
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict, List
import config

@dataclass
class CorrelationAnalysis:
    """Результат анализа корреляций"""
    btc_correlation: float      # Корреляция с BTC (-1 до 1)
    eth_correlation: float      # Корреляция с ETH
    correlation_regime: str     # 'HIGH', 'MEDIUM', 'LOW', 'NEGATIVE'
    btc_leading: bool          # BTC ведёт (опережает)?
    divergence_detected: bool  # Расхождение с BTC?
    safe_to_trade: bool
    description: str


class CorrelationAnalyzer:
    """
    Анализатор корреляций между активами.
    
    ЗОЛОТОЕ ПРАВИЛО КРИПТЫ:
    
    "Когда Bitcoin чихает, альткоины болеют пневмонией"
    
    Корреляция BTC-ETH обычно 0.85-0.95.
    Корреляция BTC-альты 0.7-0.9.
    
    КОГДА НЕ ТОРГОВАТЬ АЛЬТЫ:
    1. BTC на ключевом уровне (решает куда идти)
    2. BTC резко падает (альты упадут СИЛЬНЕЕ)
    3. Корреляция временно сломалась (непредсказуемость)
    
    КОГДА ТОРГОВАТЬ:
    1. BTC в спокойном тренде
    2. Альта показывает относительную силу
    3. Дивергенция в пользу альты
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        
        # Бенчмарки
        self.btc_symbol = "BTCUSDT"
        self.eth_symbol = "ETHUSDT"
    
    def analyze(self, symbol: str = None, period: int = 50) -> CorrelationAnalysis:
        """
        Анализирует корреляцию актива с BTC и ETH.
        
        Args:
            symbol: Торговая пара
            period: Период для расчёта корреляции
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем данные
        target_df = self.data.get_klines(symbol, limit=period + 10)
        btc_df = self.data.get_klines(self.btc_symbol, limit=period + 10)
        eth_df = self.data.get_klines(self.eth_symbol, limit=period + 10)
        
        if target_df is None or btc_df is None:
            return self._empty_analysis()
        
        # Рассчитываем returns
        target_returns = target_df['close'].pct_change().dropna()
        btc_returns = btc_df['close'].pct_change().dropna()
        eth_returns = eth_df['close'].pct_change().dropna() if eth_df is not None else None
        
        # Выравниваем по длине
        min_len = min(len(target_returns), len(btc_returns))
        target_returns = target_returns.iloc[-min_len:]
        btc_returns = btc_returns.iloc[-min_len:]
        
        # Корреляция с BTC
        btc_corr = target_returns.corr(btc_returns)
        
        # Корреляция с ETH
        eth_corr = 0
        if eth_returns is not None and len(eth_returns) >= min_len:
            eth_returns = eth_returns.iloc[-min_len:]
            eth_corr = target_returns.corr(eth_returns)
        
        # Определяем режим корреляции
        regime = self._classify_correlation(btc_corr)
        
        # Проверяем, ведёт ли BTC
        btc_leading = self._check_btc_leading(target_returns, btc_returns)
        
        # Проверяем дивергенцию
        divergence = self._check_divergence(target_df, btc_df)
        
        # Определяем безопасность торговли
        safe, reason = self._assess_safety(btc_corr, btc_df, divergence)
        
        return CorrelationAnalysis(
            btc_correlation=btc_corr,
            eth_correlation=eth_corr,
            correlation_regime=regime,
            btc_leading=btc_leading,
            divergence_detected=divergence,
            safe_to_trade=safe,
            description=reason
        )
    
    def _classify_correlation(self, corr: float) -> str:
        """Классифицирует уровень корреляции."""
        if corr > 0.8:
            return "HIGH"
        elif corr > 0.5:
            return "MEDIUM"
        elif corr > 0.2:
            return "LOW"
        else:
            return "NEGATIVE"
    
    def _check_btc_leading(self, target_returns: pd.Series, btc_returns: pd.Series) -> bool:
        """
        Проверяет, опережает ли BTC движение актива.
        
        Используем кросс-корреляцию с лагом.
        """
        # Корреляция с BTC смещённым на 1 период назад
        if len(btc_returns) < 3:
            return False
        
        btc_lagged = btc_returns.shift(1).dropna()
        target_aligned = target_returns.iloc[1:]
        
        if len(btc_lagged) != len(target_aligned):
            min_len = min(len(btc_lagged), len(target_aligned))
            btc_lagged = btc_lagged.iloc[-min_len:]
            target_aligned = target_aligned.iloc[-min_len:]
        
        lagged_corr = target_aligned.corr(btc_lagged)
        normal_corr = target_returns.corr(btc_returns)
        
        # Если лаговая корреляция выше — BTC ведёт
        return lagged_corr > normal_corr + 0.1
    
    def _check_divergence(self, target_df: pd.DataFrame, btc_df: pd.DataFrame) -> bool:
        """
        Проверяет дивергенцию между активом и BTC.
        
        Дивергенция = актив идёт в другую сторону от BTC.
        """
        # Изменение за последние 10 свечей
        target_change = (target_df['close'].iloc[-1] - target_df['close'].iloc[-10]) / target_df['close'].iloc[-10]
        btc_change = (btc_df['close'].iloc[-1] - btc_df['close'].iloc[-10]) / btc_df['close'].iloc[-10]
        
        # Дивергенция если направления разные и разница значительная
        if target_change > 0.01 and btc_change < -0.01:
            return True  # Актив растёт, BTC падает
        if target_change < -0.01 and btc_change > 0.01:
            return True  # Актив падает, BTC растёт
        
        return False
    
    def _assess_safety(self, btc_corr: float, btc_df: pd.DataFrame, divergence: bool) -> tuple:
        """Оценивает безопасность торговли."""
        
        # Проверяем волатильность BTC
        btc_volatility = btc_df['close'].pct_change().std() * 100
        
        # Проверяем текущее движение BTC
        btc_recent_move = (btc_df['close'].iloc[-1] - btc_df['close'].iloc[-5]) / btc_df['close'].iloc[-5] * 100
        
        # Опасные ситуации
        if abs(btc_recent_move) > 3:
            return False, f"⚠️ BTC двигается резко ({btc_recent_move:+.1f}%). Альты непредсказуемы."
        
        if btc_volatility > 2:
            return False, f"⚠️ BTC высоко волатилен ({btc_volatility:.1f}%). Подожди."
        
        if btc_corr < 0.3:
            return False, f"⚠️ Корреляция сломана ({btc_corr:.2f}). Рынок хаотичен."
        
        # Относительно безопасно
        if divergence:
            return True, f"✅ Дивергенция с BTC. Актив показывает силу/слабость."
        
        return True, f"✅ BTC стабилен. Корреляция {btc_corr:.2f}. Можно торговать."
    
    def _empty_analysis(self) -> CorrelationAnalysis:
        """Пустой анализ при ошибке."""
        return CorrelationAnalysis(
            btc_correlation=0,
            eth_correlation=0,
            correlation_regime="UNKNOWN",
            btc_leading=False,
            divergence_detected=False,
            safe_to_trade=False,
            description="Ошибка получения данных"
        )
    
    def get_relative_strength(self, symbol: str = None, period: int = 20) -> dict:
        """
        Рассчитывает относительную силу актива vs BTC.
        
        RS > 1 = актив сильнее BTC
        RS < 1 = актив слабее BTC
        """
        if symbol is None:
            symbol = config.SYMBOL
        
        target_df = self.data.get_klines(symbol, limit=period + 5)
        btc_df = self.data.get_klines(self.btc_symbol, limit=period + 5)
        
        if target_df is None or btc_df is None:
            return {'relative_strength': 1.0, 'interpretation': 'NEUTRAL'}
        
        # Изменение за период
        target_change = (target_df['close'].iloc[-1] / target_df['close'].iloc[-period]) - 1
        btc_change = (btc_df['close'].iloc[-1] / btc_df['close'].iloc[-period]) - 1
        
        # Relative Strength
        if btc_change != 0:
            rs = (1 + target_change) / (1 + btc_change)
        else:
            rs = 1.0
        
        interpretation = "NEUTRAL"
        if rs > 1.1:
            interpretation = "OUTPERFORMING"
        elif rs < 0.9:
            interpretation = "UNDERPERFORMING"
        
        return {
            'relative_strength': rs,
            'target_change': target_change * 100,
            'btc_change': btc_change * 100,
            'interpretation': interpretation
        }
