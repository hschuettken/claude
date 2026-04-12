"""Smart EV Charging Service — entry point and control loop.

Reads the charge mode from Home Assistant, calculates the optimal wallbox
power, and writes the HEMS power limit every control cycle (~30 s).

Modes:
  Off         — wallbox paused (0 W)
  PV Surplus  — dynamic tracking of solar surplus only
  Smart       — PV surplus + grid fill by departure time
  Eco         — fixed ~5 kW constant
  Fast        — fixed 11 kW maximum
  Manual      — service hands off, user controls wallbox directly
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from shared.service import BaseService

from charger import WallboxController
from config import EVChargingSettings
from strategy import ChargeMode, ChargingContext, ChargingDecision, ChargingStrategy

HEALTHCHECK_FILE = Path("/app/data/healthcheck")


class SmartEVChargingService(BaseService):
    name = "smart-ev-charging"
    HA_READ_TIMEOUT = 10

    def __init__(self) -> None:
        super().__init__(settings=EVChargingSettings())
        self.settings: EVChargingSettings  # narrow type for IDE
        self.tz = ZoneInfo(self.settings.timezone)
        self._current_trace_id: str = ""

        # --- BUG #2 FIX: Cumulative grid kWh tracker ---
        # Persists across plug cycles, reset only on new overnight session start
        self._cumulative_grid_kwh: float = 0.0
        self._last_session_energy: float = 0.0  # track deltas
        self._grid_charging_active: bool = False  # is current cycle grid-charging?
        self._overnight_session_active: bool = False

        # --- BUG #3: Car target SOC drift check ---
        self._cycle_count: int = 0
        self._last_soc_push_time: float = 0.0

        # --- Feature #6: Plug/unplug resilience ---
        self._last_vehicle_connected: bool = False

        # --- R3: Smart mode sync state ---
        self._last_sync_vehicle_state: bool = False  # True = was connected last cycle

        # --- Forecast plan cache (from ev-forecast MQTT) ---
        self._forecast_needed_kwh: float = 0.0
        self._forecast_needed_soc: float = 0.0

        # --- Watchdog ---
        self._last_cycle_completed_at: float = time.monotonic()
        self._watchdog_task: asyncio.Task | None = None

        # Note: self.nats (NatsPublisher) is provided by BaseService and connected
        # in start() before run() is called. Do not override it here.

        # --- Session tracking for NATS events ---
        self._session_start_time: float | None = None
        self._session_start_energy: float = 0.0
        self._session_battery_assist_kwh: float = 0.0
        self._current_mode: str = ""

        # --- Drain mode tracking ---
        self._drain_budget_kwh: float = 0.0
        self._drain_used_kwh: float = 0.0
        self._drain_mode_active: bool = False
        self._drain_budget_exhausted_fired: bool = False
        self._drain_session_start_energy: float = 0.0
        self._drain_session_start_soc: float = 0.0
        self._drain_session_start_time: float | None = None

        # --- Sunset hour for drain budget calculation ---
        self._sunset_hour: int = 21
        self._sunset_hhmm: str = "21:00"

        # --- PV accuracy tracking ---
        self._pv_accuracy_pct: float = 100.0

        # --- Weekly EV plan (from energy.ev.weekly_plan NATS) ---
        self._weekly_plan: list[dict] | None = None

        # --- PV hourly forecast (from energy.pv.hourly_forecast NATS) ---
        self._pv_hourly_forecast: list[dict] | None = None  # today
        self._pv_hourly_forecast_tomorrow: list[dict] | None = None  # tomorrow

        # --- Strategy reference (set in run()) ---
        self._strategy: ChargingStrategy | None = None

        # --- Counters ---
        self._surplus_publish_counter: int = 0
        self._influx_cycle_count: int = 0

    async def run(self) -> None:
        # NATS is already connected by BaseService.start() before run() is called.
        # Register HA discovery entities via NATS ha.discovery subjects.
        await self._register_ha_discovery()

        # Subscribe to orchestrator commands via NATS
        self._force_cycle = asyncio.Event()
        if self.nats and self.nats.connected:
            await self.nats.subscribe_json(
                "orchestrator.command.smart-ev-charging",
                self._on_orchestrator_command,
            )

        charger = WallboxController(
            ha=self.ha,
            vehicle_state_entity=self.settings.wallbox_vehicle_state_entity,
            power_entity=self.settings.wallbox_power_entity,
            energy_session_entity=self.settings.wallbox_energy_session_entity,
            hems_power_number=self.settings.wallbox_hems_power_number,
        )

        self._strategy = ChargingStrategy(
            max_power_w=self.settings.wallbox_max_power_w,
            min_power_w=self.settings.wallbox_min_power_w,
            eco_power_w=self.settings.eco_charge_power_w,
            grid_reserve_w=self.settings.grid_reserve_w,
            start_hysteresis_w=self.settings.surplus_start_hysteresis_w,
            ramp_step_w=self.settings.ramp_step_w,
            startup_ramp_power_w=self.settings.startup_ramp_power_w,
            startup_ramp_duration_s=self.settings.startup_ramp_duration_s,
            battery_min_soc_pct=self.settings.battery_min_soc_pct,
            battery_ev_assist_max_w=self.settings.battery_ev_assist_max_w,
            battery_capacity_kwh=self.settings.battery_capacity_kwh,
            battery_target_eod_soc_pct=self.settings.battery_target_eod_soc_pct,
            pv_forecast_good_kwh=self.settings.pv_forecast_good_kwh,
            pv_morning_fraction=self.settings.pv_morning_fraction,
            charger_efficiency=self.settings.charger_efficiency,
            battery_hold_soc_pct=self.settings.battery_hold_soc_pct,
            battery_hold_margin=self.settings.battery_hold_margin,
            pv_defer_confidence_factor=self.settings.pv_defer_confidence_factor,
            pv_defer_min_hours_before_departure=self.settings.pv_defer_min_hours_before_departure,
        )
        strategy = self._strategy

        # Subscribe to service-to-service NATS events
        if self.nats and self.nats.connected:
            await self.nats.subscribe_json(
                "energy.ev.plan_updated", self._on_ev_plan_nats
            )
            await self.nats.subscribe_json(
                "energy.pv.forecast_updated", self._on_pv_forecast_nats
            )
            await self.nats.subscribe_json(
                "energy.pv.accuracy_checked", self._on_pv_accuracy_nats
            )
            await self.nats.subscribe_json(
                "energy.ev.weekly_plan", self._on_weekly_plan_nats
            )
            await self.nats.subscribe_json(
                "energy.pv.hourly_forecast", self._on_pv_hourly_forecast_nats
            )

        self.logger.info(
            "service_ready",
            control_interval=self.settings.control_interval_seconds,
            max_power=self.settings.wallbox_max_power_w,
            min_power=self.settings.wallbox_min_power_w,
            eco_power=self.settings.eco_charge_power_w,
            battery_min_soc=self.settings.battery_min_soc_pct,
            battery_max_assist=self.settings.battery_ev_assist_max_w,
        )

        # Start watchdog
        self._watchdog_task = asyncio.create_task(self._watchdog_loop())

        # Control loop
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._control_cycle(charger, strategy),
                    timeout=self.settings.control_interval_seconds * 3,
                )
            except asyncio.TimeoutError:
                self.logger.error(
                    "control_cycle_timeout",
                    timeout_s=self.settings.control_interval_seconds * 3,
                )
            except Exception:
                self.logger.exception("control_cycle_error")
            finally:
                self._touch_healthcheck()
                self._last_cycle_completed_at = time.monotonic()

            try:
                done, _ = await asyncio.wait(
                    [
                        asyncio.create_task(self._shutdown_event.wait()),
                        asyncio.create_task(self._force_cycle.wait()),
                    ],
                    timeout=self.settings.control_interval_seconds,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if self._shutdown_event.is_set():
                    break
                if self._force_cycle.is_set():
                    self._force_cycle.clear()
                    self.logger.info("forced_cycle_triggered")
            except asyncio.TimeoutError:
                pass

    async def shutdown(self) -> None:
        """Clean up resources. BaseService.shutdown() handles NATS close."""
        await super().shutdown()

    # ------------------------------------------------------------------
    # Watchdog -- monitors control loop liveness
    # ------------------------------------------------------------------

    async def _watchdog_loop(self) -> None:
        """Background task that monitors the control loop heartbeat.

        If the control loop hasn't completed a cycle within the configured
        timeout, this publishes an MQTT alert and optionally exits the
        process (triggering a Docker restart via the restart policy).
        """
        self.logger.info(
            "watchdog_started",
            timeout_s=self.settings.watchdog_timeout_seconds,
            check_interval_s=self.settings.watchdog_check_interval_seconds,
            restart_on_freeze=self.settings.watchdog_restart_on_freeze,
        )
        consecutive_alerts = 0

        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.settings.watchdog_check_interval_seconds)
            except asyncio.CancelledError:
                break

            age = time.monotonic() - self._last_cycle_completed_at
            if age > self.settings.watchdog_timeout_seconds:
                consecutive_alerts += 1
                self.logger.critical(
                    "watchdog_alert",
                    last_cycle_age_s=round(age, 1),
                    timeout_s=self.settings.watchdog_timeout_seconds,
                    consecutive_alerts=consecutive_alerts,
                )

                # Publish MQTT alert so HA / monitoring can pick it up
                try:
                    await self.publish(
                        "watchdog",
                        {
                            "status": "frozen",
                            "last_cycle_age_s": round(age, 1),
                            "timeout_s": self.settings.watchdog_timeout_seconds,
                            "consecutive_alerts": consecutive_alerts,
                            "action": "restart"
                            if self.settings.watchdog_restart_on_freeze
                            else "alert_only",
                        },
                    )
                except Exception:
                    self.logger.exception("watchdog_nats_publish_failed")

                if self.settings.watchdog_restart_on_freeze:
                    self.logger.critical(
                        "watchdog_forcing_exit",
                        reason="Control loop frozen, exiting to trigger Docker restart",
                        frozen_for_s=round(age, 1),
                    )
                    # Give MQTT a moment to send the alert
                    await asyncio.sleep(1)
                    os._exit(1)  # Hard exit -- asyncio cleanup may hang too
            else:
                if consecutive_alerts > 0:
                    self.logger.info(
                        "watchdog_recovered",
                        previous_alerts=consecutive_alerts,
                        cycle_age_s=round(age, 1),
                    )
                consecutive_alerts = 0

    # ------------------------------------------------------------------
    # Control cycle
    # ------------------------------------------------------------------

    async def _control_cycle(
        self,
        charger: WallboxController,
        strategy: ChargingStrategy,
    ) -> None:
        """Single iteration: read → decide → apply → publish."""
        self._cycle_count += 1

        # 1) Read all inputs from HA
        mode = await self._read_charge_mode()
        wallbox = await charger.read_state()
        grid_power = await self._read_float(self.settings.grid_power_entity)
        pv_power = await self._read_float(self.settings.pv_power_entity)
        full_by_morning = await self._read_bool(self.settings.full_by_morning_entity)
        departure_time = await self._read_time(self.settings.departure_time_entity)
        target_energy = await self._read_float(self.settings.target_energy_entity)

        battery_power = await self._read_float(self.settings.battery_power_entity)
        battery_soc = await self._read_float(self.settings.battery_soc_entity)
        drain_pv_battery = await self._read_bool(self.settings.drain_pv_battery_entity)

        pv_forecast_remaining = await self._read_float(
            self.settings.pv_forecast_remaining_entity,
        )
        pv_forecast_tomorrow = await self._read_float(
            self.settings.pv_forecast_tomorrow_entity,
        )

        house_power = await self._read_float(self.settings.house_power_entity)

        ev_soc: float | None = None
        if self.settings.ev_soc_entity:
            ev_soc = await self._read_float_optional(self.settings.ev_soc_entity)

        ev_battery_capacity = await self._read_float(
            self.settings.ev_battery_capacity_entity,
            default=77.0,
        )
        ev_target_soc = await self._read_float(
            self.settings.target_soc_entity,
            default=80.0,
        )

        # --- Read manual override targets (R2) ---
        manual_target_kwh = await self._read_float(
            self.settings.manual_target_kwh_entity,
            default=0.0,
        )
        manual_target_soc = await self._read_float(
            self.settings.manual_target_soc_entity,
            default=0.0,
        )

        # --- Read Ready By mode helpers ---
        ready_by_target_soc = await self._read_float(
            self.settings.ready_by_target_soc_entity,
            default=0.0,
        )
        ready_by_deadline = await self._read_datetime(
            self.settings.ready_by_deadline_entity,
        )

        now = datetime.now(self.tz)

        # --- Feature #6: Plug/unplug resilience ---
        vehicle_just_plugged = (
            wallbox.vehicle_connected and not self._last_vehicle_connected
        )
        if vehicle_just_plugged:
            self.logger.info(
                "vehicle_replugged",
                ev_soc=round(ev_soc) if ev_soc is not None else None,
                ev_target_soc=round(ev_target_soc),
                mode=mode.value,
                full_by_morning=full_by_morning,
                session_energy_kwh=round(wallbox.session_energy_kwh, 2),
            )
            # --- R3: Smart mode sync on plug-in ---
            # When mode=Smart AND car just connected: write forecast values to HA input_numbers
            if mode.value == "Smart" and not self._last_sync_vehicle_state:
                if self._forecast_needed_kwh > 0:
                    try:
                        await self.ha.call_service(
                            "input_number",
                            "set_value",
                            {
                                "entity_id": self.settings.manual_target_kwh_entity,
                                "value": round(self._forecast_needed_kwh, 1),
                            },
                        )
                        await self.ha.call_service(
                            "input_number",
                            "set_value",
                            {
                                "entity_id": self.settings.manual_target_soc_entity,
                                "value": round(self._forecast_needed_soc, 0),
                            },
                        )
                        self._last_sync_vehicle_state = True
                        self.logger.info(
                            "smart_sync_forecast_to_manual",
                            forecast_kwh=round(self._forecast_needed_kwh, 1),
                            forecast_soc=round(self._forecast_needed_soc, 0),
                        )
                        # Update local vars so ctx gets the synced values this cycle
                        manual_target_kwh = round(self._forecast_needed_kwh, 1)
                        manual_target_soc = round(self._forecast_needed_soc, 0)
                    except Exception:
                        self.logger.exception("smart_sync_failed")
                else:
                    self.logger.info(
                        "smart_sync_skipped", reason="no forecast data available"
                    )

        # Reset sync flag when vehicle disconnects
        if not wallbox.vehicle_connected:
            self._last_sync_vehicle_state = False

        self._last_vehicle_connected = wallbox.vehicle_connected

        # --- BUG #2 FIX: Cumulative grid kWh tracker ---
        # Track grid charging based on power deltas, not session energy
        current_hour = now.hour

        # Start new overnight session at 22:00
        if current_hour == 22 and not self._overnight_session_active:
            self._overnight_session_active = True
            self._cumulative_grid_kwh = 0.0
            self._last_session_energy = wallbox.session_energy_kwh
            self.logger.info(
                "overnight_session_started",
                session_energy_at_start=wallbox.session_energy_kwh,
            )

        # End overnight session at 08:00
        if 8 <= current_hour < 22 and self._overnight_session_active:
            self._overnight_session_active = False
            self.logger.info(
                "overnight_session_ended",
                cumulative_grid_kwh=round(self._cumulative_grid_kwh, 2),
            )

        # Track grid charging increments (works across unplug/replug)
        # If session energy went DOWN (replug reset), don't subtract
        session_delta = wallbox.session_energy_kwh - self._last_session_energy
        if session_delta < 0:
            # Session was reset (unplug/replug) — ignore the negative delta
            session_delta = 0.0
        if self._grid_charging_active and session_delta > 0:
            self._cumulative_grid_kwh += session_delta
        self._last_session_energy = wallbox.session_energy_kwh

        # Determine if current charging is grid-based (nighttime or grid fallback)
        # We'll set this AFTER the decision so it's used next cycle
        overnight_grid_kwh = self._cumulative_grid_kwh

        # --- BUG #1/#4: Determine if departure has passed ---
        departure_passed = False
        if departure_time is not None:
            dep_dt = now.replace(
                hour=departure_time.hour,
                minute=departure_time.minute,
                second=0,
                microsecond=0,
            )
            departure_passed = dep_dt <= now

        # Compute kwh_tocharge_left for this cycle (R4)
        kwh_tocharge_left_val = max(0.0, manual_target_kwh - wallbox.session_energy_kwh)

        # --- Track charging state transition for NATS events ---
        was_charging = wallbox.vehicle_charging
        old_mode = self._current_mode
        new_mode_str = mode.value

        # --- Compute drain budget ---
        drain_budget = 0.0
        if drain_pv_battery:
            drain_budget = self._compute_drain_budget(
                pv_remaining_kwh=pv_forecast_remaining,
                battery_soc_pct=battery_soc,
                house_power_w=house_power,
                battery_capacity_kwh=self.settings.battery_capacity_kwh,
            )
            self._drain_budget_kwh = drain_budget

        ctx = ChargingContext(
            mode=mode,
            wallbox=wallbox,
            grid_power_w=grid_power,
            pv_power_w=pv_power,
            battery_power_w=battery_power,
            battery_soc_pct=battery_soc,
            pv_forecast_remaining_kwh=pv_forecast_remaining,
            pv_forecast_tomorrow_kwh=pv_forecast_tomorrow,
            house_power_w=house_power,
            battery_capacity_kwh=self.settings.battery_capacity_kwh,
            battery_target_eod_soc_pct=self.settings.battery_target_eod_soc_pct,
            full_by_morning=full_by_morning,  # Keep true even post-departure for overnight charging
            departure_time=departure_time,
            target_energy_kwh=target_energy,
            session_energy_kwh=wallbox.session_energy_kwh,
            ev_soc_pct=ev_soc,
            ev_battery_capacity_kwh=ev_battery_capacity,
            ev_target_soc_pct=ev_target_soc,
            overnight_grid_kwh_charged=overnight_grid_kwh,
            now=now,
            departure_passed=departure_passed,
            manual_target_kwh=manual_target_kwh,
            manual_target_soc=manual_target_soc,
            forecast_needed_kwh=self._forecast_needed_kwh,
            forecast_needed_soc=self._forecast_needed_soc,
            drain_pv_battery=drain_pv_battery,
            drain_budget_kwh=drain_budget,
            drain_used_kwh=self._drain_used_kwh,
            # New: Auto / Ready By / PV Only fields
            weekly_plan=self._weekly_plan,
            ready_by_target_soc=ready_by_target_soc,
            ready_by_deadline=ready_by_deadline,
            pv_hourly_forecast=self._pv_hourly_forecast,
            pv_forecast_tomorrow_hourly=self._pv_hourly_forecast_tomorrow,
        )

        # 2) Decide target power
        decision = strategy.decide(ctx)

        # Update grid charging flag for next cycle's tracking
        # Grid charging = charging at night or during grid fallback (not PV surplus)
        is_night = current_hour >= 22 or current_hour < 8
        self._grid_charging_active = (
            decision.target_power_w > 0
            and (is_night or "grid" in decision.reason.lower())
            and "pv surplus" not in decision.reason.lower()
            and "pv resume" not in decision.reason.lower()
        )

        # --- NATS: Mode changed ---
        self._current_mode = new_mode_str
        if old_mode and old_mode != new_mode_str:
            await self._nats_publish(
                "energy.ev.mode_changed",
                {
                    "old_mode": old_mode,
                    "new_mode": new_mode_str,
                    "reason": decision.reason[:200] if decision else "",
                    "timestamp": now.isoformat(),
                },
            )

        # --- Determine vehicle_charging state (post-decision for accuracy) ---
        is_now_charging = decision.target_power_w > 0 and wallbox.vehicle_connected

        # --- NATS: Charging started ---
        if not was_charging and is_now_charging:
            self._session_start_time = time.monotonic()
            self._session_start_energy = wallbox.session_energy_kwh
            self._session_battery_assist_kwh = 0.0
            await self._nats_publish(
                "energy.ev.charging_started",
                {
                    "mode": self._current_mode,
                    "target_kwh": float(ctx.target_energy_kwh),
                    "target_soc": float(ctx.ev_target_soc_pct)
                    if ctx.ev_soc_pct is not None
                    else None,
                    "timestamp": now.isoformat(),
                },
            )

        # --- NATS: Charging completed ---
        if was_charging and not is_now_charging and self._session_start_time:
            session_kwh = wallbox.session_energy_kwh - self._session_start_energy
            if session_kwh > 0.1:
                duration_min = (time.monotonic() - self._session_start_time) / 60
                cost = session_kwh * self.settings.grid_price_ct / 100
                await self._nats_publish(
                    "energy.ev.charging_completed",
                    {
                        "session_kwh": round(session_kwh, 2),
                        "duration_minutes": round(duration_min, 1),
                        "pv_fraction": 0.0,
                        "grid_fraction": 1.0,
                        "battery_assist_kwh": round(
                            self._session_battery_assist_kwh, 3
                        ),
                        "cost_estimate_eur": round(cost, 2),
                        "timestamp": now.isoformat(),
                    },
                )
                self._write_charging_session_influx(
                    session_kwh=session_kwh,
                    duration_min=duration_min,
                    mode=old_mode or self._current_mode,
                    battery_assist_kwh=self._session_battery_assist_kwh,
                )
            self._session_start_time = None
            self._session_battery_assist_kwh = 0.0

        # Accumulate battery assist kWh for the session
        if is_now_charging and decision.battery_assist_w > 0:
            assist_kwh_this_cycle = (decision.battery_assist_w / 1000.0) * (
                self.settings.control_interval_seconds / 3600.0
            )
            self._session_battery_assist_kwh += assist_kwh_this_cycle

        # --- NATS: PV surplus available (every 10 cycles ~5 min) ---
        self._surplus_publish_counter += 1
        if self._surplus_publish_counter >= 10:
            self._surplus_publish_counter = 0
            if decision.pv_surplus_w > 0 and wallbox.vehicle_connected:
                await self._nats_publish(
                    "energy.ev.surplus_available",
                    {
                        "pv_w": round(pv_power, 0),
                        "battery_soc": round(battery_soc, 1),
                        "ev_soc": round(ev_soc, 1) if ev_soc is not None else None,
                        "surplus_w": round(decision.pv_surplus_w, 0),
                        "timestamp": now.isoformat(),
                    },
                )

        # --- Drain mode tracking ---
        # Drain started: toggle went from off to on
        if drain_pv_battery and not self._drain_mode_active:
            self._drain_mode_active = True
            self._drain_budget_exhausted_fired = False
            self._drain_used_kwh = 0.0
            self._drain_session_start_energy = wallbox.session_energy_kwh
            self._drain_session_start_soc = battery_soc
            self._drain_session_start_time = time.monotonic()
            await self._nats_publish(
                "energy.ev.drain_started",
                {
                    "drain_budget_kwh": round(self._drain_budget_kwh, 2),
                    "battery_soc_pct": round(battery_soc, 1),
                    "pv_remaining_kwh": round(pv_forecast_remaining, 2),
                    "timestamp": now.isoformat(),
                },
            )

        # Accumulate drain usage
        if decision.drain_boost_w > 0:
            drain_kwh_this_cycle = (decision.drain_boost_w / 1000.0) * (
                self.settings.control_interval_seconds / 3600.0
            )
            self._drain_used_kwh += drain_kwh_this_cycle

        # Fire drain budget exhausted (once per drain session)
        if (
            self._drain_mode_active
            and not self._drain_budget_exhausted_fired
            and self._drain_budget_kwh > 0
            and self._drain_used_kwh >= self._drain_budget_kwh
        ):
            self._drain_budget_exhausted_fired = True
            await self._nats_publish(
                "energy.ev.drain_budget_exhausted",
                {
                    "kwh_drained": round(self._drain_used_kwh, 3),
                    "budget_kwh": round(self._drain_budget_kwh, 2),
                    "battery_soc_pct": round(battery_soc, 1),
                    "timestamp": now.isoformat(),
                },
            )

        # Reset drain mode when toggle goes off
        if not drain_pv_battery and self._drain_mode_active:
            if self._drain_session_start_time is not None:
                import time as _time_module

                duration_min = (
                    _time_module.monotonic() - self._drain_session_start_time
                ) / 60.0
                self._write_drain_session_influx(
                    kwh_drained=self._drain_used_kwh,
                    battery_soc_start=self._drain_session_start_soc,
                    battery_soc_end=battery_soc,
                    duration_minutes=duration_min,
                )
            self._drain_mode_active = False

        # --- Publish drain status via NATS (bridge forwards to MQTT for HA discovery) ---
        drain_remaining = max(0.0, self._drain_budget_kwh - self._drain_used_kwh)
        await self.publish(
            "drain-status",
            {
                "drain_mode_active": self._drain_mode_active,
                "drain_budget_kwh": round(self._drain_budget_kwh, 2),
                "drain_used_kwh": round(self._drain_used_kwh, 3),
                "drain_remaining_kwh": round(drain_remaining, 2),
                "drain_reason": decision.drain_boost_reason
                if decision.drain_boost_w > 0
                else "",
                "battery_refill_eta": self._sunset_hhmm,
            },
        )

        # --- InfluxDB: control decision (every 10 cycles ~5 min) ---
        self._influx_cycle_count += 1
        if self._influx_cycle_count >= 10:
            self._influx_cycle_count = 0
            self._write_control_decision_influx(
                target_power_w=float(decision.target_power_w),
                actual_power_w=float(wallbox.current_power_w),
                mode=self._current_mode,
                reason_code=decision.reason[:50],
            )

        # 3) Apply to wallbox
        if not decision.skip_control:
            if await self.is_safe_mode():
                self.logger.warning(
                    "safe_mode_active",
                    target_w=decision.target_power_w,
                )
                decision.reason = (
                    f"SAFE MODE: would set {decision.target_power_w} W (blocked)"
                )
                decision.skip_control = True
            else:
                await charger.set_power_limit(decision.target_power_w)

        # --- BUG #3 + R7: Car target SOC drift check (mode-based) ---
        if (
            self._cycle_count % self.settings.car_target_soc_check_interval == 0
            and wallbox.vehicle_connected
        ):
            await self._check_car_target_soc(ctx, ev_target_soc, now)

        # --- Feature #5: Calculate and publish kWh remaining + ETA ---
        kwh_remaining = ctx.energy_needed_kwh
        estimated_completion: str | None = None
        if decision.target_power_w > 0 and kwh_remaining > 0:
            # Use actual current power for more accurate ETA
            actual_power_kw = (
                max(wallbox.current_power_w, decision.target_power_w) / 1000.0
            )
            if actual_power_kw > 0:
                hours_to_complete = kwh_remaining / actual_power_kw
                completion_dt = now + timedelta(hours=hours_to_complete)
                estimated_completion = completion_dt.strftime("%H:%M")

        # --- R4: kwh_tocharge_left ---
        kwh_tocharge_left_val = ctx.kwh_tocharge_left

        # Publish forecast sensors via NATS
        await self.publish(
            "forecast",
            {
                "ev_forecast_needed_kwh": round(self._forecast_needed_kwh, 1),
                "ev_forecast_needed_soc": round(self._forecast_needed_soc, 1),
                "ev_kwh_to_charge_left": round(kwh_tocharge_left_val, 2),
            },
        )

        # 4) Publish status
        await self._publish_status(
            ctx,
            decision,
            house_power,
            kwh_remaining,
            estimated_completion,
            kwh_tocharge_left_val,
        )
        self._touch_healthcheck()

        self.logger.info(
            "cycle",
            mode=mode.value,
            vehicle=wallbox.vehicle_state_text,
            grid_w=round(grid_power),
            pv_w=round(pv_power),
            ev_w=round(wallbox.current_power_w),
            house_w=round(house_power),
            bat_w=round(battery_power),
            bat_soc=round(battery_soc),
            ev_soc=round(ev_soc) if ev_soc is not None else None,
            ev_target_soc=round(ev_target_soc),
            energy_needed_kwh=round(ctx.energy_needed_kwh, 1),
            forecast_kwh=round(pv_forecast_remaining, 1),
            target_w=decision.target_power_w,
            reason=decision.reason,
            departure_passed=departure_passed,
            cumulative_grid_kwh=round(self._cumulative_grid_kwh, 2),
        )

    # ------------------------------------------------------------------
    # BUG #3: Car target SOC drift correction
    # ------------------------------------------------------------------

    async def _check_car_target_soc(
        self, ctx, desired_soc: float, now: datetime
    ) -> None:
        """Check if the car's target SOC matches our desired SOC, correct if not.

        R7: Mode-based target SoC logic:
        - Fast / PV Surplus → target 100%
        - Manual Until → target manual_target_soc
        - Smart → target ev_target_soc_pct (from ev-forecast, unchanged)
        - Manual → do NOT update
        """
        # Manual mode: do not update car target SoC at all
        if ctx.mode == ChargeMode.MANUAL:
            return

        # Determine desired SoC based on mode (R7)
        if ctx.mode in (ChargeMode.FAST, ChargeMode.PV_SURPLUS):
            desired_soc = 100.0
        elif ctx.mode == ChargeMode.MANUAL_UNTIL:
            if ctx.manual_target_soc > 0:
                desired_soc = ctx.manual_target_soc
            else:
                desired_soc = 100.0  # fallback if no target set
        # For Smart, Eco: use the passed desired_soc (from ev-forecast / target_soc_entity)

        # Cooldown check
        elapsed = time.monotonic() - self._last_soc_push_time
        if elapsed < self.settings.car_target_soc_cooldown_seconds:
            return

        car_target_soc = await self._read_float_optional(
            self.settings.car_target_soc_entity,
        )
        if car_target_soc is None:
            return  # Can't read car's target SOC

        if abs(car_target_soc - desired_soc) >= 1.0:
            self.logger.info(
                "car_target_soc_corrected",
                car=round(car_target_soc),
                desired=round(desired_soc),
                mode=ctx.mode.value,
            )
            try:
                await self.ha.call_service(
                    "script",
                    "turn_on",
                    {
                        "entity_id": self.settings.car_target_soc_script,
                    },
                )
                self._last_soc_push_time = time.monotonic()
            except Exception:
                self.logger.exception("car_target_soc_push_failed")

    # ------------------------------------------------------------------
    # HA state readers
    # ------------------------------------------------------------------

    async def _read_charge_mode(self) -> ChargeMode:
        try:
            state = await asyncio.wait_for(
                self.ha.get_state(self.settings.charge_mode_entity),
                timeout=self.HA_READ_TIMEOUT,
            )
            return ChargeMode(state.get("state", "Off"))
        except (ValueError, KeyError):
            return ChargeMode.OFF
        except Exception:
            return ChargeMode.OFF

    async def _read_float(self, entity_id: str, default: float = 0.0) -> float:
        try:
            state = await asyncio.wait_for(
                self.ha.get_state(entity_id),
                timeout=self.HA_READ_TIMEOUT,
            )
            val = state.get("state", str(default))
            if val in ("unavailable", "unknown"):
                return default
            return float(val)
        except Exception:
            self.logger.warning("read_float_failed", entity_id=entity_id)
            return default

    async def _read_float_optional(self, entity_id: str) -> float | None:
        try:
            state = await asyncio.wait_for(
                self.ha.get_state(entity_id),
                timeout=self.HA_READ_TIMEOUT,
            )
            val = state.get("state", "")
            if val in ("unavailable", "unknown", ""):
                return None
            return float(val)
        except Exception:
            self.logger.warning("read_float_optional_failed", entity_id=entity_id)
            return None

    async def _read_bool(self, entity_id: str) -> bool:
        try:
            state = await asyncio.wait_for(
                self.ha.get_state(entity_id),
                timeout=self.HA_READ_TIMEOUT,
            )
            return state.get("state", "off") == "on"
        except Exception:
            return False

    async def _read_datetime(self, entity_id: str) -> datetime | None:
        """Read an input_datetime entity and return a timezone-aware datetime, or None."""
        if not entity_id:
            return None
        try:
            state = await asyncio.wait_for(
                self.ha.get_state(entity_id),
                timeout=self.HA_READ_TIMEOUT,
            )
            val = state.get("state", "")
            if not val or val in ("unavailable", "unknown"):
                return None
            # HA input_datetime format: "2026-04-13 07:30:00" or "2026-04-13T07:30:00"
            val = val.replace(" ", "T")
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self.tz)
            return dt
        except Exception:
            self.logger.warning("read_datetime_failed", entity_id=entity_id)
            return None

    async def _read_time(self, entity_id: str) -> dt_time | None:
        try:
            state = await asyncio.wait_for(
                self.ha.get_state(entity_id),
                timeout=self.HA_READ_TIMEOUT,
            )
            val = state.get("state", "")
            if not val or val in ("unavailable", "unknown"):
                return dt_time(7, 0)
            parts = val.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except Exception:
            return dt_time(7, 0)

    # ------------------------------------------------------------------
    # NATS publishing
    # ------------------------------------------------------------------

    async def _publish_status(
        self,
        ctx: ChargingContext,
        decision: ChargingDecision,
        house_power: float = 0.0,
        kwh_remaining: float = 0.0,
        estimated_completion: str | None = None,
        kwh_tocharge_left: float = 0.0,
    ) -> None:
        pv_available = max(
            0,
            ctx.grid_power_w
            + ctx.wallbox.current_power_w
            + ctx.battery_power_w
            - self.settings.grid_reserve_w,
        )
        payload: dict = {
            "trace_id": self._current_trace_id,
            "mode": ctx.mode.value,
            "vehicle": ctx.wallbox.vehicle_state_text,
            "vehicle_connected": ctx.wallbox.vehicle_connected,
            "target_power_w": decision.target_power_w,
            "actual_power_w": round(ctx.wallbox.current_power_w),
            "session_energy_kwh": round(ctx.wallbox.session_energy_kwh, 2),
            "energy_needed_kwh": round(ctx.energy_needed_kwh, 1),
            "grid_power_w": round(ctx.grid_power_w),
            "pv_power_w": round(ctx.pv_power_w),
            "pv_available_w": round(pv_available),
            "house_power_w": round(house_power),
            "battery_power_w": round(ctx.battery_power_w),
            "battery_soc_pct": round(ctx.battery_soc_pct, 1),
            "ev_soc_pct": round(ctx.ev_soc_pct, 1)
            if ctx.ev_soc_pct is not None
            else None,
            "ev_target_soc_pct": round(ctx.ev_target_soc_pct),
            "pv_forecast_remaining_kwh": round(ctx.pv_forecast_remaining_kwh, 1),
            "pv_forecast_tomorrow_kwh": round(ctx.pv_forecast_tomorrow_kwh, 1),
            "overnight_grid_kwh_charged": round(ctx.overnight_grid_kwh_charged, 1),
            "full_by_morning": ctx.full_by_morning,
            "departure_passed": ctx.departure_passed,
            "reason": decision.reason,
            # --- Feature #5: kWh remaining + ETA ---
            "kwh_remaining": round(kwh_remaining, 2),
            "estimated_completion_time": estimated_completion,
            # --- R4: kwh_tocharge_left (Manual Until mode) ---
            "kwh_tocharge_left": round(kwh_tocharge_left, 2),
            # --- R1: Forecast sensors ---
            "ev_forecast_needed_kwh": round(ctx.forecast_needed_kwh, 1),
            "ev_forecast_needed_soc": round(ctx.forecast_needed_soc, 1),
            # --- R2: Manual targets ---
            "manual_target_kwh": round(ctx.manual_target_kwh, 1),
            "manual_target_soc": round(ctx.manual_target_soc, 0),
            # --- Enhanced decision context ---
            "pv_surplus_w": round(decision.pv_surplus_w),
            "battery_assist_w": round(decision.battery_assist_w),
            "battery_assist_reason": decision.battery_assist_reason,
            "deadline_active": decision.deadline_active,
            "deadline_hours_left": decision.deadline_hours_left,
            "deadline_required_w": round(decision.deadline_required_w),
            "energy_remaining_kwh": decision.energy_remaining_kwh,
            "target_energy_kwh": ctx.target_energy_kwh,
            "plan_target_reached": ctx.target_reached,
            # --- Phase 2: Solar defer ---
            "solar_defer_active": decision.solar_defer_active,
            "solar_defer_pv_kwh": round(decision.solar_defer_pv_kwh, 1),
            "solar_defer_needed_kwh": round(decision.solar_defer_needed_kwh, 1),
            # --- Drain PV battery ---
            "drain_pv_battery": ctx.drain_pv_battery,
            "drain_boost_w": round(decision.drain_boost_w),
            "drain_boost_reason": decision.drain_boost_reason,
            "reasoning": self._compose_reasoning(
                ctx, decision, house_power, pv_available
            ),
        }
        await self.publish("status", payload)

    def _compose_reasoning(
        self,
        ctx: ChargingContext,
        decision: ChargingDecision,
        house_power: float,
        pv_available: float,
    ) -> str:
        """Compose detailed human-readable reasoning for the current decision."""
        lines: list[str] = []

        lines.append(
            f"Mode: {ctx.mode.value} | Vehicle: {ctx.wallbox.vehicle_state_text}"
        )

        if ctx.departure_passed:
            lines.append(
                "⚠️ Departure time has passed — deadline cleared, PV surplus mode"
            )

        if not ctx.wallbox.vehicle_connected:
            lines.append("→ No vehicle connected, nothing to do.")
            return "\n".join(lines)

        if ctx.ev_soc_pct is not None:
            lines.append(
                f"EV SoC: {ctx.ev_soc_pct:.0f}% → target {ctx.ev_target_soc_pct:.0f}% | "
                f"Energy needed: {ctx.energy_needed_kwh:.1f} kWh"
            )

        grid_dir = "export" if ctx.grid_power_w > 0 else "import"
        bat_dir = "charging" if ctx.battery_power_w > 0 else "discharging"
        lines.append(
            f"Grid: {ctx.grid_power_w:+.0f} W ({grid_dir}) | "
            f"PV: {ctx.pv_power_w:.0f} W | House: {house_power:.0f} W"
        )
        lines.append(
            f"Battery: {ctx.battery_power_w:+.0f} W ({bat_dir}, "
            f"SoC {ctx.battery_soc_pct:.0f}%)"
        )

        if ctx.mode in (ChargeMode.PV_SURPLUS, ChargeMode.SMART):
            lines.append(
                f"PV surplus: {decision.pv_surplus_w:.0f} W "
                f"(grid {ctx.grid_power_w:+.0f} + EV {ctx.wallbox.current_power_w:.0f} "
                f"+ bat {ctx.battery_power_w:+.0f} - reserve {self.settings.grid_reserve_w})"
            )
            if decision.battery_assist_w > 0:
                lines.append(
                    f"Battery assist: +{decision.battery_assist_w:.0f} W — "
                    f"{decision.battery_assist_reason}"
                )
            elif decision.battery_assist_reason:
                lines.append(f"Battery assist: off — {decision.battery_assist_reason}")

        lines.append(f"PV forecast remaining: {ctx.pv_forecast_remaining_kwh:.1f} kWh")
        lines.append(f"PV forecast tomorrow: {ctx.pv_forecast_tomorrow_kwh:.1f} kWh")

        if decision.solar_defer_active:
            lines.append(
                f"Solar defer: ON — waiting for tomorrow's PV "
                f"({decision.solar_defer_pv_kwh:.1f} kWh forecast, "
                f"{decision.solar_defer_needed_kwh:.1f} kWh needed)"
            )

        if ctx.full_by_morning and not ctx.departure_passed:
            lines.append(
                f"Full-by-morning: ON | Target: {ctx.target_energy_kwh:.0f} kWh | "
                f"Charged: {ctx.wallbox.session_energy_kwh:.1f} kWh | "
                f"Remaining: {decision.energy_remaining_kwh:.1f} kWh"
            )
            if decision.deadline_active and decision.deadline_hours_left >= 0:
                dep = ctx.departure_time
                dep_str = f"{dep.hour:02d}:{dep.minute:02d}" if dep else "?"
                lines.append(
                    f"Departure: {dep_str} ({decision.deadline_hours_left:.1f}h left) | "
                    f"Required: {decision.deadline_required_w:.0f} W avg"
                )

        if decision.skip_control:
            lines.append("→ Manual mode: not controlling wallbox")
        elif decision.target_power_w > 0:
            lines.append(f"→ Charging at {decision.target_power_w} W")
        else:
            lines.append("→ Not charging")
        lines.append(f"Reason: {decision.reason}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Orchestrator command handler
    # ------------------------------------------------------------------

    async def _on_orchestrator_command(self, subject: str, payload: dict) -> None:
        """Handle commands from orchestrator (NATS async callback)."""
        command = payload.get("command", "")
        self.logger.info("orchestrator_command", command=command)

        if command == "refresh":
            self._force_cycle.set()
        else:
            self.logger.debug("unknown_command", command=command)

    async def _on_ev_plan_nats(self, subject: str, payload: dict) -> None:
        """Handle energy.ev.plan_updated from NATS."""
        trace_id = payload.get("trace_id", "")
        if trace_id:
            self._current_trace_id = trace_id

        days = payload.get("days", [])
        if days:
            day0 = days[0]
            self._forecast_needed_kwh = float(day0.get("energy_needed_kwh", 0.0))
            current_soc = float(payload.get("current_soc_pct") or 0.0)
            ev_capacity = 77.0
            self._forecast_needed_soc = min(
                100.0, current_soc + (self._forecast_needed_kwh / ev_capacity * 100.0)
            )
            self.logger.info(
                "ev_plan_nats_cached",
                forecast_needed_kwh=round(self._forecast_needed_kwh, 1),
            )

    async def _on_pv_forecast_nats(self, subject: str, payload: dict) -> None:
        """Handle energy.pv.forecast_updated from NATS — extract sunset hour."""
        sunset = payload.get("sunset")
        if sunset and isinstance(sunset, str) and ":" in sunset:
            try:
                parts = sunset.split(":")
                self._sunset_hour = int(parts[0])
                self._sunset_hhmm = sunset[:5]
            except (ValueError, IndexError):
                pass

    async def _on_weekly_plan_nats(self, subject: str, payload: dict) -> None:
        """Handle energy.ev.weekly_plan from NATS — cache for Auto mode multi-day deferral."""
        days = payload.get("days", [])
        if days:
            self._weekly_plan = days
            self.logger.info(
                "weekly_plan_nats_cached",
                days=len(days),
                first_day=days[0].get("date") if days else None,
            )

    async def _on_pv_hourly_forecast_nats(self, subject: str, payload: dict) -> None:
        """Handle energy.pv.hourly_forecast from NATS — cache today + tomorrow slots."""
        today = payload.get("today", [])
        tomorrow = payload.get("tomorrow", [])
        if today:
            self._pv_hourly_forecast = today
        if tomorrow:
            self._pv_hourly_forecast_tomorrow = tomorrow
        self.logger.debug(
            "pv_hourly_forecast_cached",
            today_slots=len(today),
            tomorrow_slots=len(tomorrow),
        )

    async def _on_pv_accuracy_nats(self, subject: str, payload: dict) -> None:
        """Handle energy.pv.accuracy_checked — adjust PV defer confidence."""
        accuracy_pct = float(payload.get("accuracy_pct", 100.0))
        self._pv_accuracy_pct = accuracy_pct
        if self._strategy is None:
            return
        if accuracy_pct < 70.0:
            self._strategy.pv_defer_confidence_factor = 1.95
            self.logger.info(
                "pv_accuracy_low_defer_confidence_raised", accuracy_pct=accuracy_pct
            )
        else:
            self._strategy.pv_defer_confidence_factor = (
                self.settings.pv_defer_confidence_factor
            )
            self.logger.debug(
                "pv_accuracy_ok_defer_confidence_normal", accuracy_pct=accuracy_pct
            )

    # ------------------------------------------------------------------
    # NATS helpers
    # ------------------------------------------------------------------

    async def _nats_publish(self, subject: str, data: dict) -> None:
        """Fire-and-forget NATS publish — never raises."""
        if self.nats and self.nats.connected:
            try:
                await self.nats.publish(subject, data)
            except Exception:
                self.logger.debug("nats_publish_failed", subject=subject)

    # ------------------------------------------------------------------
    # Drain budget calculation
    # ------------------------------------------------------------------

    def _compute_drain_budget(
        self,
        pv_remaining_kwh: float,
        battery_soc_pct: float,
        house_power_w: float,
        battery_capacity_kwh: float,
    ) -> float:
        """Calculate how many kWh we can safely drain from battery.

        Budget = min(available_battery_kwh, pv_net_remaining_kwh)
        Only drain what PV can refill by sunset.
        Safety: floor 10% SoC (hardcoded), minimum budget 0.5 kWh.
        """
        drain_floor_soc = (
            max(self.settings.battery_min_soc_pct, 10.0) + 5.0
        )  # 5% safety margin
        available_kwh = max(
            0.0, (battery_soc_pct - drain_floor_soc) / 100.0 * battery_capacity_kwh
        )

        # Estimate hours until sunset
        now_hour = datetime.now(self.tz).hour
        hours_to_sunset = max(0.5, self._sunset_hour - now_hour)
        house_kwh_remaining = (house_power_w / 1000.0) * hours_to_sunset
        pv_net = max(0.0, pv_remaining_kwh - house_kwh_remaining)

        budget = min(available_kwh, pv_net * 0.85)

        if budget < 0.5:
            return 0.0  # Not worth enabling drain
        return round(budget, 2)

    # ------------------------------------------------------------------
    # InfluxDB analytics writers
    # ------------------------------------------------------------------

    def _write_charging_session_influx(
        self,
        session_kwh: float,
        duration_min: float,
        mode: str,
        battery_assist_kwh: float,
    ) -> None:
        """Write EV charging session to InfluxDB for analytics."""
        try:
            self.influx.write_point(
                bucket="ev_analytics",
                measurement="ev_charging_session",
                fields={
                    "energy_kwh": round(session_kwh, 3),
                    "duration_minutes": round(duration_min, 1),
                    "battery_assist_kwh": round(battery_assist_kwh, 3),
                    "pv_kwh": 0.0,  # TODO: track
                    "grid_kwh": round(session_kwh, 3),
                    "cost_estimate": round(
                        session_kwh * self.settings.grid_price_ct / 100, 2
                    ),
                },
                tags={"mode": mode},
            )
        except Exception:
            self.logger.debug("influx_session_write_failed")

    def _write_drain_session_influx(
        self,
        kwh_drained: float,
        battery_soc_start: float,
        battery_soc_end: float,
        duration_minutes: float,
    ) -> None:
        """Write EV drain session to InfluxDB."""
        try:
            self.influx.write_point(
                bucket=self.settings.influxdb_bucket,
                measurement="ev_drain_session",
                fields={
                    "kwh_drained": round(kwh_drained, 3),
                    "battery_soc_start_pct": round(battery_soc_start, 1),
                    "battery_soc_end_pct": round(battery_soc_end, 1),
                    "duration_minutes": round(duration_minutes, 1),
                },
                tags={"service": "smart-ev-charging"},
            )
        except Exception:
            self.logger.debug("influx_drain_session_write_failed")

    def _write_control_decision_influx(
        self,
        target_power_w: float,
        actual_power_w: float,
        mode: str,
        reason_code: str,
    ) -> None:
        """Write control decision to InfluxDB (every ~5 min)."""
        try:
            self.influx.write_point(
                bucket="ev_analytics",
                measurement="ev_control_decision",
                fields={
                    "target_power_w": round(target_power_w, 0),
                    "actual_power_w": round(actual_power_w, 0),
                },
                tags={"mode": mode, "reason_code": reason_code[:50]},
            )
        except Exception:
            self.logger.debug("influx_decision_write_failed")

    # ------------------------------------------------------------------
    # NATS HA auto-discovery (bridge forwards to MQTT for HA)
    # ------------------------------------------------------------------

    async def _publish_ha_discovery(
        self, component: str, object_id: str, config: dict, node_id: str = ""
    ) -> None:
        """Publish HA auto-discovery config via NATS."""
        if not self.nats.connected:
            return
        if "unique_id" not in config:
            config["unique_id"] = f"{node_id}_{object_id}" if node_id else object_id
        if node_id:
            subject = f"ha.discovery.{component}.{node_id}.{object_id}.config"
        else:
            subject = f"ha.discovery.{component}.{object_id}.config"
        await self.nats.publish(subject, config)

    async def _register_ha_discovery(self) -> None:
        """Register entities in HA under the 'Smart EV Charging' device."""
        device = {
            "identifiers": ["homelab_smart_ev_charging"],
            "name": "Smart EV Charging",
            "manufacturer": "Homelab",
            "model": "smart-ev-charging",
        }
        node = "smart_ev_charging"
        status_topic = f"homelab/{self.name}/status"
        heartbeat_topic = f"homelab/{self.name}/heartbeat"

        # --- Connectivity & uptime ---
        await self._publish_ha_discovery(
            "binary_sensor",
            "service_status",
            node_id=node,
            config={
                "name": "Service Status",
                "device": device,
                "state_topic": heartbeat_topic,
                "value_template": (
                    "{{ 'ON' if value_json.status == 'online' else 'OFF' }}"
                ),
                "device_class": "connectivity",
                "expire_after": 180,
            },
        )

        # --- Core charging sensors ---
        await self._publish_ha_discovery(
            "sensor",
            "charge_mode",
            node_id=node,
            config={
                "name": "Charge Mode",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.mode }}",
                "icon": "mdi:ev-station",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "target_power",
            node_id=node,
            config={
                "name": "Target Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.target_power_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:flash",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "actual_power",
            node_id=node,
            config={
                "name": "Actual Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.actual_power_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "session_energy",
            node_id=node,
            config={
                "name": "Session Energy",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.session_energy_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-charging",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "pv_available",
            node_id=node,
            config={
                "name": "PV Available for EV",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.pv_available_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:solar-power",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "status_reason",
            node_id=node,
            config={
                "name": "Status",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.reason[:250] }}",
                "icon": "mdi:information-outline",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "battery_power",
            node_id=node,
            config={
                "name": "Home Battery Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.battery_power_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:home-battery",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "battery_soc",
            node_id=node,
            config={
                "name": "Home Battery SoC",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.battery_soc_pct }}",
                "unit_of_measurement": "%",
                "device_class": "battery",
                "state_class": "measurement",
                "icon": "mdi:battery-medium",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "house_power",
            node_id=node,
            config={
                "name": "House Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.house_power_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:home-lightning-bolt",
            },
        )

        # --- EV SoC sensors ---

        await self._publish_ha_discovery(
            "sensor",
            "ev_soc",
            node_id=node,
            config={
                "name": "EV SoC",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ value_json.ev_soc_pct "
                    "if value_json.ev_soc_pct is not none "
                    "else 'unknown' }}"
                ),
                "unit_of_measurement": "%",
                "device_class": "battery",
                "state_class": "measurement",
                "icon": "mdi:car-battery",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "energy_needed",
            node_id=node,
            config={
                "name": "Energy Needed",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.energy_needed_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-charging-outline",
            },
        )

        # --- Enhanced decision context sensors ---

        await self._publish_ha_discovery(
            "sensor",
            "pv_surplus",
            node_id=node,
            config={
                "name": "PV Surplus (before assist)",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.pv_surplus_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:solar-power-variant",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "battery_assist",
            node_id=node,
            config={
                "name": "Battery Assist Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.battery_assist_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:battery-arrow-down",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "battery_assist_reason",
            node_id=node,
            config={
                "name": "Battery Assist Reason",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.battery_assist_reason[:250] }}",
                "icon": "mdi:battery-heart-variant",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "pv_power",
            node_id=node,
            config={
                "name": "PV DC Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.pv_power_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:solar-panel-large",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "grid_power",
            node_id=node,
            config={
                "name": "Grid Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.grid_power_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:transmission-tower",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "pv_forecast_remaining",
            node_id=node,
            config={
                "name": "PV Forecast Remaining",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.pv_forecast_remaining_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-power-variant-outline",
            },
        )

        # --- Deadline / Full-by-morning sensors ---

        await self._publish_ha_discovery(
            "binary_sensor",
            "full_by_morning",
            node_id=node,
            config={
                "name": "Full by Morning",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ 'ON' if value_json.full_by_morning else 'OFF' }}"
                ),
                "icon": "mdi:clock-alert-outline",
            },
        )

        await self._publish_ha_discovery(
            "binary_sensor",
            "drain_pv_battery",
            node_id=node,
            config={
                "name": "Drain PV Battery",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ 'ON' if value_json.drain_pv_battery else 'OFF' }}"
                ),
                "icon": "mdi:battery-arrow-down",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "drain_boost_w",
            node_id=node,
            config={
                "name": "Drain Battery Boost",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.drain_boost_w | default(0) }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
                "icon": "mdi:battery-arrow-down-outline",
            },
        )

        await self._publish_ha_discovery(
            "binary_sensor",
            "vehicle_connected",
            node_id=node,
            config={
                "name": "Vehicle Connected",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ 'ON' if value_json.vehicle_connected else 'OFF' }}"
                ),
                "device_class": "plug",
                "icon": "mdi:car-electric-outline",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "energy_remaining",
            node_id=node,
            config={
                "name": "Energy Remaining to Target",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.energy_remaining_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-alert-variant-outline",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "target_energy",
            node_id=node,
            config={
                "name": "Target Energy",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.target_energy_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:bullseye-arrow",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "deadline_hours_left",
            node_id=node,
            config={
                "name": "Deadline Hours Left",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.deadline_hours_left }}",
                "unit_of_measurement": "h",
                "icon": "mdi:timer-sand",
                "entity_category": "diagnostic",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "deadline_required_power",
            node_id=node,
            config={
                "name": "Deadline Required Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.deadline_required_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "icon": "mdi:speedometer",
                "entity_category": "diagnostic",
            },
        )

        # --- Feature #5: kWh remaining & estimated completion ---

        await self._publish_ha_discovery(
            "sensor",
            "kwh_remaining",
            node_id=node,
            config={
                "name": "kWh Remaining",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.kwh_remaining }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-charging",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "estimated_completion_time",
            node_id=node,
            config={
                "name": "Estimated Completion",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ value_json.estimated_completion_time "
                    "if value_json.estimated_completion_time "
                    "else 'unknown' }}"
                ),
                "icon": "mdi:clock-check-outline",
            },
        )

        # --- Departure passed sensor ---

        await self._publish_ha_discovery(
            "binary_sensor",
            "departure_passed",
            node_id=node,
            config={
                "name": "Departure Passed",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ 'ON' if value_json.departure_passed else 'OFF' }}"
                ),
                "icon": "mdi:car-clock",
                "entity_category": "diagnostic",
            },
        )

        # --- Phase 2: Solar defer sensors ---

        await self._publish_ha_discovery(
            "binary_sensor",
            "solar_defer",
            node_id=node,
            config={
                "name": "Solar Defer Active",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ 'ON' if value_json.solar_defer_active else 'OFF' }}"
                ),
                "icon": "mdi:weather-sunny-off",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "solar_defer_pv_kwh",
            node_id=node,
            config={
                "name": "Solar Defer PV Forecast",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.solar_defer_pv_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:solar-power",
                "entity_category": "diagnostic",
            },
        )

        # --- Decision reasoning ---

        await self._publish_ha_discovery(
            "sensor",
            "decision_reasoning",
            node_id=node,
            config={
                "name": "Decision Reasoning",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.reason[:250] }}",
                "json_attributes_topic": status_topic,
                "json_attributes_template": (
                    '{{ {"full_reasoning": value_json.reasoning, '
                    '"mode": value_json.mode, '
                    '"pv_surplus_w": value_json.pv_surplus_w, '
                    '"battery_assist_w": value_json.battery_assist_w, '
                    '"battery_assist_reason": value_json.battery_assist_reason, '
                    '"deadline_active": value_json.deadline_active, '
                    '"deadline_hours_left": value_json.deadline_hours_left, '
                    '"deadline_required_w": value_json.deadline_required_w, '
                    '"energy_remaining_kwh": value_json.energy_remaining_kwh, '
                    '"departure_passed": value_json.departure_passed, '
                    '"kwh_remaining": value_json.kwh_remaining, '
                    '"estimated_completion_time": value_json.estimated_completion_time, '
                    '"solar_defer_active": value_json.solar_defer_active, '
                    '"solar_defer_pv_kwh": value_json.solar_defer_pv_kwh, '
                    '"solar_defer_needed_kwh": value_json.solar_defer_needed_kwh} | tojson }}'
                ),
                "icon": "mdi:head-cog-outline",
            },
        )

        # --- Watchdog sensor ---

        await self._publish_ha_discovery(
            "binary_sensor",
            "watchdog_status",
            node_id=node,
            config={
                "name": "Watchdog Status",
                "device": device,
                "state_topic": f"homelab/{self.name}/watchdog",
                "value_template": (
                    "{{ 'ON' if value_json.status == 'frozen' else 'OFF' }}"
                ),
                "device_class": "problem",
                "icon": "mdi:alert-circle-outline",
                "expire_after": 600,
            },
        )

        # --- R1: Forecast sensors (read-only, from ev-forecast planner) ---
        forecast_topic = f"homelab/{self.name}/forecast"

        await self._publish_ha_discovery(
            "sensor",
            "ev_forecast_needed_kwh",
            node_id=node,
            config={
                "name": "EV Forecast Needed kWh",
                "device": device,
                "state_topic": forecast_topic,
                "value_template": "{{ value_json.ev_forecast_needed_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-charging-outline",
            },
        )

        await self._publish_ha_discovery(
            "sensor",
            "ev_forecast_needed_soc",
            node_id=node,
            config={
                "name": "EV Forecast Needed SoC",
                "device": device,
                "state_topic": forecast_topic,
                "value_template": "{{ value_json.ev_forecast_needed_soc }}",
                "unit_of_measurement": "%",
                "device_class": "battery",
                "icon": "mdi:battery-charging",
            },
        )

        # --- R4: kWh to charge left sensor ---
        await self._publish_ha_discovery(
            "sensor",
            "ev_kwh_to_charge_left",
            node_id=node,
            config={
                "name": "EV kWh to Charge Left",
                "device": device,
                "state_topic": forecast_topic,
                "value_template": "{{ value_json.ev_kwh_to_charge_left }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-alert-variant-outline",
            },
        )

        # --- Drain mode status sensors ---
        drain_state_topic = "homelab/smart-ev-charging/drain-status"

        await self._publish_ha_discovery(
            "binary_sensor",
            "drain_mode_active",
            node_id=node,
            config={
                "name": "EV Drain PV Battery Active",
                "device": device,
                "state_topic": drain_state_topic,
                "value_template": "{{ 'ON' if value_json.drain_mode_active else 'OFF' }}",
                "payload_on": "ON",
                "payload_off": "OFF",
                "icon": "mdi:battery-arrow-down",
            },
        )
        await self._publish_ha_discovery(
            "sensor",
            "drain_budget_kwh",
            node_id=node,
            config={
                "name": "EV Drain Budget",
                "device": device,
                "state_topic": drain_state_topic,
                "value_template": "{{ value_json.drain_budget_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-arrow-down-outline",
            },
        )
        await self._publish_ha_discovery(
            "sensor",
            "drain_used_kwh",
            node_id=node,
            config={
                "name": "EV Drain Used",
                "device": device,
                "state_topic": drain_state_topic,
                "value_template": "{{ value_json.drain_used_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-minus",
            },
        )
        await self._publish_ha_discovery(
            "sensor",
            "drain_remaining_kwh",
            node_id=node,
            config={
                "name": "EV Drain Remaining",
                "device": device,
                "state_topic": drain_state_topic,
                "value_template": "{{ value_json.drain_remaining_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-charging-low",
            },
        )
        await self._publish_ha_discovery(
            "sensor",
            "drain_reason",
            node_id=node,
            config={
                "name": "EV Drain Reason",
                "device": device,
                "state_topic": drain_state_topic,
                "value_template": "{{ value_json.drain_reason }}",
                "icon": "mdi:information-outline",
            },
        )
        await self._publish_ha_discovery(
            "sensor",
            "battery_refill_eta",
            node_id=node,
            config={
                "name": "Battery Refill ETA",
                "device": device,
                "state_topic": drain_state_topic,
                "value_template": "{{ value_json.battery_refill_eta }}",
                "icon": "mdi:battery-clock",
            },
        )

        self.logger.info("ha_discovery_registered", entity_count=38)

    # ------------------------------------------------------------------
    # Healthcheck
    # ------------------------------------------------------------------

    def _touch_healthcheck(self) -> None:
        try:
            HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
            HEALTHCHECK_FILE.write_text(str(time.time()))
        except OSError:
            pass


if __name__ == "__main__":
    import asyncio

    asyncio.run(SmartEVChargingService().start())
