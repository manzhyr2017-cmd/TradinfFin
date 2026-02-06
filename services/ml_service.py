import pandas as pd
import numpy as np
import logging
import os
import joblib
from typing import Dict, Optional, List
import xgboost as xgb
from lightgbm import LGBMRegressor
import ta

logger = logging.getLogger(__name__)

class FeatureEngine:
    """
    Advanced Feature Engineering inspired by Trading Bot Ultimate Upgrade
    """
    @staticmethod
    def create_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        
        # Ensure column names are lowercase
        df.columns = [c.lower() for c in df.columns]
        
        # 1. Momentum Indicators
        for p in [7, 14, 21, 30]:
            df[f'rsi_{p}'] = ta.momentum.RSIIndicator(df['close'], window=p).rsi()
            
        macd = ta.trend.MACD(df['close'])
        df['macd'] = macd.macd()
        df['macd_signal'] = macd.macd_signal()
        df['macd_diff'] = macd.macd_diff()
        
        # 2. Volatility Indicators
        bb = ta.volatility.BollingerBands(df['close'])
        df['bb_upper'] = bb.bollinger_hband()
        df['bb_lower'] = bb.bollinger_lband()
        df['bb_width'] = bb.bollinger_wband()
        
        df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close']).average_true_range()
        
        # 3. Trend Indicators
        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()
        
        for p in [9, 21, 50, 200]:
            df[f'ema_{p}'] = ta.trend.EMAIndicator(df['close'], window=p).ema_indicator()
            
        # 4. Volume Indicators
        df['obv'] = ta.volume.OnBalanceVolumeIndicator(df['close'], df['volume']).on_balance_volume()
        df['mfi'] = ta.volume.MFIIndicator(df['high'], df['low'], df['close'], df['volume']).money_flow_index()
        
        # 5. Price Derivatives
        for p in [1, 3, 5, 10]:
            df[f'return_{p}'] = df['close'].pct_change(p)
            
        # Distance from EMAs
        df['dist_ema_50'] = (df['close'] - df['ema_50']) / df['ema_50']
        df['dist_ema_200'] = (df['close'] - df['ema_200']) / df['ema_200']
        
        # Fill NaN values
        df = df.fillna(method='ffill').fillna(0)
        
        return df

class MLService:
    """
    Machine Learning Ensemble Service (XGBoost + LightGBM)
    """
    def __init__(self, model_dir: str = "models"):
        self.model_dir = model_dir
        self.xgb_model = None
        self.lgb_model = None
        self.is_ready = False
        
        if not os.path.exists(self.model_dir):
            os.makedirs(self.model_dir)
            
        self._load_models()
        
    def _load_models(self):
        xgb_path = os.path.join(self.model_dir, "xgb_model.pkl")
        lgb_path = os.path.join(self.model_dir, "lgb_model.pkl")
        
        if os.path.exists(xgb_path) and os.path.exists(lgb_path):
            try:
                self.xgb_model = joblib.load(xgb_path)
                self.lgb_model = joblib.load(lgb_path)
                self.is_ready = True
                logger.info("✅ ML Models loaded successfully")
            except Exception as e:
                logger.error(f"❌ Failed to load ML models: {e}")
        else:
            logger.warning("⚠️ ML Models not found. Training required.")

    def predict(self, df: pd.DataFrame) -> Dict:
        """
        Predicts price direction or success probability
        """
        if not self.is_ready:
            return {"prediction": 0, "confidence": 0, "status": "no_model"}
            
        try:
            # Prepare features
            features_df = FeatureEngine.create_features(df).tail(1)
            
            # Select only numeric features for prediction (excluding OHLCV)
            X = features_df.drop(['open', 'high', 'low', 'close', 'volume'], axis=1, errors='ignore')
            # Handle potential timestamp or other non-numeric cols
            X = X.select_dtypes(include=[np.number])
            
            xgb_pred = self.xgb_model.predict(X)[0]
            lgb_pred = self.lgb_model.predict(X)[0]
            
            # Simple average ensemble
            final_pred = (xgb_pred * 0.6 + lgb_pred * 0.4)
            
            # Confidence is based on agreement between models
            diff = abs(xgb_pred - lgb_pred)
            confidence = max(0, 1.0 - diff)
            
            return {
                "prediction": float(final_pred),
                "confidence": float(confidence),
                "status": "ok"
            }
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return {"prediction": 0, "confidence": 0, "status": f"error: {str(e)}"}

    def train_on_data(self, df: pd.DataFrame, target_shift: int = 4):
        """
        Train ensemble on historical data
        """
        logger.info(f"🔄 Training ML Ensemble on {len(df)} candles...")
        
        try:
            df_feat = FeatureEngine.create_features(df)
            
            # Target is price change after target_shift bars
            df_feat['target'] = (df_feat['close'].shift(-target_shift) - df_feat['close']) / df_feat['close']
            df_feat = df_feat.dropna()
            
            X = df_feat.drop(['open', 'high', 'low', 'close', 'volume', 'target'], axis=1, errors='ignore')
            X = X.select_dtypes(include=[np.number])
            y = df_feat['target']
            
            # XGBoost
            self.xgb_model = xgb.XGBRegressor(n_estimators=100, max_depth=5, learning_rate=0.1)
            self.xgb_model.fit(X, y)
            
            # LightGBM
            self.lgb_model = LGBMRegressor(n_estimators=100, max_depth=5, learning_rate=0.1)
            self.lgb_model.fit(X, y)
            
            # Save
            joblib.dump(self.xgb_model, os.path.join(self.model_dir, "xgb_model.pkl"))
            joblib.dump(self.lgb_model, os.path.join(self.model_dir, "lgb_model.pkl"))
            
            self.is_ready = True
            logger.info("✅ ML Ensemble training completed and saved")
            return True
        except Exception as e:
            logger.error(f"❌ ML Training failed: {e}")
            return False
