"""Forecast orchestrator — ties together data, model, and weather.

Produces hourly forecasts for each PV array for today, tomorrow,
and the day after tomorrow. Handles the decision between ML model
and fallback estimation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from shared.ha_client import HomeAssistantClient
from shared.logging import get_logger

from config import PVForecastSettings
from data import PVDataCollector
from model import FEATURE_COLS, PVModel, fallback_estimate
from weather import OpenMeteoClient

logger = get_logger("pv-forecast")


@dataclass
class HourlyForecast:
    """Forecast for a single hour."""

    time: datetime
    kwh: float


@dataclass
class DayForecast:
    """Forecast for a single day."""

    date: date
    total_kwh: float
    hourly: list[HourlyForecast] = field(default_factory=list)


@dataclass
class ArrayForecast:
    """Complete forecast for one PV array."""

    array_name: str  # "east" or "west"
    today: DayForecast | None = None
    tomorrow: DayForecast | None = None
    day_after: DayForecast | None = None
    model_type: str = "fallback"  # "ml" or "fallback"


@dataclass
class FullForecast:
    """Combined forecast for all arrays."""

    timestamp: datetime
    east: ArrayForecast | None = None
    west: ArrayForecast | None = None
    today_remaining_kwh: float = 0.0

    @property
    def today_total_kwh(self) -> float:
        total = 0.0
        if self.east and self.east.today:
            total += self.east.today.total_kwh
        if self.west and self.west.today:
            total += self.west.today.total_kwh
        return total

    @property
    def tomorrow_total_kwh(self) -> float:
        total = 0.0
        if self.east and self.east.tomorrow:
            total += self.east.tomorrow.total_kwh
        if self.west and self.west.tomorrow:
            total += self.west.tomorrow.total_kwh
        return total

    @property
    def day_after_total_kwh(self) -> float:
        total = 0.0
        if self.east and self.east.day_after:
            total += self.east.day_after.total_kwh
        if self.west and self.west.day_after:
            total += self.west.day_after.total_kwh
        return total


class ForecastEngine:
    """Orchestrates training and forecasting for all PV arrays."""

    def __init__(
        self,
        settings: PVForecastSettings,
        data_collector: PVDataCollector,
        weather: OpenMeteoClient,
        ha: HomeAssistantClient,
    ) -> None:
        self.settings = settings
        self.data = data_collector
        self.weather = weather
        self.ha = ha

        # One model per array
        self.models: dict[str, PVModel] = {}
        self._init_models()

    def _init_models(self) -> None:
        """Initialize or load persisted models."""
        for array_name in ("east", "west"):
            model = PVModel(array_name, model_dir=self.settings.model_dir)
            if model.load():
                logger.info("model_restored", array=array_name)
            self.models[array_name] = model

    async def train(self) -> dict[str, dict]:
        """Train (or retrain) models for all arrays with available data."""
        results = {}

        arrays = [
            (
                "east",
                self.settings.pv_east_energy_entity_id,
                self.settings.pv_east_capacity_kwp,
                self.settings.forecast_solar_east_entity_id,
            ),
            (
                "west",
                self.settings.pv_west_energy_entity_id,
                self.settings.pv_west_capacity_kwp,
                self.settings.forecast_solar_west_entity_id,
            ),
        ]

        for array_name, entity_id, capacity_kwp, fs_entity_id in arrays:
            if not entity_id:
                logger.info("skipping_array_no_entity", array=array_name)
                continue

            days_available = self.data.count_days_of_data(entity_id)
            logger.info("data_check", array=array_name, days_available=days_available)

            if days_available < self.settings.model_min_days:
                logger.info(
                    "insufficient_data_for_ml",
                    array=array_name,
                    days=days_available,
                    required=self.settings.model_min_days,
                )
                results[array_name] = {"status": "fallback", "days": days_available}
                continue

            training_data = await self.data.get_training_data(
                entity_id=entity_id,
                capacity_kwp=capacity_kwp,
                days_back=min(days_available, 365),
                forecast_solar_entity_id=fs_entity_id,
            )

            if training_data.empty:
                results[array_name] = {"status": "no_data"}
                continue

            metrics = self.models[array_name].train(training_data)
            results[array_name] = {"status": "trained", **metrics}

        return results

    async def forecast(self) -> FullForecast:
        """Generate forecast for today, tomorrow, and day after tomorrow."""
        now = datetime.now(timezone.utc)

        # Get 3-day weather forecast from Open-Meteo
        weather_records = await self.weather.get_solar_forecast(forecast_days=3)
        if not weather_records:
            logger.error("no_weather_forecast_available")
            return FullForecast(timestamp=now)

        weather_df = pd.DataFrame(weather_records)
        weather_df["hour"] = weather_df["time"].dt.hour
        weather_df["day_of_year"] = weather_df["time"].dt.dayofyear
        weather_df["month"] = weather_df["time"].dt.month

        # Only daylight hours
        weather_df = weather_df[(weather_df["hour"] >= 5) & (weather_df["hour"] <= 21)]

        # Split into days
        weather_df["date"] = weather_df["time"].dt.date
        today = now.date()
        tomorrow = today + timedelta(days=1)
        day_after = today + timedelta(days=2)

        day_groups = {
            "today": weather_df[weather_df["date"] == today],
            "tomorrow": weather_df[weather_df["date"] == tomorrow],
            "day_after": weather_df[weather_df["date"] == day_after],
        }

        # Fetch current Forecast.Solar values from HA (if configured)
        fs_values = await self._get_forecast_solar_values()

        # Forecast each array
        east_forecast = self._forecast_array(
            "east",
            day_groups,
            self.settings.pv_east_capacity_kwp,
            self.settings.pv_east_azimuth,
            self.settings.pv_east_tilt,
            fs_values.get("east", {}),
        )
        west_forecast = self._forecast_array(
            "west",
            day_groups,
            self.settings.pv_west_capacity_kwp,
            self.settings.pv_west_azimuth,
            self.settings.pv_west_tilt,
            fs_values.get("west", {}),
        )

        # Calculate remaining today
        current_hour = now.hour
        remaining_kwh = 0.0
        for arr_forecast in (east_forecast, west_forecast):
            if arr_forecast and arr_forecast.today:
                for h in arr_forecast.today.hourly:
                    if h.time.hour > current_hour:
                        remaining_kwh += h.kwh

        full = FullForecast(
            timestamp=now,
            east=east_forecast,
            west=west_forecast,
            today_remaining_kwh=round(remaining_kwh, 2),
        )

        logger.info(
            "forecast_complete",
            today_total=full.today_total_kwh,
            today_remaining=full.today_remaining_kwh,
            tomorrow=full.tomorrow_total_kwh,
            day_after=full.day_after_total_kwh,
            east_model=east_forecast.model_type if east_forecast else "none",
            west_model=west_forecast.model_type if west_forecast else "none",
        )

        return full

    async def _get_forecast_solar_values(self) -> dict[str, dict[str, float]]:
        """Fetch current Forecast.Solar predictions from HA for each array.

        The Forecast.Solar integration typically provides entities like:
          sensor.energy_production_today  → 12.5  (kWh)
          sensor.energy_production_tomorrow → 8.3  (kWh)

        Returns: {"east": {"today": 12.5, "tomorrow": 8.3, ...}, "west": {...}}
        """
        result: dict[str, dict[str, float]] = {}

        for array_name, entity_id in [
            ("east", self.settings.forecast_solar_east_entity_id),
            ("west", self.settings.forecast_solar_west_entity_id),
        ]:
            if not entity_id:
                continue

            try:
                state = await self.ha.get_state(entity_id)
                value = float(state.get("state", 0))

                # The configured entity is the "today" value. Try to find
                # related tomorrow/day_after entities by naming convention.
                # Forecast.Solar typically uses: *_today, *_tomorrow
                base_id = entity_id
                values = {"today": value}

                # Try common naming patterns for tomorrow
                for suffix_today, suffix_tomorrow in [
                    ("_today", "_tomorrow"),
                    ("_production_today", "_production_tomorrow"),
                ]:
                    if suffix_today in base_id:
                        tomorrow_id = base_id.replace(suffix_today, suffix_tomorrow)
                        try:
                            tm_state = await self.ha.get_state(tomorrow_id)
                            values["tomorrow"] = float(tm_state.get("state", 0))
                        except Exception:
                            pass
                        break

                result[array_name] = values
                logger.info(
                    "forecast_solar_fetched",
                    array=array_name,
                    values=values,
                )
            except Exception:
                logger.warning("forecast_solar_fetch_failed", array=array_name, entity_id=entity_id)

        return result

    def _forecast_array(
        self,
        array_name: str,
        day_groups: dict[str, pd.DataFrame],
        capacity_kwp: float,
        azimuth: float,
        tilt: float,
        forecast_solar: dict[str, float] | None = None,
    ) -> ArrayForecast | None:
        """Forecast a single array for all 3 days."""
        if capacity_kwp <= 0:
            return None

        model = self.models.get(array_name)
        use_ml = model is not None and model.is_trained
        model_type = "ml" if use_ml else "fallback"
        forecast_solar = forecast_solar or {}

        # Map day_key to Forecast.Solar key
        fs_day_map = {
            "today": "today",
            "tomorrow": "tomorrow",
            "day_after": "day_after",
        }

        day_forecasts = {}
        for day_key, weather_day in day_groups.items():
            if weather_day.empty:
                continue

            # Add capacity as feature
            weather_day = weather_day.copy()
            weather_day["capacity_kwp"] = capacity_kwp

            # Inject Forecast.Solar prediction (daily total for this day)
            fs_key = fs_day_map.get(day_key, "")
            fs_value = forecast_solar.get(fs_key, 0.0)
            weather_day["forecast_solar_kwh"] = fs_value

            if use_ml:
                predictions = model.predict(weather_day)
            else:
                predictions = fallback_estimate(
                    weather_day,
                    capacity_kwp,
                    azimuth,
                    tilt,
                    self.settings.pv_latitude,
                )

            hourly = [
                HourlyForecast(
                    time=row["time"],
                    kwh=round(float(pred), 3),
                )
                for (_, row), pred in zip(weather_day.iterrows(), predictions)
            ]
            total = round(float(np.sum(predictions)), 2)

            day_forecasts[day_key] = DayForecast(
                date=weather_day["date"].iloc[0],
                total_kwh=total,
                hourly=hourly,
            )

        return ArrayForecast(
            array_name=array_name,
            today=day_forecasts.get("today"),
            tomorrow=day_forecasts.get("tomorrow"),
            day_after=day_forecasts.get("day_after"),
            model_type=model_type,
        )
