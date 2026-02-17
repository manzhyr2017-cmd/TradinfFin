import pandas as pd
import numpy as np
import logging
import os
import joblib
from typing import Dict, Optional, List
import ta

logger = logging.getLogger(__name__)

class FeatureEngine:
    """
    Advanced Feature Engineering inspired by Trading Bot Ultimate Upgrade
    """
    @staticmethod
    def create_features(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        # Ensured lowercase columns
        df.columns = [c.lower() for c in df.columns]
        
        # 1. Momentum + Slopes
        for p in [7, 14, 21, 30]:
            df[f'rsi_{p}'] = ta.momentum.RSIIndicator(df['close'], window=p).rsi()
            df[f'rsi_slope_{p}'] = df[f'rsi_{p}'].diff()
            
        macd = ta.trend.MACD(df['close'])
        df['macd_diff'] = macd.macd_diff()
        
        # 2. Volatility & Liquidity
        bb = ta.volatility.BollingerBands(df['close'])
        df['bb_width'] = bb.bollinger_wband()
        df['bb_position'] = (df['close'] - bb.bollinger_lband()) / (bb.bollinger_hband() - bb.bollinger_lband() + 0.001)
        
        # 3. Market Structure
        for p in [20, 50, 200]:
            df[f'sma_{p}'] = ta.trend.SMAIndicator(df['close'], window=p).ema_indicator()
            df[f'dist_sma_{p}'] = (df['close'] - df[f'sma_{p}']) / (df[f'sma_{p}'] + 0.001)
            
        # 4. ADX & Trend Strength
        df['adx'] = ta.trend.ADXIndicator(df['high'], df['low'], df['close']).adx()
        
        # 5. Volume Flow
        df['mfi'] = ta.volume.MFIIndicator(df['high'], df['low'], df['close'], df['volume']).money_flow_index()
        df['vol_delta'] = df['volume'].pct_change()
        
        return df.fillna(method='ffill').fillna(0)

class MLService:
    """
    Machine Learning Triple Ensemble Service (XGBoost + LightGBM + Random Forest)
    """
    def __init__(self, model_dir: str = "models"):
        self.model_dir = model_dir
        self.xgb_model = None
        self.lgb_model = None
        self.rf_model = None
        self.is_ready = False
        
        if not os.path.exists(self.model_dir):
            os.makedirs(self.model_dir)
            
        self._load_models()
        
    def _load_models(self):
        xgb_path = os.path.join(self.model_dir, "xgb_model.pkl")
        lgb_path = os.path.join(self.model_dir, "lgb_model.pkl")
        rf_path = os.path.join(self.model_dir, "rf_model.pkl")
        
        if os.path.exists(xgb_path) and os.path.exists(lgb_path):
            try:
                self.xgb_model = joblib.load(xgb_path)
                self.lgb_model = joblib.load(lgb_path)
                if os.path.exists(rf_path):
                    from sklearn.ensemble import RandomForestRegressor
                    self.rf_model = joblib.load(rf_path)
                self.is_ready = True
                logger.info("✅ ML Triple Ensemble loaded successfully")
            except Exception as e:
                logger.error(f"❌ Failed to load ML models: {e}")
        else:
            logger.warning("⚠️ ML Models not found. Training required.")

    def predict(self, df: pd.DataFrame) -> Dict:
        """
        Predicts price direction (Ensemble: XGB + LGB + RF)
        """
        if not self.is_ready:
            return {"prediction": 0, "confidence": 0, "status": "no_model"}
            
        try:
            features_df = FeatureEngine.create_features(df).tail(1)
            X = features_df.select_dtypes(include=[np.number])
            
            xgb_p = self.xgb_model.predict(X)[0]
            lgb_p = self.lgb_model.predict(X)[0]
            
            # Use RF if loaded
            rf_p = lgb_p # Fallback
            if hasattr(self, 'rf_model'):
                rf_p = self.rf_model.predict(X)[0]
            
            # Weighted Ensemble: XGB (40%), LGB (35%), RF (25%)
            final_pred = (xgb_p * 0.4 + lgb_p * 0.35 + rf_p * 0.25)
            
            # Agreement confidence
            std_dev = np.std([xgb_p, lgb_p, rf_p])
            confidence = max(0, 1.0 - (std_dev * 10)) # Penalty for disagreement
            
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
            
            # Random Forest (Triple Ensemble)
            from sklearn.ensemble import RandomForestRegressor
            self.rf_model = RandomForestRegressor(n_estimators=100, max_depth=5)
            self.rf_model.fit(X, y)
            
            # Save
            joblib.dump(self.xgb_model, os.path.join(self.model_dir, "xgb_model.pkl"))
            joblib.dump(self.lgb_model, os.path.join(self.model_dir, "lgb_model.pkl"))
            joblib.dump(self.rf_model, os.path.join(self.model_dir, "rf_model.pkl"))
            
            self.is_ready = True
            logger.info("✅ ML Triple Ensemble training completed and saved")
            return True
        except Exception as e:
            logger.error(f"❌ ML Training failed: {e}")
            return False
