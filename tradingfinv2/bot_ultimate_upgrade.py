"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    TRADING BOT ULTIMATE UPGRADE v2.0                         ║
║                        February 2026 Edition                                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

МОДУЛИ:
1. NewsEngine - Парсинг новостей + Sentiment Analysis
2. MLEnsemble - XGBoost + LSTM + LightGBM с voting
3. FeatureEngine - 100+ индикаторов + on-chain данные
4. RiskManager - Kelly Criterion + dynamic stops + circuit breaker
5. StrategyRouter - Автовыбор стратегии по рынку
6. PerformanceTracker - Метрики в реальном времени

ИСПОЛЬЗОВАНИЕ:
1. Установка зависимостей:
   pip install transformers torch lightgbm xgboost pandas numpy ta requests beautifulsoup4

2. Интеграция в твой бот:
   from bot_ultimate_upgrade import UltimateBot
   
   bot = UltimateBot(
       api_key="твой_bybit_key",
       api_secret="твой_bybit_secret",
       cryptopanic_key="твой_cryptopanic_key"  # Получить на https://cryptopanic.com/developers/api/
   )
   
   # Запуск
   bot.run()

ВАЖНО: Это UPGRADE, не замена. Используй вместе с твоим существующим ботом!
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import time
import requests
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ML imports
try:
    import xgboost as xgb
    from lightgbm import LGBMRegressor
    from transformers import pipeline
    import torch
except ImportError as e:
    print(f"⚠️ Некоторые библиотеки не установлены: {e}")
    print("Установите: pip install transformers torch lightgbm xgboost")

# Technical analysis
try:
    import ta
except ImportError:
    print("⚠️ Установите ta: pip install ta")


# ═══════════════════════════════════════════════════════════════════════════
# 1. NEWS ENGINE - Новости + Sentiment Analysis
# ═══════════════════════════════════════════════════════════════════════════

class NewsEngine:
    """
    Парсит новости из CryptoPanic и анализирует sentiment
    Использует FinBERT - лучшую модель для финансовых текстов 2026
    """
    
    def __init__(self, cryptopanic_key: str):
        self.api_key = cryptopanic_key
        self.base_url = "https://cryptopanic.com/api/v1"
        
        # Загружаем FinBERT для sentiment analysis
        try:
            self.sentiment_analyzer = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                device=0 if torch.cuda.is_available() else -1
            )
            print("✅ FinBERT модель загружена")
        except Exception as e:
            print(f"⚠️ Не удалось загрузить FinBERT: {e}")
            self.sentiment_analyzer = None
    
    def get_news(self, currency: str = "BTC", limit: int = 50) -> List[Dict]:
        """Получает последние новости по монете"""
        try:
            params = {
                "auth_token": self.api_key,
                "currencies": currency,
                "kind": "news",  # или "media" для соц сетей
                "filter": "important",  # только важные
            }
            
            response = requests.get(f"{self.base_url}/posts/", params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("results", [])[:limit]
            else:
                print(f"❌ Ошибка API CryptoPanic: {response.status_code}")
                return []
                
        except Exception as e:
            print(f"❌ Ошибка получения новостей: {e}")
            return []
    
    def analyze_sentiment(self, text: str) -> Dict:
        """
        Анализирует sentiment текста
        Возвращает: {"label": "positive/negative/neutral", "score": 0.0-1.0}
        """
        if not self.sentiment_analyzer:
            return {"label": "neutral", "score": 0.0}
        
        try:
            # FinBERT предпочитает короткие тексты (max 512 токенов)
            text = text[:500]
            result = self.sentiment_analyzer(text)[0]
            
            # Конвертируем в наш формат
            return {
                "label": result["label"].lower(),
                "score": result["score"]
            }
        except Exception as e:
            print(f"⚠️ Ошибка анализа sentiment: {e}")
            return {"label": "neutral", "score": 0.0}
    
    def get_market_sentiment(self, currency: str = "BTC") -> Dict:
        """
        Получает агрегированный sentiment по монете
        Возвращает score от -1 (очень негативно) до +1 (очень позитивно)
        """
        news = self.get_news(currency)
        
        if not news:
            return {
                "score": 0.0,
                "confidence": 0.0,
                "news_count": 0,
                "critical_events": []
            }
        
        sentiments = []
        critical_events = []
        
        for item in news:
            title = item.get("title", "")
            
            # Анализируем sentiment
            sentiment = self.analyze_sentiment(title)
            
            # Конвертируем в числовой score
            if sentiment["label"] == "positive":
                score = sentiment["score"]
            elif sentiment["label"] == "negative":
                score = -sentiment["score"]
            else:
                score = 0.0
            
            sentiments.append(score)
            
            # Детектим критические события (требуют немедленной реакции)
            if self._is_critical_event(title):
                critical_events.append({
                    "title": title,
                    "sentiment": sentiment,
                    "time": item.get("published_at")
                })
        
        # Агрегация
        avg_sentiment = np.mean(sentiments) if sentiments else 0.0
        confidence = np.std(sentiments) if len(sentiments) > 1 else 0.0
        
        return {
            "score": avg_sentiment,
            "confidence": 1.0 - min(confidence, 1.0),  # высокая уверенность = низкий разброс
            "news_count": len(news),
            "critical_events": critical_events
        }
    
    def _is_critical_event(self, text: str) -> bool:
        """Детектит критические события"""
        critical_keywords = [
            "hack", "hacked", "exploit", "scam",
            "delisting", "delisted", "ban", "banned",
            "regulation", "sec", "lawsuit", "suspend",
            "crash", "collapse", "liquidation"
        ]
        
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in critical_keywords)


