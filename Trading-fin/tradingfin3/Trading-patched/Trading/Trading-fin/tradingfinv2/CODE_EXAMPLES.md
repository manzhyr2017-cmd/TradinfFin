# 💻 ПРИМЕРЫ КОДА - ГОТОВЫЕ РЕШЕНИЯ

## 🎯 БЫСТРАЯ ИНТЕГРАЦИЯ В ТВОЙ БОТ

---

## ПРИМЕР 1: Добавление NewsEngine (5 минут)

### Файл: `add_news_to_bot.py`

```python
"""
Минимальная интеграция новостного модуля в твой бот
Добавь это в свой main_bybit.py или mean_reversion_bybit.py
"""

from bot_ultimate_upgrade import NewsEngine

# ═══════════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ (один раз при старте бота)
# ═══════════════════════════════════════════════════════════════

CRYPTOPANIC_KEY = "твой_ключ_здесь"  # Получить на https://cryptopanic.com/developers/api/
news_engine = NewsEngine(CRYPTOPANIC_KEY)

# ═══════════════════════════════════════════════════════════════
# В ТВОЕЙ ФУНКЦИИ АНАЛИЗА (перед генерацией сигнала)
# ═══════════════════════════════════════════════════════════════

def analyze_trade_opportunity(symbol: str, confluence_score: float):
    """Твоя существующая функция анализа"""
    
    # 1. ДОБАВЬ ПРОВЕРКУ НОВОСТЕЙ
    currency = symbol.replace("USDT", "")  # BTCUSDT -> BTC
    news_sentiment = news_engine.get_market_sentiment(currency)
    
    print(f"\n📰 Новости {currency}:")
    print(f"   Sentiment Score: {news_sentiment['score']:.2f}")
    print(f"   Confidence: {news_sentiment['confidence']:.2f}")
    print(f"   News Count: {news_sentiment['news_count']}")
    
    # 2. ПРОВЕРЬ КРИТИЧЕСКИЕ СОБЫТИЯ
    if news_sentiment['critical_events']:
        print(f"⚠️ ВНИМАНИЕ! Критические события:")
        for event in news_sentiment['critical_events'][:3]:
            print(f"   - {event['title']}")
        
        # Если очень негативные - НЕ ВХОДИМ
        if news_sentiment['score'] < -0.5:
            print("❌ Слишком негативные новости - SKIP")
            return None
    
    # 3. ДОБАВЬ НОВОСТИ В CONFLUENCE SCORE
    if news_sentiment['score'] > 0.3:
        print("✅ Позитивные новости: +20 баллов")
        confluence_score += 20
    elif news_sentiment['score'] < -0.3:
        print("⚠️ Негативные новости: -20 баллов")
        confluence_score -= 20
    
    # Твоя дальнейшая логика...
    if confluence_score >= 70:
        return "BUY"
    else:
        return "HOLD"

# ПРИМЕР ИСПОЛЬЗОВАНИЯ
result = analyze_trade_opportunity("BTCUSDT", confluence_score=65)
print(f"Сигнал: {result}")
```

---

## ПРИМЕР 2: Smart Risk Management (10 минут)

### Файл: `add_risk_management.py`

