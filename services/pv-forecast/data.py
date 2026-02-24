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

import numpy as np
import pandas as pd

from shared.influx_client import InfluxClient
from shared.log import get_logger

from config import PVForecastSettings
from weather import OpenMeteoClient

logger = get_logger("pv-data")


def compute_solar_position(
    day_of_year: np.ndarray,
    hour: np.ndarray,
    latitude: float,
    longitude: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute solar elevation and azimuth angles.

    Args:
        day_of_year: Array of day-of-year values (1-366).
        hour: Array of UTC hour values (0-23).
        latitude: Location latitude in degrees.
        longitude: Location longitude in degrees.

    Returns:
        Tuple of (elevation_degrees, azimuth_degrees) arrays.
    """
    lat_rad = np.radians(latitude)

    # Solar declination (Spencer, 1971 simplified)
    declination_deg = 23.45 * np.sin(np.radians(360 / 365.0 * (284 + day_of_year)))
    decl_rad = np.radians(declination_deg)

    # Solar time correction: approximate using longitude offset from UTC
    # (ignores equation of time for simplicity — adds ~15 min error max)
    solar_hour = hour + longitude / 15.0
    hour_angle_deg = 15.0 * (solar_hour - 12.0)
    hour_angle_rad = np.radians(hour_angle_deg)

    # Solar elevation
    sin_elev = (
        np.sin(lat_rad) * np.sin(decl_rad)
        + np.cos(lat_rad) * np.cos(decl_rad) * np.cos(hour_angle_rad)
    )
    sin_elev = np.clip(sin_elev, -1, 1)
    elevation_rad = np.arcsin(sin_elev)
    elevation_deg = np.degrees(elevation_rad)

    # Solar azimuth
    cos_elev = np.cos(elevation_rad)
    # Avoid division by zero when sun is at horizon
    cos_elev_safe = np.where(np.abs(cos_elev) < 1e-6, 1e-6, cos_elev)
    cos_az = (sin_elev * np.sin(lat_rad) - np.sin(decl_rad)) / (cos_elev_safe * np.cos(lat_rad))
    cos_az = np.clip(cos_az, -1, 1)
    azimuth_deg = np.degrees(np.arccos(cos_az))
    # Afternoon: azimuth > 180
    azimuth_deg = np.where(hour_angle_deg > 0, 360 - azimuth_deg, azimuth_deg)

    return elevation_deg, azimuth_deg


def compute_clear_sky_ghi(elevation_deg: np.ndarray) -> np.ndarray:
    """Compute theoretical clear-sky GHI using simplified Meinel model.

    GHI_clear = 1361 * 0.7^(1/sin(elevation)) for elevation > 0.
    """
    elev_rad = np.radians(np.clip(elevation_deg, 0, 90))
    sin_elev = np.sin(elev_rad)
    # Avoid division by zero for very low sun
    sin_elev_safe = np.where(sin_elev < 0.01, 0.01, sin_elev)
    ghi_clear = np.where(
        elevation_deg > 0,
        1361.0 * np.power(0.7, 1.0 / sin_elev_safe) * sin_elev,
        0.0,
    )
    return ghi_clear


def add_solar_features(
    df: pd.DataFrame,
    latitude: float,
    longitude: float,
) -> pd.DataFrame:
    """Add solar_elevation, solar_azimuth, and clear_sky_index to DataFrame.

    Requires columns: day_of_year, hour, shortwave_radiation.
    """
    doy = df["day_of_year"].values.astype(float)
    hour = df["hour"].values.astype(float)

    elev, azim = compute_solar_position(doy, hour, latitude, longitude)
    df["solar_elevation"] = elev
    df["solar_azimuth"] = azim

    # Clear sky index
    ghi_clear = compute_clear_sky_ghi(elev)
    actual_ghi = df["shortwave_radiation"].fillna(0).values
    csi = np.where(ghi_clear > 10, actual_ghi / ghi_clear, 0.0)
    df["clear_sky_index"] = np.clip(csi, 0, 1.5)

    return df


def add_lagged_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add lagged production features for training data.

    Requires columns: time, hour, kwh. Data must be sorted by time.
    """
    df = df.sort_values("time").reset_index(drop=True)

    # Build a pivot: rows=date, cols=hour, values=kwh
    df["date"] = df["time"].dt.date
    pivot = df.pivot_table(index="date", columns="hour", values="kwh", aggfunc="first")

    # Yesterday same hour: shift the pivot by 1 day
    yesterday = pivot.shift(1)
    # Rolling 3-day mean per hour
    rolling_3d = pivot.rolling(3, min_periods=1).mean().shift(1)  # shift to avoid leakage

    # Map back to the original DataFrame
    kwh_yesterday = []
    kwh_rolling = []
    for _, row in df.iterrows():
        d = row["date"]
        h = row["hour"]
        yval = yesterday.loc[d, h] if d in yesterday.index and h in yesterday.columns else np.nan
        rval = rolling_3d.loc[d, h] if d in rolling_3d.index and h in rolling_3d.columns else np.nan
        kwh_yesterday.append(yval)
        kwh_rolling.append(rval)

    df["kwh_yesterday_same_hour"] = pd.Series(kwh_yesterday, dtype=float).fillna(0).values
    df["kwh_rolling_3d_mean"] = pd.Series(kwh_rolling, dtype=float).fillna(0).values
    df = df.drop(columns=["date"], errors="ignore")

    return df


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

        # Drop per-hour values above a reasonable maximum (outlier/sensor glitch).
        # A residential array rarely exceeds 20 kWh in a single hour.
        hourly_kwh[hourly_kwh > 20] = np.nan

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
        latitude: float = 0.0,
        longitude: float = 0.0,
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

        # Merge Forecast.Solar predictions — distribute daily total across hours
        # proportional to GHI profile (instead of repeating the same daily value)
        if forecast_solar_entity_id:
            fs_daily = self.get_forecast_solar_history(
                forecast_solar_entity_id, days_back
            )
            if not fs_daily.empty:
                merged["date"] = merged["time"].dt.date
                merged = merged.merge(fs_daily, on="date", how="left")
                merged["forecast_solar_kwh"] = merged["forecast_solar_kwh"].fillna(0)

                # Distribute daily total proportional to GHI
                if "shortwave_radiation" in merged.columns:
                    ghi = merged["shortwave_radiation"].fillna(0)
                    daily_ghi_sum = merged.groupby("date")["shortwave_radiation"].transform("sum")
                    # Weight: this hour's GHI / total GHI for the day
                    weight = np.where(daily_ghi_sum > 0, ghi / daily_ghi_sum, 0)
                    merged["forecast_solar_hourly_kwh"] = merged["forecast_solar_kwh"] * weight
                else:
                    merged["forecast_solar_hourly_kwh"] = merged["forecast_solar_kwh"]

                merged = merged.drop(columns=["date", "forecast_solar_kwh"], errors="ignore")
                logger.info(
                    "forecast_solar_merged",
                    matched_rows=int((merged["forecast_solar_hourly_kwh"] > 0).sum()),
                    total_rows=len(merged),
                )

        # Only keep daylight hours — use actual sunrise/sunset from weather data.
        # In winter at 52°N, sunrise can be ~7:15 UTC and sunset ~16:15 UTC,
        # so the old hardcoded 5–21 range included many dark hours.
        if "sunrise_hour" in merged.columns and "sunset_hour" in merged.columns:
            merged = merged[
                (merged["hour"] >= np.floor(merged["sunrise_hour"]).astype(int))
                & (merged["hour"] < np.ceil(merged["sunset_hour"]).astype(int))
            ]
        else:
            # Fallback if sunrise/sunset not in weather data
            merged = merged[(merged["hour"] >= 6) & (merged["hour"] <= 18)]

        # Remove hours with negligible solar radiation (GHI < 5 W/m²).
        # These are trivially dark and handled by a physics constraint at
        # inference time. Including them in training dilutes the model with
        # easy "dark → 0" examples instead of learning actual production.
        if "shortwave_radiation" in merged.columns:
            before = len(merged)
            merged = merged[merged["shortwave_radiation"].fillna(0) >= 5]
            logger.info("dark_hours_filtered", removed=before - len(merged))

        # Add computed solar features (elevation, azimuth, clear sky index)
        if latitude != 0.0 and longitude != 0.0:
            merged = add_solar_features(merged, latitude, longitude)

        # Add lagged production features (yesterday same hour, rolling 3d mean)
        merged = add_lagged_features(merged)

        logger.info(
            "training_data_ready",
            entity_id=entity_id,
            samples=len(merged),
            date_range=f"{start_date} to {end_date}",
            has_forecast_solar="forecast_solar_hourly_kwh" in merged.columns,
        )
        return merged

    def count_days_of_data(self, entity_id: str) -> int:
        """Check how many days of production data exist."""
        history_days = self.settings.data_history_days
        records = self.influx.query_records(
            bucket=self.settings.influxdb_bucket,
            entity_id=entity_id,
            range_start=f"-{history_days}d",
            field="value",
        )
        if not records:
            return 0
        times = [r.get("_time") for r in records if r.get("_time")]
        if not times:
            return 0
        unique_days = {t.date() if hasattr(t, "date") else t for t in times}
        return len(unique_days)
