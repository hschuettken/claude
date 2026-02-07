"""Historical data collector for PV forecast model training.

Fetches actual PV production from InfluxDB and aligns it with weather data
from Open-Meteo to create training datasets.

The key insight: we train the model on (weather features) → (actual kWh per hour),
so it learns the relationship between radiation/clouds/temp and what each array
actually produces — accounting for shading, inverter losses, panel degradation, etc.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from shared.influx_client import InfluxClient
from shared.logging import get_logger

from config import PVForecastSettings
from weather import OpenMeteoClient

logger = get_logger("pv-data")


def _to_utc(dt: datetime) -> datetime:
    """Ensure datetime is UTC-aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PVDataCollector:
    """Collects and aligns historical PV production with weather data."""

    def __init__(
        self,
        influx: InfluxClient,
        weather: OpenMeteoClient,
        settings: PVForecastSettings,
    ) -> None:
        self.influx = influx
        self.weather = weather
        self.settings = settings

    def get_production_history(
        self,
        entity_id: str,
        days_back: int = 90,
    ) -> pd.DataFrame:
        """Get hourly production from InfluxDB for an entity.

        Handles total_increasing cumulative energy sensors (e.g. Riemann sum
        integration sensors like sensor.inverter_pv_east_energy). These sensors
        only go up over time, accumulating total kWh. We diff consecutive
        hourly values to derive energy produced per hour.

        Returns a DataFrame with columns: [time, kwh].
        """
        range_start = f"-{days_back}d"

        records = self.influx.query_records(
            bucket=self.settings.influxdb_bucket,
            entity_id=entity_id,
            range_start=range_start,
        )

        if not records:
            logger.warning("no_production_data", entity_id=entity_id, days_back=days_back)
            return pd.DataFrame(columns=["time", "kwh"])

        df = pd.DataFrame(records)

        # InfluxDB records have _time and _value
        if "_time" not in df.columns or "_value" not in df.columns:
            logger.warning("unexpected_columns", columns=list(df.columns))
            return pd.DataFrame(columns=["time", "kwh"])

        df = df.rename(columns={"_time": "time", "_value": "value"})
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df = df.dropna(subset=["value"])
        df = df.sort_values("time")

        # The energy sensors are total_increasing (cumulative Riemann sum).
        # Values only go up — they represent total accumulated kWh since
        # the integration sensor was created. To get hourly energy:
        # 1. Resample to hourly by taking the last value per hour
        # 2. Diff consecutive hours to get the increment
        # 3. Drop negative diffs (sensor restarts / unavailable periods)
        df = df.set_index("time")

        # Take last value per hour (end-of-hour cumulative total)
        hourly = df["value"].resample("1h").last()
        hourly = hourly.dropna()

        # Diff gives energy produced in each hour
        hourly_kwh = hourly.diff()

        # Negative diffs indicate sensor restart or data gap — discard them.
        # No special midnight handling needed: total_increasing sensors
        # do NOT reset at midnight (unlike daily energy sensors).
        hourly_kwh[hourly_kwh < 0] = 0

        # Cap per-hour production at a reasonable maximum to filter outliers.
        # A residential array rarely exceeds 20 kWh in a single hour.
        hourly_kwh[hourly_kwh > 20] = 0

        result = hourly_kwh.reset_index()
        result.columns = ["time", "kwh"]
        result = result.dropna()

        # Filter out negative values (shouldn't happen after clipping, but safety)
        result = result[result["kwh"] >= 0]

        logger.info(
            "production_data_loaded",
            entity_id=entity_id,
            rows=len(result),
            days=days_back,
        )
        return result

    def get_forecast_solar_history(
        self,
        entity_id: str,
        days_back: int = 90,
    ) -> pd.DataFrame:
        """Get historical Forecast.Solar predictions from InfluxDB.

        The Forecast.Solar integration in HA typically stores daily kWh
        predictions. We query these and align them by date so the model
        can learn the bias of Forecast.Solar predictions.

        Returns a DataFrame with columns: [time, forecast_solar_kwh].
        """
        if not entity_id:
            return pd.DataFrame(columns=["time", "forecast_solar_kwh"])

        range_start = f"-{days_back}d"

        records = self.influx.query_records(
            bucket=self.settings.influxdb_bucket,
            entity_id=entity_id,
            range_start=range_start,
        )

        if not records:
            logger.info("no_forecast_solar_data", entity_id=entity_id)
            return pd.DataFrame(columns=["time", "forecast_solar_kwh"])

        df = pd.DataFrame(records)
        if "_time" not in df.columns or "_value" not in df.columns:
            return pd.DataFrame(columns=["time", "forecast_solar_kwh"])

        df = df.rename(columns={"_time": "time", "_value": "forecast_solar_kwh"})
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["forecast_solar_kwh"] = pd.to_numeric(df["forecast_solar_kwh"], errors="coerce")
        df = df.dropna(subset=["forecast_solar_kwh"])
        df = df[["time", "forecast_solar_kwh"]]

        # Forecast.Solar values are daily totals — spread them across
        # daylight hours so they align with hourly training rows.
        # We assign the daily value to every hour of that day; the model
        # learns the per-hour contribution from the other features.
        df["date"] = df["time"].dt.date

        # Take the last reported value per day (most up-to-date forecast)
        daily = df.sort_values("time").groupby("date")["forecast_solar_kwh"].last()
        daily = daily.reset_index()
        daily.columns = ["date", "forecast_solar_kwh"]

        logger.info(
            "forecast_solar_data_loaded",
            entity_id=entity_id,
            days=len(daily),
        )
        return daily

    async def get_training_data(
        self,
        entity_id: str,
        capacity_kwp: float,
        days_back: int = 90,
        forecast_solar_entity_id: str = "",
    ) -> pd.DataFrame:
        """Build a training dataset: weather features + actual hourly production.

        Optionally includes Forecast.Solar predictions as an extra feature
        when forecast_solar_entity_id is provided.

        Returns a DataFrame with columns:
            time, kwh, hour, day_of_year, month,
            shortwave_radiation, direct_radiation, diffuse_radiation,
            cloud_cover, temperature_2m, wind_speed_10m, ...
            capacity_kwp, forecast_solar_kwh (if available)
        """
        # Get production history from InfluxDB
        production = self.get_production_history(entity_id, days_back)
        if production.empty:
            return pd.DataFrame()

        # Determine date range for weather history
        start_date = production["time"].min().date()
        # Historical weather API needs end_date at most yesterday
        end_date = min(
            production["time"].max().date(),
            date.today() - timedelta(days=1),
        )

        if start_date >= end_date:
            logger.warning("insufficient_date_range", start=start_date, end=end_date)
            return pd.DataFrame()

        # Fetch historical weather from Open-Meteo
        weather_records = await self.weather.get_historical_weather(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        if not weather_records:
            logger.warning("no_weather_data")
            return pd.DataFrame()

        weather_df = pd.DataFrame(weather_records)
        weather_df["time"] = pd.to_datetime(weather_df["time"], utc=True)
        weather_df = weather_df.set_index("time")

        # Align production with weather on the hour
        production = production.set_index("time")
        production.index = production.index.floor("h")

        # Join on hourly timestamps
        merged = production.join(weather_df, how="inner")
        merged = merged.reset_index()

        if merged.empty:
            logger.warning("no_aligned_data")
            return pd.DataFrame()

        # Add temporal features
        merged["hour"] = merged["time"].dt.hour
        merged["day_of_year"] = merged["time"].dt.dayofyear
        merged["month"] = merged["time"].dt.month
        merged["capacity_kwp"] = capacity_kwp

        # Merge Forecast.Solar predictions (daily value joined by date)
        if forecast_solar_entity_id:
            fs_daily = self.get_forecast_solar_history(
                forecast_solar_entity_id, days_back
            )
            if not fs_daily.empty:
                merged["date"] = merged["time"].dt.date
                merged = merged.merge(fs_daily, on="date", how="left")
                # Fill missing days with 0 — model handles it gracefully
                merged["forecast_solar_kwh"] = merged["forecast_solar_kwh"].fillna(0)
                merged = merged.drop(columns=["date"])
                logger.info(
                    "forecast_solar_merged",
                    matched_rows=int((merged["forecast_solar_kwh"] > 0).sum()),
                    total_rows=len(merged),
                )

        # Only keep daylight hours (5-21) — no point training on nighttime
        merged = merged[(merged["hour"] >= 5) & (merged["hour"] <= 21)]

        logger.info(
            "training_data_ready",
            entity_id=entity_id,
            samples=len(merged),
            date_range=f"{start_date} to {end_date}",
            has_forecast_solar="forecast_solar_kwh" in merged.columns,
        )
        return merged

    def count_days_of_data(self, entity_id: str) -> int:
        """Check how many days of production data exist."""
        records = self.influx.query_records(
            bucket=self.settings.influxdb_bucket,
            entity_id=entity_id,
            range_start="-365d",
            field="value",
        )
        if not records:
            return 0
        times = [r.get("_time") for r in records if r.get("_time")]
        if not times:
            return 0
        unique_days = {t.date() if hasattr(t, "date") else t for t in times}
        return len(unique_days)
