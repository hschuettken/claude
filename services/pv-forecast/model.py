"""PV production forecast model.

Two modes:
  1. ML mode (≥14 days of data): Gradient Boosting trained on
     historical weather-vs-production. One model per array.
  2. Fallback mode (<14 days): Simple radiation-based estimate using
     panel capacity and Global Horizontal Irradiance from Open-Meteo.

The model learns array-specific factors like shading patterns, inverter
efficiency curves, and panel degradation — things a generic forecast
(like Forecast.Solar) can't account for.

When Forecast.Solar predictions are available as a feature, the model
learns to correct its biases (e.g., "Forecast.Solar overestimates by
20% on cloudy days for this array"). This ensemble approach typically
outperforms either source alone.
"""

from __future__ import annotations

import math
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import GroupKFold, cross_val_score

from shared.log import get_logger

logger = get_logger("pv-model")

# Features used by the ML model
FEATURE_COLS = [
    "hour",
    "day_of_year",
    "month",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "direct_normal_irradiance",
    "cloud_cover",
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "sunshine_duration",
    "capacity_kwp",
    "forecast_solar_kwh",  # Forecast.Solar prediction (daily total for this array)
    "sunrise_hour",  # Decimal UTC hour of sunrise (e.g. 7.25 = 07:15)
    "sunset_hour",  # Decimal UTC hour of sunset (e.g. 16.5 = 16:30)
]


class PVModel:
    """Gradient Boosting model for PV production forecasting."""

    def __init__(
        self,
        array_name: str,
        model_dir: str = "/app/data/models",
        n_estimators: int = 200,
        max_depth: int = 5,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        min_samples_leaf: int = 10,
        min_training_samples: int = 50,
        cv_folds: int = 3,
    ) -> None:
        self.array_name = array_name
        self.model_dir = Path(model_dir)
        self.model: GradientBoostingRegressor | None = None
        self._trained_features: list[str] | None = None
        self._model_path = self.model_dir / f"pv_model_{array_name}.joblib"
        self._n_estimators = n_estimators
        self._max_depth = max_depth
        self._learning_rate = learning_rate
        self._subsample = subsample
        self._min_samples_leaf = min_samples_leaf
        self._min_training_samples = min_training_samples
        self._cv_folds = cv_folds

    def train(self, df: pd.DataFrame) -> dict[str, float]:
        """Train the model on historical data.

        Args:
            df: Training DataFrame with FEATURE_COLS + 'kwh' column.

        Returns:
            Dict with training metrics (r2, mae, cv_r2).
        """
        # Prepare features
        available_features = [c for c in FEATURE_COLS if c in df.columns]
        missing = set(FEATURE_COLS) - set(available_features)
        if missing:
            logger.warning("missing_features", missing=list(missing))

        self._trained_features = available_features
        X = df[available_features].fillna(0).values
        y = df["kwh"].values

        # Clip negative targets (shouldn't happen but safety)
        y = np.clip(y, 0, None)

        if len(X) < self._min_training_samples:
            logger.warning("too_few_samples", count=len(X))
            return {"r2": 0.0, "mae": 0.0, "cv_r2": 0.0}

        # Train Gradient Boosting
        self.model = GradientBoostingRegressor(
            n_estimators=self._n_estimators,
            max_depth=self._max_depth,
            learning_rate=self._learning_rate,
            subsample=self._subsample,
            min_samples_leaf=self._min_samples_leaf,
            random_state=42,
        )
        self.model.fit(X, y)

        # Evaluate
        train_r2 = self.model.score(X, y)
        train_pred = self.model.predict(X)
        train_mae = float(np.mean(np.abs(y - train_pred)))

        # Cross-validation R² — use GroupKFold by date so that hours from
        # the same day stay together. Random K-fold leaks intra-day
        # correlation and gives unrealistic CV scores for time-series data.
        groups = df["time"].dt.date if "time" in df.columns else None
        n_groups = len(set(groups)) if groups is not None else len(X)
        n_folds = min(self._cv_folds, n_groups)
        if n_folds >= 2 and groups is not None:
            gkf = GroupKFold(n_splits=n_folds)
            cv_scores = cross_val_score(
                self.model, X, y, cv=gkf, groups=groups.values, scoring="r2",
            )
            cv_r2 = float(cv_scores.mean())
        elif n_folds >= 2:
            cv_scores = cross_val_score(self.model, X, y, cv=n_folds, scoring="r2")
            cv_r2 = float(cv_scores.mean())
        else:
            cv_r2 = train_r2

        # Save model
        self._save()

        # Feature importance logging
        importances = dict(zip(available_features, self.model.feature_importances_))
        top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]

        metrics = {"r2": round(train_r2, 4), "mae": round(train_mae, 4), "cv_r2": round(cv_r2, 4)}
        logger.info(
            "model_trained",
            array=self.array_name,
            samples=len(X),
            metrics=metrics,
            top_features=top_features,
        )
        return metrics

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        """Predict hourly kWh for given weather features.

        Args:
            df: DataFrame with FEATURE_COLS (weather forecast data).

        Returns:
            Array of predicted kWh values (one per row).
        """
        if self.model is None:
            raise RuntimeError(f"Model not trained for array '{self.array_name}'")

        # Use the exact features the model was trained with (order matters)
        if self._trained_features:
            features = [c for c in self._trained_features if c in df.columns]
        else:
            features = [c for c in FEATURE_COLS if c in df.columns]
        X = df[features].fillna(0).values
        predictions = self.model.predict(X)
        # Ensure non-negative
        return np.clip(predictions, 0, None)

    def _save(self) -> None:
        """Persist model and feature list to disk."""
        self.model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {"model": self.model, "features": self._trained_features},
            self._model_path,
        )
        logger.info("model_saved", path=str(self._model_path))

    def load(self) -> bool:
        """Load model from disk. Returns True if features match current config."""
        if not self._model_path.exists():
            return False

        data = joblib.load(self._model_path)

        if isinstance(data, dict):
            saved_features = data.get("features", [])
            # If saved features don't match current FEATURE_COLS, force retrain
            if saved_features and set(saved_features) != set(FEATURE_COLS):
                logger.info(
                    "model_features_changed",
                    array=self.array_name,
                    old_count=len(saved_features),
                    new_count=len(FEATURE_COLS),
                )
                return False
            self.model = data["model"]
            self._trained_features = saved_features or None
        else:
            # Old format (bare model without features) — force retrain
            logger.info("model_old_format", array=self.array_name)
            return False

        logger.info("model_loaded", path=str(self._model_path))
        return True

    @property
    def is_trained(self) -> bool:
        return self.model is not None


