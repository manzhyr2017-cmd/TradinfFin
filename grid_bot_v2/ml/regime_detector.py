import numpy as np
import pickle
import logging
from pathlib import Path
from typing import List, Tuple, Optional
from decimal import Decimal
from datetime import datetime

from enum import Enum

log = logging.getLogger("GridBot")

class MarketRegime(Enum):
    SIDEWAYS = 0
    UPTREND = 1
    DOWNTREND = 2
    VOLATILE = 3
    UNKNOWN = -1

# ─── Пробуем импортировать ML библиотеки ─────────────
try:
    import lightgbm as lgb
    HAS_LGB = True
except ImportError:
    HAS_LGB = False
    log.warning(
        "⚠️ LightGBM не установлен. "
        "pip install lightgbm для ML-режима"
    )

try:
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import classification_report
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False
    log.warning("⚠️ scikit-learn не установлен")


class FeatureEngine:
    """
    Генерация фичей из свечных данных.
    Каждая фича — это числовая характеристика рынка,
    которую модель использует для классификации.
    """

    @staticmethod
    def compute_features(
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
    ) -> dict:
        """
        Из одного окна свечей генерируем ~40 фичей.
        Каждая фича несёт уникальную информацию о состоянии рынка.
        """
        n = len(closes)
        if n < 30:
            return {}

        features = {}

        # ─── 1. ЦЕНОВЫЕ ФИЧИ ─────────────────────────

        # Возвраты (returns) за разные периоды
        returns = np.diff(closes) / closes[:-1]
        features["return_1"] = returns[-1]         # Последний возврат
        features["return_5"] = (
            (closes[-1] - closes[-6]) / closes[-6]
            if n > 5 else 0
        )
        features["return_10"] = (
            (closes[-1] - closes[-11]) / closes[-11]
            if n > 10 else 0
        )
        features["return_20"] = (
            (closes[-1] - closes[-21]) / closes[-21]
            if n > 20 else 0
        )

        # ─── 2. ВОЛАТИЛЬНОСТЬ ─────────────────────────

        # Стандартное отклонение возвратов (историческая волатильность)
        features["volatility_5"] = np.std(returns[-5:])
        features["volatility_10"] = np.std(returns[-10:])
        features["volatility_20"] = np.std(returns[-20:])

        # Отношение короткой к длинной волатильности
        # >1 = волатильность растёт, <1 = падает
        features["vol_ratio_5_20"] = (
            features["volatility_5"] / features["volatility_20"]
            if features["volatility_20"] > 0 else 1
        )

        # ATR (Average True Range) нормализованный
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1]),
            ),
        )
        atr_14 = np.mean(tr[-14:]) if len(tr) >= 14 else np.mean(tr)
        features["atr_norm"] = atr_14 / closes[-1]  # % от цены

        # ─── 3. ТРЕНДОВЫЕ ФИЧИ ───────────────────────

        # EMA и их соотношения
        def ema(data, period):
            alpha = 2 / (period + 1)
            result = np.zeros_like(data, dtype=float)
            result[0] = data[0]
            for i in range(1, len(data)):
                result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
            return result

        ema_9 = ema(closes, 9)
        ema_21 = ema(closes, 21)
        ema_50 = ema(closes, 50) if n >= 50 else ema(closes, n)

        # Расстояние цены от EMA (нормализованное)
        features["price_vs_ema9"] = (
            (closes[-1] - ema_9[-1]) / ema_9[-1]
        )
        features["price_vs_ema21"] = (
            (closes[-1] - ema_21[-1]) / ema_21[-1]
        )

        # EMA crossover
        features["ema_diff_9_21"] = (
            (ema_9[-1] - ema_21[-1]) / ema_21[-1]
        )

        # Наклон EMA (скорость тренда)
        features["ema9_slope"] = (
            (ema_9[-1] - ema_9[-5]) / ema_9[-5] if n > 5 else 0
        )
        features["ema21_slope"] = (
            (ema_21[-1] - ema_21[-5]) / ema_21[-5] if n > 5 else 0
        )

        # ─── 4. ОСЦИЛЛЯТОРЫ ──────────────────────────

        # RSI
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains[-14:])
        avg_loss = np.mean(losses[-14:])
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            features["rsi_14"] = 100 - (100 / (1 + rs))
        else:
            features["rsi_14"] = 100

        # Stochastic RSI (RSI от RSI — более чувствительный)
        rsi_values = []
        for i in range(14, n):
            g = np.mean(np.where(
                np.diff(closes[i-14:i+1]) > 0,
                np.diff(closes[i-14:i+1]), 0
            ))
            l = np.mean(np.where(
                np.diff(closes[i-14:i+1]) < 0,
                -np.diff(closes[i-14:i+1]), 0
            ))
            if l > 0:
                rsi_values.append(100 - (100 / (1 + g / l)))
            else:
                rsi_values.append(100)

        if len(rsi_values) >= 14:
            rsi_arr = np.array(rsi_values[-14:])
            rsi_min = np.min(rsi_arr)
            rsi_max = np.max(rsi_arr)
            features["stoch_rsi"] = (
                (rsi_arr[-1] - rsi_min) / (rsi_max - rsi_min)
                if rsi_max > rsi_min else 0.5
            )
        else:
            features["stoch_rsi"] = 0.5

        # ─── 5. ОБЪЁМНЫЕ ФИЧИ ────────────────────────

        # Средний объём
        avg_vol_20 = np.mean(volumes[-20:])
        features["volume_ratio"] = (
            volumes[-1] / avg_vol_20 if avg_vol_20 > 0 else 1
        )

        # OBV тренд (On-Balance Volume)
        obv = np.zeros(n)
        for i in range(1, n):
            if closes[i] > closes[i - 1]:
                obv[i] = obv[i - 1] + volumes[i]
            elif closes[i] < closes[i - 1]:
                obv[i] = obv[i - 1] - volumes[i]
            else:
                obv[i] = obv[i - 1]

        obv_ema = ema(obv, 10)
        features["obv_trend"] = (
            (obv[-1] - obv_ema[-1]) / abs(obv_ema[-1])
            if abs(obv_ema[-1]) > 0 else 0
        )

        # Volume-price divergence
        # Цена растёт, а объём падает = слабый тренд
        price_trend = features["return_10"]
        vol_trend = (
            (np.mean(volumes[-5:]) - np.mean(volumes[-15:-5]))
            / np.mean(volumes[-15:-5])
            if np.mean(volumes[-15:-5]) > 0 else 0
        )
        features["vol_price_divergence"] = (
            price_trend * vol_trend  # Отрицательное = дивергенция
        )

        # ─── 6. СВЕЧНЫЕ ПАТТЕРНЫ ─────────────────────

        # Средний размер тела свечи (body)
        bodies = np.abs(closes - opens)
        wicks_upper = highs - np.maximum(closes, opens)
        wicks_lower = np.minimum(closes, opens) - lows
        candle_range = highs - lows

        # Body ratio — какая доля свечи = тело
        features["avg_body_ratio"] = float(np.mean(
            bodies[-10:] / np.maximum(candle_range[-10:], 1e-10)
        ))

        # Upper/lower wick ratio (перевес теней)
        features["wick_imbalance"] = float(np.mean(
            (wicks_upper[-10:] - wicks_lower[-10:])
            / np.maximum(candle_range[-10:], 1e-10)
        ))

        # ─── 7. МИКРОСТРУКТУРА ───────────────────────

        # Количество свечей, закрывшихся выше открытия
        bullish_count = np.sum(closes[-20:] > opens[-20:])
        features["bullish_ratio_20"] = bullish_count / 20

        # Серия подряд идущих бычьих/медвежьих свечей
        streak = 0
        direction = 0
        for i in range(n - 1, max(n - 20, 0), -1):
            if closes[i] > opens[i]:
                if direction >= 0:
                    streak += 1
                    direction = 1
                else:
                    break
            else:
                if direction <= 0:
                    streak -= 1
                    direction = -1
                else:
                    break
        features["candle_streak"] = streak

        # ─── 8. СТАТИСТИЧЕСКИЕ ФИЧИ ──────────────────

        # Skewness (асимметрия) возвратов
        if len(returns) > 5:
            mean_r = np.mean(returns[-20:])
            std_r = np.std(returns[-20:])
            if std_r > 0:
                features["skewness"] = float(np.mean(
                    ((returns[-20:] - mean_r) / std_r) ** 3
                ))
            else:
                features["skewness"] = 0
        else:
            features["skewness"] = 0

        # Kurtosis (толщина хвостов)
        if len(returns) > 5 and std_r > 0:
            features["kurtosis"] = float(np.mean(
                ((returns[-20:] - mean_r) / std_r) ** 4
            )) - 3  # Excess kurtosis
        else:
            features["kurtosis"] = 0

        # Hurst exponent (оценка: тренд vs mean-reversion)
        # H > 0.5 = тренд, H < 0.5 = mean-reversion (грид-рай!)
        # H = 0.5 = случайное блуждание
        features["hurst_estimate"] = (
            FeatureEngine._estimate_hurst(closes[-50:])
            if n >= 50 else 0.5
        )

        return features

    @staticmethod
    def _estimate_hurst(prices: np.ndarray) -> float:
        """
        Упрощённая оценка экспоненты Хёрста.
        H < 0.5 → mean-reverting (ИДЕАЛЬНО для грида!)
        H = 0.5 → random walk
        H > 0.5 → trending (ПЛОХО для грида!)
        """
        n = len(prices)
        if n < 20:
            return 0.5

        returns = np.diff(np.log(prices))
        lags = range(2, min(20, n // 4))
        tau = []
        for lag in lags:
            std = np.std(
                np.subtract(
                    returns[lag:], returns[:-lag]
                )
            )
            if std > 0:
                tau.append(np.log(std))
            else:
                tau.append(0)

        if len(tau) < 3:
            return 0.5

        log_lags = [np.log(l) for l in lags[: len(tau)]]
        try:
            poly = np.polyfit(log_lags, tau, 1)
            hurst = poly[0]
            return max(0.0, min(1.0, hurst))
        except Exception:
            return 0.5


class RegimeLabeler:
    """
    Создаёт метки (labels) для обучения.
    
    КЛЮЧЕВОЙ МОМЕНТ: как определить, что "было" флэтом,
    а что "было" трендом — задним числом?
    
    Метод: смотрим на БУДУЩЕЕ движение цены.
    - Если за следующие N свечей цена осталась в ±X% → SIDEWAYS
    - Если ушла > +X% → UPTREND
    - Если ушла < -X% → DOWNTREND
    - Если волатильность > Y% → VOLATILE
    """

    @staticmethod
    def label_regimes(
        closes: np.ndarray,
        forward_window: int = 20,
        sideways_threshold_pct: float = 1.5,
        volatility_threshold_pct: float = 3.0,
    ) -> np.ndarray:
        """
        Создаём массив меток:
        0 = SIDEWAYS  (грид торгует!)
        1 = UPTREND   (грид осторожен)
        2 = DOWNTREND (грид осторожен)
        3 = VOLATILE  (грид стоит!)
        """
        n = len(closes)
        labels = np.full(n, -1)  # -1 = неизвестно

        for i in range(n - forward_window):
            future = closes[i + 1: i + 1 + forward_window]
            current = closes[i]

            # Максимальное движение вперёд
            max_up = (np.max(future) - current) / current * 100
            max_down = (current - np.min(future)) / current * 100
            net_change = (future[-1] - current) / current * 100
            future_vol = np.std(
                np.diff(future) / future[:-1]
            ) * 100

            # Сначала проверяем хаос
            if future_vol > volatility_threshold_pct:
                labels[i] = 3  # VOLATILE

            # Затем тренд
            elif net_change > sideways_threshold_pct:
                labels[i] = 1  # UPTREND
            elif net_change < -sideways_threshold_pct:
                labels[i] = 2  # DOWNTREND

            # Иначе флэт
            else:
                labels[i] = 0  # SIDEWAYS

        return labels


class MLRegimeDetector:
    """
    ═══════════════════════════════════════════
     ОБУЧАЕМЫЙ ДЕТЕКТОР РЕЖИМА РЫНКА
    ═══════════════════════════════════════════
    
    Обучается на исторических данных.
    Переобучается каждые N часов на свежих данных.
    Заменяет жёсткие RSI/EMA правила.
    """

    MODEL_PATH = Path("models/regime_model.pkl")
    SCALER_PATH = Path("models/regime_scaler.pkl")

    # Названия классов
    REGIME_NAMES = {
        0: "SIDEWAYS",
        1: "UPTREND",
        2: "DOWNTREND",
        3: "VOLATILE",
    }

    def __init__(self):
        self.model = None
        self.scaler = None
        self.feature_names = []
        self.is_trained = False
        self.last_train_time: Optional[datetime] = None
        self.retrain_interval_hours = 6  # Переобучение каждые 6 часов

        # Пробуем загрузить сохранённую модель
        self._try_load_model()

    def _try_load_model(self):
        """Загружаем модель из файла, если есть."""
        try:
            if self.MODEL_PATH.exists() and self.SCALER_PATH.exists():
                with open(self.MODEL_PATH, "rb") as f:
                    self.model = pickle.load(f)
                with open(self.SCALER_PATH, "rb") as f:
                    self.scaler = pickle.load(f)
                self.is_trained = True
                log.info("🧠 ML-модель загружена из файла")
        except Exception as e:
            log.warning(f"Не удалось загрузить ML-модель: {e}")

    def _save_model(self):
        """Сохраняем модель на диск."""
        try:
            self.MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.MODEL_PATH, "wb") as f:
                pickle.dump(self.model, f)
            with open(self.SCALER_PATH, "wb") as f:
                pickle.dump(self.scaler, f)
            log.info("💾 ML-модель сохранена")
        except Exception as e:
            log.error(f"Ошибка сохранения модели: {e}")

    def train(
        self,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
    ) -> dict:
        """
        ═══════════════════════════════════
         ОБУЧЕНИЕ МОДЕЛИ
        ═══════════════════════════════════
        
        Вызывается:
        1. При первом запуске (на исторических данных)
        2. Каждые retrain_interval_hours часов
        """
        if not HAS_LGB or not HAS_SKLEARN:
            log.error("ML библиотеки не установлены!")
            return {"error": "Missing dependencies"}

        n = len(closes)
        if n < 200:
            log.warning(f"Мало данных для обучения: {n} < 200")
            return {"error": "Not enough data"}

        log.info(f"🧠 Обучение ML-модели на {n} свечах...")

        # ① Генерируем фичи для каждого окна
        window_size = 50
        X_list = []
        valid_indices = []

        for i in range(window_size, n):
            features = FeatureEngine.compute_features(
                opens[i - window_size: i + 1],
                highs[i - window_size: i + 1],
                lows[i - window_size: i + 1],
                closes[i - window_size: i + 1],
                volumes[i - window_size: i + 1],
            )
            if features:
                X_list.append(features)
                valid_indices.append(i)

        if not X_list:
            return {"error": "No features generated"}

        # ② Создаём метки
        labels = RegimeLabeler.label_regimes(closes)

        # Фильтруем: берём только точки с валидными метками
        X_filtered = []
        y_filtered = []
        for idx, feat in zip(valid_indices, X_list):
            if labels[idx] >= 0:
                X_filtered.append(feat)
                y_filtered.append(labels[idx])

        if len(X_filtered) < 100:
            return {"error": "Not enough labeled data"}

        # ③ Создаём DataFrame-подобную структуру
        self.feature_names = sorted(X_filtered[0].keys())
        X = np.array([
            [f[k] for k in self.feature_names]
            for f in X_filtered
        ])
        y = np.array(y_filtered)

        # Заменяем NaN/Inf
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # ④ Нормализация
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        # ⑤ Time Series Split (ВАЖНО: нельзя обычный train_test_split!)
        # Данные временные — будущее не должно утекать в обучение
        tscv = TimeSeriesSplit(n_splits=3)
        scores = []

        for train_idx, test_idx in tscv.split(X_scaled):
            X_train = X_scaled[train_idx]
            X_test = X_scaled[test_idx]
            y_train = y[train_idx]
            y_test = y[test_idx]

            model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                num_leaves=31,
                min_child_samples=20,     # Защита от переобучения
                reg_alpha=0.1,            # L1 регуляризация
                reg_lambda=0.1,           # L2 регуляризация
                subsample=0.8,            # Используем 80% данных
                colsample_bytree=0.8,     # 80% фичей
                random_state=42,
                verbose=-1,
                class_weight="balanced",  # Балансировка классов
            )

            model.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
                callbacks=[
                    lgb.early_stopping(stopping_rounds=20),
                    lgb.log_evaluation(period=0),
                ],
            )

            score = model.score(X_test, y_test)
            scores.append(score)

        # ⑥ Финальное обучение на всех данных
        self.model = lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=20,
            reg_alpha=0.1,
            reg_lambda=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbose=-1,
            class_weight="balanced",
        )
        self.model.fit(X_scaled, y)

        self.is_trained = True
        self.last_train_time = datetime.utcnow()
        self._save_model()

        # Важность фичей
        importances = dict(zip(
            self.feature_names,
            self.model.feature_importances_,
        ))
        top_features = sorted(
            importances.items(), key=lambda x: x[1], reverse=True
        )[:10]

        avg_score = np.mean(scores)
        log.info(f"🧠 Модель обучена! Accuracy: {avg_score:.3f}")
        log.info(f"   Топ-5 фичей:")
        for fname, fimp in top_features[:5]:
            log.info(f"     {fname}: {fimp}")

        return {
            "accuracy": avg_score,
            "samples": len(X_filtered),
            "top_features": top_features[:10],
            "class_distribution": {
                self.REGIME_NAMES[i]: int(np.sum(y == i))
                for i in range(4)
            },
        }

    def predict(
        self,
        opens: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
    ) -> dict:
        """
        ═══════════════════════════════════
         ПРЕДСКАЗАНИЕ РЕЖИМА
        ═══════════════════════════════════
        
        Возвращает:
        - regime: "SIDEWAYS" / "UPTREND" / "DOWNTREND" / "VOLATILE"
        - confidence: 0.0 — 1.0
        - should_trade: bool
        - probabilities: {regime: probability}
        """
        if not self.is_trained:
            return {
                "regime": "UNKNOWN",
                "confidence": 0.0,
                "should_trade": True,
                "should_buy": True,
                "should_sell": True,
                "qty_multiplier": 1.0,
                "probabilities": {},
            }

        # Генерируем фичи
        features = FeatureEngine.compute_features(
            opens, highs, lows, closes, volumes
        )
        if not features:
            return self._default_prediction()

        # Создаём вектор фичей
        X = np.array([[
            features.get(k, 0) for k in self.feature_names
        ]])
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Нормализуем
        X_scaled = self.scaler.transform(X)

        # Предсказываем
        pred_class = self.model.predict(X_scaled)[0]
        pred_proba = self.model.predict_proba(X_scaled)[0]

        regime = self.REGIME_NAMES.get(pred_class, "UNKNOWN")
        confidence = float(np.max(pred_proba))

        # Вероятности по классам
        probabilities = {
            self.REGIME_NAMES[i]: float(pred_proba[i])
            for i in range(len(pred_proba))
        }

        # Решения на основе режима
        should_trade = True
        should_buy = True
        should_sell = True
        qty_mult = 1.0

        if regime == "SIDEWAYS":
            qty_mult = 1.0 + confidence * 0.5  # До 1.5x в сильном флэте
        elif regime == "UPTREND":
            should_buy = False  # Не покупаем на хаях
            qty_mult = 0.5
        elif regime == "DOWNTREND":
            should_sell = False  # Не продаём на лоях
            qty_mult = 0.5
        elif regime == "VOLATILE":
            should_trade = False  # Полная пауза
            qty_mult = 0.0

        # Если уверенность низкая — торгуем осторожно
        if confidence < 0.5:
            qty_mult *= 0.7

        # Используем Hurst exponent как доп. сигнал
        hurst = features.get("hurst_estimate", 0.5)
        if hurst < 0.4:
            # Mean-reverting → грид-рай!
            qty_mult *= 1.2
        elif hurst > 0.6:
            # Trending → осторожно
            qty_mult *= 0.7

        return {
            "regime": regime,
            "confidence": confidence,
            "should_trade": should_trade,
            "should_buy": should_buy,
            "should_sell": should_sell,
            "qty_multiplier": round(qty_mult, 2),
            "probabilities": probabilities,
            "hurst": float(hurst),
            "features_snapshot": {
                k: round(float(v), 4)
                for k, v in sorted(
                    features.items(),
                    key=lambda x: abs(x[1]),
                    reverse=True,
                )[:8]
            },
        }

    def needs_retrain(self) -> bool:
        """Пора ли переобучаться?"""
        if not self.is_trained or not self.last_train_time:
            return True
        hours_since = (
            datetime.utcnow() - self.last_train_time
        ).total_seconds() / 3600
        return hours_since >= self.retrain_interval_hours

    def _default_prediction(self):
        return {
            "regime": "UNKNOWN",
            "confidence": 0.0,
            "should_trade": True,
            "should_buy": True,
            "should_sell": True,
            "qty_multiplier": 0.8,
            "probabilities": {},
        }
