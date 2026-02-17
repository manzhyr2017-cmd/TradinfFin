import asyncio
import os
import pandas as pd
import logging
from datetime import datetime
from backtesting import HistoricalDataLoader, Backtester
from mean_reversion_bybit import AdvancedMeanReversionEngine
from strategies.trend_following import TrendFollowingStrategy
from strategies.breakout import BreakoutStrategy
from ai_engine import AIEngine
from bybit_client import BybitClient

from dotenv import load_dotenv

# Загружаем переменные окружения (Proxy, API Keys)
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CollectData")

async def collect_and_train():
    """
    Скрипт для массового сбора данных через бэктесты и обучения модели.
    """
    logger.info("🚀 Starting ML Data Collection & Training...")
    
    # 0. Инициализация
    client = BybitClient()
    loader = HistoricalDataLoader()
    ai = AIEngine()
    
    # Удаляем старые данные если нужно начать с нуля
    # Удаляем старые данные, чтобы структура CSV обновилась
    if os.path.exists("training_data.csv"):
        os.remove("training_data.csv")
        logger.info("Deleted old training_data.csv")
    
    # 1. Получаем ТОП-20 монет по объему
    try:
        symbols_data = client.get_top_symbols_by_volume(top_n=20)
        symbols = [s['symbol'] for s in symbols_data]
        logger.info(f"Top 20 Symbols: {symbols}")
    except Exception as e:
        logger.error(f"Failed to fetch top symbols: {e}")
        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]

    # 2. Список стратегий для прогона
    strategies = [
        AdvancedMeanReversionEngine(),
        TrendFollowingStrategy(),
        BreakoutStrategy()
    ]
    
    # 3. Цикл по монетам и стратегиям
    for symbol in symbols:
        logger.info(f"--- Processing {symbol} ---")
        
        # Скачиваем данные (30 дней по 15м)
        df_15m = loader.fetch_from_bybit(symbol, days=30)
        if df_15m.empty:
            continue
            
        for strategy in strategies:
            strat_name = strategy.__class__.__name__
            logger.info(f"  Running Backtest: {strat_name}")
            
            backtester = Backtester(engine=strategy, risk_per_trade=1.0)
            backtester.collect_data = True # Включаем сбор данных
            
            # Запускаем (данные автоматом пишутся в training_data.csv)
            backtester.run(df_15m, symbol=symbol)

    # 4. Обучение модели
    logger.info("--- Data Collection Complete. Training Model ---")
    if os.path.exists("training_data.csv"):
        # Проверяем, есть ли данные
        df = pd.read_csv("training_data.csv")
        if len(df) > 100:
            results = ai.train_model("training_data.csv")
            logger.info(f"Training Results: {results}")
        else:
             logger.error(f"Not enough data collected ({len(df)} rows). Skipping training.")
    else:
        logger.error("No training data collected! (Bybit API Error?)")

if __name__ == "__main__":
    asyncio.run(collect_and_train())