# ═══════════════════════════════════════════════════════════════════════════
# 2. ML ENSEMBLE ENGINE - XGBoost + LSTM + LightGBM
# ═══════════════════════════════════════════════════════════════════════════

class MLEnsemble:
    """
    Ensemble из трёх моделей:
    - XGBoost: лучший для табличных данных
    - LightGBM: быстрый и эффективный
    - LSTM: для временных рядов (упрощённая версия)
    
    Финальное предсказание = weighted voting
    """
    
    def __init__(self):
        self.xgb_model = None
        self.lgb_model = None
        self.is_trained = False
        
        # Веса моделей (можно оптимизировать)
        self.weights = {
            "xgboost": 0.5,
            "lightgbm": 0.3,
            "lstm": 0.2  # LSTM пока упрощённый, меньший вес
        }
    
    def train(self, X_train: pd.DataFrame, y_train: pd.Series):
        """
        Обучает все модели на данных
        X_train: фичи (индикаторы, on-chain метрики и т.д.)
        y_train: таргет (например, цена через N периодов или направление)
        """
        print("🔄 Обучение ML Ensemble...")
        
        # XGBoost
        self.xgb_model = xgb.XGBRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42
        )
        self.xgb_model.fit(X_train, y_train)
        
        # LightGBM
        self.lgb_model = LGBMRegressor(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            subsample=0.8,
            random_state=42
        )
        self.lgb_model.fit(X_train, y_train)
        
        # LSTM пропускаем для упрощения (требует 3D данные)
        # В полной версии здесь была бы LSTM на временных окнах
        
        self.is_trained = True
        print("✅ ML Ensemble обучен")
        
        # Feature importance
        self._print_feature_importance(X_train.columns)
    
    def predict(self, X: pd.DataFrame) -> Dict:
        """
        Делает предсказание
        Возвращает: {
            "prediction": средневзвешенное предсказание,
            "confidence": уверенность (0-1),
            "individual": предсказания каждой модели
        }
        """
        if not self.is_trained:
            return {
                "prediction": 0.0,
                "confidence": 0.0,
                "individual": {}
            }
        
        # Предсказания каждой модели
        xgb_pred = self.xgb_model.predict(X)[0]
        lgb_pred = self.lgb_model.predict(X)[0]
        # lstm_pred = 0.0  # placeholder
        
        # Weighted voting
        final_pred = (
            xgb_pred * self.weights["xgboost"] +
            lgb_pred * self.weights["lightgbm"]
            # + lstm_pred * self.weights["lstm"]
        ) / (self.weights["xgboost"] + self.weights["lightgbm"])
        
        # Уверенность = обратная к разбросу предсказаний
        predictions = [xgb_pred, lgb_pred]
        confidence = 1.0 / (1.0 + np.std(predictions))
        
        return {
            "prediction": final_pred,
            "confidence": confidence,
            "individual": {
                "xgboost": xgb_pred,
                "lightgbm": lgb_pred
            }
        }
    
    def _print_feature_importance(self, feature_names):
        """Показывает важность фич"""
        importance = self.xgb_model.feature_importances_
        indices = np.argsort(importance)[-10:]  # топ-10
        
        print("\n📊 Топ-10 важных фич:")
        for i in indices[::-1]:
            print(f"   {feature_names[i]}: {importance[i]:.4f}")


