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

        Queries the raw data points and resamples to hourly energy (kWh).
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

        # The entity might report cumulative daily energy (resets at midnight)
        # or instantaneous power. We handle both by looking at the value pattern.
        # If values mostly increase within a day and reset, it's cumulative.
        # We diff to get per-interval energy and resample to hourly.
        df = df.set_index("time")

        # Resample to hourly: take the max value per hour (handles cumulative)
        # and then diff to get the hourly increment
        hourly = df["value"].resample("1h").max()
        hourly_diff = hourly.diff()

        # Where diff is negative (midnight reset or data gap), use the raw value
        # (which represents energy since last reset = midnight)
        first_of_day = hourly.index.hour == 0
        hourly_kwh = hourly_diff.copy()
        hourly_kwh[hourly_diff < 0] = 0
        hourly_kwh[first_of_day] = hourly[first_of_day]

        result = hourly_kwh.reset_index()
        result.columns = ["time", "kwh"]
        result = result.dropna()

        # Filter out nighttime zeros and obvious outliers
        result = result[result["kwh"] >= 0]

        logger.info(
            "production_data_loaded",
            entity_id=entity_id,
            rows=len(result),
            days=days_back,
        )
        return result

    async def get_training_data(
        self,
        entity_id: str,
        capacity_kwp: float,
        days_back: int = 90,
    ) -> pd.DataFrame:
        """Build a training dataset: weather features + actual hourly production.

        Returns a DataFrame with columns:
            time, kwh, hour, day_of_year, month,
            shortwave_radiation, direct_radiation, diffuse_radiation,
            cloud_cover, temperature_2m, wind_speed_10m, ...
            capacity_kwp
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

        # Only keep daylight hours (6-21) — no point training on nighttime
        merged = merged[(merged["hour"] >= 5) & (merged["hour"] <= 21)]

        logger.info(
            "training_data_ready",
            entity_id=entity_id,
            samples=len(merged),
            date_range=f"{start_date} to {end_date}",
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
