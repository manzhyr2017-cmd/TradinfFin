"""
═══════════════════════════════════════════════════════════════════
  MASTER BRAIN v1.0 — Единая логика управления Grid Bot
  ═══════════════════════════════════════════════════════════════
  
  ФИЛОСОФИЯ:
  ─────────────────────────────────────────────────────────────
  Все 30+ модулей бота — это инструменты.
  Master Brain — это рука, которая берёт нужный инструмент
  в нужный момент.
  
  КЛЮЧЕВЫЕ ПРИНЦИПЫ:
  1. ИЕРАРХИЯ: каждое решение имеет приоритет
  2. КОНСЕНСУС: важные решения требуют согласия модулей
  3. ОБЪЯСНИМОСТЬ: каждое действие логируется с причиной
  4. АДАПТИВНОСТЬ: логика меняется при разных режимах
  5. FAIL-SAFE: при неопределённости → минимальный риск
  
  ПИРАМИДА РЕШЕНИЙ (порядок выполнения):
  
  1️⃣  SURVIVAL CHECK   — живы ли мы? (SL, drawdown, API)
  2️⃣  MARKET READING   — что делает рынок?
  3️⃣  MODE SELECTION   — какой режим торговли?
  4️⃣  TIMING GATE      — сейчас хороший момент?
  5️⃣  ORDER DECISION   — конкретное решение по ордеру
  6️⃣  SIZE CALCULATION — сколько ставить?
  7️⃣  EXECUTION        — размещаем ордер
  8️⃣  LEARNING         — учимся из результата
═══════════════════════════════════════════════════════════════════
"""

import time
import logging
import threading
import numpy as np
from decimal import Decimal
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

# ── Все наши модули ────────────────────────────────────
import config
from core.database import Database
from core.notifier import TelegramNotifier
from core.bybit_client import BybitClient

# ── WebSocket (новая bulletproof версия) ──────────────
from core.websocket_manager import RobustWebSocket, WebSocketManager

# ── Analysis ──────────────────────────────────────────
try:
    from analysis.indicators import TechnicalAnalyzer
except ImportError:
    TechnicalAnalyzer = None

try:
    from analysis.smart_entry import SmartEntryAnalyzer, EntrySignal
except ImportError:
    SmartEntryAnalyzer = None
    EntrySignal = None

try:
    from analysis.spread_analyzer import SpreadAnalyzer
except ImportError:
    SpreadAnalyzer = None

try:
    from analysis.multi_timeframe import MultiTimeframeAnalyzer
except ImportError:
    MultiTimeframeAnalyzer = None

try:
    from analysis.anomaly_detector import AnomalyDetector
except ImportError:
    AnomalyDetector = None

try:
    from analysis.market_scanner import MarketScanner
except ImportError:
    MarketScanner = None

# ── ML ────────────────────────────────────────────────
try:
    from ml.regime_detector import MLRegimeDetector, MarketRegime
except ImportError:
    MLRegimeDetector = None
    MarketRegime = None

try:
    from ml.reinforcement import RLGridOptimizer, GridParams
except ImportError:
    RLGridOptimizer = None
    GridParams = None

try:
    from ml.sentiment import SentimentAnalyzer
except ImportError:
    SentimentAnalyzer = None

# ── Strategies ────────────────────────────────────────
try:
    from strategies.avellaneda_stoikov import AvellanedaStoikovModel
except ImportError:
    AvellanedaStoikovModel = None

try:
    from strategies.liquidation_heatmap import LiquidationHeatmapAnalyzer
except ImportError:
    LiquidationHeatmapAnalyzer = None

try:
    from strategies.volume_profile import VolumeProfileAnalyzer
except ImportError:
    VolumeProfileAnalyzer = None

try:
    from strategies.delta_neutral import DeltaNeutralHedger
except ImportError:
    DeltaNeutralHedger = None

try:
    from strategies.adverse_selection import AdverseSelectionDetector
except ImportError:
    AdverseSelectionDetector = None

try:
    from strategies.spoofing_detector import SpoofingDetector
except ImportError:
    SpoofingDetector = None

try:
    from strategies.genetic_optimizer import GeneticOptimizer
except ImportError:
    GeneticOptimizer = None

try:
    from strategies.arbitrage import CrossExchangeArbitrage
except ImportError:
    CrossExchangeArbitrage = None

try:
    from strategies.onchain import OnChainAnalyzer
except ImportError:
    OnChainAnalyzer = None

try:
    from strategies.ab_testing import ABTestEngine
except ImportError:
    ABTestEngine = None

try:
    from strategies.auto_compound import AutoCompounder
except ImportError:
    AutoCompounder = None

try:
    from strategies.hybrid_grid_dca import HybridGridDCA, BotMode
except ImportError:
    HybridGridDCA = None
    BotMode = None

try:
    from strategies.infinity_grid import InfinityGridEngine
except ImportError:
    InfinityGridEngine = None

# ── Bybit Specific ────────────────────────────────────
try:
    from bybit_specific.fee_optimizer import BybitFeeOptimizer
except ImportError:
    BybitFeeOptimizer = None

try:
    from bybit_specific.rate_limiter import RateLimitManager
except ImportError:
    RateLimitManager = None

try:
    from bybit_specific.batch_orders import BatchOrderManager
except ImportError:
    BatchOrderManager = None

# ── Precision Decision Engines ────────────────────────
try:
    from analysis.precision_timing import PrecisionTimingEngine, TimingScore
except ImportError:
    PrecisionTimingEngine = None
    TimingScore = None

try:
    from analysis.smart_pause import SmartPauseEngine, PauseLevel, PauseDecision
except ImportError:
    SmartPauseEngine = None
    PauseLevel = None
    PauseDecision = None

try:
    from strategies.adaptive_sizing import AdaptiveSizingEngine, SizingResult
except ImportError:
    AdaptiveSizingEngine = None
    SizingResult = None


log = logging.getLogger("GridBot")


# ═══════════════════════════════════════════════════════
#  ТИПЫ ДАННЫХ
# ═══════════════════════════════════════════════════════

class TradingMode(Enum):
    """Режим торговли бота."""
    GRID_STANDARD   = "grid_standard"    # Обычный грид (боковик)
    GRID_INFINITY   = "grid_infinity"    # Грид без верхней границы
    DCA_ACCUMULATE  = "dca_accumulate"   # Накопление в даунтренде
    SELL_ONLY       = "sell_only"        # Только продажи (аптренд)
    ARBITRAGE       = "arbitrage"        # Арбитраж межбиржевой
    EMERGENCY_STOP  = "emergency_stop"   # Полная остановка


class DecisionType(Enum):
    """Тип решения."""
    PLACE_BUY   = "place_buy"
    PLACE_SELL  = "place_sell"
    CANCEL_ALL  = "cancel_all"
    REBALANCE   = "rebalance"
    SWITCH_MODE = "switch_mode"
    COMPOUND    = "compound"
    NO_ACTION   = "no_action"


@dataclass
class MarketSnapshot:
    """
    Полный снимок рынка на текущий момент.
    Собирается один раз за цикл и передаётся всем модулям.
    """
    timestamp: datetime
    price: Decimal
    bid: Decimal
    ask: Decimal
    spread_pct: float
    volume_24h: float

    # Технический анализ
    rsi: float = 50.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    atr: float = 0.0
    volatility_pct: float = 0.0
    hurst: float = 0.5
    funding_rate: float = 0.0

    # Режим рынка
    ml_regime: str = "unknown"
    ml_confidence: float = 0.0
    mtf_regime: str = "unknown"
    trend_strength: float = 0.0

    # Внешние данные
    fear_greed: int = 50
    onchain_signal: float = 0.0
    whale_alert: bool = False

    # Качество рынка
    obi: float = 0.5           # Order Book Imbalance
    spoof_score: float = 0.0
    toxicity_score: float = 0.0
    timing_score: int = 50


@dataclass
class BrainLevel:
    """Уровень сетки во внутреннем представлении мозга."""
    index: int
    price: Decimal
    side: str = ""
    recommended_qty: Decimal = Decimal("0")
    skewed_price: Decimal = Decimal("0") # Для обратной совместимости с AS