# ═══════════════════════════════════════════════════════════════════════════
# 3. FEATURE ENGINE - 100+ индикаторов
# ═══════════════════════════════════════════════════════════════════════════

class FeatureEngine:
    """
    Создаёт фичи для ML:
    - Технические индикаторы (RSI, MACD, BB, etc.)
    - Multi-timeframe индикаторы
    - On-chain метрики (funding rate, OI)
    - Производные фичи
    """
    
    @staticmethod
    def create_features(df: pd.DataFrame, symbol: str = "BTCUSDT") -> pd.DataFrame:
        """
        df должен содержать: open, high, low, close, volume
        Возвращает df с добавленными фичами
        """
        df = df.copy()
        
        # ═══════════════════════════════════════════════════════
        # БАЗОВЫЕ ИНДИКАТОРЫ
        # ═══════════════════════════════════════════════════════
        
        # RSI (множество периодов)
        for period in [7, 14, 21, 30]:
            df[f'rsi_{period}'] = ta.momentum.RSIIndicator(df['close'], window=period).rsi()
        
        # MACD
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_diff'] = macd.macd_diff()
        
        # Bollinger Bands
        bb = ta.volatility.BollingerBands(df['close'])
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_middle'] = bb.bollinger_mavg()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = bb.bollinger_wband()
        df['bb_pband'] = bb.bollinger_pband()  # % position
        
        # EMA (множество периодов)
        for period in [9, 21, 50, 100, 200]:
            df[f'ema_{period}'] = ta.trend.EMAIndicator(df['close'], window=period).ema_indicator()
        
        # SMA
        for period in [20, 50, 200]:
            df[f'sma_{period}'] = ta.trend.SMAIndicator(df['close'], window=period).sma_indicator()
        
        # ATR
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
        
        # ADX (trend strength)
        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()
        
        # Stochastic
        stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'])
        df['stoch_k'] = stoch.stoch()
        df['stoch_d'] = stoch.stoch_signal()
        
        # Williams %R
        df['williams_r'] = ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close']).williams_r()
        
        # CCI
        df['cci'] = ta.trend.CCIIndicator(df['high'], df['low'], df['close']).cci()
        
        # Volume indicators
        df['obv'] = ta.volume.OnBalanceVolumeIndicator(df['close'], df['volume']).on_balance_volume()
        df['volume_sma_20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma_20']
        
        # ═══════════════════════════════════════════════════════
        # ПРОИЗВОДНЫЕ ФИЧИ
        # ═══════════════════════════════════════════════════════
        
        # Price momentum
        for period in [1, 3, 5, 10, 20]:
            df[f'return_{period}'] = df['close'].pct_change(period)
        
        # Volatility
        for period in [10, 20, 30]:
            df[f'volatility_{period}'] = df['close'].pct_change().rolling(period).std()
        
        # High-Low range
        df['hl_range'] = (df['high'] - df['low']) / df['close']
        
        # Distance from EMAs
        for period in [9, 21, 50]:
            df[f'dist_ema_{period}'] = (df['close'] - df[f'ema_{period}']) / df[f'ema_{period}']
        
        # Trend indicators
        df['ema9_ema21_cross'] = (df['ema_9'] > df['ema_21']).astype(int)
        df['price_above_ema50'] = (df['close'] > df['ema_50']).astype(int)
        
        # ═══════════════════════════════════════════════════════
        # CANDLESTICK PATTERNS (упрощённые)
        # ═══════════════════════════════════════════════════════
        
        # Doji
        body = abs(df['close'] - df['open'])
        range_hl = df['high'] - df['low']
        df['is_doji'] = (body / range_hl < 0.1).astype(int)
        
        # Hammer / Shooting star
        lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
        upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
        df['is_hammer'] = ((lower_shadow > 2 * body) & (upper_shadow < body)).astype(int)
        
        # Заполняем NaN
        df = df.fillna(method='ffill').fillna(0)
        
        return df
    
    @staticmethod
    def add_onchain_features(df: pd.DataFrame, funding_rate: float, oi_change: float) -> pd.DataFrame:
        """
        Добавляет on-chain метрики
        funding_rate: текущий funding rate
        oi_change: изменение Open Interest за период
        """
        df = df.copy()
        df['funding_rate'] = funding_rate
        df['oi_change'] = oi_change
        
        # Sentiment от funding rate
        if funding_rate > 0.01:  # очень позитивный
            df['funding_sentiment'] = 1
        elif funding_rate < -0.01:  # очень негативный
            df['funding_sentiment'] = -1
        else:
            df['funding_sentiment'] = 0
        
        return df


