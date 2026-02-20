"""
TITAN BOT 2026 - ML Engine
Машинное обучение для предсказания движения цены
"""

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score
import joblib
import os
from datetime import datetime
import config

class MLEngine:
    """
    Движок машинного обучения.
    
    Особенности:
    1. Walk-Forward Validation (не смотрим в будущее)
    2. Feature Engineering (правильные признаки)
    3. Целевая переменная = "Цена вырастет на X% до того, как упадет на Y%"
    """
    
    def __init__(self, data_engine):
        self.data = data_engine
        self.model = None
        self.scaler = StandardScaler()
        self.is_trained = False
        self.feature_columns = []
        
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Подготовка признаков для ML.
        
        НЕ используем: абсолютные цены, время
        Используем: относительные изменения, нормализованные индикаторы
        """
        features = pd.DataFrame(index=df.index)
        
        # === ЦЕНОВЫЕ ПРИЗНАКИ (относительные) ===
        
        # Изменение цены за N периодов
        for period in [1, 3, 5, 10, 20]:
            features[f'return_{period}'] = df['close'].pct_change(period)
        
        # Волатильность
        features['volatility_10'] = df['close'].pct_change().rolling(10).std()
        features['volatility_20'] = df['close'].pct_change().rolling(20).std()
        
        # Позиция цены относительно EMA
        features['price_vs_ema20'] = (df['close'] - df['ema_20']) / df['ema_20']
        features['price_vs_ema50'] = (df['close'] - df['ema_50']) / df['ema_50']
        
        # Тренд EMA
        features['ema_trend'] = (df['ema_20'] - df['ema_50']) / df['ema_50']
        
        # === ОБЪЕМНЫЕ ПРИЗНАКИ ===
        
        # Относительный объем
        features['volume_ratio'] = df['volume_ratio']
        
        # Изменение объема
        features['volume_change'] = df['volume'].pct_change(5)
        
        # === СВЕЧНЫЕ ПАТТЕРНЫ ===
        
        # Размер тела относительно ATR
        features['body_atr_ratio'] = df['body_size'] / df['atr']
        
        # Соотношение теней
        total_range = df['high'] - df['low']
        features['upper_wick_ratio'] = df['wick_upper'] / total_range.replace(0, np.nan)
        features['lower_wick_ratio'] = df['wick_lower'] / total_range.replace(0, np.nan)
        
        # Бычья/медвежья свеча
        features['is_bullish'] = df['is_bullish'].astype(int)
        
        # === ВРЕМЕННЫЕ ПРИЗНАКИ ===
        
        # Час торговли (для определения сессии)
        features['hour'] = df['timestamp'].dt.hour
        features['hour_sin'] = np.sin(2 * np.pi * features['hour'] / 24)
        features['hour_cos'] = np.cos(2 * np.pi * features['hour'] / 24)
        
        # День недели
        features['dayofweek'] = df['timestamp'].dt.dayofweek
        features['is_weekend'] = (features['dayofweek'] >= 5).astype(int)
        
        # === МОМЕНТУМ ===
        
        # RSI нормализованный
        rsi = self._calculate_rsi(df['close'], 14)
        features['rsi_normalized'] = (rsi - 50) / 50  # от -1 до 1
        
        # Сохраняем список колонок
        self.feature_columns = features.columns.tolist()
        
        return features
    
    def create_target(self, df: pd.DataFrame, profit_target: float = 0.015, stop_target: float = 0.01) -> pd.Series:
        """
        Создает целевую переменную.
        
        Target = 1, если цена сначала достигает +profit_target%
                 0, если цена сначала достигает -stop_target%
        
        Это более реалистично, чем просто "цена через N свечей".
        """
        target = pd.Series(index=df.index, dtype=float)
        
        for i in range(len(df) - 50):  # Оставляем запас
            entry_price = df['close'].iloc[i]
            
            take_profit = entry_price * (1 + profit_target)
            stop_loss = entry_price * (1 - stop_target)
            
            # Смотрим следующие 50 свечей
            for j in range(i + 1, min(i + 50, len(df))):
                high = df['high'].iloc[j]
                low = df['low'].iloc[j]
                
                # Сначала проверяем стоп (консервативно)
                if low <= stop_loss:
                    target.iloc[i] = 0
                    break
                
                if high >= take_profit:
                    target.iloc[i] = 1
                    break
            else:
                # Если ни один уровень не достигнут за 50 свечей
                target.iloc[i] = np.nan
        
        return target
    
    def train(self, symbol: str = None, days: int = None):
        """
        Обучает модель с Walk-Forward Validation.
        """
        if symbol is None:
            symbol = config.SYMBOL
        if days is None:
            days = config.ML_TRAINING_DAYS
        
        print(f"[MLEngine] Начало обучения на {days} дней данных...")
        
        # Получаем данные (максимум что дает API)
        df = self.data.get_klines(symbol, limit=1000)
        
        if df is None or len(df) < 200:
            print("[MLEngine] Недостаточно данных для обучения")
            return False
        
        # Подготовка признаков и целевой переменной
        features = self.prepare_features(df)
        target = self.create_target(df)
        
        # Объединяем и убираем NaN
        data = pd.concat([features, target.rename('target')], axis=1)
        data = data.dropna()
        
        if len(data) < 100:
            print("[MLEngine] Недостаточно валидных данных")
            return False
        
        X = data[self.feature_columns]
        y = data['target']
        
        # Walk-Forward Split
        tscv = TimeSeriesSplit(n_splits=5)
        
        scores = []
        
        for train_idx, test_idx in tscv.split(X):
            X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
            y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
            
            # Масштабирование
            X_train_scaled = self.scaler.fit_transform(X_train)
            X_test_scaled = self.scaler.transform(X_test)
            
            # Обучение
            model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.1,
                random_state=42
            )
            model.fit(X_train_scaled, y_train)
            
            # Оценка
            y_pred = model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            precision = precision_score(y_test, y_pred, zero_division=0)
            
            scores.append({'accuracy': accuracy, 'precision': precision})
        
        # Финальное обучение на всех данных
        X_scaled = self.scaler.fit_transform(X)
        self.model = GradientBoostingClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            random_state=42
        )
        self.model.fit(X_scaled, y)
        
        # Статистика
        avg_accuracy = np.mean([s['accuracy'] for s in scores])
        avg_precision = np.mean([s['precision'] for s in scores])
        
        print(f"[MLEngine] Обучение завершено!")
        print(f"[MLEngine] Avg Accuracy: {avg_accuracy:.2%}")
        print(f"[MLEngine] Avg Precision: {avg_precision:.2%}")
        
        self.is_trained = True
        
        # Сохраняем модель
        self.save_model()
        
        return True
    
    def predict(self, symbol: str = None) -> dict:
        """
        Делает предсказание на текущих данных.
        
        Returns:
            dict с prediction (0/1), probability, confidence
        """
        if not self.is_trained:
            return {'prediction': None, 'probability': 0.5, 'confidence': 0}
        
        if symbol is None:
            symbol = config.SYMBOL
        
        # Получаем свежие данные
        df = self.data.get_klines(symbol, limit=100)
        
        if df is None:
            return {'prediction': None, 'probability': 0.5, 'confidence': 0}
        
        # Подготовка признаков
        features = self.prepare_features(df)
        
        # Берем последнюю строку (текущий момент)
        X = features[self.feature_columns].iloc[[-1]]
        
        # Убираем NaN
        if X.isna().any().any():
            return {'prediction': None, 'probability': 0.5, 'confidence': 0}
        
        # Масштабирование
        X_scaled = self.scaler.transform(X)
        
        # Предсказание
        prediction = self.model.predict(X_scaled)[0]
        probabilities = self.model.predict_proba(X_scaled)[0]
        
        # Уверенность = насколько далеко от 50%
        confidence = abs(probabilities[1] - 0.5) * 2
        
        return {
            'prediction': int(prediction),
            'probability': probabilities[1],
            'confidence': confidence,
            'signal': 'LONG' if prediction == 1 else 'NEUTRAL'
        }
    
    def get_features_dict(self, symbol: str) -> dict:
        """Возвращает текущий вектор признаков в виде словаря для БД."""
        try:
            df = self.data.get_klines(symbol, limit=100)
            if df is None: return {}
            features = self.prepare_features(df)
            last_row = features.iloc[-1].fillna(0).to_dict()
            return last_row
        except:
            return {}

    def save_model(self):
        """Сохраняет модель на диск."""
        os.makedirs(os.path.dirname(config.ML_MODEL_PATH), exist_ok=True)
        
        joblib.dump({
            'model': self.model,
            'scaler': self.scaler,
            'feature_columns': self.feature_columns
        }, config.ML_MODEL_PATH)
        
        print(f"[MLEngine] Модель сохранена: {config.ML_MODEL_PATH}")
    
    def load_model(self) -> bool:
        """Загружает модель с диска."""
        if not os.path.exists(config.ML_MODEL_PATH):
            print("[MLEngine] Модель не найдена")
            return False
        
        try:
            data = joblib.load(config.ML_MODEL_PATH)
            self.model = data['model']
            self.scaler = data['scaler']
            self.feature_columns = data['feature_columns']
            self.is_trained = True
            print("[MLEngine] Модель загружена")
            return True
        except Exception as e:
            print(f"[MLEngine] Ошибка загрузки модели: {e}")
            return False
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Расчет RSI."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
