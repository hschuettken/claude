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
from sklearn.model_selection import GroupKFold, TimeSeriesSplit, cross_val_score

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
    "forecast_solar_hourly_kwh",  # Forecast.Solar prediction distributed across hours
    "sunrise_hour",  # Decimal UTC hour of sunrise (e.g. 7.25 = 07:15)
    "sunset_hour",  # Decimal UTC hour of sunset (e.g. 16.5 = 16:30)
    "solar_elevation",  # Sun elevation angle (degrees)
    "solar_azimuth",  # Sun azimuth angle (degrees)
    "clear_sky_index",  # Ratio of actual GHI to theoretical clear-sky GHI
    "kwh_yesterday_same_hour",  # Production at same hour yesterday
    "kwh_rolling_3d_mean",  # Rolling 3-day mean production at this hour
]


class PVModel:
    """Gradient Boosting model for PV production forecasting.

    Trains three quantile regression models (q10, q50, q90) for prediction
    intervals, with the median (q50) as the primary prediction.
    """

    def __init__(
        self,
        array_name: str,
        model_dir: str = "/app/data/models",
        n_estimators: int = 150,
        max_depth: int = 4,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        min_samples_leaf: int = 20,
        min_training_samples: int = 50,
        cv_folds: int = 5,
    ) -> None:
        self.array_name = array_name
        self.model_dir = Path(model_dir)
        self.model: GradientBoostingRegressor | None = None  # q50 (median)
        self.model_low: GradientBoostingRegressor | None = None  # q10
        self.model_high: GradientBoostingRegressor | None = None  # q90
        self._trained_features: list[str] | None = None
        self._model_path = self.model_dir / f"pv_model_{array_name}.joblib"
        self._n_estimators = n_estimators
        self._max_depth = max_depth
        self._learning_rate = learning_rate
        self._subsample = subsample
        self._min_samples_leaf = min_samples_leaf
        self._min_training_samples = min_training_samples
        self._cv_folds = cv_folds

    def _make_gbr(self, loss: str = "squared_error", alpha: float = 0.5) -> GradientBoostingRegressor:
        """Create a GBR with current hyperparameters."""
        kwargs = dict(
            n_estimators=self._n_estimators,
            max_depth=self._max_depth,
            learning_rate=self._learning_rate,
            subsample=self._subsample,
            min_samples_leaf=self._min_samples_leaf,
            random_state=42,
        )
        if loss == "quantile":
            kwargs["loss"] = "quantile"
            kwargs["alpha"] = alpha
        else:
            kwargs["loss"] = loss
        return GradientBoostingRegressor(**kwargs)

    def train(self, df: pd.DataFrame) -> dict[str, float]:
        """Train the model on historical data.

        Trains three quantile models (q10, q50, q90) for prediction intervals.
        Uses TimeSeriesSplit for primary CV (data must be sorted by time).

        Args:
            df: Training DataFrame with FEATURE_COLS + 'kwh' column.

        Returns:
            Dict with training metrics (r2, mae, cv_r2, cv_r2_group).
        """
        # Prepare features
        available_features = [c for c in FEATURE_COLS if c in df.columns]
        missing = set(FEATURE_COLS) - set(available_features)
        if missing:
            logger.warning("missing_features", missing=list(missing))

        # Sort by time for time-series CV and lagged features
        if "time" in df.columns:
            df = df.sort_values("time").reset_index(drop=True)

        self._trained_features = available_features
        X = df[available_features].fillna(0).values
        y = df["kwh"].values

        # Clip negative targets (shouldn't happen but safety)
        y = np.clip(y, 0, None)

        if len(X) < self._min_training_samples:
            logger.warning("too_few_samples", count=len(X))
            return {"r2": 0.0, "mae": 0.0, "cv_r2": 0.0}

        # Train quantile models: q10 (low), q50 (median/main), q90 (high)
        self.model = self._make_gbr("squared_error")
        self.model.fit(X, y)

        self.model_low = self._make_gbr("quantile", alpha=0.1)
        self.model_low.fit(X, y)

        self.model_high = self._make_gbr("quantile", alpha=0.9)
        self.model_high.fit(X, y)

        # Evaluate main model
        train_r2 = self.model.score(X, y)
        train_pred = self.model.predict(X)
        train_mae = float(np.mean(np.abs(y - train_pred)))

        # Primary CV: TimeSeriesSplit (always train on past, predict future)
        n_folds = min(self._cv_folds, len(X) // 20)  # need enough samples per fold
        cv_r2 = train_r2
        if n_folds >= 2:
            tscv = TimeSeriesSplit(n_splits=n_folds)
            cv_scores = cross_val_score(
                self._make_gbr("squared_error"), X, y, cv=tscv, scoring="r2",
            )
            cv_r2 = float(cv_scores.mean())

        # Secondary CV: GroupKFold by date (for comparison)
        cv_r2_group = cv_r2
        groups = df["time"].dt.date if "time" in df.columns else None
        if groups is not None:
            n_groups = len(set(groups))
            n_gfolds = min(self._cv_folds, n_groups)
            if n_gfolds >= 2:
                gkf = GroupKFold(n_splits=n_gfolds)
                gkf_scores = cross_val_score(
                    self._make_gbr("squared_error"), X, y,
                    cv=gkf, groups=groups.values, scoring="r2",
                )
                cv_r2_group = float(gkf_scores.mean())

        # Save model
        self._save()

        # Feature importance logging
        importances = dict(zip(available_features, self.model.feature_importances_))
        top_features = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:5]

        metrics = {
            "r2": round(train_r2, 4),
            "mae": round(train_mae, 4),
            "cv_r2": round(cv_r2, 4),
            "cv_r2_group": round(cv_r2_group, 4),
        }
        logger.info(
            "model_trained",
            array=self.array_name,
            samples=len(X),
            metrics=metrics,
            top_features=top_features,
        )
        return metrics

    def predict(
        self, df: pd.DataFrame, return_intervals: bool = False,
    ) -> np.ndarray | tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Predict hourly kWh for given weather features.

        Args:
            df: DataFrame with FEATURE_COLS (weather forecast data).
            return_intervals: If True, return (prediction, low, high) tuple.

        Returns:
            Array of predicted kWh values, or tuple of (pred, low, high).
        """
        if self.model is None:
            raise RuntimeError(f"Model not trained for array '{self.array_name}'")

        # Use the exact features the model was trained with (order matters)
        if self._trained_features:
            features = [c for c in self._trained_features if c in df.columns]
        else:
            features = [c for c in FEATURE_COLS if c in df.columns]
        X = df[features].fillna(0).values
        predictions = np.clip(self.model.predict(X), 0, None)

        if return_intervals and self.model_low is not None and self.model_high is not None:
            low = np.clip(self.model_low.predict(X), 0, None)
            high = np.clip(self.model_high.predict(X), 0, None)
            return predictions, low, high

        return predictions

    def _save(self) -> None:
        """Persist model and feature list to disk."""
        self.model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self.model,
                "model_low": self.model_low,
                "model_high": self.model_high,
                "features": self._trained_features,
            },
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
            self.model_low = data.get("model_low")
            self.model_high = data.get("model_high")
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