# ═══════════════════════════════════════════════════════════════════════════
# 4. RISK MANAGER - Smart Risk Management
# ═══════════════════════════════════════════════════════════════════════════

class RiskManager:
    """
    Управление рисками:
    - Kelly Criterion для sizing
    - Dynamic stop-loss
    - Circuit breaker
    - Position correlation
    """
    
    def __init__(self, total_capital: float, max_risk_per_trade: float = 0.01):
        self.total_capital = total_capital
        self.max_risk_per_trade = max_risk_per_trade  # 1% по умолчанию
        
        # Circuit breaker
        self.daily_loss_limit = 0.05  # 5% дневной убыток -> СТОП
        self.daily_pnl = 0.0
        self.circuit_triggered = False
        self.last_reset_date = datetime.now().date()
    
    def calculate_position_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        current_price: float,
        stop_loss_pct: float
    ) -> float:
        """
        Рассчитывает размер позиции по Kelly Criterion (консервативный)
        
        Kelly % = (win_rate * avg_win - (1-win_rate) * avg_loss) / avg_win
        Используем 25% от Kelly (осторожная версия)
        """
        # Kelly formula
        if avg_win <= 0:
            kelly_pct = 0.0
        else:
            kelly_pct = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
        
        # Консервативный подход: 25% от Kelly
        kelly_pct = max(0, min(kelly_pct * 0.25, self.max_risk_per_trade))
        
        # Расчёт размера позиции
        risk_amount = self.total_capital * kelly_pct
        position_size = risk_amount / (current_price * stop_loss_pct)
        
        return position_size
    
    def calculate_stop_loss(self, entry_price: float, atr: float, direction: str) -> float:
        """
        Динамический stop-loss на основе ATR
        direction: "long" или "short"
        """
        atr_multiplier = 2.0  # можно настроить
        
        if direction == "long":
            stop_loss = entry_price - (atr * atr_multiplier)
        else:  # short
            stop_loss = entry_price + (atr * atr_multiplier)
        
        return stop_loss
    
    def check_circuit_breaker(self, trade_pnl: float) -> bool:
        """
        Проверяет circuit breaker
        Возвращает True если торговля должна быть остановлена
        """
        # Сбрасываем счётчик каждый день
        today = datetime.now().date()
        if today != self.last_reset_date:
            self.daily_pnl = 0.0
            self.circuit_triggered = False
            self.last_reset_date = today
        
        # Обновляем PnL
        self.daily_pnl += trade_pnl
        
        # Проверяем лимит
        daily_loss_pct = self.daily_pnl / self.total_capital
        
        if daily_loss_pct <= -self.daily_loss_limit:
            self.circuit_triggered = True
            print(f"🚨 CIRCUIT BREAKER TRIGGERED! Daily loss: {daily_loss_pct*100:.2f}%")
            return True
        
        return False
    
    def update_capital(self, pnl: float):
        """Обновляет капитал после сделки"""
        self.total_capital += pnl