def fallback_estimate(
    weather_df: pd.DataFrame,
    capacity_kwp: float,
    azimuth: float,
    tilt: float,
    latitude: float,
    system_efficiency: float = 0.78,
    peak_irradiance: float = 1000.0,
) -> np.ndarray:
    """Simple radiation-based estimate when ML model isn't available.

    Uses GHI (shortwave_radiation) from Open-Meteo with a basic model
    that accounts for panel orientation and a configurable system efficiency.

    This is intentionally simple — it's a fallback, not the main model.
    """
    SYSTEM_EFFICIENCY = system_efficiency
    PEAK_IRRADIANCE = peak_irradiance

    ghi = weather_df["shortwave_radiation"].fillna(0).values
    hours = weather_df["hour"].values if "hour" in weather_df.columns else np.zeros(len(ghi))
    days = weather_df["day_of_year"].values if "day_of_year" in weather_df.columns else np.full(len(ghi), 180)

    estimates = []
    for i in range(len(ghi)):
        if ghi[i] <= 0:
            estimates.append(0.0)
            continue

        # Simple orientation factor based on azimuth
        # East-facing produces more in morning, west more in afternoon
        hour = hours[i] if i < len(hours) else 12
        solar_noon_offset = hour - 12  # hours from solar noon

        # East panels (azimuth ~90) benefit from morning sun
        # West panels (azimuth ~-90) benefit from afternoon sun
        azimuth_rad = math.radians(azimuth)
        orientation_factor = 1.0 + 0.1 * math.sin(azimuth_rad) * solar_noon_offset / 6.0
        orientation_factor = max(0.5, min(1.3, orientation_factor))

        # Estimate kWh for this hour
        kwh = (ghi[i] / PEAK_IRRADIANCE) * capacity_kwp * SYSTEM_EFFICIENCY * orientation_factor
        estimates.append(max(0.0, kwh))

    return np.array(estimates)
