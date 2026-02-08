"""Open-Meteo API client for solar radiation and weather forecasts.

Open-Meteo is free, requires no API key, and provides excellent solar
radiation data (GHI, DNI, DHI) plus cloud cover, temperature, etc.

Usage:
    client = OpenMeteoClient(latitude=51.0, longitude=7.0)

    # Get forecast for next 3 days
    forecast = await client.get_solar_forecast()

    # Get historical weather for model training
    history = await client.get_historical_weather("2025-01-01", "2025-12-31")
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import httpx

from shared.log import get_logger

logger = get_logger("open-meteo")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_URL = "https://archive-api.open-meteo.com/v1/archive"

# Hourly weather variables we request
HOURLY_VARS = [
    "shortwave_radiation",  # GHI - Global Horizontal Irradiance (W/m²)
    "direct_radiation",  # DNI projected to horizontal (W/m²)
    "diffuse_radiation",  # DHI - Diffuse Horizontal Irradiance (W/m²)
    "direct_normal_irradiance",  # DNI - Direct Normal Irradiance (W/m²)
    "cloud_cover",  # Total cloud cover (%)
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "temperature_2m",  # Temperature at 2m (°C)
    "relative_humidity_2m",
    "precipitation_probability",
    "wind_speed_10m",  # Wind speed at 10m (km/h) — affects panel cooling
    "sunshine_duration",  # Seconds of sunshine per hour
]

# Daily variables — sunrise/sunset for proper daylight filtering
DAILY_VARS = ["sunrise", "sunset"]


class OpenMeteoClient:
    """Async client for the Open-Meteo weather API."""

    def __init__(self, latitude: float, longitude: float) -> None:
        self.latitude = latitude
        self.longitude = longitude
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_solar_forecast(self, forecast_days: int = 3) -> list[dict[str, Any]]:
        """Get hourly solar radiation and weather forecast.

        Returns a list of hourly records, each containing:
            time, shortwave_radiation, direct_radiation, diffuse_radiation,
            direct_normal_irradiance, cloud_cover, temperature_2m, etc.
        """
        client = await self._get_client()
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join(HOURLY_VARS),
            "daily": ",".join(DAILY_VARS),
            "forecast_days": forecast_days,
            "timezone": "UTC",
        }
        resp = await client.get(FORECAST_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_hourly(data)

    async def get_historical_weather(
        self, start_date: str | date, end_date: str | date
    ) -> list[dict[str, Any]]:
        """Get historical hourly weather data for model training.

        Args:
            start_date: Start date (YYYY-MM-DD or date object).
            end_date: End date (YYYY-MM-DD or date object).

        Returns:
            List of hourly records with same fields as forecast.
        """
        client = await self._get_client()
        params = {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "hourly": ",".join(HOURLY_VARS),
            "daily": ",".join(DAILY_VARS),
            "start_date": str(start_date),
            "end_date": str(end_date),
            "timezone": "UTC",
        }
        resp = await client.get(HISTORICAL_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        return self._parse_hourly(data)

    def _parse_hourly(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert Open-Meteo response to a list of hourly dicts.

        Includes sunrise_hour and sunset_hour (decimal UTC hours) from daily
        data, merged into each hourly record by date.
        """
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])

        # Parse daily sunrise/sunset → decimal hour by date
        daily = data.get("daily", {})
        daily_times = daily.get("time", [])
        sunrise_by_date: dict[str, float] = {}
        sunset_by_date: dict[str, float] = {}
        for i, dt_str in enumerate(daily_times):
            sr_list = daily.get("sunrise", [])
            ss_list = daily.get("sunset", [])
            if i < len(sr_list) and sr_list[i]:
                sr_dt = datetime.fromisoformat(sr_list[i])
                sunrise_by_date[dt_str] = sr_dt.hour + sr_dt.minute / 60.0
            if i < len(ss_list) and ss_list[i]:
                ss_dt = datetime.fromisoformat(ss_list[i])
                sunset_by_date[dt_str] = ss_dt.hour + ss_dt.minute / 60.0

        records = []
        for i, time_str in enumerate(times):
            record: dict[str, Any] = {
                "time": datetime.fromisoformat(time_str),
            }
            for var in HOURLY_VARS:
                record[var] = hourly.get(var, [None])[i]

            # Attach sunrise/sunset for this day (fallback 6/18 if missing)
            date_str = time_str[:10]
            record["sunrise_hour"] = sunrise_by_date.get(date_str, 6.0)
            record["sunset_hour"] = sunset_by_date.get(date_str, 18.0)

            records.append(record)
        return records
