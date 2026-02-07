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
import time
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.mqtt_client import MQTTClient

HEALTHCHECK_FILE = Path("/app/data/healthcheck")

from config import PVForecastSettings
from data import PVDataCollector
from forecast import ForecastEngine
from ha_sensors import HASensorPublisher
from weather import OpenMeteoClient

logger = get_logger("pv-forecast")


class PVForecastService:
    """Main service coordinating model training, forecasting, and publishing."""

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
        self.mqtt = MQTTClient(
            host=self.settings.mqtt_host,
            port=self.settings.mqtt_port,
            client_id="pv-forecast",
            username=self.settings.mqtt_username,
            password=self.settings.mqtt_password,
        )

        self._start_time = time.monotonic()

        # Location — will be resolved from HA if not configured
        self.latitude = self.settings.pv_latitude
        self.longitude = self.settings.pv_longitude

        # These are initialized in start() after resolving location
        self.weather: OpenMeteoClient | None = None
        self.data_collector: PVDataCollector | None = None
        self.engine: ForecastEngine | None = None
        self.publisher: HASensorPublisher | None = None

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

        # Resolve location
        await self._resolve_location()

        # Initialize components
        self.weather = OpenMeteoClient(self.latitude, self.longitude)
        self.data_collector = PVDataCollector(self.influx, self.weather, self.settings)
        self.engine = ForecastEngine(self.settings, self.data_collector, self.weather, self.ha)
        self.publisher = HASensorPublisher(self.ha, self.settings.ha_sensor_prefix)

        # Connect MQTT for broadcasting events
        self.mqtt.connect_background()

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
            self._heartbeat,
            "interval",
            seconds=self.settings.heartbeat_interval_seconds,
            id="heartbeat",
        )
        self.scheduler.start()

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

    async def _train(self) -> None:
        """Train or retrain the models."""
        try:
            results = await self.engine.train()
            logger.info("training_complete", results=results)
            self.mqtt.publish("homelab/pv-forecast/model-trained", results)
        except Exception:
            logger.exception("training_failed")

    async def _forecast(self) -> None:
        """Generate and publish forecast."""
        try:
            forecast = await self.engine.forecast()
            await self.publisher.publish(forecast)

            # Also publish to MQTT for other services
            summary = {
                "today_kwh": forecast.today_total_kwh,
                "today_remaining_kwh": forecast.today_remaining_kwh,
                "tomorrow_kwh": forecast.tomorrow_total_kwh,
                "day_after_kwh": forecast.day_after_total_kwh,
                "east_model": forecast.east.model_type if forecast.east else "none",
                "west_model": forecast.west.model_type if forecast.west else "none",
                "timestamp": forecast.timestamp.isoformat(),
            }
            self.mqtt.publish("homelab/pv-forecast/updated", summary)

            # Touch healthcheck file for Docker healthcheck
            self._touch_healthcheck()

        except Exception:
            logger.exception("forecast_failed")

    def _heartbeat(self) -> None:
        """Publish MQTT heartbeat so other services know we're alive."""
        self.mqtt.publish("homelab/pv-forecast/heartbeat", {
            "status": "online",
            "service": "pv-forecast",
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
        })
        self._touch_healthcheck()

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
        self.scheduler.shutdown(wait=False)
        await self.ha.close()
        self.influx.close()
        self.mqtt.disconnect()
        if self.weather:
            await self.weather.close()
        logger.info("shutdown_complete")


async def main() -> None:
    service = PVForecastService()
    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
