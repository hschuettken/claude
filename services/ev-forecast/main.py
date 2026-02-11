"""EV Forecast Service — entry point and main loop.

Monitors the Audi A6 e-tron via dual Audi Connect accounts, predicts
upcoming driving needs from the family calendar, and generates demand-
focused charging plans. The planner expresses what energy is needed
and by when — the smart-ev-charging service handles PV optimization.

Schedule:
  - Every 15 min: refresh vehicle state from Audi Connect
  - Every 30 min: re-evaluate charging plan (calendar + demand)
  - On startup: initial state read + plan generation

Output:
  - MQTT: homelab/ev-forecast/plan, homelab/ev-forecast/vehicle, homelab/ev-forecast/heartbeat
  - HA helpers: sets charge mode, target energy, departure time, full-by-morning
  - MQTT HA discovery: registers sensors under "EV Forecast" device
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.ha_client import HomeAssistantClient
from shared.log import get_logger
from shared.mqtt_client import MQTTClient

from config import EVForecastSettings
from planner import ChargingPlan, ChargingPlanner
from trips import GeoDistance, TripPredictor
from vehicle import AccountConfig, VehicleMonitor, VehicleState

HEALTHCHECK_FILE = Path("/app/data/healthcheck")

logger = get_logger("ev-forecast")

# Google Calendar client (same pattern as orchestrator)
try:
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False


class EVForecastService:
    """Main service: vehicle monitoring + trip prediction + charging planner."""

    def __init__(self) -> None:
        self.settings = EVForecastSettings()
        self.scheduler = AsyncIOScheduler()
        self._tz = ZoneInfo(self.settings.timezone)
        self._start_time = time.monotonic()

        # Clients
        self.ha = HomeAssistantClient(self.settings.ha_url, self.settings.ha_token)
        self.mqtt = MQTTClient(
            host=self.settings.mqtt_host,
            port=self.settings.mqtt_port,
            client_id="ev-forecast",
            username=self.settings.mqtt_username,
            password=self.settings.mqtt_password,
        )

        # Vehicle monitor
        account1 = AccountConfig(
            name=self.settings.audi_account1_name,
            soc_entity=self.settings.audi_account1_soc_entity,
            range_entity=self.settings.audi_account1_range_entity,
            charging_entity=self.settings.audi_account1_charging_entity,
            plug_entity=self.settings.audi_account1_plug_entity,
            mileage_entity=self.settings.audi_account1_mileage_entity,
            remaining_charge_entity=self.settings.audi_account1_remaining_charge_entity,
            vin=self.settings.audi_account1_vin,
        )
        account2 = AccountConfig(
            name=self.settings.audi_account2_name,
            soc_entity=self.settings.audi_account2_soc_entity,
            range_entity=self.settings.audi_account2_range_entity,
            charging_entity=self.settings.audi_account2_charging_entity,
            plug_entity=self.settings.audi_account2_plug_entity,
            mileage_entity=self.settings.audi_account2_mileage_entity,
            remaining_charge_entity=self.settings.audi_account2_remaining_charge_entity,
            vin=self.settings.audi_account2_vin,
        )
        self.vehicle = VehicleMonitor(
            ha=self.ha,
            account1=account1,
            account2=account2,
            net_capacity_kwh=self.settings.ev_battery_capacity_net_kwh,
            stale_threshold_minutes=self.settings.audi_stale_threshold_minutes,
        )

        # Home location (resolved in start())
        self._home_lat = self.settings.home_latitude
        self._home_lon = self.settings.home_longitude

        # Trip predictor (initialized in start() after resolving home location)
        self.trips: TripPredictor | None = None

        # Charging planner
        self.planner = ChargingPlanner(
            ha=self.ha,
            net_capacity_kwh=self.settings.ev_battery_capacity_net_kwh,
            min_soc_pct=self.settings.min_soc_pct,
            buffer_soc_pct=self.settings.buffer_soc_pct,
            min_arrival_soc_pct=self.settings.min_arrival_soc_pct,
            timezone=self.settings.timezone,
        )

        # Google Calendar
        self._gcal_service: Any = None

        # Last plan for publishing
        self._last_plan: ChargingPlan | None = None

    async def start(self) -> None:
        """Initialize and start the service."""
        logger.info("service_starting")

        # Resolve home location (for geocoding)
        await self._resolve_home_location()

        # Initialize trip predictor (needs home location for geocoding)
        geo = GeoDistance(
            home_lat=self._home_lat,
            home_lon=self._home_lon,
            road_factor=self.settings.geocoding_road_factor,
        ) if self._home_lat and self._home_lon else None

        known_destinations = json.loads(self.settings.known_destinations)
        commute_days = [d.strip() for d in self.settings.nicole_commute_days.split(",")]
        self.trips = TripPredictor(
            known_destinations=known_destinations,
            consumption_kwh_per_100km=self.settings.ev_consumption_kwh_per_100km,
            nicole_commute_km=self.settings.nicole_commute_km,
            nicole_commute_days=commute_days,
            nicole_departure_time=self.settings.nicole_departure_time,
            nicole_arrival_time=self.settings.nicole_arrival_time,
            hans_train_threshold_km=self.settings.hans_train_threshold_km,
            calendar_prefix_hans=self.settings.calendar_prefix_hans,
            calendar_prefix_nicole=self.settings.calendar_prefix_nicole,
            timezone=self.settings.timezone,
            geo_distance=geo,
        )

        # Connect MQTT
        self.mqtt.connect_background()

        # Register HA auto-discovery entities
        self._register_ha_discovery()

        # Subscribe to orchestrator trip clarification responses
        self.mqtt.subscribe(
            self.settings.orchestrator_response_topic,
            self._on_trip_response,
        )

        # Initialize Google Calendar
        self._init_google_calendar()

        # Initial vehicle state + plan
        await self._update_vehicle()
        await self._update_plan()

        # Schedule recurring tasks
        self.scheduler.add_job(
            self._update_vehicle,
            "interval",
            minutes=self.settings.vehicle_check_minutes,
            id="vehicle_check",
        )
        self.scheduler.add_job(
            self._update_plan,
            "interval",
            minutes=self.settings.plan_update_minutes,
            id="plan_update",
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
            vehicle_interval_min=self.settings.vehicle_check_minutes,
            plan_interval_min=self.settings.plan_update_minutes,
        )

        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown()

    # ------------------------------------------------------------------
    # Vehicle monitoring
    # ------------------------------------------------------------------

    async def _update_vehicle(self) -> None:
        """Read vehicle state and publish to MQTT."""
        try:
            state = await self.vehicle.ensure_fresh_data()
            payload = {
                "soc_pct": state.soc_pct,
                "range_km": state.range_km,
                "charging_state": state.charging_state,
                "plug_state": state.plug_state,
                "mileage_km": state.mileage_km,
                "remaining_charge_min": state.remaining_charge_min,
                "active_account": state.active_account,
                "is_valid": state.is_valid,
                "timestamp": datetime.now(self._tz).isoformat(),
            }
            self.mqtt.publish("homelab/ev-forecast/vehicle", payload)
            self._touch_healthcheck()
        except Exception:
            logger.exception("vehicle_update_failed")

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    async def _update_plan(self) -> None:
        """Generate charging plan and apply to HA helpers."""
        try:
            vehicle = self.vehicle.last_state

            # Get calendar events
            events = await self._get_calendar_events()

            # Predict trips (async for geocoding of unknown destinations)
            day_plans = await self.trips.predict_trips(
                events,
                days=self.settings.planning_horizon_days,
            )

            # Generate demand-focused plan (no PV forecast — smart-ev-charging handles supply)
            plan = await self.planner.generate_plan(vehicle, day_plans)
            self._last_plan = plan

            # Publish plan to MQTT
            self.mqtt.publish("homelab/ev-forecast/plan", plan.to_dict())

            # Apply immediate action to HA helpers
            await self.planner.apply_plan(
                plan,
                charge_mode_entity=self.settings.charge_mode_entity,
                full_by_morning_entity=self.settings.full_by_morning_entity,
                departure_time_entity=self.settings.departure_time_entity,
                target_energy_entity=self.settings.target_energy_entity,
            )

            # Publish any pending clarifications to orchestrator
            clarifications = self.trips.get_pending_clarifications()
            if clarifications:
                self.mqtt.publish(
                    "homelab/ev-forecast/clarification-needed",
                    {"clarifications": clarifications},
                )

            # Log summary
            for day in plan.days:
                logger.info(
                    "plan_day",
                    date=day.date.isoformat(),
                    trips=len(day.trips),
                    energy_needed=round(day.energy_needed_kwh, 1),
                    charge_kwh=round(day.energy_to_charge_kwh, 1),
                    mode=day.charge_mode,
                    reason=day.reason,
                )

            self._touch_healthcheck()

        except Exception:
            logger.exception("plan_update_failed")

    async def _get_calendar_events(self) -> list[dict[str, Any]]:
        """Fetch calendar events for the planning horizon."""
        if not self._gcal_service:
            return []

        try:
            now = datetime.now(self._tz)
            time_min = now.isoformat()
            time_max = (now + timedelta(
                days=self.settings.planning_horizon_days,
            )).isoformat()

            result = (
                self._gcal_service.events()
                .list(
                    calendarId=self.settings.google_calendar_family_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=50,
                )
                .execute()
            )

            events: list[dict[str, Any]] = []
            for item in result.get("items", []):
                start = item.get("start", {})
                end = item.get("end", {})
                events.append({
                    "id": item.get("id", ""),
                    "summary": item.get("summary", ""),
                    "start": start.get("dateTime") or start.get("date", ""),
                    "end": end.get("dateTime") or end.get("date", ""),
                    "all_day": "date" in start,
                    "location": item.get("location", ""),
                })

            logger.info("calendar_events_fetched", count=len(events))
            return events

        except Exception:
            logger.exception("calendar_fetch_failed")
            return []

    # ------------------------------------------------------------------
    # Home location resolution
    # ------------------------------------------------------------------

    async def _resolve_home_location(self) -> None:
        """Get home lat/lon from HA config if not explicitly set."""
        if self._home_lat and self._home_lon:
            logger.info("home_location_from_config", lat=self._home_lat, lon=self._home_lon)
            return

        try:
            client = await self.ha._get_client()
            resp = await client.get("/config")
            resp.raise_for_status()
            config = resp.json()
            self._home_lat = config.get("latitude", 0.0)
            self._home_lon = config.get("longitude", 0.0)
            logger.info("home_location_from_ha", lat=self._home_lat, lon=self._home_lon)
        except Exception:
            logger.warning("home_location_unavailable", detail="Geocoding for unknown destinations will be disabled")

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_trip_response(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle trip clarification response from orchestrator."""
        event_id = payload.get("event_id", "")
        use_ev = payload.get("use_ev", False)
        distance_km = payload.get("distance_km", 0)

        if event_id:
            self.trips.resolve_clarification(event_id, use_ev, distance_km)
            logger.info(
                "trip_clarification_resolved",
                event_id=event_id,
                use_ev=use_ev,
                distance_km=distance_km,
            )

    # ------------------------------------------------------------------
    # Google Calendar initialization
    # ------------------------------------------------------------------

    def _init_google_calendar(self) -> None:
        """Initialize Google Calendar API client."""
        if not HAS_GOOGLE:
            logger.info("google_calendar_not_available", reason="library not installed")
            return

        if not self.settings.google_calendar_family_id:
            logger.info("google_calendar_not_configured", reason="no family calendar ID")
            return

        try:
            import base64
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            scopes = [
                "https://www.googleapis.com/auth/calendar.readonly",
            ]

            creds_file = self.settings.google_calendar_credentials_file
            creds_json = self.settings.google_calendar_credentials_json

            if creds_file and Path(creds_file).exists():
                creds = Credentials.from_service_account_file(creds_file, scopes=scopes)
            elif creds_json:
                try:
                    raw = base64.b64decode(creds_json)
                    info = json.loads(raw)
                except Exception:
                    info = json.loads(creds_json)
                creds = Credentials.from_service_account_info(info, scopes=scopes)
            else:
                logger.info("google_calendar_no_credentials")
                return

            self._gcal_service = build("calendar", "v3", credentials=creds)
            logger.info("google_calendar_initialized")

        except Exception:
            logger.exception("google_calendar_init_failed")

    # ------------------------------------------------------------------
    # MQTT HA auto-discovery
    # ------------------------------------------------------------------

    def _register_ha_discovery(self) -> None:
        """Register entities in HA under the 'EV Forecast' device."""
        device = {
            "identifiers": ["homelab_ev_forecast"],
            "name": "EV Forecast",
            "manufacturer": "Homelab",
            "model": "ev-forecast",
        }
        node = "ev_forecast"

        # Service status
        self.mqtt.publish_ha_discovery(
            "binary_sensor", "service_status", node_id=node, config={
                "name": "Service Status",
                "device": device,
                "state_topic": "homelab/ev-forecast/heartbeat",
                "value_template": (
                    "{{ 'ON' if value_json.status == 'online' else 'OFF' }}"
                ),
                "device_class": "connectivity",
                "expire_after": 180,
            },
        )

        vehicle_topic = "homelab/ev-forecast/vehicle"
        plan_topic = "homelab/ev-forecast/plan"

        # EV SoC
        self.mqtt.publish_ha_discovery(
            "sensor", "ev_soc", node_id=node, config={
                "name": "EV Battery SoC",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.soc_pct | default('unknown') }}",
                "unit_of_measurement": "%",
                "device_class": "battery",
                "state_class": "measurement",
                "icon": "mdi:car-battery",
            },
        )

        # EV Range
        self.mqtt.publish_ha_discovery(
            "sensor", "ev_range", node_id=node, config={
                "name": "EV Range",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.range_km | default('unknown') }}",
                "unit_of_measurement": "km",
                "icon": "mdi:map-marker-distance",
            },
        )

        # Active Account
        self.mqtt.publish_ha_discovery(
            "sensor", "active_account", node_id=node, config={
                "name": "Active Audi Account",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.active_account | default('unknown') }}",
                "icon": "mdi:account-check",
            },
        )

        # Charging State
        self.mqtt.publish_ha_discovery(
            "sensor", "charging_state", node_id=node, config={
                "name": "EV Charging State",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.charging_state | default('unknown') }}",
                "icon": "mdi:ev-plug-type2",
            },
        )

        # Plug State
        self.mqtt.publish_ha_discovery(
            "sensor", "plug_state", node_id=node, config={
                "name": "EV Plug State",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.plug_state | default('unknown') }}",
                "icon": "mdi:power-plug",
            },
        )

        # Plan: Energy Needed Today
        self.mqtt.publish_ha_discovery(
            "sensor", "energy_needed_today", node_id=node, config={
                "name": "Energy Needed Today",
                "device": device,
                "state_topic": plan_topic,
                "value_template": (
                    "{% if value_json.days and value_json.days | length > 0 %}"
                    "{{ value_json.days[0].energy_needed_kwh }}"
                    "{% else %}0{% endif %}"
                ),
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-charging-outline",
            },
        )

        # Plan: Charge Mode
        self.mqtt.publish_ha_discovery(
            "sensor", "recommended_mode", node_id=node, config={
                "name": "Recommended Charge Mode",
                "device": device,
                "state_topic": plan_topic,
                "value_template": (
                    "{% if value_json.days and value_json.days | length > 0 %}"
                    "{{ value_json.days[0].charge_mode }}"
                    "{% else %}PV Surplus{% endif %}"
                ),
                "icon": "mdi:ev-station",
            },
        )

        # Plan: Next Trip
        self.mqtt.publish_ha_discovery(
            "sensor", "next_trip", node_id=node, config={
                "name": "Next Trip",
                "device": device,
                "state_topic": plan_topic,
                "value_template": (
                    "{% set ns = namespace(found=false) %}"
                    "{% for day in value_json.days | default([]) %}"
                    "{% for trip in day.trips | default([]) %}"
                    "{% if not ns.found %}"
                    "{{ trip.person }}: {{ trip.destination }} ({{ trip.distance_km }}km)"
                    "{% set ns.found = true %}"
                    "{% endif %}"
                    "{% endfor %}"
                    "{% endfor %}"
                    "{% if not ns.found %}None{% endif %}"
                ),
                "icon": "mdi:car-arrow-right",
            },
        )

        # Plan: Departure Time
        self.mqtt.publish_ha_discovery(
            "sensor", "next_departure", node_id=node, config={
                "name": "Next Departure",
                "device": device,
                "state_topic": plan_topic,
                "value_template": (
                    "{% if value_json.days and value_json.days | length > 0 "
                    "and value_json.days[0].departure_time %}"
                    "{{ value_json.days[0].departure_time }}"
                    "{% else %}None{% endif %}"
                ),
                "icon": "mdi:clock-outline",
            },
        )

        # Plan: Status/Reason
        self.mqtt.publish_ha_discovery(
            "sensor", "plan_status", node_id=node, config={
                "name": "Plan Status",
                "device": device,
                "state_topic": plan_topic,
                "value_template": (
                    "{% if value_json.days and value_json.days | length > 0 %}"
                    "{{ value_json.days[0].reason[:250] }}"
                    "{% else %}No plan{% endif %}"
                ),
                "icon": "mdi:information-outline",
            },
        )

        logger.info("ha_discovery_registered", entity_count=11)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _heartbeat(self) -> None:
        """Publish MQTT heartbeat."""
        vehicle = self.vehicle.last_state
        self.mqtt.publish("homelab/ev-forecast/heartbeat", {
            "status": "online",
            "service": "ev-forecast",
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "ev_soc_pct": vehicle.soc_pct,
            "active_account": vehicle.active_account,
            "has_plan": self._last_plan is not None,
        })
        self._touch_healthcheck()

    # ------------------------------------------------------------------
    # Healthcheck / Shutdown
    # ------------------------------------------------------------------

    def _touch_healthcheck(self) -> None:
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(str(time.time()))
        except OSError:
            pass

    async def _shutdown(self) -> None:
        logger.info("shutting_down")
        self.scheduler.shutdown(wait=False)
        self.mqtt.publish("homelab/ev-forecast/heartbeat", {
            "status": "offline",
            "service": "ev-forecast",
        })
        await self.ha.close()
        self.mqtt.disconnect()
        logger.info("shutdown_complete")


async def main() -> None:
    service = EVForecastService()
    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