@dataclass
class BrainDecision:
    """
    Решение Master Brain.
    Содержит ВСЁ необходимое для исполнения.
    """
    decision_type: DecisionType
    trading_mode: TradingMode
    should_buy: bool
    should_sell: bool
    qty_multiplier: float       # Итоговый множитель объёма
    grid_levels_override: Optional[int] = None
    notes: List[str] = field(default_factory=list)

    # Детали по блокировкам
    blocked_by: Optional[str] = None  # Что заблокировало торговлю
    confidence: float = 0.0           # Уверенность в решении (0-1)

    # Диагностика (для логов)
    module_votes: Dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class BrainState:
    """Внутреннее состояние мозга."""
    current_mode: TradingMode = TradingMode.GRID_STANDARD
    last_mode_change: datetime = field(default_factory=datetime.utcnow)
    consecutive_blocks: int = 0    # Сколько раз подряд заблокировали
    total_decisions: int = 0
    mode_history: List[Tuple[datetime, TradingMode]] = field(
        default_factory=list
    )


# ═══════════════════════════════════════════════════════
#  MASTER BRAIN
# ═══════════════════════════════════════════════════════

class MasterBrain:
    """
    Единый мозг грид-бота.
    
    Координирует все 30+ модулей через чёткую
    5-уровневую иерархию решений.
    
    Каждый модуль — это "советник".
    Master Brain — это "CEO", который слушает советников
    и принимает финальное решение.
    """

    # ─── Интервалы обновления каждого модуля ──────────
    # (в секундах, чтобы не перегружать API)
    UPDATE_INTERVALS = {
        "market_snapshot":  2,      # Каждые 2 сек
        "orderbook":        5,      # Каждые 5 сек
        "ml_predict":       30,     # Каждые 30 сек
        "mtf_analysis":     60,     # Каждую минуту
        "sentiment":        300,    # Каждые 5 минут
        "onchain":          600,    # Каждые 10 минут
        "liquidation_map":  300,    # Каждые 5 минут
        "volume_profile":   3600,   # Каждый час
        "ml_retrain":       21600,  # Каждые 6 часов
        "genetic_optimize": 86400,  # Раз в сутки
        "compound_check":   86400,  # Раз в сутки
        "vip_check":        3600,   # Каждый час
        "scanner":          300,    # Каждые 5 минут
    }

    def __init__(self):
        log.info("🧠 Master Brain: инициализация...")
        self._init_core()
        self._init_analysis()
        self._init_ml()
        self._init_strategies()
        self._init_bybit_specific()
        self._init_state()

        # Считаем сколько модулей загрузилось
        loaded = sum(1 for v in [
            self.classic, self.smart_entry, self.spread_analyzer,
            self.mtf, self.anomaly, self.timing, self.pause_engine,
            self.sizer, self.ml_regime, self.rl_optimizer,
            self.sentiment, self.as_model, self.liq_heatmap,
            self.vpvr, self.delta_hedge, self.adverse,
            self.spoof_detector, self.genetic, self.arbitrage,
            self.onchain, self.ab_tester, self.compounder,
            self.hybrid_dca, self.fee_optimizer, self.rate_limiter,
            self.batch_manager,
        ] if v is not None)

        log.info(f"🧠 Master Brain: готов ({loaded}/26 модулей)")

    def _init_core(self):
        """Ядро — обязательно."""
        self.client = BybitClient()
        self.db = Database()
        self.notifier = TelegramNotifier()
        self.ws_manager = WebSocketManager()
        self.rate_limiter = RateLimitManager() if RateLimitManager else None
        self.batch_manager = BatchOrderManager(self.client) if BatchOrderManager else None

    def _init_analysis(self):
        """Аналитика — graceful если нет."""
        self.classic = (
            TechnicalAnalyzer() if TechnicalAnalyzer else None
        )
        self.smart_entry = (
            SmartEntryAnalyzer(symbol=config.SYMBOL) if SmartEntryAnalyzer else None
        )
        self.spread_analyzer = (
            SpreadAnalyzer(self.client) if SpreadAnalyzer else None
        )
        self.mtf = (
            MultiTimeframeAnalyzer(self.client)
            if MultiTimeframeAnalyzer else None
        )
        self.anomaly = (
            AnomalyDetector() if AnomalyDetector else None
        )
        self.timing = (
            PrecisionTimingEngine(self.client)
            if PrecisionTimingEngine else None
        )
        self.pause_engine = (
            SmartPauseEngine(self.client, self.db)
            if SmartPauseEngine else None
        )
        self.sizer = (
            AdaptiveSizingEngine(self.client, self.db)
            if AdaptiveSizingEngine else None
        )
        self.scanner = (
            MarketScanner(self.client) if MarketScanner else None
        )

    def _init_ml(self):
        """ML — опционально."""
        self.ml_regime = (
            MLRegimeDetector() if MLRegimeDetector else None
        )
        self.rl_optimizer = (
            RLGridOptimizer() if RLGridOptimizer else None
        )
        self.sentiment = (
            SentimentAnalyzer() if SentimentAnalyzer else None
        )

    def _init_strategies(self):
        """Стратегии — опционально."""
        self.as_model = (
            AvellanedaStoikovModel(self.client)
            if AvellanedaStoikovModel else None
        )
        self.liq_heatmap = (
            LiquidationHeatmapAnalyzer(self.client)
            if LiquidationHeatmapAnalyzer else None
        )
        self.vpvr = (
            VolumeProfileAnalyzer(self.client)
            if VolumeProfileAnalyzer else None
        )
        self.delta_hedge = (
            DeltaNeutralHedger(self.client)
            if DeltaNeutralHedger else None
        )
        self.adverse = (
            AdverseSelectionDetector()
            if AdverseSelectionDetector else None
        )
        self.spoof_detector = (
            SpoofingDetector(self.client)
            if SpoofingDetector else None
        )
        self.genetic = (
            GeneticOptimizer() if GeneticOptimizer else None
        )
        self.arbitrage = (
            CrossExchangeArbitrage(self.client)
            if CrossExchangeArbitrage else None
        )
        self.onchain = (
            OnChainAnalyzer() if OnChainAnalyzer else None
        )
        self.ab_tester = (
            ABTestEngine() if ABTestEngine else None
        )
        self.compounder = (
            AutoCompounder(self.client, self.db)
            if AutoCompounder else None
        )
        self.hybrid_dca = (
            HybridGridDCA(self.client, self.db)
            if HybridGridDCA else None
        )
        self.infinity_grid = (
            InfinityGridEngine(self.client)
            if InfinityGridEngine else None
        )

    def _init_bybit_specific(self):
        """Bybit-специфика — опционально."""
        self.fee_optimizer = (
            BybitFeeOptimizer(self.client)
            if BybitFeeOptimizer else None
        )

    # def _init_websockets(self):
    #     """WebSockets для реального времени (выключено, управляет WebSocketManager)."""
    #     pass

    def start(self):
        """Запуск Master Brain."""
        log.info(f"🧠 Master Brain: запущен на {self.current_symbol}")

    def stop(self):
        """Остановка Master Brain."""
        log.info("🧠 Master Brain: остановка...")

    def _init_state(self):
        """Состояние мозга."""
        self.state = BrainState()
        self.last_snapshot: Optional[MarketSnapshot] = None
        self.active_orders: Dict[str, Any] = {}
        self.grid_levels: List[Any] = []
        self.current_symbol = config.SYMBOL
        self._instrument_info = None

        # Кэш последних результатов модулей
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, datetime] = {}
        self._last_updates: Dict[str, datetime] = {}

        # Статистика
        self.stats = {
            "decisions_made": 0,
            "trades_executed": 0,
            "blocks_by_module": {},
            "mode_switches": 0,
        }


    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 1: SURVIVAL CHECK
    #  "Живы ли мы? Можно ли вообще торговать?"
    # ═══════════════════════════════════════════════════

    def _level1_survival_check(
        self, price: Decimal,
    ) -> Tuple[bool, str]:
        """
        ПЕРВЫЙ УРОВЕНЬ — самый важный.
        Если здесь СТОП → ничего дальше не делаем.
        
        Проверяем:
        ① Стоп-лосс (цена ниже SL)
        ② Максимальная просадка
        ③ Дневной лимит убытков
        ④ Здоровье API
        ⑤ Аномальные движения цены
        ⑥ Smart Pause Engine (8 метрик здоровья)
        """
        checks = []

        # ① Stop Loss
        if config.GRID_LOWER_PRICE > 0:
            sl_price = Decimal(str(config.GRID_LOWER_PRICE)) * Decimal(
                str(1 - config.STOP_LOSS_PCT / 100)
            )
            if price < sl_price:
                return False, f"🛑 STOP LOSS: {price} < {sl_price}"

        # ② Max Drawdown
        net_profit = self.db.get_total_profit()
        if net_profit < -Decimal(str(config.MAX_DRAWDOWN_USDT)):
            return False, f"🛑 MAX DRAWDOWN: {net_profit} USDT"

        # ③ Дневной лимит
        today_trades = self.db.get_trades_today()
        daily_pnl = sum(
            Decimal(t.get("profit_usdt", 0)) for t in today_trades
        )
        if daily_pnl < -Decimal(str(config.DAILY_LOSS_LIMIT_USDT)):
            return False, f"🛑 DAILY LIMIT: {daily_pnl} USDT"

        # ④ Smart Pause Engine
        if self.pause_engine:
            pause = self._get_cached(
                "smart_pause",
                lambda: self.pause_engine.evaluate(),
                ttl_sec=10,
            )
            if pause and hasattr(pause, 'level') and pause.level == PauseLevel.EMERGENCY_STOP:
                return False, f"🛑 EMERGENCY PAUSE: {pause.reasons[0] if pause.reasons else '?'}"

        # ⑤ Аномалии
        if self.anomaly:
            anomaly_check = self._get_cached(
                "anomaly",
                lambda: self.anomaly.should_pause(),
                ttl_sec=5,
            )
            if isinstance(anomaly_check, tuple):
                should_pause, reason = anomaly_check
            else:
                should_pause, reason = False, ""

            if should_pause:
                return False, f"⚠️ ANOMALY: {reason}"

        return True, "✅ Survival OK"

    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 2: MARKET READING
    #  "Что происходит на рынке прямо сейчас?"
    # ═══════════════════════════════════════════════════

    def _level2_read_market(self) -> MarketSnapshot:
        """
        ВТОРОЙ УРОВЕНЬ — читаем рынок.
        Собираем данные из ВСЕХ источников в единый снимок.
        
        Важно: каждый источник опрашивается с РАЗНОЙ частотой.
        Быстрые данные (цена, стакан) → каждые 2-5 сек.
        Медленные данные (ML, on-chain) → раз в 5-60 мин.
        """
        now = datetime.utcnow()

        # ① Текущая цена и стакан (всегда свежие)
        price = self.client.get_price()
        spread_info = self._get_cached(
            "spread",
            lambda: self.spread_analyzer.get_current_spread(),
            ttl_sec=3,
        )

        bid = spread_info.get("bid", price)
        ask = spread_info.get("ask", price)
        spread_pct = float(spread_info.get("spread_pct", Decimal("0")))

        # ② Технические индикаторы (каждые 30 сек)
        klines = self._get_cached(
            "klines_15m",
            lambda: self._fetch_klines("15", 100),
            ttl_sec=30,
        )

        rsi = 50.0
        ema_fast = float(price)
        ema_slow = float(price)
        atr = 0.0
        volatility = 0.0
        hurst = 0.5

        if klines and self.classic:
            closes = [Decimal(k[4]) for k in klines]
            highs = [Decimal(k[2]) for k in klines]
            lows = [Decimal(k[3]) for k in klines]

            analysis = self.classic.analyze(
                prices=closes, highs=highs, lows=lows,
            )
            rsi = float(analysis.rsi)
            ema_fast = float(analysis.ema_fast)
            ema_slow = float(analysis.ema_slow)
            atr = float(analysis.atr)
            volatility = float(analysis.volatility_pct)

        # ③ ML режим (каждые 30 сек)
        if self.ml_regime:
            ml_result = self._get_cached(
                "ml_regime",
                lambda: self._predict_ml_regime(),
                ttl_sec=30,
            )
        if not ml_result:
            ml_result = {"regime": "unknown", "confidence": 0.0}
            
        ml_regime = ml_result.get("regime", "unknown")
        ml_confidence = ml_result.get("confidence", 0.0)

        # ④ Multi-Timeframe (каждые 60 сек)
        if self.mtf:
            mtf_result = self._get_cached(
                "mtf",
                lambda: self.mtf.full_analysis(),
                ttl_sec=60,
            )
            mtf_regime = mtf_result.overall_regime if mtf_result else "unknown"
        else:
            mtf_regime = "unknown"
        trend_strength = 0.0

        # ⑤ Funding Rate (каждые 30 сек)
        if self.timing:
            funding = self._get_cached(
                "funding",
                lambda: self.timing._analyze_funding_rate(),
                ttl_sec=30,
            )
            funding_rate = funding.get("funding_rate", 0.0)
        else:
            funding_rate = 0.0

        # ⑥ Order Book Imbalance (каждые 5 сек)
        if self.timing:
            ob_result = self._get_cached(
                "orderbook",
                lambda: self.timing._analyze_orderbook(),
                ttl_sec=5,
            )
            obi = ob_result.get("obi", 0.5) if ob_result else 0.5
        else:
            obi = 0.5

        # ⑦ Spoofing (каждые 10 сек)
        if self.spoof_detector:
            self.spoof_detector.take_snapshot()
            spoof = self._get_cached(
                "spoof",
                lambda: self.spoof_detector.analyze(),
                ttl_sec=10,
            )
            spoof_score = spoof.spoof_score if spoof else 0.0
        else:
            spoof_score = 0.0

        # ⑧ Adverse Selection (каждые 30 сек)
        if self.adverse:
            adverse = self._get_cached(
                "adverse",
                lambda: self.adverse.analyze(),
                ttl_sec=30,
            )
            toxicity = adverse.toxicity_score if adverse else 0.0
        else:
            toxicity = 0.0

        # ⑨ Sentiment (каждые 5 мин)
        if self.sentiment:
            sentiment = self._get_cached(
                "sentiment",
                lambda: self.sentiment.get_sentiment(),
                ttl_sec=300,
            )
            fear_greed = sentiment.fear_greed_value if sentiment else 50
        else:
            fear_greed = 50

        # ⑩ On-Chain (каждые 10 мин)
        if self.onchain:
            onchain = self._get_cached(
                "onchain",
                lambda: self.onchain.get_onchain_data(),
                ttl_sec=600,
            )
            onchain_signal = onchain.overall_signal if onchain else 0.0
            whale_alert = (
                bool(onchain.alerts) if onchain else False
            )
        else:
            onchain_signal = 0.0
            whale_alert = False

        # ⑪ Timing Score (каждые 10 сек)
        if self.timing:
            timing = self._get_cached(
                "timing_score",
                lambda: self.timing.calculate_timing_score(),
                ttl_sec=10,
            )
            timing_score = timing.score if timing else 50
        else:
            timing_score = 50

        # ⑫ Avellaneda-Stoikov Quotes (обновляем каждые 5 сек)
        if self.as_model:
            # q (inventory) берем из модели AS
            inv = float(self.as_model.current_inventory)
            self._get_cached(
                "as_quotes",
                lambda: self.as_model.calculate_quotes(
                    mid_price=float(price),
                    volatility=volatility / 100, # Переводим из % в десятичный вид
                    inventory=inv,
                    time_left=1.0 # Упрощенно 1.0 для вечной сетки
                ),
                ttl_sec=5,
            )

        snapshot = MarketSnapshot(
            timestamp=now,
            price=price,
            bid=Decimal(str(bid)),
            ask=Decimal(str(ask)),
            spread_pct=spread_pct,
            volume_24h=0,
            rsi=rsi,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            atr=atr,
            volatility_pct=volatility,
            hurst=hurst,
            funding_rate=funding_rate,
            ml_regime=ml_regime,
            ml_confidence=ml_confidence,
            mtf_regime=mtf_regime,
            trend_strength=trend_strength,
            fear_greed=fear_greed,
            onchain_signal=onchain_signal,
            whale_alert=whale_alert,
            obi=obi,
            spoof_score=spoof_score,
            toxicity_score=toxicity,
            timing_score=timing_score,
        )

        self.last_snapshot = snapshot
        return snapshot

    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 3: MODE SELECTION
    #  "Какая стратегия оптимальна СЕЙЧАС?"
    # ═══════════════════════════════════════════════════

    def _level3_select_mode(
        self, snap: MarketSnapshot,
    ) -> TradingMode:
        """
        ТРЕТИЙ УРОВЕНЬ — выбор режима торговли.
        Выбирает режим с гистерезисом (не прыгаем туда-сюда).
        """
        votes = {mode: 0 for mode in TradingMode}
        reasons = []

        # ── Голос 1: ML Режим ─────────────────────────
        if snap.ml_confidence > 0.6:
            if snap.ml_regime in ("STRONG_DOWNTREND", "DOWNTREND"):
                votes[TradingMode.DCA_ACCUMULATE] += 3
                reasons.append(f"ML: {snap.ml_regime}")
            elif snap.ml_regime == "STRONG_UPTREND":
                votes[TradingMode.SELL_ONLY] += 3
                reasons.append(f"ML: {snap.ml_regime}")
            elif snap.ml_regime == "SIDEWAYS":
                votes[TradingMode.GRID_STANDARD] += 3
                reasons.append("ML: боковик")

        # ── Голос 2: MTF ──────────────────────────────
        if hasattr(snap, 'mtf_regime') and snap.mtf_regime:
            if "downtrend" in str(snap.mtf_regime).lower():
                votes[TradingMode.DCA_ACCUMULATE] += 2
            elif "sideways" in str(snap.mtf_regime).lower():
                votes[TradingMode.GRID_STANDARD] += 2

        # ── Голос 3: RSI + Тренд ──────────────────────
        if snap.rsi < 30:
            votes[TradingMode.DCA_ACCUMULATE] += 2
            reasons.append(f"RSI={snap.rsi:.0f} перепродано")
        elif snap.rsi > 70:
            votes[TradingMode.SELL_ONLY] += 2

        # ── Голос 4: Hurst ────────────────────────────
        if snap.hurst < 0.4:
            votes[TradingMode.GRID_STANDARD] += 2
        elif snap.hurst > 0.65:
            votes[TradingMode.GRID_STANDARD] -= 1

        # ── Голос 5: Infinity Grid ────────────────────
        # ТОЛЬКО если цена СИЛЬНО за пределами сетки
        if self.grid_levels:
            prices = [float(l.price) for l in self.grid_levels]
            if prices:
                upper = max(prices)
                lower = min(prices)
                price = float(snap.price)
                grid_range = upper - lower

                if grid_range > 0:
                    position = (price - lower) / grid_range * 100

                    # Только если цена ВЫШЕ верхней границы
                    # (а не просто "близко")
                    if price > upper * 1.02:   # >2% выше верхней
                        votes[TradingMode.GRID_INFINITY] += 3
                        reasons.append(
                            f"Цена {price:.0f} выше сетки "
                            f"({upper:.0f})"
                        )
                    elif position > 95:
                        votes[TradingMode.GRID_INFINITY] += 1

        # ── Голос 6: Арбитраж ─────────────────────────
        if hasattr(self, 'arbitrage') and self.arbitrage and hasattr(self.arbitrage, 'is_available'):
            try:
                if self.arbitrage.is_available():
                    arb_opps = self._get_cached(
                        "arb_check",
                        lambda: self.arbitrage.find_opportunities(),
                        ttl_sec=30,
                    )
                    if arb_opps and any(
                        o.is_actionable for o in arb_opps
                    ):
                        votes[TradingMode.ARBITRAGE] += 2
            except Exception:
                pass

        # ── Финальное решение ─────────────────────────
        best_mode = max(votes, key=lambda m: votes[m])
        best_votes = votes[best_mode]

        # Если нет явного победителя → дефолт GRID
        if best_votes <= 1:
            best_mode = TradingMode.GRID_STANDARD

        # ══════════════════════════════════════════════
        #  ГИСТЕРЕЗИС: не переключаем режим слишком часто
        # ══════════════════════════════════════════════
        if best_mode != self.state.current_mode:
            time_in_current = (
                datetime.utcnow() - self.state.last_mode_change
            ).total_seconds()

            # Минимум 5 минут в текущем режиме
            # (кроме EMERGENCY — переключаемся сразу)
            min_mode_duration = 300  # 5 минут

            if (time_in_current < min_mode_duration
                    and best_mode != TradingMode.EMERGENCY_STOP):
                # Слишком рано для переключения
                return self.state.current_mode

            # Нужно минимум 3 голоса для переключения
            # (избегаем случайных переключений)
            if best_votes < 3 and best_mode != TradingMode.EMERGENCY_STOP:
                return self.state.current_mode

            # Переключаемся
            log.info(
                f"🔄 РЕЖИМ: {self.state.current_mode.value} → "
                f"{best_mode.value} "
                f"(голоса: {best_votes}, "
                f"в текущем: {time_in_current:.0f}s) | "
                f"{', '.join(reasons[:3])}"
            )
            self.state.current_mode = best_mode
            self.state.last_mode_change = datetime.utcnow()
            self.state.mode_history.append(
                (datetime.utcnow(), best_mode)
            )
            self.stats["mode_switches"] += 1

            if self.notifier:
                self.notifier.send(
                    f"🔄 Режим: <b>{best_mode.value}</b>\n"
                    f"{', '.join(reasons[:2])}"
                )

        return self.state.current_mode

    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 4: TIMING GATE
    #  "Сейчас хороший момент для действия?"
    # ═══════════════════════════════════════════════════

    def _level4_timing_gate(
        self,
        snap: MarketSnapshot,
        mode: TradingMode,
    ) -> Tuple[bool, bool, str]:
        """
        ЧЕТВЁРТЫЙ УРОВЕНЬ — фильтр времени.
        
        Возвращает: (can_buy, can_sell, reason)
        
        Логика:
        — Smart Pause говорит насколько здоров рынок
        — Timing Score говорит насколько сейчас хороший момент
        — Liquidation Heatmap говорит где опасные зоны
        — Spoofing говорит реален ли стакан
        — Adverse Selection говорит не токсичен ли поток
        """
        can_buy = True
        can_sell = True
        reasons = []

        # ① Smart Pause (уже рассчитан в survival)
        pause = self._get_cached("smart_pause", None, ttl_sec=10)
        if pause:
            if pause.level == PauseLevel.HARD_PAUSE:
                can_buy = False
                can_sell = False
                reasons.append(f"Hard pause (health={pause.overall_health:.2f})")
            elif pause.level == PauseLevel.SOFT_PAUSE:
                # Soft pause: торгуем, но меньше (через qty_multiplier)
                reasons.append(f"Soft pause: осторожно")

        # ② Timing Score
        if snap.timing_score < 20:
            can_buy = False
            can_sell = False
            reasons.append(f"Timing={snap.timing_score}/100: плохой момент")
        elif snap.timing_score < 40:
            # Низкий скор → только по направлению тренда
            if snap.ml_regime in ("UPTREND", "STRONG_UPTREND"):
                can_buy = False
                reasons.append(f"Timing={snap.timing_score}: тренд вверх")
            elif snap.ml_regime in ("DOWNTREND", "STRONG_DOWNTREND"):
                can_sell = False

        # ③ Спуфинг
        if snap.spoof_score > 0.7:
            can_buy = False
            can_sell = False
            reasons.append(f"Spoofing={snap.spoof_score:.2f}: стакан нечестный")
        elif snap.spoof_score > 0.4:
            reasons.append(f"Осторожно: спуфинг {snap.spoof_score:.2f}")

        # ④ Токсичный поток
        if snap.toxicity_score > 0.7:
            # Токсичный поток → расширяем только спред, не блокируем
            reasons.append(
                f"Токсичный поток={snap.toxicity_score:.2f}: расширяем спред"
            )

        # ⑤ Liquidation Heatmap
        liq = self._get_cached(
            "liquidation",
            lambda: self.liq_heatmap.analyze(float(snap.price)),
            ttl_sec=300,
        )
        if liq and liq.grid_adjustment.get("risk_level") == "elevated":
            reasons.append("⚠️ Ликвидационные зоны рядом")
            # Не блокируем, но предупреждаем

        # ⑥ Whale Alert
        if snap.whale_alert:
            can_buy = False
            reasons.append("🐋 Кит переводит на биржу: не покупаем")

        # ⑦ Funding Rate экстремальный
        if snap.funding_rate > 0.001:
            can_buy = False
            reasons.append(f"Funding={snap.funding_rate:.4%}: не покупаем на хаях")
        elif snap.funding_rate < -0.001:
            can_sell = False
            reasons.append(f"Funding={snap.funding_rate:.4%}: не продаём на лоях")

        reason_str = " | ".join(reasons) if reasons else "Timing OK"
        return can_buy, can_sell, reason_str

    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 5: ORDER DECISION
    #  "Какой конкретный ордер поставить?"
    # ═══════════════════════════════════════════════════

    def _level5_order_decision(
        self,
        snap: MarketSnapshot,
        mode: TradingMode,
        can_buy: bool,
        can_sell: bool,
        level_index: int,
        order_price: Decimal,
        side: str,
    ) -> Tuple[bool, str]:
        """
        ПЯТЫЙ УРОВЕНЬ — решение по конкретному ордеру.
        
        Собирает голоса от Smart Entry индикаторов
        и принимает финальное решение: ставить или нет.
        """
        if side == "Buy" and not can_buy:
            return False, "Глобальный запрет на BUY"
        if side == "Sell" and not can_sell:
            return False, "Глобальный запрет на SELL"

        # Smart Entry анализ
        klines_5m = self._get_cached(
            "klines_5m",
            lambda: self._fetch_klines("5", 60),
            ttl_sec=15,
        )

        if klines_5m and self.smart_entry:
            klines_5m_reversed = list(reversed(klines_5m))
            closes = np.array([float(k[4]) for k in klines_5m_reversed])
            highs = np.array([float(k[2]) for k in klines_5m_reversed])
            lows = np.array([float(k[3]) for k in klines_5m_reversed])
            volumes = np.array([float(k[5]) for k in klines_5m_reversed])

            if side == "Buy":
                entry_signal = self.smart_entry.analyze_buy_entry(
                    closes=closes,
                    highs=highs,
                    lows=lows,
                    volumes=volumes,
                    target_price=float(order_price),
                )
            else:
                entry_signal = self.smart_entry.analyze_sell_entry(
                    closes=closes,
                    highs=highs,
                    lows=lows,
                    volumes=volumes,
                    target_price=float(order_price),
                )

            # Если сигнал очень против → не ставим
            if entry_signal and not entry_signal.should_enter and entry_signal.score < -0.4:
                return False, (
                    f"Smart Entry отклонил: score={entry_signal.score:.2f}"
                )

        # Avellaneda-Stoikov: проверяем reservation price
        if self.as_model and self.as_model.last_quotes:
            quotes = self.as_model.last_quotes
            if side == "Buy":
                if order_price > quotes.reservation_price * Decimal("1.005"):
                    return False, (
                        f"A-S: BUY выше reservation price "
                        f"({float(quotes.reservation_price):.0f})"
                    )
            else:
                if order_price < quotes.reservation_price * Decimal("0.995"):
                    return False, (
                        f"A-S: SELL ниже reservation price "
                        f"({float(quotes.reservation_price):.0f})"
                    )

        # Volume Profile: не ставить в LVN зоны
        vp = self._get_cached("volume_profile", None, ttl_sec=3600)
        if vp:
            for lvn_low, lvn_high in vp.lvn_zones:
                if lvn_low <= float(order_price) <= lvn_high:
                    return False, (
                        f"VPVR: уровень в LVN зоне "
                        f"({lvn_low:.0f}-{lvn_high:.0f})"
                    )

        return True, "✅ Order Decision OK"

    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 6: SIZE CALCULATION
    #  "Сколько именно ставить?"
    # ═══════════════════════════════════════════════════

    def _level6_calculate_size(
        self,
        snap: MarketSnapshot,
        mode: TradingMode,
        level_index: int,
        price: Decimal,
        side: str,
        next_level_price: Decimal,
    ) -> Decimal:
        """
        ШЕСТОЙ УРОВЕНЬ — точный расчёт объёма.
        """
        if self.sizer:
            base_qty_res = self.sizer.calculate_order_size(
                level_index=level_index,
                price=price,
                side=side,
                next_level_price=next_level_price,
                active_orders=self.active_orders,
                timing_score=snap.timing_score,
                pause_qty_mult=self._get_pause_qty_mult(),
                ml_qty_mult=self._get_ml_qty_mult(snap),
            )
            base_qty = base_qty_res.adjusted_qty
        else:
            base_qty = Decimal(str(config.ORDER_QTY_USDT)) / price

        mode_multipliers = {
            TradingMode.GRID_STANDARD: 1.0,
            TradingMode.GRID_INFINITY: 1.0,
            TradingMode.DCA_ACCUMULATE: 1.3,
            TradingMode.SELL_ONLY: 1.2,
            TradingMode.ARBITRAGE: 0.8,
            TradingMode.EMERGENCY_STOP: 0.0,
        }
        mode_mult = Decimal(str(mode_multipliers.get(mode, 1.0)))
        vpvr_mult = self._get_vpvr_qty_mult(price)

        if snap.toxicity_score > 0.5:
            toxicity_mult = Decimal(str(1 - (snap.toxicity_score - 0.5) * 0.4))
        else:
            toxicity_mult = Decimal("1")

        as_mult = Decimal("1")
        if self.as_model and self.as_model.last_quotes:
            inv = float(self.as_model.current_inventory)
            if side == "Buy" and inv > 0:
                as_mult = Decimal(str(max(0.5, 1 - inv / 0.1)))
            elif side == "Sell" and inv > 0:
                as_mult = Decimal(str(min(1.5, 1 + inv / 0.1)))

        compound_mult = Decimal("1")
        if self.compounder and hasattr(self.compounder, 'state'):
            try:
                # Ensure initial_capital is not zero to prevent division by zero
                initial_capital = float(self.compounder.state.initial_capital)
                if initial_capital == 0:
                    initial_capital = 1.0 # Fallback to 1 to avoid division by zero
                raw_mult = 1 + float(self.compounder.state.total_compounded) / initial_capital * 0.5
                compound_mult = Decimal(str(raw_mult))
            except (AttributeError, ValueError, TypeError) as e:
                log.warning(f"Error calculating compound_mult: {e}. Using default 1.")
                compound_mult = Decimal("1")
        compound_mult = min(compound_mult, Decimal("2.0"))

        final_qty = (
            base_qty
            * mode_mult
            * vpvr_mult
            * toxicity_mult
            * as_mult
            * compound_mult
        )

        final_qty = max(final_qty, Decimal(str(config.MIN_ORDER_QTY)))
        final_qty = min(final_qty, Decimal(str(config.MAX_ORDER_QTY)))

        return final_qty

    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 7: EXECUTION
    # ═══════════════════════════════════════════════════

    def _level7_execute(
        self,
        side: str,
        qty: Decimal,
        price: Decimal,
        level: Any,
    ) -> Optional[str]:
        """СЕДЬМОЙ УРОВЕНЬ — исполнение."""
        adj_qty, adj_price = self._adjust_precision(qty, price)
        qty_str = str(adj_qty)
        price_str = str(adj_price)

        # Генерируем уникальный order_link_id для отслеживания в WS
        # Формат: SYMBOL-LVL-INDEX-TIMESTAMP
        order_link_id = f"{config.SYMBOL}-LVL-{level.index}-{int(time.time()*1000)}"

        order_id = None
        if self.fee_optimizer:
            order_id = self.fee_optimizer.place_postonly_order(
                side=side, qty=qty_str, price=price_str, order_link_id=order_link_id
            )

        if not order_id:
            order_id = self.client.place_order(
                side=side, qty=qty_str, price=price_str, order_link_id=order_link_id
            )

        if order_id:
            self.active_orders[order_id] = level
            self.db.update_level_order(level.index, side, order_id)
            log.info(f"📋 {side} {qty_str} @ {price_str} | ID: {order_id[:12]}...")

        return order_id

    # ═══════════════════════════════════════════════════
    #  УРОВЕНЬ 8: LEARNING
    # ═══════════════════════════════════════════════════

    def _level8_learn(
        self,
        order_id: str,
        side: str,
        fill_price: float,
        qty: float,
        profit: float,
        level_index: int,
    ):
        """ВОСЬМОЙ УРОВЕНЬ — обучение."""
        if self.sizer:
            self.sizer.record_cycle_result(level_index, profit)

        state = self._get_rl_state()
        if self.rl_optimizer and state is not None and self.rl_optimizer.last_action is not None:
            reward = profit / max(fill_price * qty, 1) * 100
            new_state = self._get_rl_state()
            if new_state is not None:
                self.rl_optimizer.record_result(
                    old_state=state,
                    action=self.rl_optimizer.last_action,
                    reward=reward,
                    new_state=new_state,
                )

        if self.adverse:
            self.adverse.record_fill(
                order_id=order_id,
                side=side,
                fill_price=fill_price,
                price_after_1min=float(self.client.get_price()),
            )

        if self.as_model:
            self.as_model.update_inventory(
                side=side,
                qty=Decimal(str(qty)),
                price=Decimal(str(fill_price)),
            )

        if self.delta_hedge and config.USE_DELTA_NEUTRAL and profit > 0:
            if side == "Buy":
                self.delta_hedge.on_spot_buy(Decimal(str(qty)), Decimal(str(fill_price)))
            else:
                self.delta_hedge.on_spot_sell(Decimal(str(qty)), Decimal(str(fill_price)))

        if self.compounder and profit > 0:
            try:
                self.compounder.add_profit(Decimal(str(profit)))
            except Exception as e:
                log.warning(f"Error adding profit to compounder: {e}")

        if self.ab_tester and self.ab_tester.is_testing:
            variant, _ = self.ab_tester.get_variant_for_trade()
            self.ab_tester.record_trade_result(
                variant_name=variant,
                profit=profit,
                fee=fill_price * qty * float(config.MAKER_FEE_PCT) / 100,
            )

        if side == "Buy" and self.hybrid_dca:
            for level in self.hybrid_dca.dca_levels:
                if level.order_id == order_id:
                    self.hybrid_dca.on_dca_fill(level, Decimal(str(fill_price)))
                    break

    # ═══════════════════════════════════════════════════
    #  ГЛАВНЫЙ ПУБЛИЧНЫЙ МЕТОД
    # ═══════════════════════════════════════════════════

    def decide_and_act(
        self,
        filled_order_id: Optional[str] = None,
        filled_side: Optional[str] = None,
        filled_price: Optional[float] = None,
        filled_qty: Optional[float] = None,
        filled_profit: Optional[float] = None,
        filled_level_index: Optional[int] = None,
    ) -> BrainDecision:
        """ГЛАВНЫЙ МЕТОД."""
        self.stats["decisions_made"] += 1

        if filled_order_id and filled_side and filled_price:
            return self._handle_fill(
                filled_order_id, filled_side,
                filled_price, filled_qty or 0,
                filled_profit or 0,
                filled_level_index or 0,
            )

        return self._periodic_check()

    def _handle_fill(
        self, order_id: str, side: str, fill_price: float,
        qty: float, profit: float, level_index: int,
    ) -> BrainDecision:
        notes = [f"Fill: {side} {qty:.6f} @ {fill_price:.2f}"]

        price = Decimal(str(fill_price))
        alive, survival_msg = self._level1_survival_check(price)
        notes.append(f"L1: {survival_msg}")

        if not alive:
            self._emergency_shutdown(survival_msg)
            return BrainDecision(
                decision_type=DecisionType.CANCEL_ALL,
                trading_mode=TradingMode.EMERGENCY_STOP,
                should_buy=False, should_sell=False,
                qty_multiplier=0, blocked_by=survival_msg, notes=notes,
            )

        snap = self._level2_read_market()
        self._level8_learn(order_id, side, fill_price, qty, profit, level_index)

        mode = self._level3_select_mode(snap)
        notes.append(f"L3: mode={mode.value}")

        can_buy, can_sell, timing_msg = self._level4_timing_gate(snap, mode)
        notes.append(f"L4: {timing_msg}")

        result_side = "Sell" if side == "Buy" else "Buy"
        result_level = self._find_response_level(level_index, result_side)

        placed = False
        if result_level:
            ok, reason = self._level5_order_decision(snap, mode, can_buy, can_sell, result_level.index, result_level.price, result_side)
            notes.append(f"L5: {reason}")

            if ok:
                next_level = self._find_next_level(result_level.index, result_side)
                qty_dec = self._level6_calculate_size(snap, mode, result_level.index, result_level.price, result_side, next_level.price if next_level else result_level.price)
                notes.append(f"L6: qty={float(qty_dec):.6f}")

                new_oid = self._level7_execute(side=result_side, qty=qty_dec, price=result_level.price, level=result_level)
                placed = new_oid is not None
                notes.append(f"L7: {'✅' if placed else '❌'}")
                if placed: self.stats["trades_executed"] += 1

        if self.compounder and getattr(self.compounder, 'should_compound', False):
            self._run_compound()

        dec_type = (DecisionType.PLACE_SELL if result_side == "Sell" else DecisionType.PLACE_BUY) if placed else DecisionType.NO_ACTION
        return BrainDecision(decision_type=dec_type, trading_mode=mode, should_buy=can_buy, should_sell=can_sell, qty_multiplier=self._get_ml_qty_mult(snap), notes=notes, confidence=snap.ml_confidence)

    def _periodic_check(self) -> BrainDecision:
        """Периодическая проверка."""
        notes = []

        # L1: Survival
        try:
            price = self.client.get_price()
        except Exception:
            return BrainDecision(
                decision_type=DecisionType.NO_ACTION,
                trading_mode=self.state.current_mode,
                should_buy=False, should_sell=False,
                qty_multiplier=0,
                blocked_by="API недоступен",
                notes=["L1: API error"],
            )

        alive, msg = self._level1_survival_check(price)
        if not alive:
            self._emergency_shutdown(msg)
            return BrainDecision(
                decision_type=DecisionType.CANCEL_ALL,
                trading_mode=TradingMode.EMERGENCY_STOP,
                should_buy=False, should_sell=False,
                qty_multiplier=0, blocked_by=msg, notes=[msg],
            )

        # L2: Market Reading
        snap = self._level2_read_market()

        # L3: Mode
        mode = self._level3_select_mode(snap)

        # L4: Timing
        can_buy, can_sell, timing_msg = self._level4_timing_gate(
            snap, mode
        )

        # Режимные действия
        self._handle_mode_specific_actions(snap, mode)

        # Ребаланс
        if self._needs_rebalance(snap):
            self._rebalance_grid(snap, mode)
            notes.append("Ребаланс сетки")

        # ═══════════════════════════════════════════════
        # ML и Genetic — только каждый N-й цикл
        # (дополнительная защита помимо кэша)
        # ═══════════════════════════════════════════════
        cycle = self.stats["decisions_made"]

        # ML retrain: проверяем каждые 100 циклов (~5 минут)
        if cycle % 100 == 0:
            self._maybe_retrain_ml()

        # Genetic: проверяем каждые 1000 циклов (~50 минут)
        if cycle % 1000 == 0:
            self._maybe_run_genetic()

        # A/B тест
        if self.ab_tester and cycle % 50 == 0:
            try:
                result = self.ab_tester.check_test_completion()
                if result:
                    changes = self.ab_tester.apply_winner(result)
            except Exception:
                pass

        # Auto-compound: проверяем каждые 500 циклов
        if self.compounder and cycle % 500 == 0:
            try:
                if getattr(self.compounder, 'should_compound', False):
                    self._run_compound()
            except Exception as e:
                log.warning(f"Compound error: {e}")

        # Scanner: проверяем каждые 500 циклов
        if self.scanner and cycle % 500 == 0:
            self._run_scanner()

        # Статистика
        if cycle % 200 == 0:
            self._log_full_stats(snap)

        return BrainDecision(
            decision_type=DecisionType.NO_ACTION,
            trading_mode=mode,
            should_buy=can_buy,
            should_sell=can_sell,
            qty_multiplier=self._get_ml_qty_mult(snap),
            notes=notes,
        )

    def _check_orders_rest(self):
        """
        Проверка ордеров через REST API. 
        Используется как fallback, если WebSocket упал.
        """
        try:
            open_orders = self.client.get_open_orders()
            market_oids = {o['orderId'] for o in open_orders}
            
            # Находим ордера, которые есть у нас в памяти, но пропали с биржи
            missing_oids = [oid for oid in self.active_orders.keys() if oid not in market_oids]
            
            for oid in missing_oids:
                # Проверяем историю, чтобы понять: был он зафиллен или отменен
                history = self.client.get_order_history(limit=10) # Берем последние 10
                for h in history:
                    if h['orderId'] == oid:
                        status = h['orderStatus']
                        if status == "Filled":
                            log.info(f"🔄 Polling Fill detected: {h['side']} @ {h['avgPrice']}")
                            level = self.active_orders.get(oid)
                            self.decide_and_act(
                                filled_order_id=oid,
                                filled_side=h['side'],
                                filled_price=float(h['avgPrice']),
                                filled_qty=float(h['qty']),
                                filled_level_index=level.index if level else 0
                            )
                        elif status in ("Cancelled", "Rejected"):
                            log.warning(f"🔄 Polling Cancel detected: {oid}")
                            if oid in self.active_orders: del self.active_orders[oid]
                        break
        except Exception as e:
            log.error(f"Error in _check_orders_rest: {e}")

    # ── Вспомогательные методы ──

    def _adjust_precision(self, qty: Decimal, price: Decimal) -> Tuple[Decimal, Decimal]:
        """Корректировка объема и цены под правила биржи (Lot Size/Tick Size)."""
        if not self._instrument_info:
            self._instrument_info = self.client.get_instrument_info(self.current_symbol)
            
        info = self._instrument_info
        min_qty = info["min_qty"]
        qty_step = info["qty_step"]
        tick_size = info["tick_size"]
        
        # 1. Округляем цену до шага
        adj_price = (price / tick_size).quantize(Decimal('1'), rounding="ROUND_HALF_UP") * tick_size
        
        # 2. Округляем объем до шага
        adj_qty = (qty / qty_step).quantize(Decimal('1'), rounding="ROUND_DOWN") * qty_step
        
        # Если после округления вниз получили 0, но исходный qty > 0 -> берем минимальный шаг
        if adj_qty == 0 and qty > 0:
            adj_qty = qty_step
            
        # 3. Проверка на минимальный объем
        if adj_qty < min_qty:
            log.warning(f"⚠️ Qty {adj_qty} < Min Qty {min_qty}. Поднимаем до минимального.")
            adj_qty = min_qty
            
        return adj_qty, adj_price

    def _get_cached(self, key, factory, ttl_sec=30):
        now = datetime.utcnow()
        last = self._cache_times.get(key)
        if last and (now - last).total_seconds() < ttl_sec: return self._cache.get(key)
        if factory is None: return self._cache.get(key)
        try:
            res = factory()
            self._cache[key], self._cache_times[key] = res, now
            return res
        except: return self._cache.get(key)

    def _fetch_klines(self, interval, limit):
        klines = self.client.get_klines(interval=interval, limit=limit)
        if klines:
            klines.reverse()
            # Filter valid candles (must have at least 6 elements [time, o, h, l, c, v])
            klines = [k for k in klines if isinstance(k, (list, tuple)) and len(k) >= 6]
        return klines or []

    def _predict_ml_regime(self):
        klines = self._fetch_klines("15", 200)
        if len(klines) < 50: return {"regime": "unknown", "confidence": 0}
        opens = np.array([float(k[1]) for k in klines])
        highs = np.array([float(k[2]) for k in klines])
        lows = np.array([float(k[3]) for k in klines])
        closes = np.array([float(k[4]) for k in klines])
        volumes = np.array([float(k[5]) for k in klines])
        return self.ml_regime.predict(opens, highs, lows, closes, volumes)

    def _get_pause_qty_mult(self):
        p = self._get_cached("smart_pause", None, ttl_sec=10)
        return p.qty_multiplier if p else 1.0

    def _get_ml_qty_mult(self, snap):
        ml = self._get_cached("ml_regime", None, ttl_sec=30)
        return ml.get("qty_multiplier", 1.0) if ml else 1.0

    def _get_vpvr_qty_mult(self, price):
        vp = self._get_cached("volume_profile", None, ttl_sec=3600)
        if not vp: return Decimal("1.0")
        pf = float(price)
        for n in vp.nodes:
            if abs(n.price - pf) / pf < 0.002:
                if n.node_type == "poc": return Decimal("1.5")
                if n.node_type == "hvn": return Decimal("1.3")
                if n.node_type == "lvn": return Decimal("0.5")
        return Decimal("1.0")

    def _get_rl_state(self):
        try:
            klines = self._fetch_klines("15", 100)
            if len(klines) < 50: return None
            prices = np.array([float(k[4]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])
            from ml.reinforcement import StateEncoder
            return StateEncoder.encode(prices, volumes, self.rl_optimizer.current_params, float(self.db.get_total_profit()), float(self.client.get_balance()))
        except: return None

    def _find_response_level(self, level_index, side):
        if not self.grid_levels: return None
        target = level_index + 1 if side == "Sell" else level_index - 1
        for l in self.grid_levels:
            if l.index == target: return l
        return None

    def _find_next_level(self, index, side):
        target = index + 1 if side == "Sell" else index - 1
        for l in self.grid_levels:
            if l.index == target: return l
        return None

    def _needs_rebalance(self, snap):
        if not self.grid_levels: return True
        lower = min(float(l.price) for l in self.grid_levels)
        upper = max(float(l.price) for l in self.grid_levels)
        price = float(snap.price)
        if upper <= lower: return False
        pos = (price - lower) / (upper - lower) * 100
        return pos > (100 - config.REBALANCE_THRESHOLD_PCT) or pos < config.REBALANCE_THRESHOLD_PCT

    def _rebalance_grid(self, snap, mode):
        log.info(f"🔄 Ребаланс сетки @ {snap.price}")
        self.client.cancel_all()
        self.active_orders.clear()
        self._place_initial_grid(snap, mode)

    def _place_initial_grid(self, snap, mode):
        price = snap.price
        klines = self._fetch_klines("15", 200)
        if klines and self.rl_optimizer:
            ps = np.array([float(k[4]) for k in klines])
            vs = np.array([float(k[5]) for k in klines])
            rl_p = self.rl_optimizer.get_optimal_params(ps, vs, float(self.db.get_total_profit()), float(self.client.get_balance()))
        else:
            levels_count = getattr(config, "GRID_LEVELS", 20)
            rl_p = GridParams(grid_levels=levels_count, grid_range_pct=15.0, profit_target_pct=1.0)

        half = price * Decimal(str(rl_p.grid_range_pct / 100 / 2))
        lower, upper = price - half, price + half
        
        # Генерация уровней
        if self.vpvr:
            vp_g = self.vpvr.generate_weighted_grid(float(lower), float(upper), rl_p.grid_levels)
        else:
            # Простой равномерный грид — создаем список FLOATS
            vp_g = list(np.linspace(float(lower), float(upper), rl_p.grid_levels))

        if self.liq_heatmap:
            filtered = self.liq_heatmap.filter_grid_levels(vp_g, float(price))
        else:
            filtered = vp_g

        # Проставляем индексы и конвертируем в BrainLevel
        self.grid_levels = []
        base_qty = Decimal(str(config.BASE_ORDER_QTY))
        
        # Если есть as_model, она уже вернула список объектов (GridLevel)
        # Если нет - у нас список floats (filtered)
        if self.as_model:
            klines_15m = self._fetch_klines("15", 100)
            p_dec = [Decimal(k[4]) for k in klines_15m] if klines_15m else [price]
            as_levels = self.as_model.skew_grid_levels(filtered, p_dec, price)
            for sl in as_levels:
                self.grid_levels.append(BrainLevel(
                    index=sl.index,
                    price=Decimal(str(sl.price)),
                    side=sl.side,
                    recommended_qty=sl.recommended_qty,
                    skewed_price=sl.skewed_price
                ))
        else:
            for i, p in enumerate(sorted(filtered)):
                p_dec = Decimal(str(p))
                self.grid_levels.append(BrainLevel(
                    index=i,
                    price=p_dec,
                    side="Buy" if p_dec < price else "Sell",
                    recommended_qty=base_qty / p_dec if p_dec > 0 else Decimal("0"),
                    skewed_price=p_dec
                ))

        # Сохраняем границы в конфиг для SL
        lower_p = min(float(l.price) for l in self.grid_levels) if self.grid_levels else 0.0
        upper_p = max(float(l.price) for l in self.grid_levels) if self.grid_levels else 0.0
        config.GRID_LOWER_PRICE = lower_p
        config.GRID_UPPER_PRICE = upper_p
        
        # Определяем режим позиции для учета Hedge Mode
        pos_mode = self.client.get_position_mode()
        
        orders = []
        for bl in self.grid_levels:
            adj_qty, adj_price = self._adjust_precision(bl.recommended_qty, bl.price)
            side = bl.side
            
            # В Hedge Mode: 1=Buy, 2=Sell. В One-Way: 0.
            p_idx = 0
            if pos_mode == 3: # My code for Hedge
                p_idx = 1 if side == "Buy" else 2
                
            orders.append({
                "side": side,
                "qty": str(adj_qty),
                "price": str(adj_price),
                "positionIdx": p_idx
            })
        if orders:
            if self.batch_manager:
                ids, errs = self.batch_manager.place_grid_batch(orders, use_postonly=True)
                log.info(f"📋 Начальная сетка: {len(ids)} ордеров | Ошибок: {len(errs)}")
            else:
                # Поодиночке если нет batch manager
                for o in orders:
                    self.client.place_order(side=o["side"], qty=o["qty"], price=o["price"])

    def _handle_mode_specific_actions(self, snap, mode):
        if mode == TradingMode.DCA_ACCUMULATE and self.hybrid_dca:
            if len(self.hybrid_dca.dca_levels) == 0 and float(self.hybrid_dca.dca_accumulated_qty) == 0:
                self.client.cancel_all()
                self.active_orders.clear()
                self.hybrid_dca.activate_dca_mode(snap.price)
        elif mode == TradingMode.GRID_STANDARD and self.hybrid_dca:
            if float(self.hybrid_dca.dca_accumulated_qty) > 0:
                self.hybrid_dca.switch_dca_to_grid()
        elif mode == TradingMode.ARBITRAGE and self.arbitrage:
            opps = self.arbitrage.find_opportunities()
            for o in opps:
                if o.is_actionable: self.arbitrage.execute_arbitrage(o)

        if self.delta_hedge and config.USE_DELTA_NEUTRAL:
            s = self.delta_hedge.get_status()
            if s.get("rebalance_needed"): self.delta_hedge.rebalance()

    def _run_compound(self):
        if not self.compounder: return
        try:
            res = self.compounder.compound(Decimal(str(config.BASE_ORDER_QTY)), config.GRID_LEVELS)
            if res.get("compounded"):
                config.BASE_ORDER_QTY, config.GRID_LEVELS = float(res["new_qty"]), res["new_levels"]
                self.notifier.send(f"💰 Авто-компаундинг #{res['compound_count']}\nРеинвестировано: {res['profit_reinvested']:.4f} USDT")
        except Exception as e:
            log.error(f"Error during _run_compound: {e}")

    def _maybe_retrain_ml(self):
        """Переобучаем ML если пришло время."""
        # Модуль не загружен → выходим
        if not self.ml_regime:
            return

        # Проверяем кэш: не переобучали ли недавно?
        last = self._cache_times.get("ml_retrain")
        if last:
            elapsed = (datetime.utcnow() - last).total_seconds()
            if elapsed < 21600:  # 6 часов = 21600 секунд
                return

        # Пробуем переобучить
        try:
            # Проверяем есть ли метод train
            if not hasattr(self.ml_regime, 'train'):
                self._cache_times["ml_retrain"] = datetime.utcnow()
                return

            klines = self._fetch_klines("15", 1000)
            if not klines or len(klines) < 200:
                # Мало данных — попробуем через час
                self._cache_times["ml_retrain"] = (
                    datetime.utcnow() - timedelta(hours=5)
                )
                return

            import numpy as np
            opens = np.array([float(k[1]) for k in klines])
            highs = np.array([float(k[2]) for k in klines])
            lows = np.array([float(k[3]) for k in klines])
            closes = np.array([float(k[4]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])

            result = self.ml_regime.train(
                opens, highs, lows, closes, volumes
            )

            # Ставим время ПОСЛЕ успешного обучения
            self._cache_times["ml_retrain"] = datetime.utcnow()

            if result and isinstance(result, dict):
                acc = result.get("accuracy", "?")
                log.info(f"🧠 ML переобучена: accuracy={acc}")
            else:
                log.info("🧠 ML retrain завершён (без метрик)")

        except Exception as e:
            # При ЛЮБОЙ ошибке — ставим кэш чтобы не спамить
            self._cache_times["ml_retrain"] = datetime.utcnow()
            log.warning(f"⚠️ ML retrain: {e}")

    def _maybe_run_genetic(self):
        """Генетическая оптимизация раз в сутки."""
        # Модуль не загружен → выходим
        if not self.genetic:
            return

        # Проверяем кэш: не запускали ли недавно?
        last = self._cache_times.get("genetic_run")
        if last:
            elapsed = (datetime.utcnow() - last).total_seconds()
            if elapsed < 86400:  # 24 часа = 86400 секунд
                return

        # Ставим кэш СРАЗУ (чтобы не запускать повторно при ошибке)
        self._cache_times["genetic_run"] = datetime.utcnow()

        try:
            # Проверяем есть ли метод evolve
            if not hasattr(self.genetic, 'evolve'):
                return

            klines = self._fetch_klines("5", 1000)
            if not klines or len(klines) < 200:
                return

            import numpy as np
            prices = np.array([float(k[4]) for k in klines])
            volumes = np.array([float(k[5]) for k in klines])

            log.info("🧬 Генетическая оптимизация...")
            best = self.genetic.evolve(prices, volumes, generations=50)

            # apply_best_genome может вернуть dict, bool, или None
            if hasattr(self.genetic, 'apply_best_genome'):
                changes = self.genetic.apply_best_genome()

                # Проверяем тип перед len()
                if isinstance(changes, dict) and changes:
                    log.info(
                        f"🧬 Применено {len(changes)} изменений"
                    )
                elif changes:
                    log.info("🧬 Параметры обновлены")
                else:
                    log.info("🧬 Без изменений")

        except Exception as e:
            log.warning(f"⚠️ Genetic: {e}")

    def _emergency_shutdown(self, reason):
        log.critical(f"🛑 EMERGENCY SHUTDOWN: {reason}")
        self.client.cancel_all()
        self.active_orders.clear()
        self.notifier.send_alert(f"🛑 EMERGENCY SHUTDOWN\n{reason}")

    def _log_full_stats(self, snap):
        projection_info = ""
        if self.compounder:
            try:
                if hasattr(self.compounder, 'get_projection'):
                    prj = self.compounder.get_projection(2.0, 12)
                    if prj and 'total_roi_pct' in prj:
                        projection_info = f" | Compound ROI: {prj['total_roi_pct']:.2f}%"
            except Exception as e:
                log.warning(f"Error getting compounder projection: {e}")

        total_profit = float(self.db.get_total_profit()) if self.db else 0.0
        
        log.info("═"*60)
        log.info(f"🧠 MASTER BRAIN — Режим: {self.state.current_mode.value} | Цена: {snap.price}")
        log.info(f"   Net P&L: {total_profit:.4f}{projection_info}")
        log.info("═"*60)
    def _is_interval_passed(self, key: str) -> bool:
        """Проверяет, прошло ли достаточно времени с последнего обновления."""
        now = datetime.utcnow()
        last = self._last_updates.get(key)
        interval = self.UPDATE_INTERVALS.get(key, 0)
        
        if last is None or (now - last).total_seconds() >= interval:
            self._last_updates[key] = now
            return True
        return False

    def _run_scanner(self):
        """Периодическое сканирование рынка на наличие лучших пар."""
        if not self.scanner: return
        if not self._is_interval_passed("scanner"): return
        
        log.info("🔍 Scanner: Поиск лучшего инструмента...")
        best = self.scanner.scan()
        if not best: return
        
        if best.symbol != self.current_symbol and best.score > 70:
            # Проверяем наличие активной позиции ПЕРЕД переключением
            pos = self.client.get_position(symbol=self.current_symbol)
            has_pos = any(float(p.get('size', 0)) != 0 for p in pos)
            
            if has_pos:
                log.warning(f"⚠️ Scanner: Найдена лучшая пара {best.symbol}, но есть открытая позиция по {self.current_symbol}. Пропуск.")
                return

            log.info(f"💎 Scanner: Найдена лучшая пара: {best.symbol} (Score: {best.score:.1f})")
            self._switch_symbol(best.symbol)

    def _switch_symbol(self, new_symbol: str):
        """Логика переключения на новый торговый инструмент."""
        log.info(f"🔄 Switching symbol: {self.current_symbol} -> {new_symbol}")
        
        # 0. Сбрасываем лимиты в конфиге, чтобы не сработал Stop Loss прошлого символа
        config.GRID_LOWER_PRICE = 0.0
        config.GRID_UPPER_PRICE = 0.0
        
        # 1. Отменяем всё на старом символе
        self.client.cancel_all()
        import time
        time.sleep(0.5) # Даем бирже "выдохнуть" перед новой сеткой
        
        # 2. Обновляем состояние
        self.current_symbol = new_symbol
        self.client.symbol = new_symbol
        self.grid_levels = []
        self.db.clear_active_orders() # Очистка БД от старых ордеров
        
        # 2.1 Устанавливаем плечо для нового символа
        self.client.set_leverage(symbol=new_symbol, leverage=getattr(config, 'LEVERAGE', 10))
        
        # 3. WS Перезапускается автоматически при смене символа в config.SYMBOL
        # Но в RobustWebSocket нам стоит иметь метод для смены если нужно. 
        # Пока просто сбрасываем состояние.
        # self.ticker_ws.stop()
        # self.ticker_ws.start(new_symbol)
        
        # 4. Обновляем аналитику
        self.smart_entry = SmartEntryAnalyzer(symbol=new_symbol)
        self._instrument_info = None
        
        self.notifier.send_message(f"🔄 Бот переключился на {new_symbol}\nПричина: лучший 'боковик' для сетки.")