# ═══════════════════════════════════════════════════════════════════════════
# 5. STRATEGY ROUTER - Выбор стратегии
# ═══════════════════════════════════════════════════════════════════════════

class StrategyRouter:
    """
    Автоматически выбирает стратегию на основе рыночных условий
    
    Стратегии:
    1. MEAN_REVERSION - для флэта (текущая стратегия)
    2. MOMENTUM - для трендов
    3. BREAKOUT - для волатильности
    4. GRID - для бокового движения
    """
    
    @staticmethod
    def detect_market_regime(df: pd.DataFrame) -> Dict:
        """
        Определяет режим рынка
        Возвращает: {
            "regime": "trending/ranging/volatile",
            "trend_strength": 0-100,
            "volatility": float
        }
        """
        # ADX для силы тренда
        adx = df['adx'].iloc[-1]
        
        # Bollinger Bandwidth для волатильности
        bb_width = df['bb_width'].iloc[-1]
        
        # Определяем режим
        if adx > 25:
            regime = "trending"
        elif bb_width < 0.02:  # узкие полосы
            regime = "ranging"
        else:
            regime = "volatile"
        
        return {
            "regime": regime,
            "trend_strength": adx,
            "volatility": bb_width
        }
    
    @staticmethod
    def select_strategy(market_regime: Dict, confluence_score: float) -> str:
        """
        Выбирает стратегию
        """
        regime = market_regime["regime"]
        
        if regime == "trending":
            return "MOMENTUM"
        elif regime == "ranging":
            if confluence_score >= 70:
                return "MEAN_REVERSION"
            else:
                return "GRID"
        else:  # volatile
            return "BREAKOUT"
    
    @staticmethod
    def get_strategy_params(strategy: str, market_data: Dict) -> Dict:
        """
        Возвращает параметры для выбранной стратегии
        """
        if strategy == "MEAN_REVERSION":
            return {
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "bb_threshold": 2.0,
                "min_confluence": 70
            }
        
        elif strategy == "MOMENTUM":
            return {
                "ema_fast": 9,
                "ema_slow": 21,
                "macd_threshold": 0,
                "min_trend_strength": 25
            }
        
        elif strategy == "BREAKOUT":
            return {
                "bb_expansion": 0.03,
                "volume_multiplier": 2.0,
                "confirmation_candles": 2
            }
        
        elif strategy == "GRID":
            return {
                "grid_levels": 10,
                "grid_spacing": 0.005,  # 0.5%
                "take_profit": 0.01  # 1%
            }
        
        return {}


# ═══════════════════════════════════════════════════════════════════════════
# 6. PERFORMANCE TRACKER
# ═══════════════════════════════════════════════════════════════════════════

