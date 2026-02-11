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

        # --- Tracking state for enhanced sensors ---
        self._last_training_results: dict[str, dict] = {}
        self._last_training_time: str = ""
        self._last_forecast_time: str = ""
        self._data_days: dict[str, int] = {"east": 0, "west": 0}
        self._forecast_solar_today: dict[str, float] = {}
        self._last_forecast_summary: str = ""

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
            self._last_training_results = results
            self._last_training_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Count data days per array for sensor exposure
            for array_name, entity_id in [
                ("east", self.settings.pv_east_energy_entity_id),
                ("west", self.settings.pv_west_energy_entity_id),
            ]:
                if entity_id and self.data_collector:
                    self._data_days[array_name] = self.data_collector.count_days_of_data(entity_id)

            # Publish training results with enhanced data
            enriched_results = {
                **results,
                "training_time": self._last_training_time,
                "data_days": self._data_days,
            }
            self.mqtt.publish("homelab/pv-forecast/model-trained", enriched_results)
        except Exception:
            logger.exception("training_failed")

    async def _forecast(self) -> None:
        """Generate and publish forecast."""
        try:
            forecast = await self.engine.forecast()
            await self.publisher.publish(forecast)

            self._last_forecast_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

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
                    if forecast.east and forecast.east.today else 0.0
                ),
                "west_today_kwh": (
                    forecast.west.today.total_kwh
                    if forecast.west and forecast.west.today else 0.0
                ),
                "east_tomorrow_kwh": (
                    forecast.east.tomorrow.total_kwh
                    if forecast.east and forecast.east.tomorrow else 0.0
                ),
                "west_tomorrow_kwh": (
                    forecast.west.tomorrow.total_kwh
                    if forecast.west and forecast.west.tomorrow else 0.0
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
                "forecast_solar_today_east": self._forecast_solar_today.get("east", 0.0),
                "forecast_solar_today_west": self._forecast_solar_today.get("west", 0.0),
                "forecast_solar_today_total": (
                    self._forecast_solar_today.get("east", 0.0)
                    + self._forecast_solar_today.get("west", 0.0)
                ),
                "reasoning": self._last_forecast_summary,
            }
            self.mqtt.publish("homelab/pv-forecast/updated", summary)

            # Touch healthcheck file for Docker healthcheck
            self._touch_healthcheck()

        except Exception:
            logger.exception("forecast_failed")

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

    def _compose_forecast_reasoning(self, forecast: 'FullForecast') -> str:
        """Compose a human-readable reasoning for the current forecast."""
        from forecast import FullForecast
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
                r2 = self._last_training_results.get(arr_name.lower(), {}).get("r2", 0.0)
                mae = self._last_training_results.get(arr_name.lower(), {}).get("mae", 0.0)
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
                    f"  vs Forecast.Solar: {fs_val:.1f} kWh "
                    f"(AI is {diff_pct:+.0f}%)"
                )

        lines.append(
            f"Total today: {forecast.today_total_kwh:.1f} kWh | "
            f"Remaining: {forecast.today_remaining_kwh:.1f} kWh | "
            f"Tomorrow: {forecast.tomorrow_total_kwh:.1f} kWh"
        )
        return "\n".join(lines)

    def _register_ha_discovery(self) -> None:
        """Register service entities in HA via MQTT auto-discovery."""
        device = {
            "identifiers": ["homelab_pv_forecast"],
            "name": "PV AI Forecast",
            "manufacturer": "Homelab",
            "model": "pv-forecast",
        }
        node = "pv_forecast"
        updated_topic = "homelab/pv-forecast/updated"
        heartbeat_topic = "homelab/pv-forecast/heartbeat"
        trained_topic = "homelab/pv-forecast/model-trained"

        # --- Connectivity & uptime ---
        self.mqtt.publish_ha_discovery("binary_sensor", "status", node_id=node, config={
            "name": "PV Forecast Service",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ 'ON' if value_json.status == 'online' else 'OFF' }}",
            "payload_on": "ON",
            "payload_off": "OFF",
            "device_class": "running",
            "expire_after": 180,
            "icon": "mdi:solar-power-variant",
        })

        self.mqtt.publish_ha_discovery("sensor", "uptime", node_id=node, config={
            "name": "PV Forecast Uptime",
            "device": device,
            "state_topic": heartbeat_topic,
            "value_template": "{{ value_json.uptime_seconds | round(0) }}",
            "unit_of_measurement": "s",
            "device_class": "duration",
            "entity_category": "diagnostic",
            "icon": "mdi:timer-outline",
        })

        # --- Core forecast sensors ---
        self.mqtt.publish_ha_discovery("sensor", "today_kwh", node_id=node, config={
            "name": "PV Forecast Today",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.today_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        self.mqtt.publish_ha_discovery("sensor", "today_remaining_kwh", node_id=node, config={
            "name": "PV Forecast Today Remaining",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.today_remaining_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        self.mqtt.publish_ha_discovery("sensor", "tomorrow_kwh", node_id=node, config={
            "name": "PV Forecast Tomorrow",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.tomorrow_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        self.mqtt.publish_ha_discovery("sensor", "day_after_kwh", node_id=node, config={
            "name": "PV Forecast Day After Tomorrow",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.day_after_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-power-variant",
        })

        # --- Per-array breakdown sensors ---
        self.mqtt.publish_ha_discovery("sensor", "east_today_kwh", node_id=node, config={
            "name": "PV Forecast East Today",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.east_today_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-panel",
        })

        self.mqtt.publish_ha_discovery("sensor", "west_today_kwh", node_id=node, config={
            "name": "PV Forecast West Today",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.west_today_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-panel",
        })

        self.mqtt.publish_ha_discovery("sensor", "east_tomorrow_kwh", node_id=node, config={
            "name": "PV Forecast East Tomorrow",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.east_tomorrow_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-panel",
        })

        self.mqtt.publish_ha_discovery("sensor", "west_tomorrow_kwh", node_id=node, config={
            "name": "PV Forecast West Tomorrow",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.west_tomorrow_kwh }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:solar-panel",
        })

        # --- Model quality & training sensors ---
        self.mqtt.publish_ha_discovery("sensor", "east_model_type", node_id=node, config={
            "name": "East Model Type",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.east_model }}",
            "icon": "mdi:brain",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "west_model_type", node_id=node, config={
            "name": "West Model Type",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.west_model }}",
            "icon": "mdi:brain",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "east_model_r2", node_id=node, config={
            "name": "East Model R²",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.east_r2 }}",
            "icon": "mdi:chart-line",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "west_model_r2", node_id=node, config={
            "name": "West Model R²",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.west_r2 }}",
            "icon": "mdi:chart-line",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "east_model_mae", node_id=node, config={
            "name": "East Model MAE",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.east_mae }}",
            "unit_of_measurement": "kWh",
            "icon": "mdi:chart-scatter-plot",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "west_model_mae", node_id=node, config={
            "name": "West Model MAE",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.west_mae }}",
            "unit_of_measurement": "kWh",
            "icon": "mdi:chart-scatter-plot",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "data_days_east", node_id=node, config={
            "name": "Training Data Days (East)",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.data_days_east }}",
            "unit_of_measurement": "days",
            "icon": "mdi:database-clock-outline",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "data_days_west", node_id=node, config={
            "name": "Training Data Days (West)",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.data_days_west }}",
            "unit_of_measurement": "days",
            "icon": "mdi:database-clock-outline",
            "entity_category": "diagnostic",
        })

        self.mqtt.publish_ha_discovery("sensor", "last_training", node_id=node, config={
            "name": "Last Model Training",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.last_training_time }}",
            "device_class": "timestamp",
            "icon": "mdi:school-outline",
            "entity_category": "diagnostic",
        })

        # --- Forecast.Solar comparison ---
        self.mqtt.publish_ha_discovery("sensor", "forecast_solar_today", node_id=node, config={
            "name": "Forecast.Solar Today (comparison)",
            "device": device,
            "state_topic": updated_topic,
            "value_template": "{{ value_json.forecast_solar_today_total }}",
            "unit_of_measurement": "kWh",
            "device_class": "energy",
            "icon": "mdi:weather-sunny-alert",
        })

        # --- Decision reasoning (the key sensor) ---
        self.mqtt.publish_ha_discovery("sensor", "forecast_reasoning", node_id=node, config={
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
        })

        logger.info("ha_discovery_registered", entity_count=23)

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
