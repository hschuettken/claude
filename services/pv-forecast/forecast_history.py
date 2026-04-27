"""Forecast history logger.

Captures rolling forecast data so the ML model can later learn from
forecast revisions (volatility, drift, late changes — all signals that
correlate with cloudy/transitional weather and reduced accuracy).

Three measurements written to the `analytics` bucket:

  pv_weather_forecast_history
    timestamp = target hour (when the prediction is for, UTC)
    tags      = forecast_run_iso (when made)
    fields    = 13 weather columns (GHI, DNI, direct, diffuse, cloud cover
                ×4, temp, humidity, wind, sunshine, precipitation)

  pv_weather_actual
    timestamp = target hour
    fields    = same 13 weather columns from Open-Meteo's archive API
                (delayed ~2 days)

  pv_forecast_rolling
    timestamp = forecast_run_at (when made)
    tags      = source ('pv_ai' | 'forecast_solar'),
                array  ('east' | 'west' | 'total'),
                target_day ('D+0' | 'D+1' | 'D+2')
    fields    = forecast_kwh

Cardinality budget: ~25-30k unique series/year — well within Influx's
sweet spot. Written via the all-access admin client.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx

from shared.influx_client import InfluxClient
from shared.log import get_logger

logger = get_logger("pv-forecast-history")

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ARCHIVE_VARS = [
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
    "precipitation",
]


class ForecastHistoryLogger:
    """Logs rolling forecasts and actuals to the analytics bucket."""

    def __init__(
        self,
        influx_admin: InfluxClient,
        analytics_bucket: str,
        latitude: float,
        longitude: float,
        ha_client: Any | None = None,
        forecast_solar_east_entity: str = "",
        forecast_solar_west_entity: str = "",
    ) -> None:
        self.influx = influx_admin
        self.bucket = analytics_bucket
        self.lat = latitude
        self.lon = longitude
        self.ha = ha_client
        self.fs_east_entity = forecast_solar_east_entity
        self.fs_west_entity = forecast_solar_west_entity

    # ---------------- Open-Meteo forecast history ----------------

    async def log_open_meteo_forecast(
        self, hourly_records: list[dict[str, Any]]
    ) -> int:
        """Log a fresh Open-Meteo hourly forecast as one batch tagged by run time.

        Args:
            hourly_records: list of dicts as returned by OpenMeteoClient.get_solar_forecast()
                — each dict has 'time' (ISO) plus weather columns.

        Returns: number of points written.
        """
        if not hourly_records:
            return 0
        run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        written = 0
        for r in hourly_records:
            t = r.get("time")
            if t is None:
                continue
            try:
                if isinstance(t, datetime):
                    target_dt = t
                else:
                    target_dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            fields: dict[str, Any] = {}
            for col in ARCHIVE_VARS + ["precipitation_probability"]:
                v = r.get(col)
                if v is not None:
                    try:
                        fields[col] = float(v)
                    except (TypeError, ValueError):
                        pass
            if not fields:
                continue
            self.influx.write_point(
                bucket=self.bucket,
                measurement="pv_weather_forecast_history",
                fields=fields,
                tags={"forecast_run_iso": run_iso},
                timestamp=target_dt,
            )
            written += 1
        logger.info(
            "open_meteo_forecast_logged",
            points=written,
            run_iso=run_iso,
        )
        return written

    # ---------------- Open-Meteo archive (actuals) ----------------

    async def log_actuals_for_date(self, target_date: date) -> int:
        """Fetch & log the *actual* hourly weather for a past date from
        Open-Meteo's archive API. Archive lags reality by ~2 days, so call
        this for D-2 daily.
        """
        params = {
            "latitude": self.lat,
            "longitude": self.lon,
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
            "timezone": "UTC",
            "hourly": ",".join(ARCHIVE_VARS),
        }
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.get(ARCHIVE_URL, params=params)
                r.raise_for_status()
                j = r.json()
        except Exception as e:
            logger.warning("archive_fetch_failed", date=str(target_date), err=str(e))
            return 0

        hourly = j.get("hourly", {})
        times = hourly.get("time", [])
        if not times:
            return 0

        written = 0
        for i, t in enumerate(times):
            try:
                target_dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            fields: dict[str, Any] = {}
            for col in ARCHIVE_VARS:
                vals = hourly.get(col, [])
                if i < len(vals) and vals[i] is not None:
                    try:
                        fields[col] = float(vals[i])
                    except (TypeError, ValueError):
                        pass
            if not fields:
                continue
            self.influx.write_point(
                bucket=self.bucket,
                measurement="pv_weather_actual",
                fields=fields,
                timestamp=target_dt,
            )
            written += 1
        logger.info("archive_logged", date=str(target_date), points=written)
        return written

    # ---------------- Rolling forecast outputs (pv-ai + Forecast.Solar) ----------------

    async def log_pv_ai_forecast(
        self,
        today_east_kwh: float,
        today_west_kwh: float,
        tomorrow_east_kwh: float,
        tomorrow_west_kwh: float,
        day_after_east_kwh: float,
        day_after_west_kwh: float,
    ) -> None:
        """Log the current pv-ai forecast outputs (one row per (array, target_day))."""
        run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs_ts = datetime.now(timezone.utc)
        rows = [
            ("D+0", "east", today_east_kwh),
            ("D+0", "west", today_west_kwh),
            ("D+0", "total", today_east_kwh + today_west_kwh),
            ("D+1", "east", tomorrow_east_kwh),
            ("D+1", "west", tomorrow_west_kwh),
            ("D+1", "total", tomorrow_east_kwh + tomorrow_west_kwh),
            ("D+2", "east", day_after_east_kwh),
            ("D+2", "west", day_after_west_kwh),
            ("D+2", "total", day_after_east_kwh + day_after_west_kwh),
        ]
        for target_day, array, kwh in rows:
            if kwh is None:
                continue
            self.influx.write_point(
                bucket=self.bucket,
                measurement="pv_forecast_rolling",
                fields={"forecast_kwh": float(kwh)},
                tags={
                    "source": "pv_ai",
                    "array": array,
                    "target_day": target_day,
                    "forecast_run_iso": run_iso,
                },
                timestamp=runs_ts,
            )
        logger.debug("pv_ai_forecast_logged", rows=len(rows))

    async def log_forecast_solar_state(self) -> int:
        """Read current Forecast.Solar values from HA and log them.

        Captures how Forecast.Solar's prediction for today/tomorrow evolves
        over the day (e.g. morning prediction vs. afternoon prediction).
        """
        if self.ha is None:
            return 0
        run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        runs_ts = datetime.now(timezone.utc)
        # Map: HA entity → (target_day, array)
        entity_map: dict[str, tuple[str, str]] = {}
        if self.fs_east_entity:
            entity_map[self.fs_east_entity] = ("D+0", "east")
        if self.fs_west_entity:
            entity_map[self.fs_west_entity] = ("D+0", "west")
        # Tomorrow entities — name-replace today→tomorrow
        for today_ent, (_, array) in list(entity_map.items()):
            tomorrow_ent = today_ent.replace("_today_", "_tomorrow_")
            if tomorrow_ent != today_ent:
                entity_map[tomorrow_ent] = ("D+1", array)

        written = 0
        for entity_id, (target_day, array) in entity_map.items():
            try:
                state = await self.ha.get_state(entity_id)
                if not state or state.get("state") in (
                    None,
                    "",
                    "unknown",
                    "unavailable",
                ):
                    continue
                kwh = float(state["state"])
            except Exception as e:
                logger.debug("forecast_solar_read_failed", entity=entity_id, err=str(e))
                continue
            self.influx.write_point(
                bucket=self.bucket,
                measurement="pv_forecast_rolling",
                fields={"forecast_kwh": kwh},
                tags={
                    "source": "forecast_solar",
                    "array": array,
                    "target_day": target_day,
                    "forecast_run_iso": run_iso,
                },
                timestamp=runs_ts,
            )
            written += 1
        logger.info("forecast_solar_logged", points=written)
        return written