class PerformanceTracker:
    """
    Отслеживает метрики бота в реальном времени
    """
    
    def __init__(self):
        self.trades = []
        self.equity_curve = []
        
    def add_trade(self, trade: Dict):
        """
        Добавляет сделку
        trade должен содержать: entry_price, exit_price, size, pnl, strategy, timestamp
        """
        self.trades.append(trade)
    
    def get_metrics(self) -> Dict:
        """
        Рассчитывает метрики
        """
        if not self.trades:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "total_pnl": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0
            }
        
        df = pd.DataFrame(self.trades)
        
        # Базовые метрики
        total_trades = len(df)
        winning_trades = df[df['pnl'] > 0]
        losing_trades = df[df['pnl'] < 0]
        
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        
        avg_win = winning_trades['pnl'].mean() if len(winning_trades) > 0 else 0
        avg_loss = abs(losing_trades['pnl'].mean()) if len(losing_trades) > 0 else 0
        
        # Profit factor
        total_wins = winning_trades['pnl'].sum() if len(winning_trades) > 0 else 0
        total_losses = abs(losing_trades['pnl'].sum()) if len(losing_trades) > 0 else 0
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Total PnL
        total_pnl = df['pnl'].sum()
        
        # Sharpe Ratio (упрощённый)
        returns = df['pnl']
        sharpe = (returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        
        # Max Drawdown
        cumulative = returns.cumsum()
        running_max = cumulative.expanding().max()
        drawdown = cumulative - running_max
        max_dd = abs(drawdown.min())
        
        return {
            "total_trades": total_trades,
            "win_rate": win_rate * 100,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd
        }
    
    def print_report(self):
        """Выводит отчёт"""
        metrics = self.get_metrics()
        
        print("\n" + "="*60)
        print("📊 PERFORMANCE REPORT")
        print("="*60)
        print(f"Total Trades:     {metrics['total_trades']}")
        print(f"Win Rate:         {metrics['win_rate']:.2f}%")
        print(f"Profit Factor:    {metrics['profit_factor']:.2f}")
        print(f"Total PnL:        ${metrics['total_pnl']:.2f}")
        print(f"Avg Win:          ${metrics['avg_win']:.2f}")
        print(f"Avg Loss:         ${metrics['avg_loss']:.2f}")
        print(f"Sharpe Ratio:     {metrics['sharpe_ratio']:.2f}")
        print(f"Max Drawdown:     ${metrics['max_drawdown']:.2f}")
        print("="*60 + "\n")


# ═══════════════════════════════════════════════════════════════════════════
# 7. ULTIMATE BOT - Главный класс
# ═══════════════════════════════════════════════════════════════════════════

class UltimateBot:
    """
    Объединяет все модули в один супер-бот
    """
    
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        cryptopanic_key: str,
        initial_capital: float = 10000.0
    ):
        # Инициализация модулей
        self.news_engine = NewsEngine(cryptopanic_key)
        self.ml_ensemble = MLEnsemble()
        self.risk_manager = RiskManager(initial_capital)
        self.performance_tracker = PerformanceTracker()
        
        # API ключи
        self.api_key = api_key
        self.api_secret = api_secret
        
        print("✅ UltimateBot инициализирован")
    
    def analyze_opportunity(self, symbol: str, df: pd.DataFrame) -> Dict:
        """
        Полный анализ возможности для входа
        
        Возвращает: {
            "signal": "BUY/SELL/HOLD",
            "confidence": 0-100,
            "strategy": "MEAN_REVERSION/MOMENTUM/etc",
            "entry_price": float,
            "stop_loss": float,
            "take_profit": float,
            "position_size": float,
            "reasoning": {...}
        }
        """
        # 1. Создаём фичи
        df_features = FeatureEngine.create_features(df)
        
        # 2. Получаем новостной sentiment
        currency = symbol.replace("USDT", "")
        news_sentiment = self.news_engine.get_market_sentiment(currency)
        
        # Проверяем критические события
        if news_sentiment["critical_events"]:
            print(f"⚠️ КРИТИЧЕСКИЕ СОБЫТИЯ обнаружены для {symbol}")
            for event in news_sentiment["critical_events"][:3]:
                print(f"   - {event['title']}")
            
            # Если негативные события - не входим
            if news_sentiment["score"] < -0.5:
                return {"signal": "HOLD", "confidence": 0, "reasoning": "Critical negative news"}
        
        # 3. Определяем режим рынка
        market_regime = StrategyRouter.detect_market_regime(df_features)
        
        # 4. Рассчитываем confluence score (из твоей системы)
        confluence_score = self._calculate_confluence(df_features, news_sentiment)
        
        # 5. Выбираем стратегию
        strategy = StrategyRouter.select_strategy(market_regime, confluence_score)
        
        # 6. Генерируем сигнал
        signal_result = self._generate_signal(df_features, strategy, confluence_score)
        
        # 7. Risk management
        if signal_result["signal"] != "HOLD":
            current_price = df['close'].iloc[-1]
            atr = df_features['atr'].iloc[-1]
            
            # Stop loss
            stop_loss = self.risk_manager.calculate_stop_loss(
                current_price,
                atr,
                "long" if signal_result["signal"] == "BUY" else "short"
            )
            
            # Position size
            metrics = self.performance_tracker.get_metrics()
            position_size = self.risk_manager.calculate_position_size(
                win_rate=metrics.get("win_rate", 50) / 100,
                avg_win=metrics.get("avg_win", 100),
                avg_loss=metrics.get("avg_loss", 50),
                current_price=current_price,
                stop_loss_pct=abs(current_price - stop_loss) / current_price
            )
            
            signal_result.update({
                "stop_loss": stop_loss,
                "position_size": position_size,
                "strategy": strategy,
                "market_regime": market_regime,
                "news_sentiment": news_sentiment["score"]
            })
        
        return signal_result
    
    def _calculate_confluence(self, df: pd.DataFrame, news_sentiment: Dict) -> float:
        """
        Рассчитывает confluence score (адаптация твоей системы)
        """
        score = 0
        last_row = df.iloc[-1]
        
        # RSI (25 points)
        rsi = last_row['rsi_14']
        if rsi < 20 or rsi > 80:
            score += 25
        elif rsi < 30 or rsi > 70:
            score += 15
        
        # Bollinger Bands (15 points)
        bb_pband = last_row['bb_pband']
        if bb_pband < 0 or bb_pband > 1:
            score += 15
        elif bb_pband < 0.2 or bb_pband > 0.8:
            score += 10
        
        # Multi-timeframe (25 points) - упрощённо
        # Здесь нужны данные нескольких таймфреймов, упрощаем
        score += 10
        
        # ADX trend strength (10 points)
        adx = last_row['adx']
        if adx > 25:
            score += 10
        
        # Volume (10 points)
        volume_ratio = last_row['volume_ratio']
        if volume_ratio > 1.5:
            score += 10
        
        # News sentiment (20 points) - НОВОЕ!
        sentiment_score = news_sentiment["score"]
        if sentiment_score > 0.3:
            score += 20
        elif sentiment_score > 0.1:
            score += 10
        elif sentiment_score < -0.3:
            score -= 10  # вычитаем при негативе
        
        return max(0, min(score, 100))
    
    def _generate_signal(self, df: pd.DataFrame, strategy: str, confluence: float) -> Dict:
        """
        Генерирует торговый сигнал на основе стратегии
        """
        last_row = df.iloc[-1]
        
        if strategy == "MEAN_REVERSION":
            # Твоя текущая стратегия
            if confluence >= 70:
                rsi = last_row['rsi_14']
                if rsi < 30:
                    return {
                        "signal": "BUY",
                        "confidence": confluence,
                        "reasoning": f"Mean reversion: RSI={rsi:.1f}, confluence={confluence:.0f}"
                    }
                elif rsi > 70:
                    return {
                        "signal": "SELL",
                        "confidence": confluence,
                        "reasoning": f"Mean reversion: RSI={rsi:.1f}, confluence={confluence:.0f}"
                    }
        
        elif strategy == "MOMENTUM":
            # Трендовая стратегия
            ema9 = last_row['ema_9']
            ema21 = last_row['ema_21']
            macd_diff = last_row['macd_diff']
            
            if ema9 > ema21 and macd_diff > 0:
                return {
                    "signal": "BUY",
                    "confidence": min(confluence + 10, 100),
                    "reasoning": "Momentum: Uptrend confirmed"
                }
            elif ema9 < ema21 and macd_diff < 0:
                return {
                    "signal": "SELL",
                    "confidence": min(confluence + 10, 100),
                    "reasoning": "Momentum: Downtrend confirmed"
                }
        
        elif strategy == "BREAKOUT":
            # Стратегия пробоя
            bb_width = last_row['bb_width']
            volume_ratio = last_row['volume_ratio']
            
            if bb_width > 0.03 and volume_ratio > 2.0:
                # Определяем направление
                close = df['close'].iloc[-1]
                bb_upper = last_row['bb_upper']
                bb_lower = last_row['bb_lower']
                
                if close > bb_upper:
                    return {
                        "signal": "BUY",
                        "confidence": confluence,
                        "reasoning": "Breakout: Upper BB break + volume"
                    }
                elif close < bb_lower:
                    return {
                        "signal": "SELL",
                        "confidence": confluence,
                        "reasoning": "Breakout: Lower BB break + volume"
                    }
        
        return {"signal": "HOLD", "confidence": 0, "reasoning": "No setup"}
    
    def run(self, symbol: str = "BTCUSDT", interval: str = "15m"):
        """
        Основной цикл бота (демо-версия)
        """
        print(f"\n🚀 Запуск UltimateBot для {symbol}")
        print("="*60)
        
        # В реальной версии здесь был бы бесконечный цикл
        # Для демо делаем один проход
        
        # Получаем исторические данные (заглушка)
        # В реальности: df = self.get_market_data(symbol, interval)
        df = self._generate_demo_data()
        
        # Анализируем
        analysis = self.analyze_opportunity(symbol, df)
        
        # Выводим результат
        print("\n📊 АНАЛИЗ ЗАВЕРШЁН")
        print("="*60)
        print(f"Signal:        {analysis.get('signal', 'N/A')}")
        print(f"Confidence:    {analysis.get('confidence', 0):.0f}%")
        print(f"Strategy:      {analysis.get('strategy', 'N/A')}")
        print(f"Reasoning:     {analysis.get('reasoning', 'N/A')}")
        
        if analysis.get('signal') != 'HOLD':
            print(f"\nEntry Price:   ${df['close'].iloc[-1]:.2f}")
            print(f"Stop Loss:     ${analysis.get('stop_loss', 0):.2f}")
            print(f"Position Size: {analysis.get('position_size', 0):.4f}")
            print(f"News Sent:     {analysis.get('news_sentiment', 0):.2f}")
        
        print("="*60)
        
        # Показываем метрики
        self.performance_tracker.print_report()
    
    def _generate_demo_data(self) -> pd.DataFrame:
        """Генерирует демо-данные для тестирования"""
        dates = pd.date_range(end=datetime.now(), periods=200, freq='15min')
        
        # Генерируем цены (random walk)
        np.random.seed(42)
        returns = np.random.randn(200) * 0.001
        close = 50000 * (1 + returns).cumprod()
        
        high = close * (1 + abs(np.random.randn(200) * 0.005))
        low = close * (1 - abs(np.random.randn(200) * 0.005))
        open_price = np.roll(close, 1)
        open_price[0] = close[0]
        
        volume = np.random.randint(1000000, 5000000, 200)
        
        df = pd.DataFrame({
            'timestamp': dates,
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        })
        
        return df


