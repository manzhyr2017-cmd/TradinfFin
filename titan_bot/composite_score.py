"""
TITAN BOT 2026 - Composite Score Engine
Один скор, чтобы править всеми
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
import config

class SignalStrength(Enum):
    STRONG_BULLISH = 2
    BULLISH = 1
    NEUTRAL = 0
    BEARISH = -1
    STRONG_BEARISH = -2

@dataclass
class CompositeSignal:
    """Итоговый композитный сигнал"""
    total_score: float          # -100 до +100
    direction: str              # 'LONG', 'SHORT', 'NEUTRAL'
    confidence: float           # 0-1
    strength: str               # 'STRONG', 'MODERATE', 'WEAK'
    components: Dict[str, float]  # Вклад каждого компонента
    conflicts: List[str]        # Конфликтующие сигналы
    recommendation: str
    position_size_modifier: float  # Множитель размера позиции


class CompositeScoreEngine:
    """
    Движок композитного скоринга.
    
    ЗАЧЕМ ЭТО НУЖНО:
    
    У тебя 15+ модулей. Каждый даёт свой сигнал.
    Как понять, когда входить?
    
    Composite Score объединяет ВСЁ в одно число от -100 до +100:
    - +100 = идеальный лонг (все системы согласны)
    - -100 = идеальный шорт
    - 0 = конфликт или неопределённость
    
    ВЕСА КОМПОНЕНТОВ (из моего опыта):
    
    ┌────────────────────┬────────┬─────────────────────────────┐
    │ Компонент          │ Вес    │ Почему                      │
    ├────────────────────┼────────┼─────────────────────────────┤
    │ MTF Alignment      │ 20%    │ Тренд — главное             │
    │ SMC Signal         │ 20%    │ Точка входа                 │
    │ Order Flow         │ 15%    │ Реальное давление           │
    │ Volume Profile     │ 10%    │ Справедливая цена           │
    │ OI Analysis        │ 10%    │ Кто в позициях              │
    │ Market Regime      │ 10%    │ Контекст рынка              │
    │ Whale Activity     │ 5%     │ Smart Money                 │
    │ Fear & Greed       │ 5%     │ Настроение толпы            │
    │ Correlations       │ 5%     │ BTC влияние                 │
    └────────────────────┴────────┴─────────────────────────────┘
    """
    
    def __init__(self):
        # Веса компонентов (должны суммироваться в 1.0)
        self.weights = {
            'mtf': 0.20,
            'smc': 0.20,
            'orderflow': 0.15,
            'volume_profile': 0.10,
            'open_interest': 0.10,
            'regime': 0.10,
            'whale': 0.05,
            'fear_greed': 0.05,
            'correlation': 0.05
        }
        
        # Пороги для решений
        self.thresholds = {
            'strong_signal': 60,
            'moderate_signal': 40,
            'weak_signal': 20,
            'conflict_zone': 15
        }
    
    def calculate(
        self,
        mtf_analysis,
        smc_signal,
        orderflow_signal,
        volume_profile,
        oi_analysis,
        regime_analysis,
        whale_analysis,
        fear_greed,
        correlation_analysis
    ) -> CompositeSignal:
        """
        Рассчитывает композитный скор на основе всех входных данных.
        """
        components = {}
        conflicts = []
        
        # 1. MTF Score
        mtf_score = self._score_mtf(mtf_analysis)
        components['mtf'] = mtf_score
        
        # 2. SMC Score
        smc_score = self._score_smc(smc_signal)
        components['smc'] = smc_score
        
        # 3. Order Flow Score
        of_score = self._score_orderflow(orderflow_signal)
        components['orderflow'] = of_score
        
        # 4. Volume Profile Score
        vp_score = self._score_volume_profile(volume_profile)
        components['volume_profile'] = vp_score
        
        # 5. Open Interest Score
        oi_score = self._score_oi(oi_analysis)
        components['open_interest'] = oi_score
        
        # 6. Regime Score
        regime_score = self._score_regime(regime_analysis)
        components['regime'] = regime_score
        
        # 7. Whale Score
        whale_score = self._score_whale(whale_analysis)
        components['whale'] = whale_score
        
        # 8. Fear & Greed Score
        fg_score = self._score_fear_greed(fear_greed)
        components['fear_greed'] = fg_score
        
        # 9. Correlation Score
        corr_score = self._score_correlation(correlation_analysis)
        components['correlation'] = corr_score
        
        # Находим конфликты
        conflicts = self._find_conflicts(components)
        
        # Рассчитываем взвешенный скор
        total_score = sum(
            components[key] * self.weights.get(key, 0) * 100
            for key in components
        )
        
        # Применяем штраф за конфликты
        if conflicts:
            conflict_penalty = len(conflicts) * 10
            total_score *= (100 - conflict_penalty) / 100
        
        # Определяем направление и силу
        direction = self._determine_direction(total_score)
        strength = self._determine_strength(abs(total_score))
        confidence = self._calculate_confidence(total_score, conflicts)
        
        # Модификатор размера позиции
        size_modifier = self._calculate_size_modifier(total_score, confidence, conflicts)
        
        # Рекомендация
        recommendation = self._generate_recommendation(
            direction, strength, total_score, conflicts
        )
        
        return CompositeSignal(
            total_score=round(total_score, 1),
            direction=direction,
            confidence=confidence,
            strength=strength,
            components=components,
            conflicts=conflicts,
            recommendation=recommendation,
            position_size_modifier=size_modifier
        )
    
    def _score_mtf(self, mtf) -> float:
        """Скоринг Multi-Timeframe анализа."""
        if mtf is None:
            return 0
        
        score_map = {
            'LONG': 1.0,
            'SHORT': -1.0,
            'BOTH': 0.2,
            'NONE': 0
        }
        
        base_score = score_map.get(mtf.trade_allowed, 0)
        
        # Учитываем согласованность
        if hasattr(mtf, 'alignment'):
            if mtf.alignment == "BULLISH":
                base_score = max(base_score, 0.5)
            elif mtf.alignment == "BEARISH":
                base_score = min(base_score, -0.5)
        
        confidence = getattr(mtf, 'confidence', 1.0)
        return base_score * confidence
    
    def _score_smc(self, smc_signal) -> float:
        """Скоринг Smart Money сигнала."""
        if smc_signal is None:
            return 0
        
        # Assuming smc_signal has a signal_type attribute with a value that contains 'LONG' or 'SHORT'
        # and a confidence attribute.
        signal_type = str(getattr(smc_signal.signal_type, 'value', smc_signal.signal_type))
        confidence = getattr(smc_signal, 'confidence', 1.0)
        
        if 'LONG' in signal_type:
            return confidence
        elif 'SHORT' in signal_type:
            return -confidence
        
        return 0
    
    def _score_orderflow(self, of_signal) -> float:
        """Скоринг Order Flow."""
        if of_signal is None:
            return 0
        
        pressure_map = {
            'STRONG_BUY': 1.0,
            'WEAK_BUY': 0.5,
            'NEUTRAL': 0,
            'WEAK_SELL': -0.5,
            'STRONG_SELL': -1.0
        }
        
        pressure = getattr(of_signal.pressure, 'value', of_signal.pressure)
        confidence = getattr(of_signal, 'confidence', 1.0) or 1.0
        
        return pressure_map.get(pressure, 0) * confidence
    
    def _score_volume_profile(self, vp) -> float:
        """Скоринг Volume Profile."""
        if vp is None:
            return 0
        
        rec_map = {
            'LONG_OPPORTUNITY': 0.8,
            'NEUTRAL_BULLISH': 0.3,
            'WAIT': 0,
            'NEUTRAL_BEARISH': -0.3,
            'SHORT_OPPORTUNITY': -0.8,
            'RISKY_LONG': -0.2,
            'RISKY_SHORT': 0.2
        }
        
        recommendation = getattr(vp, 'trade_recommendation', 'UNKNOWN')
        return rec_map.get(recommendation, 0)
    
    def _score_oi(self, oi) -> float:
        """Скоринг Open Interest."""
        if oi is None:
            return 0
        
        signal_map = {
            'NEW_LONGS': 0.5,
            'SHORTS_CLOSING': 1.0,  # SHORT SQUEEZE!
            'NEUTRAL': 0,
            'NEW_SHORTS': -0.5,
            'LONGS_CLOSING': -1.0
        }
        
        oi_signal = getattr(oi.oi_signal, 'value', oi.oi_signal)
        base_score = signal_map.get(oi_signal, 0)
        
        # Корректируем по L/S ratio
        ls_ratio = getattr(oi, 'long_short_ratio', 1.0)
        if ls_ratio > 1.5:  # Много лонгов
            base_score -= 0.2
        elif ls_ratio < 0.67:  # Много шортов
            base_score += 0.2
        
        return base_score
    
    def _score_regime(self, regime) -> float:
        """Скоринг Market Regime."""
        if regime is None:
            return 0
        
        regime_map = {
            'TRENDING_UP': 0.5,
            'TRENDING_DOWN': -0.5,
            'RANGING': 0,
            'VOLATILE': 0,
            'QUIET': 0
        }
        
        regime_val = getattr(regime.regime, 'value', regime.regime)
        return regime_map.get(regime_val, 0)
    
    def _score_whale(self, whale) -> float:
        """Скоринг Whale Activity."""
        if whale is None:
            return 0
        
        sentiment_map = {
            'ACCUMULATING': 1.0,
            'NEUTRAL': 0,
            'DISTRIBUTING': -1.0
        }
        
        sentiment = getattr(whale, 'whale_sentiment', 'NEUTRAL')
        return sentiment_map.get(sentiment, 0)
    
    def _score_fear_greed(self, fg) -> float:
        """Скоринг Fear & Greed (контрарный!)."""
        if fg is None:
            return 0
        
        signal_map = {
            'STRONG_BUY': 1.0,
            'BUY': 0.5,
            'NEUTRAL': 0,
            'SELL': -0.5,
            'STRONG_SELL': -1.0
        }
        
        contrarian = getattr(fg, 'contrarian_signal', 'NEUTRAL')
        return signal_map.get(contrarian, 0)
    
    def _score_correlation(self, corr) -> float:
        """Скоринг Correlation Analysis."""
        if corr is None:
            return 0
        
        # Если небезопасно торговать — сигнал к осторожности
        safe_to_trade = getattr(corr, 'safe_to_trade', True)
        if not safe_to_trade:
            return -0.5 # Penalty if not safe
        
        # Если есть дивергенция — усиливаем сигнал
        # (актив сильнее/слабее BTC)
        divergence = getattr(corr, 'divergence_detected', False)
        return 0.3 if divergence else 0
    
    def _find_conflicts(self, components: Dict[str, float]) -> List[str]:
        """Находит конфликтующие сигналы."""
        conflicts = []
        
        # Проверяем противоречия между ключевыми компонентами
        mtf = components.get('mtf', 0)
        smc = components.get('smc', 0)
        of = components.get('orderflow', 0)
        
        # MTF vs SMC
        if mtf * smc < 0 and abs(mtf) > 0.3 and abs(smc) > 0.3:
            conflicts.append("MTF vs SMC: противоречивые направления")
        
        # SMC vs OrderFlow
        if smc * of < 0 and abs(smc) > 0.3 and abs(of) > 0.3:
            conflicts.append("SMC vs OrderFlow: сигнал против потока")
        
        # Whale vs Fear/Greed
        whale = components.get('whale', 0)
        fg = components.get('fear_greed', 0)
        
        if whale * fg < 0 and abs(whale) > 0.5 and abs(fg) > 0.5:
            conflicts.append("Whale vs Sentiment: киты против толпы")
        
        return conflicts
    
    def _determine_direction(self, score: float) -> str:
        """Определяет направление."""
        if score > self.thresholds['conflict_zone']:
            return "LONG"
        elif score < -self.thresholds['conflict_zone']:
            return "SHORT"
        else:
            return "NEUTRAL"
    
    def _determine_strength(self, abs_score: float) -> str:
        """Определяет силу сигнала."""
        if abs_score >= self.thresholds['strong_signal']:
            return "STRONG"
        elif abs_score >= self.thresholds['moderate_signal']:
            return "MODERATE"
        elif abs_score >= self.thresholds['weak_signal']:
            return "WEAK"
        else:
            return "NONE"
    
    def _calculate_confidence(self, score: float, conflicts: List) -> float:
        """Рассчитывает уверенность."""
        base_confidence = min(abs(score) / 100, 1.0)
        
        # Штраф за конфликты
        conflict_penalty = len(conflicts) * 0.15
        
        return max(0, base_confidence - conflict_penalty)
    
    def _calculate_size_modifier(
        self, 
        score: float, 
        confidence: float,
        conflicts: List
    ) -> float:
        """Рассчитывает модификатор размера позиции."""
        
        # Базовый модификатор от силы сигнала
        base = abs(score) / 100
        
        # Корректировка по уверенности
        modifier = base * confidence
        
        # Уменьшаем при конфликтах
        if conflicts:
            modifier *= 0.7
        
        # Ограничиваем диапазон
        return max(0.3, min(1.5, modifier))
    
    def _generate_recommendation(
        self,
        direction: str,
        strength: str,
        score: float,
        conflicts: List
    ) -> str:
        """Генерирует рекомендацию."""
        
        if direction == "NEUTRAL":
            return "⏸️ НЕТ СИГНАЛА. Слишком много неопределённости. Жди."
        
        if conflicts:
            return f"⚠️ {direction} с оговорками. Score: {score:.0f}. Конфликты: {len(conflicts)}. Уменьши размер."
        
        if strength == "STRONG":
            return f"🚀 СИЛЬНЫЙ {direction}! Score: {score:.0f}. Все системы согласны. Полный размер."
        
        if strength == "MODERATE":
            return f"✅ {direction}. Score: {score:.0f}. Хороший сигнал. Стандартный размер."
        
        if strength == "WEAK":
            return f"🟡 Слабый {direction}. Score: {score:.0f}. Можно войти с уменьшенным размером."
        
        return f"❓ {direction}. Score: {score:.0f}."
    
    def print_dashboard(self, signal: CompositeSignal):
        """Выводит красивый дашборд."""
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║                    COMPOSITE SCORE DASHBOARD                     ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║   TOTAL SCORE:  [{self._score_bar(signal.total_score)}]  {signal.total_score:>+6.1f}   ║
║                                                                  ║
║   Direction:    {signal.direction:<12}  Strength: {signal.strength:<10}       ║
║   Confidence:   {signal.confidence*100:>5.1f}%         Size Mod: {signal.position_size_modifier:.2f}x          ║
║                                                                  ║
╠══════════════════════════════════════════════════════════════════╣
║   COMPONENTS:                                                    ║""")
        
        for name, value in signal.components.items():
            bar = self._component_bar(value)
            weight = self.weights.get(name, 0) * 100
            print(f"║   {name:<15} [{bar}] {value:>+5.2f} (w:{weight:.0f}%)       ║")
        
        print(f"""╠══════════════════════════════════════════════════════════════════╣
║   CONFLICTS: {len(signal.conflicts) if signal.conflicts else 'None':<20}                            ║""")
        
        for conflict in signal.conflicts[:3]:
            print(f"║   ⚠️ {conflict:<56}   ║")
        
        print(f"""╠══════════════════════════════════════════════════════════════════╣
║   {signal.recommendation:<62} ║
╚══════════════════════════════════════════════════════════════════╝""")
    
    def _score_bar(self, score: float) -> str:
        """Визуальная шкала скора."""
        # От -100 до +100, маппим на 20 символов
        normalized = (score + 100) / 200  # 0 to 1
        position = int(normalized * 19)
        
        bar = '─' * position + '█' + '─' * (19 - position)
        return bar
    
    def _component_bar(self, value: float) -> str:
        """Визуальная шкала компонента."""
        # От -1 до +1
        normalized = (value + 1) / 2  # 0 to 1
        filled = int(normalized * 10)
        
        return '█' * filled + '░' * (10 - filled)