```python
"""
Умное управление рисками вместо фиксированного размера позиции
"""

from bot_ultimate_upgrade import RiskManager

# ═══════════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ
# ═══════════════════════════════════════════════════════════════

TOTAL_CAPITAL = 10000.0  # Твой капитал
risk_manager = RiskManager(
    total_capital=TOTAL_CAPITAL,
    max_risk_per_trade=0.01  # 1% риска на сделку
)

# ═══════════════════════════════════════════════════════════════
# ПРИ ОТКРЫТИИ ПОЗИЦИИ
# ═══════════════════════════════════════════════════════════════

def open_position(symbol: str, direction: str, current_price: float, atr: float):
    """
    direction: "long" или "short"
    atr: Average True Range из твоих индикаторов
    """
    
    # 1. РАССЧИТАЙ STOP LOSS (динамический, на основе ATR)
    stop_loss = risk_manager.calculate_stop_loss(
        entry_price=current_price,
        atr=atr,
        direction=direction
    )
    
    print(f"\n📊 Risk Management:")
    print(f"   Entry: ${current_price:.2f}")
    print(f"   Stop Loss: ${stop_loss:.2f}")
    print(f"   Risk: {abs(current_price - stop_loss) / current_price * 100:.2f}%")
    
    # 2. РАССЧИТАЙ РАЗМЕР ПОЗИЦИИ (Kelly Criterion)
    # Нужна статистика твоего бота (можно взять из performance_tracker)
    position_size = risk_manager.calculate_position_size(
        win_rate=0.78,  # 78% win rate (из твоей статистики)
        avg_win=150.0,  # средний профит в $
        avg_loss=75.0,  # средний убыток в $
        current_price=current_price,
        stop_loss_pct=abs(current_price - stop_loss) / current_price
    )
    
    print(f"   Position Size: {position_size:.4f} {symbol}")
    print(f"   Position Value: ${position_size * current_price:.2f}")
    
    # 3. РАЗМЕСТИ ОРДЕР (твоя логика)
    # bybit_client.place_order(
    #     symbol=symbol,
    #     side="Buy" if direction == "long" else "Sell",
    #     qty=position_size,
    #     stop_loss=stop_loss
    # )
    
    return {
        "entry": current_price,
        "stop_loss": stop_loss,
        "size": position_size
    }

# ═══════════════════════════════════════════════════════════════
# ПОСЛЕ ЗАКРЫТИЯ ПОЗИЦИИ
# ═══════════════════════════════════════════════════════════════

def close_position(entry_price: float, exit_price: float, size: float):
    """Закрытие позиции"""
    
    # Рассчитай PnL
    pnl = (exit_price - entry_price) * size
    
    print(f"\n💰 Trade Closed:")
    print(f"   PnL: ${pnl:.2f}")
    
    # ПРОВЕРЬ CIRCUIT BREAKER (защита от краха)
    if risk_manager.check_circuit_breaker(pnl):
        print("🚨 CIRCUIT BREAKER TRIGGERED!")
        print("   Дневной лимит убытков достигнут!")
        print("   Торговля ОСТАНОВЛЕНА на сегодня.")
        # Останови бота или отправь алерт
        return False
    
    # Обнови капитал
    risk_manager.update_capital(pnl)
    
    return True

# ПРИМЕР ИСПОЛЬЗОВАНИЯ
trade = open_position(
    symbol="BTCUSDT",
    direction="long",
    current_price=50000.0,
    atr=1500.0  # из твоих индикаторов
)

# После закрытия
can_continue = close_position(
    entry_price=50000.0,
    exit_price=51000.0,
    size=trade['size']
)
```

---

## ПРИМЕР 3: Multi-Strategy Router (15 минут)

### Файл: `add_multi_strategy.py`