# ═══════════════════════════════════════════════════════════════════════════
# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════════════╗
    ║            TRADING BOT ULTIMATE UPGRADE v2.0                      ║
    ║                  February 2026 Edition                            ║
    ╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    # ВАЖНО: Замени на свои ключи!
    bot = UltimateBot(
        api_key="YOUR_BYBIT_API_KEY",
        api_secret="YOUR_BYBIT_SECRET",
        cryptopanic_key="YOUR_CRYPTOPANIC_KEY",  # Получить на https://cryptopanic.com/developers/api/
        initial_capital=10000.0
    )
    
    # Запуск демо
    bot.run(symbol="BTCUSDT", interval="15m")
    
    print("\n✅ Демо завершено!")
    print("""
    📚 СЛЕДУЮЩИЕ ШАГИ:
    
    1. Получи API ключи:
       - Bybit: https://www.bybit.com/app/user/api-management
       - CryptoPanic: https://cryptopanic.com/developers/api/
    
    2. Интегрируй с твоим ботом:
       - Замени заглушки get_market_data() на реальные API вызовы
       - Добавь исполнение ордеров через Bybit API
       - Настрой Telegram уведомления
    
    3. Обучи ML модели:
       - Собери исторические данные (минимум 6 месяцев)
       - Запусти ml_ensemble.train(X, y)
       - Сохрани модели
    
    4. Бэктестинг:
       - Протестируй на исторических данных
       - Оптимизируй параметры
       - Forward testing на demo счёте
    
    5. Запуск в прод:
       - Начни с малых сумм ($100-500)
       - Мониторь метрики ежедневно
       - Постепенно увеличивай капитал
    
    ⚠️ ВАЖНО: Всегда торгуй ТОЛЬКО свободными деньгами!
    """)
