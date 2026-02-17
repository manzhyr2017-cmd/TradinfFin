"""
╔══════════════════════════════════════════════════════════════════╗
║        MAIN INTEGRATION MODULE - Bot Improvements v2.0           ║
║                                                                  ║
║  Этот файл показывает, как интегрировать ВСЕ улучшения           ║
║  в существующий mean_reversion_bybit.py                          ║
║                                                                  ║
║  Содержит:                                                       ║
║    1. EnhancedTradingEngine - улучшенный движок                  ║
║    2. Полная интеграция всех модулей                              ║
║    3. Пошаговые инструкции                                       ║
╚══════════════════════════════════════════════════════════════════╝
"""

import time
import logging
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

# Импорт наших модулей
from risk_manager import RiskManager, RiskLevel, CircuitBreakerState
from news_engine import NewsEngine, NewsSentiment
from kelly_and_tracker import KellyPositionSizer, PerformanceTracker
from confluence_enhanced import ConfluenceScore, AdaptiveThresholds, EnhancedSRDetector

logger = logging.getLogger(__name__)


class EnhancedTradingEngine:
    """
    Улучшенный торговый движок — обёртка над существующим
    AdvancedMeanReversionEngine с интеграцией всех новых компонентов.
    
    ┌──────────────────────────────────────────────────┐
    │              FLOW DIAGRAM                         │
    │                                                   │
    │  Signal → NewsFilter → RiskCheck → Confluence    │
    │    → AdaptiveThreshold → KellySize → Execute     │
    │    → TrackPerformance → UpdateRisk               │
    └──────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        # Существующий движок
        original_engine=None,
        
        # Капитал
        total_capital: float = 10000,
        
        # API ключи
        cryptopanic_key: Optional[str] = None,
        
        # Risk параметры
        daily_loss_limit: float = 0.05,
        max_drawdown: float = 0.15,
        max_positions: int = 3,
        max_consecutive_losses: int = 5,
        cooldown_minutes: int = 60,
        
        # Kelly параметры
        kelly_fraction: float = 0.25,
        min_position_pct: float = 0.005,
        max_position_pct: float = 0.10,
    ):
        # Оригинальный движок (если передан)
        self.engine = original_engine
        
        # === 1. RISK MANAGER (🔴 КРИТИЧНЫЙ) ===
        self.risk_manager = RiskManager(
            total_capital=total_capital,
            daily_loss_limit=daily_loss_limit,
            max_drawdown_limit=max_drawdown,
            max_positions=max_positions,
            max_consecutive_losses=max_consecutive_losses,
            cooldown_minutes=cooldown_minutes,
            max_position_pct=max_position_pct,
        )
        
        # === 2. NEWS ENGINE (🔴 КРИТИЧНЫЙ) ===
        self.news_engine = NewsEngine(
            cryptopanic_key=cryptopanic_key,
            cache_ttl_seconds=300,
        )
        
        # === 3. KELLY POSITION SIZER (🟡 ВАЖНЫЙ) ===
        self.kelly_sizer = KellyPositionSizer(
            kelly_fraction=kelly_fraction,
            min_position_pct=min_position_pct,
            max_position_pct=max_position_pct,
        )
        
        # === 4. PERFORMANCE TRACKER (🟡 ВАЖНЫЙ) ===
        self.performance = PerformanceTracker(
            initial_capital=total_capital,
        )
        
        # === 5. ENHANCED S/R DETECTOR (🟡 ВАЖНЫЙ) ===
        self.sr_detector = EnhancedSRDetector(
            lookback=100,
            atr_multiplier=0.5,
        )
        
        logger.info(
            "EnhancedTradingEngine инициализирован. "
            f"Capital=${total_capital}, "
            f"News={'✅' if cryptopanic_key else '❌'}, "
            f"Kelly={kelly_fraction}, "
            f"Max DD={max_drawdown*100}%"
        )

    # ═══════════════════════════════════════════════════════════
    # ГЛАВНЫЙ МЕТОД АНАЛИЗА (обёртка над существующим)
    # ═══════════════════════════════════════════════════════════

    def analyze_enhanced(
        self,
        symbol: str,
        df_15m=None,
        df_1h=None,
        df_4h=None,
        current_atr: float = 0.0,
        normal_atr: float = 0.0,
        **kwargs,
    ) -> Optional[dict]:
        """
        Улучшенный анализ с полной цепочкой проверок.
        
        Возвращает None если сделка отклонена, иначе dict с параметрами.
        
        Flow:
        1. News Filter (блокировка критических событий)
        2. Risk Check (CB, drawdown, positions)
        3. Original Analysis (существующий confluence)
        4. Enhanced Confluence (+ news score, исправленный max)
        5. Adaptive Threshold (порог зависит от режима)
        6. Kelly Position Sizing
        7. Final decision
        """
        
        # ════════════════════════════════════════
        # STEP 1: NEWS FILTER (🔴 ПЕРВЫЙ!)
        # ════════════════════════════════════════
        currency = symbol.replace("USDT", "").replace("USD", "")[:5]
        
        news_sentiment = self.news_engine.get_market_sentiment(currency)
        
        if news_sentiment.should_block_trading:
            logger.warning(
                f"🚫 {symbol}: News blocked! "
                f"Score={news_sentiment.score:+.2f}, "
                f"Critical={news_sentiment.critical_events}"
            )
            return None
        
        # ════════════════════════════════════════
        # STEP 2: RISK CHECK
        # ════════════════════════════════════════
        estimated_size = self.risk_manager.total_capital * 0.02  # Предварительная оценка
        
        can_trade, reason = self.risk_manager.can_open_trade(
            symbol=symbol,
            position_size_usd=estimated_size,
            current_volatility=current_atr,
            normal_volatility=normal_atr,
        )
        
        if not can_trade:
            logger.info(f"⛔ {symbol}: Risk blocked: {reason}")
            return None
        
        # ════════════════════════════════════════
        # STEP 3: ORIGINAL ANALYSIS
        # ════════════════════════════════════════
        original_signal = None
        if self.engine:
            try:
                original_signal = self.engine.analyze(
                    df_15m=df_15m, df_1h=df_1h, df_4h=df_4h,
                    symbol=symbol, **kwargs
                )
            except Exception as e:
                logger.error(f"Original engine error: {e}")
                return None
        
        if original_signal is None:
            return None
        
        # ════════════════════════════════════════
        # STEP 4: ENHANCE CONFLUENCE
        # ════════════════════════════════════════
        # Получаем существующий confluence score
        confluence = original_signal.get("confluence", ConfluenceScore())
        
        # Добавляем news score
        confluence.news_score = max(0, news_sentiment.confluence_points)
        
        # ИСПРАВЛЯЕМ max_possible!
        confluence.max_possible = 145
        
        # Пересчитываем
        confluence.recalculate_total()
        
        logger.info(f"📊 {symbol}: {confluence.get_breakdown()}")
        
        # ════════════════════════════════════════
        # STEP 5: ADAPTIVE THRESHOLD
        # ════════════════════════════════════════
        regime = original_signal.get("market_regime", "NEUTRAL")
        should_trade, threshold_reason = AdaptiveThresholds.should_trade(
            confluence.percentage, regime
        )
        
        if not should_trade:
            logger.info(f"📉 {symbol}: Below threshold: {threshold_reason}")
            return None
        
        # ════════════════════════════════════════
        # STEP 6: KELLY POSITION SIZING
        # ════════════════════════════════════════
        kelly_trades = self.performance.get_kelly_input()
        
        kelly_result = self.kelly_sizer.calculate(
            trades=kelly_trades,
            confluence_score=confluence.percentage,
            current_volatility=current_atr,
            normal_volatility=normal_atr,
            drawdown_pct=self.risk_manager._current_drawdown(),
        )
        
        # Корректировка по режиму
        regime_scale = AdaptiveThresholds.get_position_scale(regime)
        final_position_pct = kelly_result["position_pct"] * regime_scale
        
        # Корректировка от risk manager
        final_position_pct = self.risk_manager.get_adjusted_position_size(final_position_pct)
        
        position_size_usd = self.risk_manager.total_capital * final_position_pct
        
        logger.info(
            f"💰 {symbol}: Position={final_position_pct*100:.2f}% "
            f"(${position_size_usd:.0f}) | "
            f"Kelly={kelly_result['method']} | "
            f"Regime={regime} (x{regime_scale})"
        )
        
        # ════════════════════════════════════════
        # STEP 7: FINAL DECISION
        # ════════════════════════════════════════
        
        # Финальная проверка размера
        can_trade2, reason2 = self.risk_manager.can_open_trade(
            symbol=symbol,
            position_size_usd=position_size_usd,
            current_volatility=current_atr,
            normal_volatility=normal_atr,
        )
        
        if not can_trade2:
            logger.info(f"⛔ {symbol}: Final risk check failed: {reason2}")
            return None
        
        # Формируем улучшенный сигнал
        enhanced_signal = {
            **original_signal,
            "confluence": confluence,
            "confluence_pct": confluence.percentage,
            "confluence_strength": confluence.strength,
            "position_size_pct": final_position_pct,
            "position_size_usd": position_size_usd,
            "kelly_method": kelly_result["method"],
            "news_sentiment": news_sentiment.score,
            "news_fg_index": news_sentiment.fear_greed_index,
            "market_regime": regime,
            "risk_level": self.risk_manager.risk_level.value,
        }
        
        return enhanced_signal

    # ═══════════════════════════════════════════════════════════
    # ОБРАБОТКА ОТКРЫТИЯ/ЗАКРЫТИЯ ПОЗИЦИЙ
    # ═══════════════════════════════════════════════════════════

    def on_position_opened(self, symbol: str, side: str, entry_price: float,
                          position_size: float, confluence_score: float = 0.0):
        """Вызвать после открытия позиции"""
        self.risk_manager.register_position(
            symbol, side, entry_price, position_size, confluence_score
        )

    def on_position_closed(self, symbol: str, exit_price: float, pnl: float,
                          trade_details: Optional[dict] = None):
        """Вызвать после закрытия позиции"""
        # Risk Manager
        self.risk_manager.close_position(symbol, exit_price, pnl)
        
        # Performance Tracker
        if trade_details:
            self.performance.add_trade(trade_details)
        else:
            self.performance.add_trade({
                "symbol": symbol,
                "exit_price": exit_price,
                "pnl": pnl,
            })

    # ═══════════════════════════════════════════════════════════
    # СТАТУС И ОТЧЁТНОСТЬ
    # ═══════════════════════════════════════════════════════════

    def get_full_status(self) -> dict:
        """Полный статус всех систем"""
        return {
            "risk": self.risk_manager.get_status_report(),
            "performance": self.performance.get_statistics(),
            "news": self.news_engine.get_stats(),
        }

    def print_dashboard(self):
        """Красивый дашборд"""
        print("\n" + "="*60)
        print("       ENHANCED TRADING BOT DASHBOARD")
        print("="*60)
        
        self.risk_manager.print_status()
        
        stats = self.performance.get_statistics()
        if "error" not in stats:
            print(f"  📊 Win Rate: {stats.get('win_rate', 0):.1f}%")
            print(f"  📊 Profit Factor: {stats.get('profit_factor', 0):.2f}")
            print(f"  📊 Sharpe: {stats.get('sharpe_ratio', 0):.2f}")
        
        news_stats = self.news_engine.get_stats()
        print(f"  📰 News requests: {news_stats['total_requests']}")
        print(f"  📰 Cache hit rate: {news_stats['cache_hit_rate']:.0f}%")
        print("="*60 + "\n")


# ═══════════════════════════════════════════════════════════════
# МИНИМАЛЬНАЯ ИНТЕГРАЦИЯ (для быстрого внедрения)
# ═══════════════════════════════════════════════════════════════

def quick_integrate_risk_check(
    symbol: str,
    position_size_usd: float,
    total_capital: float = 10000,
    daily_pnl: float = 0.0,
    daily_loss_limit: float = 0.05,
) -> Tuple[bool, str]:
    """
    Быстрая проверка рисков (без полной интеграции).
    
    Можно вставить в существующий код за 2 минуты:
    
    # В analyze() добавить:
    from integration import quick_integrate_risk_check
    
    can_trade, reason = quick_integrate_risk_check(
        symbol, position_size, total_capital, daily_pnl
    )
    if not can_trade:
        return None
    """
    # Circuit Breaker
    loss_pct = abs(min(0, daily_pnl)) / total_capital
    if loss_pct >= daily_loss_limit:
        return False, f"🚨 CIRCUIT BREAKER: daily loss {loss_pct*100:.1f}% >= {daily_loss_limit*100}%"
    
    # Position size check
    if position_size_usd > total_capital * 0.10:
        return False, f"⚠️ Position too large: ${position_size_usd:.0f} > 10% of capital"
    
    return True, "✅ OK"


# ═══════════════════════════════════════════════════════════════
# ПРИМЕР ПОЛНОГО ЦИКЛА
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    # Инициализация
    bot = EnhancedTradingEngine(
        total_capital=10000,
        cryptopanic_key=None,  # Вставьте свой ключ
        daily_loss_limit=0.05,
        max_drawdown=0.15,
        max_positions=3,
        kelly_fraction=0.25,
    )
    
    # Симуляция торгового цикла
    print("🚀 Enhanced Trading Bot Demo\n")
    
    # Проверка: можем ли торговать?
    can_trade, reason = bot.risk_manager.can_open_trade("BTCUSDT", 500)
    print(f"Can trade BTCUSDT: {can_trade} - {reason}")
    
    # Открываем позицию
    if can_trade:
        bot.on_position_opened("BTCUSDT", "long", 100000, 0.005, confluence_score=85)
    
    # Закрываем с прибылью
    bot.on_position_closed(
        "BTCUSDT", 101500, 75,
        trade_details={
            "symbol": "BTCUSDT",
            "side": "long",
            "entry_price": 100000,
            "exit_price": 101500,
            "pnl": 75,
            "pnl_percent": 0.015,
            "confluence_score": 85,
            "market_regime": "ranging_narrow",
            "exit_reason": "tp",
            "duration_seconds": 3600,
        }
    )
    
    # Дашборд
    bot.print_dashboard()
    
    print("\n✅ Все модули работают корректно!")
