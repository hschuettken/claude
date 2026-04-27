"""PV Forecast Service — AI-powered solar production forecast.

Uses historical production data (InfluxDB) + weather forecasts (Open-Meteo)
to predict PV output for east and west arrays. Falls back to a radiation-based
estimate when insufficient training data is available.

Schedule:
  - On startup: load or train model, run initial forecast
  - Every hour: update forecast and push to HA
  - Daily at configured hour: retrain model with latest data

Output sensors in Home Assistant:
  - pv_ai_forecast_today_kwh
  - pv_ai_forecast_today_remaining_kwh
  - pv_ai_forecast_tomorrow_kwh
  - pv_ai_forecast_day_after_tomorrow_kwh
  - pv_ai_forecast_east_today_kwh / west_today_kwh
  - pv_ai_forecast_east_tomorrow_kwh / west_tomorrow_kwh
"""

import asyncio
import threading
import time
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.energy_events import (
    PVAnomalyDetected,
    PVDriftDetected,
    PVForecastAccuracyResult,
    PVForecastUpdated,
    PVHourlyForecast,
    PVModelRetrained,
    SolarDaylightWindow,
)
from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.nats_client import NatsPublisher

HEALTHCHECK_FILE = Path("/app/data/healthcheck")

from config import PVForecastSettings
from data import PVDataCollector
from forecast import ForecastEngine
from forecast_history import ForecastHistoryLogger
from ha_sensors import HASensorPublisher
from weather import OpenMeteoClient

logger = get_logger("pv-forecast")