```python
"""
Автоматический выбор стратегии в зависимости от рынка
"""

from bot_ultimate_upgrade import StrategyRouter, FeatureEngine
import pandas as pd

# ═══════════════════════════════════════════════════════════════
# ПОДГОТОВКА ДАННЫХ
# ═══════════════════════════════════════════════════════════════

def prepare_data(df_raw: pd.DataFrame) -> pd.DataFrame:
    """
    df_raw должен содержать: open, high, low, close, volume
    """
    # Создай все фичи (RSI, MACD, BB, ADX, etc.)
    df_features = FeatureEngine.create_features(df_raw)
    return df_features

# ═══════════════════════════════════════════════════════════════
# ОПРЕДЕЛЕНИЕ СТРАТЕГИИ
# ═══════════════════════════════════════════════════════════════

def select_best_strategy(df: pd.DataFrame, confluence_score: float):
    """Выбирает лучшую стратегию для текущих условий"""
    
    # 1. ОПРЕДЕЛИ РЕЖИМ РЫНКА
    market_regime = StrategyRouter.detect_market_regime(df)
    
    print(f"\n📊 Market Analysis:")
    print(f"   Regime: {market_regime['regime']}")
    print(f"   Trend Strength (ADX): {market_regime['trend_strength']:.1f}")
    print(f"   Volatility (BB Width): {market_regime['volatility']:.4f}")
    
    # 2. ВЫБЕРИ СТРАТЕГИЮ
    strategy = StrategyRouter.select_strategy(market_regime, confluence_score)
    
    print(f"   Selected Strategy: {strategy}")
    
    # 3. ПОЛУЧИ ПАРАМЕТРЫ
    params = StrategyRouter.get_strategy_params(strategy, market_regime)
    
    return strategy, params

# ═══════════════════════════════════════════════════════════════
# РЕАЛИЗАЦИЯ СТРАТЕГИЙ
# ═══════════════════════════════════════════════════════════════

def execute_mean_reversion(df: pd.DataFrame, params: dict):
    """Твоя текущая стратегия"""
    last = df.iloc[-1]
    
    rsi = last['rsi_14']
    bb_pband = last['bb_pband']
    
    if rsi < params['rsi_oversold'] and bb_pband < 0.1:
        return "BUY"
    elif rsi > params['rsi_overbought'] and bb_pband > 0.9:
        return "SELL"
    
    return "HOLD"

def execute_momentum(df: pd.DataFrame, params: dict):
    """Трендовая стратегия"""
    last = df.iloc[-1]
    prev = df.iloc[-2]
    
    # EMA crossover
    ema_fast = last['ema_9']
    ema_slow = last['ema_21']
    prev_ema_fast = prev['ema_9']
    prev_ema_slow = prev['ema_21']
    
    # MACD confirmation
    macd_diff = last['macd_diff']
    
    # ADX > 25 (сильный тренд)
    adx = last['adx']
    
    # Bullish: Fast EMA crosses above Slow EMA
    if (prev_ema_fast <= prev_ema_slow and ema_fast > ema_slow and 
        macd_diff > 0 and adx > params['min_trend_strength']):
        return "BUY"
    
    # Bearish: Fast EMA crosses below Slow EMA
    elif (prev_ema_fast >= prev_ema_slow and ema_fast < ema_slow and 
          macd_diff < 0 and adx > params['min_trend_strength']):
        return "SELL"
    
    return "HOLD"

def execute_breakout(df: pd.DataFrame, params: dict):
    """Стратегия пробоя"""
    last = df.iloc[-1]
    
    close = df['close'].iloc[-1]
    bb_upper = last['bb_upper']
    bb_lower = last['bb_lower']
    bb_width = last['bb_width']
    volume_ratio = last['volume_ratio']
    
    # Условия для пробоя:
    # 1. BB расширяются (волатильность)
    # 2. Высокий объём
    
    if (bb_width > params['bb_expansion'] and 
        volume_ratio > params['volume_multiplier']):
        
        # Пробой вверх
        if close > bb_upper:
            return "BUY"
        # Пробой вниз
        elif close < bb_lower:
            return "SELL"
    
    return "HOLD"

def execute_grid(df: pd.DataFrame, params: dict):
    """Grid торговля (упрощённая версия)"""
    # Grid торговля требует отдельной логики с уровнями
    # Здесь упрощённая версия
    
    last = df.iloc[-1]
    close = df['close'].iloc[-1]
    bb_middle = last['bb_middle']
    
    # Покупаем ниже middle, продаём выше
    distance = abs(close - bb_middle) / bb_middle
    
    if distance > params['grid_spacing']:
        if close < bb_middle:
            return "BUY"
        elif close > bb_middle:
            return "SELL"
    
    return "HOLD"

# ═══════════════════════════════════════════════════════════════
# ГЛАВНАЯ ФУНКЦИЯ АНАЛИЗА
# ═══════════════════════════════════════════════════════════════

def analyze_with_multi_strategy(df_raw: pd.DataFrame, confluence_score: float):
    """Полный анализ с автовыбором стратегии"""
    
    # Подготовь данные
    df = prepare_data(df_raw)
    
    # Выбери стратегию
    strategy, params = select_best_strategy(df, confluence_score)
    
    # Выполни выбранную стратегию
    signal = "HOLD"
    
    if strategy == "MEAN_REVERSION":
        signal = execute_mean_reversion(df, params)
    elif strategy == "MOMENTUM":
        signal = execute_momentum(df, params)
    elif strategy == "BREAKOUT":
        signal = execute_breakout(df, params)
    elif strategy == "GRID":
        signal = execute_grid(df, params)
    
    print(f"\n🎯 Final Signal: {signal}")
    
    return {
        "signal": signal,
        "strategy": strategy,
        "params": params
    }

# ПРИМЕР ИСПОЛЬЗОВАНИЯ
# df_raw = твои_данные_с_биржи  # должен содержать OHLCV
# result = analyze_with_multi_strategy(df_raw, confluence_score=75)
```

