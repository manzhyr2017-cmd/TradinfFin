import pandas as pd
import numpy as np
import logging
import os
import joblib
from typing import Dict, Any, Optional, List

# Пропускаем импорт sklearn, если он не установлен, чтобы не крашить остальной код
try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, precision_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("AIEngine")

class AIEngine:
    """
    Модуль ИИ для оценки вероятности успеха сделки.
    Использует RandomForestClassifier.
    """
    
    def __init__(self, model_path: str = "ai_model.pkl"):
        self.model_path = model_path
        self.model = None
        self.features = [
            'rsi_15m', 'rsi_1h', 'rsi_4h',
            'bb_position', 'vol_ratio', 'atr_pct',
            'hour_of_day', 'trend_adx', 'funding_rate',
            'rsi_slope', 'ema_dist', 'bb_width', 'vol_zscore'
        ]
        
        self.load_model()
        
    def load_model(self):
        """Загрузка обученной модели"""
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn not installed. AI disabled.")
            return

        if os.path.exists(self.model_path):
            try:
                self.model = joblib.load(self.model_path)
                logger.info(f"AI Model loaded from {self.model_path}")
            except Exception as e:
                logger.error(f"Error loading model: {e}")
        else:
            logger.info("No trained model found.")

    def train_model(self, data_path: str = "training_data.csv") -> Dict[str, float]:
        """Обучение модели на собранных данных"""
        if not SKLEARN_AVAILABLE:
            return {"error": "scikit-learn missing"}
            
        if not os.path.exists(data_path):
            return {"error": "Training data not found"}
            
        try:
            df = pd.read_csv(data_path)
            if len(df) < 50:
                return {"error": "Not enough data (<50 samples)"}
                
            # Подготовка данных (заполняем пропуски)
            df = df.fillna(0)
            
            X = df[self.features]
            y = df['target'] # 1 (WIN) or 0 (LOSS)
            
            X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
            
            self.model = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42)
            self.model.fit(X_train, y_train)
            
            y_pred = self.model.predict(X_test)
            accuracy = accuracy_score(y_test, y_pred)
            precision = precision_score(y_test, y_pred, zero_division=0)
            
            # Сохраняем
            joblib.dump(self.model, self.model_path)
            logger.info(f"Model trained! Acc: {accuracy:.2f}, Prec: {precision:.2f}")
            
            return {
                "accuracy": accuracy,
                "precision": precision,
                "samples": len(df)
            }
            
        except Exception as e:
            logger.error(f"Training failed: {e}")
            return {"error": str(e)}

    def predict_success_probability(self, signal_data: Dict[str, Any]) -> float:
        """
        Предсказывает вероятность успеха (0.0 - 1.0)
        
        signal_data должен содержать ключи из self.features
        """
        if not self.model or not SKLEARN_AVAILABLE:
            return 0.5 # Нейтральная оценка если нет модели
            
        try:
            # Формируем вектор признаков
            features_dict = {f: 0.0 for f in self.features}
            
            # Заполняем данными
            for k, v in signal_data.items():
                if k in features_dict:
                    features_dict[k] = float(v) if v is not None else 0.0
            
            # Доп. логика для отсутствующих прямо полей
            if 'indicators' in signal_data:
                inds = signal_data['indicators']
                features_dict['rsi_15m'] = inds.get('rsi_15m', 50)
                features_dict['rsi_1h'] = inds.get('rsi_1h', 50)
                features_dict['rsi_4h'] = inds.get('rsi_4h', 50)
                features_dict['bb_position'] = inds.get('bb_position', 0)
                features_dict['vol_ratio'] = inds.get('volume_ratio', 1)
                features_dict['atr_pct'] = inds.get('atr', 0) / signal_data.get('entry_price', 1) * 100
                
            features_dict['funding_rate'] = signal_data.get('funding_rate', 0) or 0
            
            # Превращаем в DataFrame (1 строка)
            X = pd.DataFrame([features_dict])
            
            # Предсказание вероятности (класс 1 = WIN)
            probs = self.model.predict_proba(X)
            win_prob = probs[0][1] # Вероятность класса 1
            
            return win_prob
            
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return 0.5