class PVForecastService:
    """Main service coordinating model training, forecasting, and publishing."""

    async def _register_with_oracle(self) -> None:
        """Best-effort Oracle registration. Non-critical — service must start even if Oracle is down."""
        try:
            manifest = {
                "service_name": "pv-forecast",
                "port": None,
                "description": "PV production forecast from Solcast API",
                "endpoints": [],
                "nats_subjects": [
                    "energy.pv.forecast.updated",
                    "energy.pv.forecast.model_trained",
                    "energy.daylight.window",
                    "heartbeat.pv-forecast",
                    "orchestrator.command.pv-forecast",
                ],
                "source_paths": [
                    {"repo": "claude", "paths": ["services/pv-forecast/"]},
                ],
            }
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post("http://192.168.0.50:8225/oracle/register", json=manifest)
        except Exception:
            pass

    def __init__(self) -> None:
        self.settings = PVForecastSettings()
        self.scheduler = AsyncIOScheduler()

        # Clients
        self.ha = HomeAssistantClient(self.settings.ha_url, self.settings.ha_token)
        self.influx = InfluxClient(
            self.settings.influxdb_url,
            self.settings.influxdb_token,
            self.settings.influxdb_org,
        )
        # Separate client for the analytics bucket (forecast accuracy + model metrics).
        # Uses an admin token with cross-bucket write access. Falls back to the
        # main client if the admin token isn't configured.
        if self.settings.influxdb_all_access_token:
            self.influx_admin = InfluxClient(
                self.settings.influxdb_url,
                self.settings.influxdb_all_access_token,
                self.settings.influxdb_org,
            )
        else:
            self.influx_admin = self.influx

        self._start_time = time.monotonic()

        # Location — will be resolved from HA if not configured
        self.latitude = self.settings.pv_latitude
        self.longitude = self.settings.pv_longitude

        # These are initialized in start() after resolving location
        self.weather: OpenMeteoClient | None = None
        self.data_collector: PVDataCollector | None = None
        self.engine: ForecastEngine | None = None
        self.publisher: HASensorPublisher | None = None

        # --- Tracking state for enhanced sensors ---
        self._last_training_results: dict[str, dict] = {}
        self._last_training_time: str = ""
        self._last_forecast_time: str = ""
        self._data_days: dict[str, int] = {"east": 0, "west": 0}
        self._forecast_solar_today: dict[str, float] = {}
        self._last_forecast_summary: str = ""

        # --- NATS publisher (initialized in start()) ---
        self.nats: NatsPublisher | None = None

        # --- Accuracy / anomaly tracking ---
        self._today_forecast_kwh: dict[str, float] = {}
        self._anomaly_threshold_pct: float = 30.0
        self._mae_history: list[float] = []
        self._last_accuracy_pct: float = 0.0

        # --- Sunrise/sunset ---
        self._sunrise_hhmm: str | None = None
        self._sunset_hhmm: str | None = None

    async def _resolve_location(self) -> None:
        """Get lat/lon from HA config if not explicitly set."""
        if self.latitude and self.longitude:
            logger.info("location_from_config", lat=self.latitude, lon=self.longitude)
            return

        try:
            client = await self.ha._get_client()
            resp = await client.get("/config")
            resp.raise_for_status()
            config = resp.json()
            self.latitude = config.get("latitude", 0.0)
            self.longitude = config.get("longitude", 0.0)
            logger.info("location_from_ha", lat=self.latitude, lon=self.longitude)
        except Exception:
            logger.exception("failed_to_get_location")
            raise RuntimeError(
                "Location not configured (PV_LATITUDE/PV_LONGITUDE) "
                "and could not be fetched from Home Assistant."
            )

    async def start(self) -> None:
        """Initialize and start the service."""
        logger.info("service_starting")

        # Register with Oracle (non-blocking)
        asyncio.create_task(self._register_with_oracle())

        # Resolve location
        await self._resolve_location()

        # Initialize NATS if enabled
        if self.settings.nats_enabled:
            self.nats = NatsPublisher(url=self.settings.nats_url)
            await self.nats.connect()

        # Initialize components
        self.weather = OpenMeteoClient(self.latitude, self.longitude)
        self.data_collector = PVDataCollector(
            self.influx, self.weather, self.settings, influx_admin=self.influx_admin
        )
        self.engine = ForecastEngine(
            self.settings, self.data_collector, self.weather, self.ha
        )
        # Pass resolved lat/lon (may have come from HA, not settings)
        self.engine.latitude = self.latitude
        self.engine.longitude = self.longitude
        self.publisher = HASensorPublisher(self.ha, self.settings.ha_sensor_prefix)

        # Forecast history logger — captures rolling forecasts to analytics bucket
        # so the model can later learn from forecast revisions/volatility.
        self.history = ForecastHistoryLogger(
            influx_admin=self.influx_admin,
            analytics_bucket=self.settings.influxdb_analytics_bucket,
            latitude=self.latitude,
            longitude=self.longitude,
            ha_client=self.ha,
            forecast_solar_east_entity=self.settings.forecast_solar_east_entity_id,
            forecast_solar_west_entity=self.settings.forecast_solar_west_entity_id,
        )

        # Register entities in HA via NATS ha.discovery (bridge forwards to MQTT for HA)
        await self._register_ha_discovery()

        # Subscribe to orchestrator commands via NATS
        if self.nats and self.nats.connected:
            await self.nats.subscribe_json(
                "orchestrator.command.pv-forecast",
                self._on_orchestrator_command,
            )

        # Calculate sunrise/sunset and publish daylight window
        await self._update_daylight_window()

        # Initial training attempt
        await self._train()

        # Initial forecast
        await self._forecast()

        # Schedule recurring tasks
        self.scheduler.add_job(
            self._forecast,
            "interval",
            minutes=self.settings.forecast_update_minutes,
            id="forecast_update",
        )
        self.scheduler.add_job(
            self._train,
            "cron",
            hour=self.settings.model_retrain_hour,
            id="daily_retrain",
        )
        self.scheduler.add_job(
            self._check_forecast_accuracy,
            "cron",
            hour=20,
            minute=0,
            id="accuracy_check",
        )
        self.scheduler.add_job(
            self._update_daylight_window,
            "cron",
            hour=4,
            minute=30,
            id="daylight_window",
        )
        # Hourly: log Open-Meteo rolling forecast to analytics bucket (Phase 1).
        # Runs at :05 to capture state slightly before the forecast cycle at :10.
        self.scheduler.add_job(
            self._log_rolling_forecasts,
            "cron",
            minute=5,
            id="log_rolling_forecasts",
        )
        # Daily at 06:00 UTC: pull D-2's actual hourly weather from Open-Meteo
        # archive (lags reality by ~2 days) → pv_weather_actual measurement.
        self.scheduler.add_job(
            self._log_actuals_archive,
            "cron",
            hour=6,
            minute=0,
            id="log_actuals_archive",
        )
        self.scheduler.start()

        # Start heartbeat in a dedicated daemon thread so it can't be
        # blocked by long-running scheduler jobs (ML training, InfluxDB queries).
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_thread_loop,
            daemon=True,
        )
        self._heartbeat_thread.start()

        logger.info(
            "service_started",
            forecast_interval_min=self.settings.forecast_update_minutes,
            retrain_hour=self.settings.model_retrain_hour,
        )

        # Keep running until interrupted
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    def _build_hourly_list(self, forecast, day_key: str) -> list[dict]:
        """Build hourly breakdown from FullForecast for a given day.

        Args:
            forecast: FullForecast object with east and west ArrayForecast
            day_key: "today", "tomorrow", or "day_after"

        Returns:
            List of dicts: [{hour: int, kwh: float, confidence: float}]
        """
        result = []
        east = forecast.east
        west = forecast.west

        # Get the day forecast from each array
        east_day = getattr(east, day_key, None) if east else None
        west_day = getattr(west, day_key, None) if west else None

        # Merge east + west hourly data by hour
        by_hour: dict[int, float] = {}
        if east_day and east_day.hourly:
            for h in east_day.hourly:
                hour = h.time.hour
                by_hour[hour] = by_hour.get(hour, 0) + h.kwh
        if west_day and west_day.hourly:
            for h in west_day.hourly:
                hour = h.time.hour
                by_hour[hour] = by_hour.get(hour, 0) + h.kwh

        for hour in sorted(by_hour.keys()):
            result.append(
                {"hour": hour, "kwh": round(by_hour[hour], 3), "confidence": 0.8}
            )
        return result

    async def _train(self) -> None:
        """Train or retrain the models."""
        try:
            results = await self.engine.train()
            logger.info("training_complete", results=results)
            self._last_training_results = results
            self._last_training_time = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )

            # Count data days per array for sensor exposure
            for array_name, entity_id in [
                ("east", self.settings.pv_east_energy_entity_id),
                ("west", self.settings.pv_west_energy_entity_id),
            ]:
                if entity_id and self.data_collector:
                    self._data_days[array_name] = (
                        self.data_collector.count_days_of_data(entity_id)
                    )

            # Publish training results with enhanced data
            enriched_results = {
                **results,
                "training_time": self._last_training_time,
                "data_days": self._data_days,
            }
            if self.nats and self.nats.connected:
                await self.nats.publish(
                    "energy.pv.forecast.model_trained", enriched_results
                )

            # Publish NATS typed event
            if self.nats and self.nats.connected and results:
                east = results.get("east", {})
                west = results.get("west", {})
                event = PVModelRetrained(
                    east_r2=east.get("r2", 0.0),
                    east_mae=east.get("mae", 0.0),
                    west_r2=west.get("r2", 0.0),
                    west_mae=west.get("mae", 0.0),
                    east_data_days=self._data_days.get("east", 0),
                    west_data_days=self._data_days.get("west", 0),
                    timestamp=self._last_training_time,
                )
                await self.nats.publish("energy.pv.model_retrained", event.model_dump())
        except Exception:
            logger.exception("training_failed")

    async def _forecast(self) -> None:
        """Generate and publish forecast."""
        try:
            forecast = await self.engine.forecast()
            await self.publisher.publish(forecast)

            self._last_forecast_time = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
            )

            # Fetch Forecast.Solar values for comparison
            await self._fetch_forecast_solar_comparison()

            east_model = forecast.east.model_type if forecast.east else "none"
            west_model = forecast.west.model_type if forecast.west else "none"

            # Build reasoning summary
            self._last_forecast_summary = self._compose_forecast_reasoning(forecast)

            # Build enriched MQTT payload
            summary: dict = {
                "today_kwh": forecast.today_total_kwh,
                "today_remaining_kwh": forecast.today_remaining_kwh,
                "tomorrow_kwh": forecast.tomorrow_total_kwh,
                "day_after_kwh": forecast.day_after_total_kwh,
                "east_today_kwh": (
                    forecast.east.today.total_kwh
                    if forecast.east and forecast.east.today
                    else 0.0
                ),
                "west_today_kwh": (
                    forecast.west.today.total_kwh
                    if forecast.west and forecast.west.today
                    else 0.0
                ),
                "east_tomorrow_kwh": (
                    forecast.east.tomorrow.total_kwh
                    if forecast.east and forecast.east.tomorrow
                    else 0.0
                ),
                "west_tomorrow_kwh": (
                    forecast.west.tomorrow.total_kwh
                    if forecast.west and forecast.west.tomorrow
                    else 0.0
                ),
                "east_model": east_model,
                "west_model": west_model,
                "timestamp": forecast.timestamp.isoformat(),
                # Enhanced model info
                "east_r2": self._last_training_results.get("east", {}).get("r2", 0.0),
                "west_r2": self._last_training_results.get("west", {}).get("r2", 0.0),
                "east_mae": self._last_training_results.get("east", {}).get("mae", 0.0),
                "west_mae": self._last_training_results.get("west", {}).get("mae", 0.0),
                "data_days_east": self._data_days.get("east", 0),
                "data_days_west": self._data_days.get("west", 0),
                "last_training_time": self._last_training_time,
                # Forecast.Solar comparison
                "forecast_solar_today_east": self._forecast_solar_today.get(
                    "east", 0.0
                ),
                "forecast_solar_today_west": self._forecast_solar_today.get(
                    "west", 0.0
                ),
                "forecast_solar_today_total": (
                    self._forecast_solar_today.get("east", 0.0)
                    + self._forecast_solar_today.get("west", 0.0)
                ),
                "reasoning": self._last_forecast_summary,
            }
            if self.nats and self.nats.connected:
                await self.nats.publish("energy.pv.forecast.updated", summary)

            # Publish NATS typed event
            if self.nats and self.nats.connected:
                east_r2 = self._last_training_results.get("east", {}).get("r2", 0.0)
                west_r2 = self._last_training_results.get("west", {}).get("r2", 0.0)
                valid_r2 = [r for r in [east_r2, west_r2] if r > 0]
                confidence = sum(valid_r2) / len(valid_r2) if valid_r2 else 0.5

                model_type = "ml" if "ml" in (east_model, west_model) else "fallback"

                # Store today's forecast per array for accuracy check
                self._today_forecast_kwh["east"] = summary.get("east_today_kwh", 0.0)
                self._today_forecast_kwh["west"] = summary.get("west_today_kwh", 0.0)

                nats_event = PVForecastUpdated(
                    today_kwh=summary["today_kwh"],
                    today_remaining_kwh=summary["today_remaining_kwh"],
                    tomorrow_kwh=summary["tomorrow_kwh"],
                    day_after_kwh=summary["day_after_kwh"],
                    east_today_kwh=summary["east_today_kwh"],
                    west_today_kwh=summary["west_today_kwh"],
                    confidence=round(confidence, 3),
                    model_type=model_type,
                    timestamp=forecast.timestamp.isoformat(),
                    sunrise=self._sunrise_hhmm,
                    sunset=self._sunset_hhmm,
                )
                await self.nats.publish(
                    "energy.pv.forecast_updated", nats_event.model_dump()
                )

                # Publish hourly forecast breakdown
                hourly_event = PVHourlyForecast(
                    today=self._build_hourly_list(forecast, "today"),
                    tomorrow=self._build_hourly_list(forecast, "tomorrow"),
                    timestamp=forecast.timestamp.isoformat(),
                )
                await self.nats.publish(
                    "energy.pv.hourly_forecast", hourly_event.model_dump()
                )

            # Log this forecast cycle's pv-ai output to analytics bucket
            # (rolling history for forecast-revision learning).
            try:
                await self.history.log_pv_ai_forecast(
                    today_east_kwh=summary["east_today_kwh"],
                    today_west_kwh=summary["west_today_kwh"],
                    tomorrow_east_kwh=summary["east_tomorrow_kwh"],
                    tomorrow_west_kwh=summary["west_tomorrow_kwh"],
                    day_after_east_kwh=(
                        forecast.east.day_after.total_kwh
                        if forecast.east and forecast.east.day_after
                        else 0.0
                    ),
                    day_after_west_kwh=(
                        forecast.west.day_after.total_kwh
                        if forecast.west and forecast.west.day_after
                        else 0.0
                    ),
                )
            except Exception:
                logger.warning("history_log_pv_ai_failed", exc_info=True)

        except Exception:
            logger.exception("forecast_failed")
        finally:
            self._touch_healthcheck()

    async def _log_rolling_forecasts(self) -> None:
        """Hourly: pull a fresh Open-Meteo forecast and log Forecast.Solar state
        to the analytics bucket. Runs at :05 each hour."""
        try:
            records = await self.weather.get_solar_forecast(forecast_days=4)
            if records:
                await self.history.log_open_meteo_forecast(records)
        except Exception:
            logger.warning("history_log_open_meteo_failed", exc_info=True)
        try:
            await self.history.log_forecast_solar_state()
        except Exception:
            logger.warning("history_log_forecast_solar_failed", exc_info=True)

    async def _log_actuals_archive(self) -> None:
        """Daily 06:00 UTC: log D-2 hourly actuals from Open-Meteo's archive."""
        from datetime import date, timedelta

        target = date.today() - timedelta(days=2)
        try:
            await self.history.log_actuals_for_date(target)
        except Exception:
            logger.warning(
                "history_log_actuals_failed", date=str(target), exc_info=True
            )

    async def _check_forecast_accuracy(self) -> None:
        """Evening job: compare today's forecast vs actual production."""
        try:
            today_str = time.strftime("%Y-%m-%d", time.localtime())

            # Query actual production for today from InfluxDB
            east_actual = 0.0
            west_actual = 0.0

            east_entity = self.settings.pv_east_energy_entity_id
            west_entity = self.settings.pv_west_energy_entity_id

            if east_entity:
                records = self.influx.query_records(
                    bucket="hass",
                    entity_id=east_entity,
                    range_start="-24h",
                    range_stop="now()",
                )
                if records:
                    values = [
                        r["_value"] for r in records if r.get("_value") is not None
                    ]
                    if len(values) >= 2:
                        east_actual = max(values) - min(values)

            if west_entity:
                records = self.influx.query_records(
                    bucket="hass",
                    entity_id=west_entity,
                    range_start="-24h",
                    range_stop="now()",
                )
                if records:
                    values = [
                        r["_value"] for r in records if r.get("_value") is not None
                    ]
                    if len(values) >= 2:
                        west_actual = max(values) - min(values)

            east_forecast = self._today_forecast_kwh.get("east", 0.0)
            west_forecast = self._today_forecast_kwh.get("west", 0.0)

            if east_forecast <= 0 and west_forecast <= 0:
                logger.info("accuracy_check_skipped", reason="no_forecast_data")
                return

            total_forecast = east_forecast + west_forecast
            total_actual = east_actual + west_actual

            def safe_delta(forecast: float, actual: float) -> float:
                if forecast <= 0:
                    return 0.0
                return ((actual - forecast) / forecast) * 100.0

            east_delta_pct = safe_delta(east_forecast, east_actual)
            west_delta_pct = safe_delta(west_forecast, west_actual)
            total_delta_pct = safe_delta(total_forecast, total_actual)
            accuracy_pct = max(0.0, 100.0 - abs(total_delta_pct))

            self._last_accuracy_pct = accuracy_pct

            # Rolling MAE history (30-day window)
            mae = abs(total_actual - total_forecast)
            self._mae_history.append(mae)
            if len(self._mae_history) > 30:
                self._mae_history.pop(0)

            # Write to InfluxDB analytics bucket via admin client
            self.influx_admin.write_point(
                bucket=self.settings.influxdb_analytics_bucket,
                measurement="pv_forecast_accuracy",
                fields={
                    "forecast_kwh": round(total_forecast, 3),
                    "actual_kwh": round(total_actual, 3),
                    "delta_pct": round(total_delta_pct, 2),
                    "accuracy_pct": round(accuracy_pct, 2),
                    "east_forecast_kwh": round(east_forecast, 3),
                    "east_actual_kwh": round(east_actual, 3),
                    "west_forecast_kwh": round(west_forecast, 3),
                    "west_actual_kwh": round(west_actual, 3),
                },
                tags={"date": today_str},
            )

            # Publish NATS accuracy event — bridge forwards to MQTT for HA discovery sensor
            if self.nats and self.nats.connected:
                await self.nats.publish(
                    "energy.pv.forecast.accuracy",
                    {
                        "accuracy_pct": round(accuracy_pct, 1),
                        "forecast_kwh": round(total_forecast, 2),
                        "actual_kwh": round(total_actual, 2),
                        "delta_pct": round(total_delta_pct, 2),
                        "date": today_str,
                    },
                )
                accuracy_event = PVForecastAccuracyResult(
                    date=today_str,
                    east_forecast_kwh=round(east_forecast, 3),
                    east_actual_kwh=round(east_actual, 3),
                    east_delta_pct=round(east_delta_pct, 2),
                    west_forecast_kwh=round(west_forecast, 3),
                    west_actual_kwh=round(west_actual, 3),
                    west_delta_pct=round(west_delta_pct, 2),
                    total_forecast_kwh=round(total_forecast, 3),
                    total_actual_kwh=round(total_actual, 3),
                    total_delta_pct=round(total_delta_pct, 2),
                    accuracy_pct=round(accuracy_pct, 2),
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
                await self.nats.publish(
                    "energy.pv.accuracy_checked", accuracy_event.model_dump()
                )

            # Drift detection: if 7-day MAE > 1.5x 30-day baseline
            if len(self._mae_history) >= 7:
                mae_7d = sum(self._mae_history[-7:]) / 7
                mae_30d = sum(self._mae_history) / len(self._mae_history)
                threshold = 1.5
                if mae_30d > 0 and mae_7d > mae_30d * threshold:
                    logger.warning(
                        "pv_forecast_drift_detected",
                        mae_7d=mae_7d,
                        mae_30d=mae_30d,
                    )
                    if self.nats and self.nats.connected:
                        drift_event = PVDriftDetected(
                            mae_7d=round(mae_7d, 3),
                            mae_30d=round(mae_30d, 3),
                            ratio=round(mae_7d / mae_30d, 2),
                            threshold=threshold,
                            timestamp=time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            ),
                        )
                        await self.nats.publish(
                            "energy.pv.drift_detected", drift_event.model_dump()
                        )

            # Anomaly detection: >30% deviation with meaningful forecast
            if (
                abs(total_delta_pct) > self._anomaly_threshold_pct
                and total_forecast > 1.0
            ):
                if self.nats and self.nats.connected:
                    anomaly_event = PVAnomalyDetected(
                        array="total",
                        actual_kwh=round(total_actual, 3),
                        forecast_kwh=round(total_forecast, 3),
                        deviation_pct=round(total_delta_pct, 2),
                        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    )
                    await self.nats.publish(
                        "energy.pv.anomaly_detected", anomaly_event.model_dump()
                    )

            logger.info(
                "accuracy_check_complete",
                accuracy_pct=round(accuracy_pct, 1),
                total_forecast=round(total_forecast, 2),
                total_actual=round(total_actual, 2),
            )
        except Exception:
            logger.exception("accuracy_check_failed")

    async def _update_daylight_window(self) -> None:
        """Calculate and publish sunrise/sunset window via NATS.

        Uses astral library if available, falls back to hard-coded estimates.
        """
        try:
            from datetime import date as _date

            now_local = time.localtime()
            today = _date(now_local.tm_year, now_local.tm_mon, now_local.tm_mday)
            today_str = today.isoformat()

            sunrise_dt = None
            sunset_dt = None

            # Try astral first
            try:
                from zoneinfo import ZoneInfo

                from astral import LocationInfo
                from astral.sun import sun

                tz_name = getattr(self.settings, "timezone", "Europe/Berlin")
                loc = LocationInfo(
                    latitude=self.latitude or 53.0,
                    longitude=self.longitude or 10.0,
                    timezone=tz_name,
                )
                s = sun(loc.observer, date=today, tzinfo=ZoneInfo(tz_name))
                sunrise_dt = s["sunrise"]
                sunset_dt = s["sunset"]
            except ImportError:
                logger.debug("astral_not_available_using_estimate")
                # Fallback: rough estimate for Hamburg (53°N)
                month = now_local.tm_mon
                if 4 <= month <= 9:
                    sunrise_h, sunrise_m = 5, 30
                    sunset_h, sunset_m = 21, 0
                elif 10 <= month <= 11 or month <= 2:
                    sunrise_h, sunrise_m = 8, 0
                    sunset_h, sunset_m = 16, 30
                else:
                    sunrise_h, sunrise_m = 6, 30
                    sunset_h, sunset_m = 19, 30
                self._sunrise_hhmm = f"{sunrise_h:02d}:{sunrise_m:02d}"
                self._sunset_hhmm = f"{sunset_h:02d}:{sunset_m:02d}"

            if sunrise_dt and sunset_dt:
                self._sunrise_hhmm = sunrise_dt.strftime("%H:%M")
                self._sunset_hhmm = sunset_dt.strftime("%H:%M")

            if (
                self.nats
                and self.nats.connected
                and self._sunrise_hhmm
                and self._sunset_hhmm
            ):
                window_event = SolarDaylightWindow(
                    sunrise=(
                        sunrise_dt.isoformat()
                        if sunrise_dt
                        else f"{today_str}T{self._sunrise_hhmm}:00"
                    ),
                    sunset=(
                        sunset_dt.isoformat()
                        if sunset_dt
                        else f"{today_str}T{self._sunset_hhmm}:00"
                    ),
                    sunrise_hhmm=self._sunrise_hhmm,
                    sunset_hhmm=self._sunset_hhmm,
                    date=today_str,
                    timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                )
                await self.nats.publish(
                    "energy.solar.daylight_window", window_event.model_dump()
                )

            logger.info(
                "daylight_window_updated",
                sunrise=self._sunrise_hhmm,
                sunset=self._sunset_hhmm,
            )
        except Exception:
            logger.exception("daylight_window_failed")

    async def _fetch_forecast_solar_comparison(self) -> None:
        """Fetch Forecast.Solar values from HA for comparison sensors."""
        for array_name, entity_id in [
            ("east", self.settings.forecast_solar_east_entity_id),
            ("west", self.settings.forecast_solar_west_entity_id),
        ]:
            if not entity_id:
                continue
            try:
                state = await self.ha.get_state(entity_id)
                val = state.get("state", "0")
                if val not in ("unavailable", "unknown"):
                    self._forecast_solar_today[array_name] = float(val)
            except Exception:
                logger.debug("forecast_solar_comparison_failed", array=array_name)

    def _compose_forecast_reasoning(self, forecast: "FullForecast") -> str:
        """Compose a human-readable reasoning for the current forecast."""

        lines: list[str] = []

        lines.append(f"Forecast updated: {self._last_forecast_time}")

        for arr_name, arr in [("East", forecast.east), ("West", forecast.west)]:
            if arr is None:
                lines.append(f"{arr_name}: not configured")
                continue

            model = arr.model_type
            data_days = self._data_days.get(arr_name.lower(), 0)
            today_kwh = arr.today.total_kwh if arr.today else 0.0
            tmrw_kwh = arr.tomorrow.total_kwh if arr.tomorrow else 0.0

            if model == "ml":
                r2 = self._last_training_results.get(arr_name.lower(), {}).get(
                    "r2", 0.0
                )
                mae = self._last_training_results.get(arr_name.lower(), {}).get(
                    "mae", 0.0
                )
                lines.append(
                    f"{arr_name}: ML model (R²={r2:.3f}, MAE={mae:.3f} kWh, "
                    f"{data_days} days training data)"
                )
            else:
                lines.append(
                    f"{arr_name}: Fallback/radiation estimate "
                    f"({data_days}/{self.settings.model_min_days} days, "
                    f"need more data for ML)"
                )

            lines.append(f"  Today: {today_kwh:.1f} kWh | Tomorrow: {tmrw_kwh:.1f} kWh")

            # Forecast.Solar comparison
            fs_val = self._forecast_solar_today.get(arr_name.lower(), 0.0)
            if fs_val > 0 and today_kwh > 0:
                diff_pct = ((today_kwh - fs_val) / fs_val) * 100
                lines.append(
                    f"  vs Forecast.Solar: {fs_val:.1f} kWh (AI is {diff_pct:+.0f}%)"
                )

        lines.append(
            f"Total today: {forecast.today_total_kwh:.1f} kWh | "
            f"Remaining: {forecast.today_remaining_kwh:.1f} kWh | "
            f"Tomorrow: {forecast.tomorrow_total_kwh:.1f} kWh"
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Orchestrator command handler
    # ------------------------------------------------------------------

    async def _on_orchestrator_command(self, subject: str, payload: dict) -> None:
        """Handle commands from the orchestrator service (NATS callback)."""
        command = payload.get("command", "")
        logger.info("orchestrator_command", command=command)

        if command == "refresh":
            await self._forecast()
        elif command == "retrain":
            await self._train()
        else:
            logger.debug("unknown_command", command=command)

    async def _publish_ha_discovery(
        self, component: str, object_id: str, config: dict, node_id: str = ""
    ) -> None:
        """Publish HA auto-discovery config via NATS (bridge forwards to MQTT for HA)."""
        if not (self.nats and self.nats.connected):
            return
        if "unique_id" not in config:
            config["unique_id"] = f"{node_id}_{object_id}" if node_id else object_id
        if node_id:
            subject = f"ha.discovery.{component}.{node_id}.{object_id}"
        else:
            subject = f"ha.discovery.{component}.{object_id}"
        await self.nats.publish(subject, config)

    async def _register_ha_discovery(self) -> None:
        """Register service entities in HA via NATS ha.discovery subjects."""
        device = {
            "identifiers": ["homelab_pv_forecast"],
            "name": "PV AI Forecast",
            "manufacturer": "Homelab",
            "model": "pv-forecast",
        }
        node = "pv_forecast"
        updated_topic = "homelab/pv-forecast/updated"
        heartbeat_topic = "homelab/pv-forecast/heartbeat"
        trained_topic = "homelab/pv-forecast/model-trained"  # noqa: F841

        # --- Connectivity & uptime ---
        await self._publish_ha_discovery(
            "binary_sensor",
            "status",
            node_id=node,
            config={
                "name": "PV Forecast Service",
                "device": device,
                "state_topic": heartbeat_topic,
                "value_template": "{{ 'ON' if value_json.status == 'online' else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "device_class": "running",
                "expire_after": 180,
                "icon": "mdi:solar-power-variant",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "uptime",
            node_id=node,
            config={
                "name": "PV Forecast Uptime",
                "device": device,
                "state_topic": heartbeat_topic,
                "value_template": "{{ value_json.uptime_seconds | round(0) }}",
                "unit_of_measurement": "s",
                "device_class": "duration",
                "entity_category": "diagnostic",
                "icon": "mdi:timer-outline",
            },
        )

        # --- Core forecast sensors ---
        await self._publish_ha_discovery(
            "sensor",
            "today_kwh",
            node_id=node,
            config={
                "name": "PV Forecast Today",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.today_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-power-variant",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "today_remaining_kwh",
            node_id=node,
            config={
                "name": "PV Forecast Today Remaining",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.today_remaining_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-power-variant",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "tomorrow_kwh",
            node_id=node,
            config={
                "name": "PV Forecast Tomorrow",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.tomorrow_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-power-variant",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "day_after_kwh",
            node_id=node,
            config={
                "name": "PV Forecast Day After Tomorrow",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.day_after_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-power-variant",
            },
        )

        # --- Per-array breakdown sensors ---
        await self._publish_ha_discovery(
            "sensor",
            "east_today_kwh",
            node_id=node,
            config={
                "name": "PV Forecast East Today",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.east_today_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-panel",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "west_today_kwh",
            node_id=node,
            config={
                "name": "PV Forecast West Today",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.west_today_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-panel",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "east_tomorrow_kwh",
            node_id=node,
            config={
                "name": "PV Forecast East Tomorrow",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.east_tomorrow_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-panel",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "west_tomorrow_kwh",
            node_id=node,
            config={
                "name": "PV Forecast West Tomorrow",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.west_tomorrow_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-panel",
            },
        )

        # --- Model quality & training sensors ---
        await self._publish_ha_discovery(
            "sensor",
            "east_model_type",
            node_id=node,
            config={
                "name": "East Model Type",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.east_model }}",
                "icon": "mdi:brain",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "west_model_type",
            node_id=node,
            config={
                "name": "West Model Type",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.west_model }}",
                "icon": "mdi:brain",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "east_model_r2",
            node_id=node,
            config={
                "name": "East Model R²",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.east_r2 }}",
                "icon": "mdi:chart-line",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "west_model_r2",
            node_id=node,
            config={
                "name": "West Model R²",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.west_r2 }}",
                "icon": "mdi:chart-line",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "east_model_mae",
            node_id=node,
            config={
                "name": "East Model MAE",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.east_mae }}",
                "unit_of_measurement": "kWh",
                "icon": "mdi:chart-scatter-plot",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "west_model_mae",
            node_id=node,
            config={
                "name": "West Model MAE",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.west_mae }}",
                "unit_of_measurement": "kWh",
                "icon": "mdi:chart-scatter-plot",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "data_days_east",
            node_id=node,
            config={
                "name": "Training Data Days (East)",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.data_days_east }}",
                "unit_of_measurement": "days",
                "icon": "mdi:database-clock-outline",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "data_days_west",
            node_id=node,
            config={
                "name": "Training Data Days (West)",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.data_days_west }}",
                "unit_of_measurement": "days",
                "icon": "mdi:database-clock-outline",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "last_training",
            node_id=node,
            config={
                "name": "Last Model Training",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.last_training_time }}",
                "device_class": "timestamp",
                "icon": "mdi:school-outline",
                "entity_category": "diagnostic",
            },
        )

        # --- Forecast.Solar comparison ---
        await self._publish_ha_discovery(
            "sensor",
            "forecast_solar_today",
            node_id=node,
            config={
                "name": "Forecast.Solar Today (comparison)",
                "device": device,
                "state_topic": updated_topic,
                "value_template": "{{ value_json.forecast_solar_today_total }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:weather-sunny-alert",
            },
        )

        # --- Decision reasoning (the key sensor) ---
        await self._publish_ha_discovery(
            "sensor",
            "forecast_reasoning",
            node_id=node,
            config={
                "name": "Forecast Reasoning",
                "device": device,
                "state_topic": updated_topic,
                "value_template": (
                    "{{ value_json.east_model }}/{{ value_json.west_model }}: "
                    "{{ value_json.today_kwh }} kWh today"
                ),
                "json_attributes_topic": updated_topic,
                "json_attributes_template": (
                    '{{ {"full_reasoning": value_json.reasoning, '
                    '"east_model": value_json.east_model, '
                    '"west_model": value_json.west_model, '
                    '"east_r2": value_json.east_r2, '
                    '"west_r2": value_json.west_r2, '
                    '"data_days_east": value_json.data_days_east, '
                    '"data_days_west": value_json.data_days_west, '
                    '"forecast_solar_today_total": value_json.forecast_solar_today_total, '
                    '"last_training_time": value_json.last_training_time} | tojson }}'
                ),
                "icon": "mdi:head-cog-outline",
            },
        )

        # --- Accuracy sensor ---
        await self._publish_ha_discovery(
            "sensor",
            "forecast_accuracy_today",
            node_id=node,
            config={
                "name": "PV Forecast Accuracy Today",
                "device": device,
                "state_topic": "homelab/pv-forecast/accuracy",
                "value_template": "{{ value_json.accuracy_pct }}",
                "unit_of_measurement": "%",
                "icon": "mdi:crosshairs-gps",
                "entity_category": "diagnostic",
            },
        )

        logger.info("ha_discovery_registered", entity_count=24)

    def _heartbeat_thread_loop(self) -> None:
        """Publish heartbeat + touch healthcheck from a dedicated thread.

        Runs independently of the asyncio event loop so it can't be blocked
        by long-running scheduler jobs (ML training, InfluxDB queries).
        Uses NatsPublisher.publish_sync() which is thread-safe.
        """
        interval = self.settings.heartbeat_interval_seconds
        # Small initial delay so NATS has time to connect
        self._heartbeat_stop.wait(min(5, interval))

        while not self._heartbeat_stop.is_set():
            self._touch_healthcheck()
            try:
                if self.nats:
                    self.nats.publish_sync(
                        "heartbeat.pv-forecast",
                        {
                            "status": "online",
                            "service": "pv-forecast",
                            "uptime_seconds": round(
                                time.monotonic() - self._start_time, 1
                            ),
                        },
                    )
            except Exception:
                logger.debug("heartbeat_publish_failed")
            self._heartbeat_stop.wait(interval)

    def _touch_healthcheck(self) -> None:
        """Write timestamp to healthcheck file for Docker HEALTHCHECK."""
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(str(time.time()))
        except OSError:
            pass

    async def _shutdown(self) -> None:
        """Clean up resources."""
        logger.info("shutting_down")
        if hasattr(self, "_heartbeat_stop"):
            self._heartbeat_stop.set()
        self.scheduler.shutdown(wait=False)
        await self.ha.close()
        self.influx.close()
        if self.nats:
            await self.nats.close()
        if self.weather:
            await self.weather.close()
        logger.info("shutdown_complete")


async def main() -> None:
    service = PVForecastService()
    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