---

## ПРИМЕР 4: Полная интеграция (30 минут)

### Файл: `integrated_bot.py`

```python
"""
Полная интеграция всех модулей в один бот
"""

from bot_ultimate_upgrade import (
    NewsEngine,
    RiskManager,
    StrategyRouter,
    FeatureEngine,
    PerformanceTracker
)
import pandas as pd
from datetime import datetime

class EnhancedTradingBot:
    """Твой бот с супер-прокачкой"""
    
    def __init__(
        self,
        bybit_api_key: str,
        bybit_secret: str,
        cryptopanic_key: str,
        initial_capital: float = 10000.0
    ):
        # Твой существующий клиент Bybit
        # from bybit_client import BybitClient
        # self.bybit = BybitClient(bybit_api_key, bybit_secret)
        
        # Новые модули
        self.news = NewsEngine(cryptopanic_key)
        self.risk = RiskManager(initial_capital)
        self.tracker = PerformanceTracker()
        
        print("✅ Enhanced Trading Bot initialized")
    
    def analyze(self, symbol: str, df_raw: pd.DataFrame) -> dict:
        """Полный анализ с использованием всех модулей"""
        
        print(f"\n{'='*60}")
        print(f"🔍 Analyzing {symbol} at {datetime.now()}")
        print(f"{'='*60}")
        
        # 1. ПОДГОТОВКА ДАННЫХ
        df = FeatureEngine.create_features(df_raw)
        
        # 2. НОВОСТИ
        currency = symbol.replace("USDT", "")
        news_sentiment = self.news.get_market_sentiment(currency)
        
        print(f"\n📰 News Sentiment: {news_sentiment['score']:.2f}")
        
        # Критические события?
        if news_sentiment['critical_events']:
            print("⚠️ Critical events detected!")
            if news_sentiment['score'] < -0.5:
                return {"signal": "HOLD", "reason": "Negative news"}
        
        # 3. CONFLUENCE SCORE (твоя логика + новости)
        confluence = self._calculate_confluence(df, news_sentiment)
        print(f"📊 Confluence Score: {confluence:.0f}/100")
        
        # 4. ВЫБОР СТРАТЕГИИ
        market_regime = StrategyRouter.detect_market_regime(df)
        strategy = StrategyRouter.select_strategy(market_regime, confluence)
        
        print(f"🎯 Market: {market_regime['regime']}")
        print(f"📈 Strategy: {strategy}")
        
        # 5. ГЕНЕРАЦИЯ СИГНАЛА
        signal = self._generate_signal(df, strategy, confluence)
        
        if signal == "HOLD":
            return {"signal": "HOLD", "reason": "No setup"}
        
        # 6. RISK MANAGEMENT
        current_price = df['close'].iloc[-1]
        atr = df['atr'].iloc[-1]
        
        stop_loss = self.risk.calculate_stop_loss(
            current_price, atr, "long" if signal == "BUY" else "short"
        )
        
        # Размер позиции
        metrics = self.tracker.get_metrics()
        position_size = self.risk.calculate_position_size(
            win_rate=metrics.get('win_rate', 50) / 100,
            avg_win=metrics.get('avg_win', 100),
            avg_loss=metrics.get('avg_loss', 50),
            current_price=current_price,
            stop_loss_pct=abs(current_price - stop_loss) / current_price
        )
        
        # 7. РЕЗУЛЬТАТ
        result = {
            "signal": signal,
            "strategy": strategy,
            "entry": current_price,
            "stop_loss": stop_loss,
            "size": position_size,
            "confluence": confluence,
            "news_sentiment": news_sentiment['score']
        }
        
        print(f"\n🎯 SIGNAL: {signal}")
        print(f"   Entry: ${current_price:.2f}")
        print(f"   Stop: ${stop_loss:.2f}")
        print(f"   Size: {position_size:.4f}")
        
        return result
    
    def _calculate_confluence(self, df: pd.DataFrame, news: dict) -> float:
        """Рассчитывает confluence (твоя логика + новости)"""
        score = 0
        last = df.iloc[-1]
        
        # RSI
        rsi = last['rsi_14']
        if rsi < 20 or rsi > 80:
            score += 25
        elif rsi < 30 or rsi > 70:
            score += 15
        
        # Bollinger Bands
        bb_pband = last['bb_pband']
        if bb_pband < 0 or bb_pband > 1:
            score += 15
        
        # ADX
        if last['adx'] > 25:
            score += 10
        
        # Volume
        if last['volume_ratio'] > 1.5:
            score += 10
        
        # НОВОЕ: Новости
        if news['score'] > 0.3:
            score += 20
        elif news['score'] < -0.3:
            score -= 20
        
        return max(0, min(score, 100))
    
    def _generate_signal(self, df: pd.DataFrame, strategy: str, confluence: float) -> str:
        """Генерирует сигнал по выбранной стратегии"""
        last = df.iloc[-1]
        
        if strategy == "MEAN_REVERSION" and confluence >= 70:
            if last['rsi_14'] < 30:
                return "BUY"
            elif last['rsi_14'] > 70:
                return "SELL"
        
        elif strategy == "MOMENTUM":
            if last['ema_9'] > last['ema_21'] and last['macd_diff'] > 0:
                return "BUY"
            elif last['ema_9'] < last['ema_21'] and last['macd_diff'] < 0:
                return "SELL"
        
        return "HOLD"
    
    def execute_trade(self, analysis: dict, symbol: str):
        """Выполнение сделки (заглушка для твоего execution)"""
        if analysis['signal'] == "HOLD":
            return
        
        print(f"\n💼 Executing trade...")
        
        # Здесь твоя логика размещения ордера через Bybit
        # self.bybit.place_order(...)
        
        # Запись в трекер
        trade = {
            "symbol": symbol,
            "entry_price": analysis['entry'],
            "exit_price": 0,  # будет обновлено при закрытии
            "size": analysis['size'],
            "pnl": 0,
            "strategy": analysis['strategy'],
            "timestamp": datetime.now()
        }
        
        # self.tracker.add_trade(trade)
        
        print("✅ Trade executed")
    
    def run(self, symbols: list = ["BTCUSDT"]):
        """Главный цикл бота"""
        print("\n🚀 Starting Enhanced Trading Bot...")
        
        for symbol in symbols:
            # Получи данные
            # df = self.bybit.get_klines(symbol, "15")
            
            # Для демо используем заглушку
            df = self._get_demo_data()
            
            # Анализ
            analysis = self.analyze(symbol, df)
            
            # Выполнение
            if not self.risk.circuit_triggered:
                self.execute_trade(analysis, symbol)
            else:
                print("🚨 Circuit breaker active - skipping trade")
        
        # Отчёт
        self.tracker.print_report()
    
    def _get_demo_data(self) -> pd.DataFrame:
        """Demo данные для тестирования"""
        import numpy as np
        np.random.seed(42)
        
        n = 200
        close = 50000 * (1 + np.random.randn(n) * 0.001).cumprod()
        high = close * (1 + abs(np.random.randn(n) * 0.005))
        low = close * (1 - abs(np.random.randn(n) * 0.005))
        open_p = np.roll(close, 1)
        volume = np.random.randint(1000000, 5000000, n)
        
        return pd.DataFrame({
            'open': open_p,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume
        })

# ═══════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    bot = EnhancedTradingBot(
        bybit_api_key="YOUR_KEY",
        bybit_secret="YOUR_SECRET",
        cryptopanic_key="YOUR_CRYPTOPANIC_KEY",
        initial_capital=10000.0
    )
    
    bot.run(symbols=["BTCUSDT", "ETHUSDT"])
```

