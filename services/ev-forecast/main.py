"""EV Forecast Service — entry point and main loop.

Monitors the Audi A6 e-tron via Audi Connect (single or dual account mode),
predicts upcoming driving needs from the family calendar, and generates
demand-focused charging plans. The planner expresses what energy is needed
and by when — the smart-ev-charging service handles PV optimization.

Features:
  - Dynamic consumption calculation: tracks actual kWh/100km from mileage
    and SoC changes, adapting to driving style, temperature, and route type.
  - Single account mode (default): uses Henning's Audi Connect directly.
  - Dual account mode (optional): uses combined HA template sensors merging
    two accounts with automatic active-account detection.

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
import threading
import time
from datetime import datetime, timedelta, timezone  # noqa: F401  (timezone used in _update_plan for scheduler deadline)
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from shared.decision_journal import DecisionJournal  # noqa: F401  (used at runtime in start())
from shared.ha_client import HomeAssistantClient
from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.nats_client import NatsPublisher

from config import EVForecastSettings
from learned_destinations import LearnedDestinations
from planner import ChargingPlan, ChargingPlanner, WeeklyPlanBuilder
from scheduler import HourlyPV, schedule_charge_windows  # noqa: F401  (used at runtime in _build_hourly_pv + _update_plan)
from trips import GeoDistance, TripPredictor
from vehicle import (
    ConsumptionTracker,
    RefreshConfig,
    VehicleConfig,
    VehicleMonitor,
    VehicleState,
)

HEALTHCHECK_FILE = Path("/app/data/healthcheck")
STATE_FILE = Path("/app/data/state.json")

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

    async def _register_with_oracle(self) -> None:
        """Best-effort Oracle registration. Non-critical — service must start even if Oracle is down."""
        try:
            manifest = {
                "service_name": "ev-forecast",
                "port": None,
                "description": "EV charging demand forecast",
                "endpoints": [],
                "nats_subjects": [
                    "energy.ev.forecast.vehicle",
                    "energy.ev.forecast.plan",
                    "energy.ev.forecast.clarification_needed",
                    "energy.ev.decision.plan",  # S1: Decision Journal
                    "energy.pv.forecast.hourly",  # S2: subscribed for greedy scheduler
                    "heartbeat.ev-forecast",
                    "orchestrator.command.ev-forecast",
                    "orchestrator.knowledge-update",
                ],
                "source_paths": [
                    {"repo": "claude", "paths": ["services/ev-forecast/"]},
                ],
            }
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post("http://192.168.0.50:8225/oracle/register", json=manifest)
        except Exception:
            pass

    def __init__(self) -> None:
        self.settings = EVForecastSettings()
        self.scheduler = AsyncIOScheduler()
        self._tz = ZoneInfo(self.settings.timezone)
        self._start_time = time.monotonic()

        # Clients
        self.ha = HomeAssistantClient(self.settings.ha_url, self.settings.ha_token)

        # Vehicle monitor — reads HA sensors (single or dual account mode)
        vehicle_config = VehicleConfig(
            soc_entity=self.settings.ev_soc_entity,
            range_entity=self.settings.ev_range_entity,
            charging_entity=self.settings.ev_charging_entity,
            plug_entity=self.settings.ev_plug_entity,
            mileage_entity=self.settings.ev_mileage_entity,
            remaining_charge_entity=self.settings.ev_remaining_charge_entity,
            active_account_entity=self.settings.ev_active_account_entity,
        )

        # Build refresh configs based on account mode
        refresh_configs = [
            RefreshConfig(
                name=self.settings.audi_account1_name,
                vin=self.settings.audi_account1_vin,
            ),
        ]
        if not self.settings.audi_single_account and self.settings.audi_account2_vin:
            refresh_configs.append(
                RefreshConfig(
                    name=self.settings.audi_account2_name,
                    vin=self.settings.audi_account2_vin,
                ),
            )
        self.vehicle = VehicleMonitor(
            ha=self.ha,
            vehicle_config=vehicle_config,
            refresh_configs=refresh_configs,
            net_capacity_kwh=self.settings.ev_battery_capacity_net_kwh,
            stale_threshold_minutes=self.settings.audi_stale_threshold_minutes,
        )

        # Consumption tracker — calculates real kWh/100km from mileage + SoC
        self.consumption_tracker = ConsumptionTracker(
            battery_capacity_kwh=self.settings.ev_battery_capacity_gross_kwh,
            default_consumption=self.settings.ev_consumption_kwh_per_100km,
            min_plausible_consumption=self.settings.ev_consumption_min_kwh_per_100km,
            max_plausible_consumption=self.settings.ev_consumption_max_kwh_per_100km,
        )

        # Home location (resolved in start())
        self._home_lat = self.settings.home_latitude
        self._home_lon = self.settings.home_longitude

        # Learned destinations from orchestrator (persistent)
        self.learned_destinations = LearnedDestinations()

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
            default_assumed_soc_pct=self.settings.default_assumed_soc_pct,
            critical_urgency_hours=self.settings.critical_urgency_hours,
            high_urgency_hours=self.settings.high_urgency_hours,
            fast_mode_threshold_kwh=self.settings.fast_mode_threshold_kwh,
            early_departure_hour=self.settings.early_departure_hour,
        )

        # NATS publisher (initialized in start() if nats_enabled)
        self.nats: NatsPublisher | None = None

        # InfluxDB client for writing consumption samples
        self.influx = InfluxClient(
            url=self.settings.influxdb_url,
            token=self.settings.influxdb_token,
            org=self.settings.influxdb_org,
        )

        # Admin Influx client for writing the analytics bucket (Decision Journal).
        # Falls back to the hass-scoped client if no admin token is configured.
        if self.settings.influxdb_all_access_token:
            self.influx_admin = InfluxClient(
                url=self.settings.influxdb_url,
                token=self.settings.influxdb_all_access_token,
                org=self.settings.influxdb_org,
            )
        else:
            self.influx_admin = self.influx

        # Decision Journal — wired in start() once NATS is connected.
        self.journal: DecisionJournal | None = None

        # Track previous mileage to compute km_delta for InfluxDB writes
        self._prev_mileage_km: float | None = None

        # Google Calendar
        self._gcal_service: Any = None

        # Last plan for publishing
        self._last_plan: ChargingPlan | None = None

        # 7-day weekly plan builder
        self._weekly_builder = WeeklyPlanBuilder()

        # Cached PV forecast values (updated via NATS subscription)
        # Keys: YYYY-MM-DD strings for today and tomorrow
        self._pv_forecast_cache: dict[str, float] = {}

        # Hour-by-hour PV forecast cache (S2 — fed by energy.pv.forecast.hourly)
        # Keys: ISO hour timestamps; values: {"kwh", "conf_low", "conf_high"}
        self._pv_hourly_cache: dict[str, dict[str, float]] = {}
        self._pv_hourly_run_iso: str | None = None

    async def start(self) -> None:
        """Initialize and start the service."""
        logger.info(
            "service_starting",
            audi_single_account=self.settings.audi_single_account,
            default_consumption=self.settings.ev_consumption_kwh_per_100km,
        )

        # Register with Oracle (non-blocking)
        asyncio.create_task(self._register_with_oracle())

        # Resolve home location (for geocoding)
        await self._resolve_home_location()

        # Initialize trip predictor (needs home location for geocoding)
        geo = (
            GeoDistance(
                home_lat=self._home_lat,
                home_lon=self._home_lon,
                road_factor=self.settings.geocoding_road_factor,
            )
            if self._home_lat and self._home_lon
            else None
        )

        known_destinations = json.loads(self.settings.known_destinations)
        commute_days = [d.strip() for d in self.settings.nicole_commute_days.split(",")]
        self.trips = TripPredictor(
            known_destinations=known_destinations,
            consumption_kwh_per_100km=self.settings.ev_consumption_kwh_per_100km,
            nicole_commute_km=self.settings.nicole_commute_km,
            nicole_commute_days=commute_days,
            nicole_departure_time=self.settings.nicole_departure_time,
            nicole_arrival_time=self.settings.nicole_arrival_time,
            henning_train_threshold_km=self.settings.henning_train_threshold_km,
            calendar_prefix_henning=self.settings.calendar_prefix_henning,
            calendar_prefix_nicole=self.settings.calendar_prefix_nicole,
            timezone=self.settings.timezone,
            geo_distance=geo,
            learned_destinations=self.learned_destinations,
            no_ev_activities=json.loads(self.settings.no_ev_activities),
        )

        # Load persisted state (before first vehicle read)
        self._load_state()

        # Connect NATS
        if self.settings.nats_enabled:
            self.nats = NatsPublisher(url=self.settings.nats_url)
            await self.nats.connect()

        # Decision Journal — best-effort writer to analytics bucket + NATS.
        self.journal = DecisionJournal(
            influx_admin=self.influx_admin,
            nats=self.nats,
            service="ev-forecast",
            bucket=self.settings.influxdb_analytics_bucket,
        )

        # Register HA auto-discovery entities
        await self._register_ha_discovery()

        # Subscribe to NATS subjects for orchestrator integration
        if self.nats and self.nats.connected:
            # Orchestrator trip clarification responses
            await self.nats.subscribe_json(
                "orchestrator.ev_forecast.trip_response",
                self._on_trip_response,
            )
            # Orchestrator commands
            await self.nats.subscribe_json(
                "orchestrator.command.ev-forecast",
                self._on_orchestrator_command,
            )

            # Learned knowledge updates from orchestrator (wrap sync handler)
            async def _on_knowledge_update(subject: str, payload: dict) -> None:
                self.learned_destinations.on_knowledge_update(subject, payload)

            await self.nats.subscribe_json(
                "orchestrator.knowledge.update",
                _on_knowledge_update,
            )

            # PV forecast updates — cache today/tomorrow values for weekly plan
            await self.nats.subscribe_json(
                "energy.pv.forecast_updated",
                self._on_pv_forecast_updated,
            )

            # Hourly 72h PV forecast — feeds the greedy charge scheduler (S2)
            await self.nats.subscribe_json(
                "energy.pv.forecast.hourly",
                self._on_pv_forecast_hourly,
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
        self.scheduler.start()

        # Start heartbeat in a dedicated daemon thread so it can't be
        # blocked by long-running scheduler jobs (HA API, Google Calendar).
        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_thread_loop,
            daemon=True,
        )
        self._heartbeat_thread.start()

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
        """Read vehicle state, update consumption tracker, and publish to MQTT."""
        try:
            state = await self.vehicle.ensure_fresh_data()

            # Feed consumption tracker with new mileage + SoC reading
            prev_mileage = self._prev_mileage_km
            consumption_sample = self.consumption_tracker.update(
                state.mileage_km, state.soc_pct
            )
            self._prev_mileage_km = state.mileage_km

            # Write driving segment to InfluxDB when a valid sample is detected
            if (
                consumption_sample is not None
                and prev_mileage is not None
                and state.mileage_km is not None
            ):
                km_delta = state.mileage_km - prev_mileage
                kwh_used = (consumption_sample / 100.0) * km_delta
                self._write_consumption_influx(km_delta, kwh_used, consumption_sample)

            # Update trip predictor with latest consumption estimate
            if self.trips is not None:
                self.trips.consumption_kwh_per_100km = (
                    self.consumption_tracker.consumption_kwh_per_100km
                )

            payload = {
                "soc_pct": state.soc_pct,
                "range_km": state.range_km,
                "charging_state": state.charging_state,
                "plug_state": state.plug_state,
                "mileage_km": state.mileage_km,
                "remaining_charge_min": state.remaining_charge_min,
                "active_account": state.active_account,
                "is_valid": state.is_valid,
                "consumption_kwh_100km": self.consumption_tracker.consumption_kwh_per_100km,
                "consumption_source": "measured"
                if self.consumption_tracker.has_data
                else "default",
                "consumption_measurements": self.consumption_tracker.measurement_count,
                "timestamp": datetime.now(self._tz).isoformat(),
            }
            if self.nats and self.nats.connected:
                await self.nats.publish("energy.ev.forecast.vehicle", payload)
            self._save_state()
        except Exception:
            logger.exception("vehicle_update_failed")
        finally:
            self._touch_healthcheck()

    def _write_consumption_influx(
        self,
        distance_km: float,
        kwh_used: float,
        kwh_per_100km: float,
    ) -> None:
        """Write a driving segment measurement to InfluxDB."""
        self.influx.write_point(
            bucket=self.settings.influxdb_bucket,
            measurement="ev_consumption_sample",
            fields={
                "distance_km": round(distance_km, 2),
                "kwh_used": round(kwh_used, 3),
                "kwh_per_100km": round(kwh_per_100km, 2),
            },
            tags={"vehicle": "audi_a6_etron"},
        )

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

            # Get PV forecast (today's remaining kWh)
            pv_forecast_kwh = []
            try:
                pv_state = await self.ha.get_state(
                    "sensor.pv_ai_forecast_today_remaining_kwh"
                )
                pv_today_kwh = float(pv_state.get("state", 0))
                if pv_today_kwh > 0:
                    pv_forecast_kwh.append(pv_today_kwh)
                    logger.info("pv_forecast_read", today_remaining_kwh=pv_today_kwh)
            except Exception:
                logger.debug("pv_forecast_unavailable")

            # Generate demand-focused plan with PV forecast awareness
            plan = await self.planner.generate_plan(
                vehicle,
                day_plans,
                pv_forecast_kwh=pv_forecast_kwh if pv_forecast_kwh else None,
            )
            self._last_plan = plan

            # Compute hour-by-hour charge schedule (S2). Best-effort: the
            # scheduler runs only if we have hourly PV forecast data and a
            # day with a deadline (departure_time). Failures are logged and
            # never block the plan publish.
            schedule_windows: list[dict] = []
            schedule_pv_kwh: float = 0.0
            schedule_grid_kwh: float = 0.0
            schedule_reason: str = ""
            try:
                if self._pv_hourly_cache:
                    today = plan.days[0] if plan.days else None
                    tomorrow = plan.days[1] if len(plan.days) > 1 else None
                    schedule_target = (
                        tomorrow
                        if tomorrow is not None and tomorrow.energy_to_charge_kwh > 0
                        else today
                    )
                    if (
                        schedule_target is not None
                        and schedule_target.energy_to_charge_kwh > 0
                    ):
                        deadline_dt = None
                        if schedule_target.departure_time is not None:
                            deadline_local = datetime.combine(
                                schedule_target.date,
                                schedule_target.departure_time,
                                tzinfo=self._tz,
                            )
                            deadline_dt = deadline_local.astimezone(timezone.utc)
                        sched = schedule_charge_windows(
                            self._build_hourly_pv(),
                            demand_kwh=schedule_target.energy_to_charge_kwh,
                            deadline=deadline_dt,
                        )
                        schedule_windows = [
                            {
                                "start_iso": w.start.isoformat(),
                                "end_iso": w.end.isoformat(),
                                "kwh": w.kwh,
                                "source": w.source,
                            }
                            for w in sched.windows
                        ]
                        schedule_pv_kwh = sched.pv_kwh
                        schedule_grid_kwh = sched.grid_kwh
                        schedule_reason = sched.reason
                        logger.info(
                            "schedule_computed",
                            target_date=schedule_target.date.isoformat(),
                            pv_kwh=sched.pv_kwh,
                            grid_kwh=sched.grid_kwh,
                            deferred_kwh=sched.deferred_kwh,
                            windows=len(sched.windows),
                            reason=sched.reason,
                        )
            except Exception:
                logger.exception("schedule_compute_failed")

            # Decision Journal — record the plan with full reasoning context.
            # Best-effort: never raises; never blocks publication below.
            if self.journal is not None:
                today = plan.days[0] if plan.days else None
                action = plan.immediate_action
                outcome_str = (
                    f"{action.charge_mode}: {action.energy_to_charge_kwh:.1f} kWh"
                    if action is not None
                    else "no plan"
                )
                outcome_class = (
                    "charge"
                    if action is not None and action.energy_to_charge_kwh > 0
                    else "hold"
                )
                pv_today_for_journal: float | None = (
                    pv_forecast_kwh[0] if pv_forecast_kwh else None
                )
                await self.journal.write(
                    decision_kind="plan_generated",
                    outcome=outcome_str,
                    reason=(action.reason if action is not None else "no day plans"),
                    outcome_class=outcome_class,
                    trace_id=plan.trace_id or None,
                    current_soc_pct=plan.current_soc_pct,
                    target_soc_pct=(
                        today.soc_needed_pct if today is not None else None
                    ),
                    energy_needed_kwh=(
                        today.energy_needed_kwh if today is not None else 0.0
                    ),
                    urgency=(action.urgency if action is not None else "none"),
                    mode=(action.charge_mode if action is not None else None),
                    inputs={
                        "vehicle_plugged_in": plan.vehicle_plugged_in,
                        "current_soc_pct": plan.current_soc_pct,
                        "current_energy_kwh": plan.current_energy_kwh,
                        "trips_today": [
                            {
                                "person": t.person,
                                "destination": t.destination,
                                "round_trip_km": t.round_trip_km,
                                "is_commute": t.is_commute,
                            }
                            for t in (today.trips if today is not None else [])
                        ],
                        "pv_forecast_today_kwh": pv_today_for_journal,
                        "horizon_days": len(plan.days),
                        "total_energy_needed_kwh": plan.total_energy_needed_kwh,
                        # S2: greedy schedule attached so post-hoc analysis can
                        # see "what we asked for vs. what actually happened".
                        "schedule": schedule_windows,
                        "schedule_pv_kwh": schedule_pv_kwh,
                        "schedule_grid_kwh": schedule_grid_kwh,
                        "schedule_reason": schedule_reason,
                        "pv_hourly_run_iso": self._pv_hourly_run_iso,
                        "pv_hourly_slots": len(self._pv_hourly_cache),
                    },
                )

            # Publish plan to NATS (bridge forwards to MQTT for HA discovery sensor)
            plan_payload = plan.to_dict()
            plan_payload["reasoning"] = self._compose_plan_reasoning(plan, vehicle)
            # S2: attach hour-by-hour schedule so downstream consumers can
            # render a real timeline (HA dashboard, NB9OS view).
            plan_payload["schedule"] = schedule_windows
            plan_payload["pv_hourly_run_iso"] = self._pv_hourly_run_iso
            if self.nats and self.nats.connected:
                await self.nats.publish("energy.ev.forecast.plan", plan_payload)

            # Publish plan to NATS event bus
            if self.nats and self.nats.connected:
                await self.nats.publish(
                    "energy.ev.plan_updated",
                    {
                        "trace_id": plan.trace_id,
                        "days": [
                            {
                                "date": d.date.isoformat(),
                                "urgency": d.urgency,
                                "charge_mode": d.charge_mode,
                                "energy_needed_kwh": round(d.energy_needed_kwh, 2),
                                "energy_to_charge_kwh": round(
                                    d.energy_to_charge_kwh, 2
                                ),
                                "departure_time": d.departure_time.strftime("%H:%M")
                                if d.departure_time
                                else None,
                            }
                            for d in plan.days
                        ],
                        "urgency": plan.days[0].urgency if plan.days else "none",
                        "mode": plan.days[0].charge_mode if plan.days else "PV Surplus",
                        "current_soc_pct": vehicle.soc_pct,
                        "timestamp": datetime.now(self._tz).isoformat(),
                    },
                )

            # Build and publish 7-day weekly plan to NATS
            if self.nats and self.nats.connected:
                # Collect all trips from day_plans
                all_trips = [t for dp in day_plans for t in dp.trips]

                # Build pv_forecast_by_date from cached NATS data
                # Days 0+1 use cached values; days 2-6 default to 0.0
                pv_by_date: dict[str, float] = dict(self._pv_forecast_cache)

                weekly_plan = self._weekly_builder.build(
                    trips=all_trips,
                    current_soc_pct=vehicle.soc_pct or 50.0,
                    battery_capacity_kwh=self.settings.ev_battery_capacity_net_kwh,
                    consumption_kwh_per_100km=self.consumption_tracker.consumption_kwh_per_100km,
                    pv_forecast_by_date=pv_by_date,
                    timestamp=datetime.now(self._tz).isoformat(),
                )
                await self.nats.publish(
                    "energy.ev.weekly_plan",
                    weekly_plan.model_dump(),
                )
                logger.info(
                    "weekly_plan_published",
                    days=len(weekly_plan.days),
                    current_soc_pct=vehicle.soc_pct,
                )

            # Apply immediate action to HA helpers (blocked in safe mode)
            safe_mode = await self._check_safe_mode()
            if safe_mode:
                logger.warning("safe_mode_active", action="apply_plan_blocked")
            else:
                await self.planner.apply_plan(
                    plan,
                    charge_mode_entity=self.settings.charge_mode_entity,
                    full_by_morning_entity=self.settings.full_by_morning_entity,
                    departure_time_entity=self.settings.departure_time_entity,
                    target_energy_entity=self.settings.target_energy_entity,
                    audi_vin=self.settings.audi_vin,
                    audi_set_target_soc=self.settings.audi_set_target_soc,
                    wallbox_vehicle_state_entity=self.settings.wallbox_vehicle_state_entity,
                    target_soc_entity=self.settings.target_soc_entity,
                )

            # Publish any pending clarifications to orchestrator via NATS
            clarifications = self.trips.get_pending_clarifications()
            if clarifications and self.nats and self.nats.connected:
                await self.nats.publish(
                    "energy.ev.forecast.clarification_needed",
                    {"clarifications": clarifications},
                )

            # Write plan to Google Calendar
            await self._write_plan_to_calendar(plan)

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

            self._save_state()

        except Exception:
            logger.exception("plan_update_failed")
        finally:
            self._touch_healthcheck()

    async def _get_calendar_events(self) -> list[dict[str, Any]]:
        """Fetch calendar events for the planning horizon."""
        if not self._gcal_service:
            return []

        try:
            now = datetime.now(self._tz)
            time_min = now.isoformat()
            time_max = (
                now
                + timedelta(
                    days=self.settings.planning_horizon_days,
                )
            ).isoformat()

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
                events.append(
                    {
                        "id": item.get("id", ""),
                        "summary": item.get("summary", ""),
                        "start": start.get("dateTime") or start.get("date", ""),
                        "end": end.get("dateTime") or end.get("date", ""),
                        "all_day": "date" in start,
                        "location": item.get("location", ""),
                    }
                )

            logger.info("calendar_events_fetched", count=len(events))
            return events

        except Exception:
            logger.exception("calendar_fetch_failed")
            return []

    # ------------------------------------------------------------------
    # PV forecast cache (updated via NATS)
    # ------------------------------------------------------------------

    async def _on_pv_forecast_updated(self, subject: str, payload: dict) -> None:
        """Cache today/tomorrow PV forecast values from NATS event."""
        try:
            today_kwh = float(payload.get("today_kwh", 0.0))
            tomorrow_kwh = float(payload.get("tomorrow_kwh", 0.0))
            now = datetime.now(self._tz).date()
            today_key = now.isoformat()
            tomorrow_key = (now + timedelta(days=1)).isoformat()
            self._pv_forecast_cache = {
                today_key: today_kwh,
                tomorrow_key: tomorrow_kwh,
            }
            logger.debug(
                "pv_forecast_cache_updated",
                today=today_kwh,
                tomorrow=tomorrow_kwh,
            )
        except Exception:
            logger.exception("pv_forecast_cache_update_failed")

    async def _on_pv_forecast_hourly(self, subject: str, payload: dict) -> None:
        """Cache the flat 72h hourly PV forecast for the charge scheduler (S2)."""
        try:
            self._pv_hourly_run_iso = payload.get("forecast_run_iso")
            new_cache: dict[str, dict[str, float]] = {}
            for slot in payload.get("hourly", []):
                t = slot.get("time_iso")
                if not t:
                    continue
                kwh = float(slot.get("kwh", 0.0))
                new_cache[t] = {
                    "kwh": kwh,
                    "conf_low": float(slot.get("conf_low", kwh)),
                    "conf_high": float(slot.get("conf_high", kwh)),
                }
            self._pv_hourly_cache = new_cache
            logger.debug("pv_hourly_cache_updated", slots=len(new_cache))
        except Exception:
            logger.exception("pv_hourly_cache_update_failed")

    def _build_hourly_pv(self) -> list[HourlyPV]:
        """Convert the NATS-fed hourly cache into HourlyPV input for the scheduler (S2)."""
        out: list[HourlyPV] = []
        for t_iso, vals in self._pv_hourly_cache.items():
            try:
                t = datetime.fromisoformat(t_iso.replace("Z", "+00:00"))
            except ValueError:
                continue
            kwh = vals.get("kwh", 0.0)
            out.append(
                HourlyPV(
                    time=t,
                    kwh=kwh,
                    conf_low=vals.get("conf_low", kwh),
                    conf_high=vals.get("conf_high", kwh),
                )
            )
        out.sort(key=lambda s: s.time)
        return out

    # ------------------------------------------------------------------
    # Home location resolution
    # ------------------------------------------------------------------

    async def _resolve_home_location(self) -> None:
        """Get home lat/lon from HA config if not explicitly set."""
        if self._home_lat and self._home_lon:
            logger.info(
                "home_location_from_config", lat=self._home_lat, lon=self._home_lon
            )
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
            logger.warning(
                "home_location_unavailable",
                detail="Geocoding for unknown destinations will be disabled",
            )

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    async def _on_orchestrator_command(self, subject: str, payload: dict) -> None:
        """Handle commands from the orchestrator service (NATS async callback)."""
        command = payload.get("command", "")
        logger.info("orchestrator_command", command=command)

        if command == "refresh":
            await self._update_plan()
        elif command == "refresh_vehicle":
            await self._update_vehicle()
        else:
            logger.debug("unknown_command", command=command)

    async def _on_trip_response(self, subject: str, payload: dict[str, Any]) -> None:
        """Handle trip clarification response from orchestrator (NATS async callback)."""
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
            # Trigger a plan update after clarification is resolved
            await self._update_plan()

    # ------------------------------------------------------------------
    # Google Calendar initialization
    # ------------------------------------------------------------------

    def _init_google_calendar(self) -> None:
        """Initialize Google Calendar API client."""
        if not HAS_GOOGLE:
            logger.info("google_calendar_not_available", reason="library not installed")
            return

        if not self.settings.google_calendar_family_id:
            logger.info(
                "google_calendar_not_configured", reason="no family calendar ID"
            )
            return

        try:
            import base64
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            scopes = [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar.events",
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
    # Google Calendar — write charging plan
    # ------------------------------------------------------------------

    async def _write_plan_to_calendar(self, plan: ChargingPlan) -> None:
        """Write/update the charging plan as calendar events.

        Creates one event per day that needs charging. Events use a
        consistent event ID (based on date) so they get updated rather
        than duplicated on each plan cycle.
        """
        if not self._gcal_service:
            return
        cal_id = self.settings.google_calendar_ev_plan_id
        if not cal_id:
            return

        try:
            now = datetime.now(self._tz)
            for day_rec in plan.days:
                # Skip days with no charging needed
                if (
                    day_rec.energy_to_charge_kwh <= 0
                    and day_rec.charge_mode == "PV Surplus"
                ):
                    # Clean up any existing event for this day
                    event_id = f"evplan{day_rec.date.strftime('%Y%m%d')}"
                    await self._delete_calendar_event(cal_id, event_id)
                    continue

                await self._upsert_plan_event(cal_id, plan, day_rec)

            # Also write a "current status" event for today
            await self._upsert_status_event(cal_id, plan)

            logger.info("calendar_plan_written", days=len(plan.days))
        except Exception as e:
            logger.error(
                "calendar_plan_write_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            logger.exception("calendar_plan_write_traceback")

    async def _upsert_plan_event(
        self,
        cal_id: str,
        plan: ChargingPlan,
        day_rec,
    ) -> None:
        """Create or update a calendar event for a single day's charging plan."""
        event_id = f"evplan{day_rec.date.strftime('%Y%m%d')}"
        dep_str = (
            day_rec.departure_time.strftime("%H:%M") if day_rec.departure_time else "—"
        )
        trips_str = (
            ", ".join(
                f"{t.person}: {t.destination} ({t.round_trip_km:.0f}km)"
                for t in day_rec.trips
            )
            or "No trips"
        )

        soc_str = f"{plan.current_soc_pct:.0f}%" if plan.current_soc_pct else "?"

        summary = (
            f"🔋 EV: {day_rec.charge_mode} ({day_rec.energy_to_charge_kwh:.1f} kWh)"
        )

        description = (
            f"Mode: {day_rec.charge_mode} | Urgency: {day_rec.urgency}\n"
            f"Departure: {dep_str}\n"
            f"Energy needed: {day_rec.energy_needed_kwh:.1f} kWh\n"
            f"Energy to charge: {day_rec.energy_to_charge_kwh:.1f} kWh\n"
            f"Required SoC: {day_rec.soc_needed_pct:.0f}%\n"
            f"Current SoC: {soc_str}\n"
            f"Trips: {trips_str}\n"
            f"Reason: {day_rec.reason}\n"
            f"\n---\nUpdated: {datetime.now(self._tz).strftime('%H:%M')}"
        )

        # Event spans the full day
        event_body = {
            "id": event_id,
            "summary": summary,
            "description": description,
            "start": {"date": day_rec.date.isoformat()},
            "end": {"date": day_rec.date.isoformat()},
            "transparency": "transparent",  # Don't block calendar
        }

        # Add color based on urgency
        color_map = {
            "critical": "11",  # red
            "high": "6",  # orange
            "medium": "5",  # yellow
            "low": "2",  # green
            "none": "8",  # grey
        }
        color_id = color_map.get(day_rec.urgency, "8")
        event_body["colorId"] = color_id

        await self._upsert_calendar_event(cal_id, event_id, event_body)

    async def _upsert_status_event(
        self,
        cal_id: str,
        plan: ChargingPlan,
    ) -> None:
        """Write a 'current status' all-day event for today."""
        today = datetime.now(self._tz).date()
        event_id = f"evstatus{today.strftime('%Y%m%d')}"

        soc = f"{plan.current_soc_pct:.0f}%" if plan.current_soc_pct else "?"
        plugged = "🔌 Plugged in" if plan.vehicle_plugged_in else "🚗 Unplugged"
        immediate = plan.immediate_action

        summary = f"⚡ EV {soc} {plugged}"
        if immediate and immediate.charge_mode != "PV Surplus":
            summary += f" → {immediate.charge_mode}"

        lines = [
            f"SoC: {soc}",
            f"Status: {plugged}",
            f"Total energy needed (7d): {plan.total_energy_needed_kwh:.1f} kWh",
        ]
        if immediate:
            lines.append(f"Active plan: {immediate.charge_mode}")
            lines.append(f"Reason: {immediate.reason}")

        for day_rec in plan.days:
            trips_str = ", ".join(t.destination for t in day_rec.trips) or "—"
            lines.append(
                f"\n{day_rec.date.strftime('%a %d.%m')}: "
                f"{day_rec.charge_mode} | "
                f"{day_rec.energy_to_charge_kwh:.1f} kWh | "
                f"Trips: {trips_str}"
            )

        lines.append(f"\n---\nUpdated: {datetime.now(self._tz).strftime('%H:%M')}")

        event_body = {
            "id": event_id,
            "summary": summary,
            "description": "\n".join(lines),
            "start": {"date": today.isoformat()},
            "end": {"date": today.isoformat()},
            "transparency": "transparent",
            "colorId": "8",  # grey for status
        }
        await self._upsert_calendar_event(cal_id, event_id, event_body)

    async def _upsert_calendar_event(
        self,
        cal_id: str,
        event_id: str,
        event_body: dict,
    ) -> None:
        """Insert or update a calendar event by ID."""
        loop = asyncio.get_event_loop()
        try:
            # Try update first
            await loop.run_in_executor(
                None,
                lambda: (
                    self._gcal_service.events()
                    .update(
                        calendarId=cal_id,
                        eventId=event_id,
                        body=event_body,
                    )
                    .execute()
                ),
            )
            logger.info("calendar_event_updated", event_id=event_id)
        except Exception as e:
            logger.debug(
                "calendar_event_update_failed", event_id=event_id, error=str(e)
            )
            try:
                # Doesn't exist — insert
                await loop.run_in_executor(
                    None,
                    lambda: (
                        self._gcal_service.events()
                        .insert(
                            calendarId=cal_id,
                            body=event_body,
                        )
                        .execute()
                    ),
                )
                logger.info("calendar_event_inserted", event_id=event_id)
            except Exception as e2:
                logger.error(
                    "calendar_event_upsert_failed",
                    event_id=event_id,
                    error=str(e2),
                    error_type=type(e2).__name__,
                )

    async def _delete_calendar_event(self, cal_id: str, event_id: str) -> None:
        """Delete a calendar event by ID (ignore if not found)."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: (
                    self._gcal_service.events()
                    .delete(
                        calendarId=cal_id,
                        eventId=event_id,
                    )
                    .execute()
                ),
            )
        except Exception:
            pass  # Not found or already deleted — fine

    # ------------------------------------------------------------------
    # NATS HA auto-discovery (bridge forwards to MQTT for HA)
    # ------------------------------------------------------------------

    async def _publish_ha_discovery(
        self, component: str, object_id: str, config: dict, node_id: str = ""
    ) -> None:
        """Publish HA auto-discovery config via NATS."""
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
        """Register entities in HA under the 'EV Forecast' device."""
        device = {
            "identifiers": ["homelab_ev_forecast"],
            "name": "EV Forecast",
            "manufacturer": "Homelab",
            "model": "ev-forecast",
        }
        node = "ev_forecast"

        # Service status
        await self._publish_ha_discovery(
            "binary_sensor",
            "service_status",
            node_id=node,
            config={
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
        await self._publish_ha_discovery(
            "sensor",
            "ev_soc",
            node_id=node,
            config={
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
        await self._publish_ha_discovery(
            "sensor",
            "ev_range",
            node_id=node,
            config={
                "name": "EV Range",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.range_km | default('unknown') }}",
                "unit_of_measurement": "km",
                "icon": "mdi:map-marker-distance",
            },
        )

        # Active Account
        await self._publish_ha_discovery(
            "sensor",
            "active_account",
            node_id=node,
            config={
                "name": "Active Audi Account",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.active_account | default('unknown') }}",
                "icon": "mdi:account-check",
            },
        )

        # Charging State
        await self._publish_ha_discovery(
            "sensor",
            "charging_state",
            node_id=node,
            config={
                "name": "EV Charging State",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.charging_state | default('unknown') }}",
                "icon": "mdi:ev-plug-type2",
            },
        )

        # Plug State
        await self._publish_ha_discovery(
            "sensor",
            "plug_state",
            node_id=node,
            config={
                "name": "EV Plug State",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.plug_state | default('unknown') }}",
                "icon": "mdi:power-plug",
            },
        )

        # Plan: Energy Needed Today
        await self._publish_ha_discovery(
            "sensor",
            "energy_needed_today",
            node_id=node,
            config={
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
        await self._publish_ha_discovery(
            "sensor",
            "recommended_mode",
            node_id=node,
            config={
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
        await self._publish_ha_discovery(
            "sensor",
            "next_trip",
            node_id=node,
            config={
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
        await self._publish_ha_discovery(
            "sensor",
            "next_departure",
            node_id=node,
            config={
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
        await self._publish_ha_discovery(
            "sensor",
            "plan_status",
            node_id=node,
            config={
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

        # Uptime (diagnostic)
        await self._publish_ha_discovery(
            "sensor",
            "uptime",
            node_id=node,
            config={
                "name": "EV Forecast Uptime",
                "device": device,
                "state_topic": "homelab/ev-forecast/heartbeat",
                "value_template": "{{ value_json.uptime_seconds | round(0) }}",
                "unit_of_measurement": "s",
                "device_class": "duration",
                "entity_category": "diagnostic",
                "icon": "mdi:timer-outline",
            },
        )

        # Consumption (dynamic kWh/100km)
        await self._publish_ha_discovery(
            "sensor",
            "consumption",
            node_id=node,
            config={
                "name": "EV Consumption",
                "device": device,
                "state_topic": vehicle_topic,
                "value_template": "{{ value_json.consumption_kwh_100km | default('unknown') }}",
                "unit_of_measurement": "kWh/100km",
                "icon": "mdi:speedometer",
                "json_attributes_topic": vehicle_topic,
                "json_attributes_template": (
                    '{{ {"source": value_json.consumption_source | default("default"), '
                    '"measurements": value_json.consumption_measurements | default(0)} | tojson }}'
                ),
            },
        )

        # Rich reasoning sensor with full plan details as JSON attributes
        await self._publish_ha_discovery(
            "sensor",
            "plan_reasoning",
            node_id=node,
            config={
                "name": "Plan Reasoning",
                "device": device,
                "state_topic": plan_topic,
                "value_template": (
                    "{% if value_json.days and value_json.days | length > 0 %}"
                    "{{ value_json.days[0].charge_mode }}: "
                    "{{ value_json.days[0].energy_needed_kwh }} kWh needed"
                    "{% else %}No plan{% endif %}"
                ),
                "json_attributes_topic": plan_topic,
                "json_attributes_template": (
                    '{{ {"full_reasoning": value_json.reasoning | default(""), '
                    '"current_soc_pct": value_json.current_soc_pct | default(0), '
                    '"vehicle_plugged_in": value_json.vehicle_plugged_in | default(false), '
                    '"total_energy_needed_kwh": value_json.total_energy_needed_kwh | default(0), '
                    '"plan_days": value_json.days | default([]) | length, '
                    '"today_charge_mode": (value_json.days[0].charge_mode if value_json.days and value_json.days | length > 0 else "none"), '
                    '"today_energy_kwh": (value_json.days[0].energy_needed_kwh if value_json.days and value_json.days | length > 0 else 0), '
                    '"today_urgency": (value_json.days[0].urgency if value_json.days and value_json.days | length > 0 else "none")} | tojson }}'
                ),
                "icon": "mdi:head-cog-outline",
            },
        )

        logger.info("ha_discovery_registered", entity_count=14)

    # ------------------------------------------------------------------
    # Reasoning
    # ------------------------------------------------------------------

    def _compose_plan_reasoning(self, plan: ChargingPlan, vehicle: VehicleState) -> str:
        """Compose detailed human-readable reasoning for the current plan."""
        lines: list[str] = []

        ct = self.consumption_tracker
        consumption_info = (
            f"{ct.consumption_kwh_per_100km} kWh/100km "
            f"({'measured' if ct.has_data else 'default'}, "
            f"{ct.measurement_count} samples)"
        )

        lines.append(
            f"Vehicle: SoC {vehicle.soc_pct}% | Range {vehicle.range_km} km | "
            f"Mileage: {vehicle.mileage_km} km | Plug: {vehicle.plug_state}"
        )
        lines.append(f"Consumption: {consumption_info}")
        lines.append(
            f"Plan: {plan.current_soc_pct}% SoC | "
            f"Plugged: {plan.vehicle_plugged_in} | "
            f"Total need: {plan.total_energy_needed_kwh:.1f} kWh"
        )

        for day in plan.days:
            trip_list = (
                ", ".join(
                    f"{t.person}: {t.destination} ({t.distance_km}km)"
                    for t in day.trips
                )
                or "no trips"
            )
            dep = day.departure_time.strftime("%H:%M") if day.departure_time else "none"
            lines.append(
                f"  {day.date}: [{day.urgency}] {day.charge_mode} | "
                f"need {day.energy_needed_kwh:.1f} kWh, "
                f"charge {day.energy_to_charge_kwh:.1f} kWh | "
                f"depart {dep}"
            )
            lines.append(f"    Trips: {trip_list}")
            lines.append(f"    Reason: {day.reason}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _heartbeat_thread_loop(self) -> None:
        """Publish heartbeat + touch healthcheck from a dedicated thread.

        Runs independently of the asyncio event loop so it can't be blocked
        by long-running scheduler jobs (HA API, Google Calendar, geocoding).
        Uses NatsPublisher.publish_sync() which is thread-safe.
        """
        interval = self.settings.heartbeat_interval_seconds
        # Small initial delay so NATS has time to connect
        self._heartbeat_stop.wait(min(5, interval))

        while not self._heartbeat_stop.is_set():
            self._touch_healthcheck()
            try:
                vehicle = self.vehicle.last_state
                if self.nats:
                    self.nats.publish_sync(
                        "heartbeat.ev-forecast",
                        {
                            "status": "online",
                            "service": "ev-forecast",
                            "uptime_seconds": round(
                                time.monotonic() - self._start_time, 1
                            ),
                            "ev_soc_pct": vehicle.soc_pct,
                            "active_account": vehicle.active_account or "single",
                            "has_plan": self._last_plan is not None,
                            "consumption_kwh_100km": self.consumption_tracker.consumption_kwh_per_100km,
                            "consumption_source": "measured"
                            if self.consumption_tracker.has_data
                            else "default",
                        },
                    )
            except Exception:
                logger.debug("heartbeat_publish_failed")
            self._heartbeat_stop.wait(interval)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist current vehicle state, consumption tracker, and last plan to disk."""
        try:
            vehicle = self.vehicle.last_state
            state_data: dict[str, Any] = {
                "vehicle": {
                    "soc_pct": vehicle.soc_pct,
                    "range_km": vehicle.range_km,
                    "charging_state": vehicle.charging_state,
                    "plug_state": vehicle.plug_state,
                    "mileage_km": vehicle.mileage_km,
                    "active_account": vehicle.active_account,
                },
                "consumption_tracker": self.consumption_tracker.to_dict(),
                "saved_at": datetime.now(self._tz).isoformat(),
            }

            if self._last_plan is not None:
                today = self._last_plan.days[0] if self._last_plan.days else None
                state_data["last_plan"] = {
                    "mode_recommendation": today.charge_mode if today else None,
                    "total_energy_needed": round(
                        self._last_plan.total_energy_needed_kwh, 2
                    ),
                }

            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(state_data, indent=2))
        except Exception:
            logger.debug("state_save_failed", exc_info=True)

    def _load_state(self) -> None:
        """Load persisted state on startup to pre-populate vehicle data and consumption history."""
        try:
            if not STATE_FILE.exists():
                return

            data = json.loads(STATE_FILE.read_text())
            v = data.get("vehicle", {})
            soc = v.get("soc_pct")

            if soc is not None:
                restored = VehicleState(
                    soc_pct=soc,
                    range_km=v.get("range_km"),
                    charging_state=v.get("charging_state", "unknown"),
                    plug_state=v.get("plug_state", "unknown"),
                    mileage_km=v.get("mileage_km"),
                    active_account=v.get("active_account", ""),
                )
                self.vehicle._last_state = restored

            # Restore consumption tracker history
            ct_data = data.get("consumption_tracker")
            if ct_data:
                self.consumption_tracker = ConsumptionTracker.from_dict(
                    ct_data,
                    capacity=self.settings.ev_battery_capacity_gross_kwh,
                    default=self.settings.ev_consumption_kwh_per_100km,
                    min_plausible=self.settings.ev_consumption_min_kwh_per_100km,
                    max_plausible=self.settings.ev_consumption_max_kwh_per_100km,
                )

            logger.info(
                "state_loaded",
                soc_pct=soc,
                consumption=self.consumption_tracker.consumption_kwh_per_100km,
                consumption_measurements=self.consumption_tracker.measurement_count,
                saved_at=data.get("saved_at"),
            )
        except Exception:
            logger.debug("state_load_failed", exc_info=True)

    # ------------------------------------------------------------------
    # Safe mode
    # ------------------------------------------------------------------

    async def _check_safe_mode(self) -> bool:
        """Check if global safe mode is active (blocks HA helper writes).

        Fail-open: if the check fails, allow actions.
        """
        entity = self.settings.safe_mode_entity
        if not entity:
            return False
        try:
            state = await self.ha.get_state(entity)
            return state.get("state", "off") == "on"
        except Exception:
            return False

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
        if hasattr(self, "_heartbeat_stop"):
            self._heartbeat_stop.set()
        self.scheduler.shutdown(wait=False)
        if self.nats and self.nats.connected:
            await self.nats.publish(
                "heartbeat.ev-forecast",
                {
                    "status": "offline",
                    "service": "ev-forecast",
                },
            )
        await self.ha.close()
        if self.nats:
            await self.nats.close()
        logger.info("shutdown_complete")


async def main() -> None:
    service = EVForecastService()
    await service.start()


if __name__ == "__main__":
    asyncio.run(main())
