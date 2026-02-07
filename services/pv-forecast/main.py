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

        # Register entities in HA via MQTT auto-discovery
        self._register_ha_discovery()

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

    def _register_ha_discovery(self) -> None:
        """Register service entities in HA via MQTT auto-discovery."""
        device = {
            "identifiers": ["homelab_pv_forecast"],
            "name": "PV AI Forecast",
            "manufacturer": "Homelab",
            "model": "pv-forecast",
        }
        node = "pv_forecast"

        # Service status (online/offline)
        self.mqtt.publish_ha_discovery("binary_sensor", "status", node_id=node, config={
            "name": "PV Forecast Service",
            "device": device,
            "state_topic": "homelab/pv-forecast/heartbeat",
            "value_template": "{{ 'ON' if value_json.status == 'online' else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "running",
            "expire_after": 180,  # Mark offline if no heartbeat for 3 minutes
            "icon": "mdi:solar-power-variant",
        })

        # Uptime sensor
        self.mqtt.publish_ha_discovery("sensor", "uptime", node_id=node, config={
            "name": "PV Forecast Uptime",
            "device": device,
            "state_topic": "homelab/pv-forecast/heartbeat",
            "value_template": "{{ value_json.uptime_seconds | round(0) }}",
            "unit_of_measurement": "s",
            "device_class": "duration",
            "entity_category": "diagnostic",
            "icon": "mdi:timer-outline",
        })

        # Today forecast
        self.mqtt.publish_ha_discovery("sensor", "today_kwh", node_id=node, config={
            "name": "PV Forecast Today",
            "device": device,
            "state_topic": "homelab/pv-forecast/updated",
            "value_template": "{{ value_json.today_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        # Today remaining
        self.mqtt.publish_ha_discovery("sensor", "today_remaining_kwh", node_id=node, config={
            "name": "PV Forecast Today Remaining",
            "device": device,
            "state_topic": "homelab/pv-forecast/updated",
            "value_template": "{{ value_json.today_remaining_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        # Tomorrow forecast
        self.mqtt.publish_ha_discovery("sensor", "tomorrow_kwh", node_id=node, config={
            "name": "PV Forecast Tomorrow",
            "device": device,
            "state_topic": "homelab/pv-forecast/updated",
            "value_template": "{{ value_json.tomorrow_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        # Day after tomorrow forecast
        self.mqtt.publish_ha_discovery("sensor", "day_after_kwh", node_id=node, config={
            "name": "PV Forecast Day After Tomorrow",
            "device": device,
            "state_topic": "homelab/pv-forecast/updated",
            "value_template": "{{ value_json.day_after_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        logger.info("ha_discovery_registered", entity_count=6)

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