---

## ПРИМЕР 5: Получение исторических данных с Bybit

### Файл: `get_historical_data.py`

```python
"""
Скачивание исторических данных для обучения ML моделей
"""

import requests
import pandas as pd
from datetime import datetime, timedelta
import time

def get_bybit_klines(
    symbol: str = "BTCUSDT",
    interval: str = "15",  # минуты: 1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, W, M
    days: int = 180  # 6 месяцев
) -> pd.DataFrame:
    """
    Получает исторические данные с Bybit
    """
    
    url = "https://api.bybit.com/v5/market/kline"
    
    # Конвертация интервала
    interval_map = {
        "1": 1, "3": 3, "5": 5, "15": 15, "30": 30,
        "60": 60, "120": 120, "240": 240, "360": 360, "720": 720,
        "D": "D", "W": "W", "M": "M"
    }
    
    all_data = []
    
    # Bybit возвращает макс 200 свечей за запрос
    # Рассчитаем количество запросов
    if interval.isdigit():
        candles_per_day = 24 * 60 / int(interval)
        total_candles = days * candles_per_day
        num_requests = int(total_candles / 200) + 1
    else:
        num_requests = days  # для D, W, M
    
    end_time = int(datetime.now().timestamp() * 1000)
    
    print(f"📥 Downloading {days} days of {interval}m data for {symbol}...")
    
    for i in range(num_requests):
        params = {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "end": end_time,
            "limit": 200
        }
        
        try:
            response = requests.get(url, params=params)
            data = response.json()
            
            if data.get("retCode") == 0:
                klines = data["result"]["list"]
                
                if not klines:
                    break
                
                all_data.extend(klines)
                
                # Следующий запрос - более старые данные
                end_time = int(klines[-1][0]) - 1
                
                print(f"   Progress: {i+1}/{num_requests} requests", end='\r')
                
                # Rate limiting
                time.sleep(0.1)
            else:
                print(f"\n❌ Error: {data.get('retMsg')}")
                break
                
        except Exception as e:
            print(f"\n❌ Error: {e}")
            break
    
    print(f"\n✅ Downloaded {len(all_data)} candles")
    
    # Конвертация в DataFrame
    df = pd.DataFrame(all_data, columns=[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 'turnover'
    ])
    
    # Конвертация типов
    df['timestamp'] = pd.to_datetime(df['timestamp'].astype(float), unit='ms')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = df[col].astype(float)
    
    # Сортировка по времени
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    return df

# ═══════════════════════════════════════════════════════════════
# ИСПОЛЬЗОВАНИЕ
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Скачать данные
    df = get_bybit_klines(
        symbol="BTCUSDT",
        interval="15",
        days=180
    )
    
    # Сохранить в CSV
    filename = "btc_historical_15m.csv"
    df.to_csv(filename, index=False)
    print(f"💾 Saved to {filename}")
    
    # Показать первые строки
    print(df.head())
    print(df.tail())
```

---

## 🎯 QUICK WINS - Что делать ПРЯМО СЕЙЧАС

### Шаг 1: Протестируй NewsEngine
```bash
python add_news_to_bot.py
```

### Шаг 2: Добавь Risk Management
```bash
python add_risk_management.py
```

### Шаг 3: Скачай исторические данные
```bash
python get_historical_data.py
```

### Шаг 4: Попробуй Multi-Strategy
```bash
python add_multi_strategy.py
```

### Шаг 5: Запусти полную интеграцию
```bash
python integrated_bot.py
```

---

**Все эти примеры готовы к использованию! Просто скопируй и запусти! 🚀**
