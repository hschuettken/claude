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
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

from shared.service import BaseService

from charger import WallboxController
from config import EVChargingSettings
from strategy import ChargeMode, ChargingContext, ChargingDecision, ChargingStrategy

HEALTHCHECK_FILE = Path("/app/data/healthcheck")


class SmartEVChargingService(BaseService):
    name = "smart-ev-charging"

    def __init__(self) -> None:
        super().__init__(settings=EVChargingSettings())
        self.settings: EVChargingSettings  # narrow type for IDE
        self.tz = ZoneInfo(self.settings.timezone)
        self._current_trace_id: str = ""
        # Track overnight grid charging (reset at 22:00 when new overnight session starts)
        self._overnight_grid_kwh_start: float = 0.0
        self._overnight_session_active: bool = False

    async def run(self) -> None:
        self.mqtt.connect_background()
        self._register_ha_discovery()

        # Subscribe to orchestrator commands
        self._force_cycle = asyncio.Event()
        self.mqtt.subscribe(
            "homelab/orchestrator/command/smart-ev-charging",
            self._on_orchestrator_command,
        )

        # Subscribe to ev-forecast plan for cross-service correlation
        self.mqtt.subscribe(
            "homelab/ev-forecast/plan",
            self._on_ev_forecast_plan,
        )

        charger = WallboxController(
            ha=self.ha,
            vehicle_state_entity=self.settings.wallbox_vehicle_state_entity,
            power_entity=self.settings.wallbox_power_entity,
            energy_session_entity=self.settings.wallbox_energy_session_entity,
            hems_power_number=self.settings.wallbox_hems_power_number,
        )

        strategy = ChargingStrategy(
            max_power_w=self.settings.wallbox_max_power_w,
            min_power_w=self.settings.wallbox_min_power_w,
            eco_power_w=self.settings.eco_charge_power_w,
            grid_reserve_w=self.settings.grid_reserve_w,
            start_hysteresis_w=self.settings.surplus_start_hysteresis_w,
            ramp_step_w=self.settings.ramp_step_w,
            battery_min_soc_pct=self.settings.battery_min_soc_pct,
            battery_ev_assist_max_w=self.settings.battery_ev_assist_max_w,
            battery_capacity_kwh=self.settings.battery_capacity_kwh,
            battery_target_eod_soc_pct=self.settings.battery_target_eod_soc_pct,
            pv_forecast_good_kwh=self.settings.pv_forecast_good_kwh,
            pv_morning_fraction=self.settings.pv_morning_fraction,
            charger_efficiency=self.settings.charger_efficiency,
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

        # Control loop — runs until SIGTERM / SIGINT
        while not self._shutdown_event.is_set():
            try:
                await self._control_cycle(charger, strategy)
            except Exception:
                self.logger.exception("control_cycle_error")
            finally:
                self._touch_healthcheck()

            # Wait for shutdown, force-cycle signal, or normal interval
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
                pass  # normal — interval elapsed

    # ------------------------------------------------------------------
    # Control cycle
    # ------------------------------------------------------------------

    async def _control_cycle(
        self,
        charger: WallboxController,
        strategy: ChargingStrategy,
    ) -> None:
        """Single iteration: read → decide → apply → publish."""

        # 1) Read all inputs from HA
        mode = await self._read_charge_mode()
        wallbox = await charger.read_state()
        grid_power = await self._read_float(self.settings.grid_power_entity)
        pv_power = await self._read_float(self.settings.pv_power_entity)
        full_by_morning = await self._read_bool(self.settings.full_by_morning_entity)
        departure_time = await self._read_time(self.settings.departure_time_entity)
        target_energy = await self._read_float(self.settings.target_energy_entity)

        # Home battery state
        battery_power = await self._read_float(
            self.settings.battery_power_entity,
        )
        battery_soc = await self._read_float(
            self.settings.battery_soc_entity,
        )

        # PV forecast (defaults to 0 if unavailable)
        pv_forecast_remaining = await self._read_float(
            self.settings.pv_forecast_remaining_entity,
        )
        pv_forecast_tomorrow = await self._read_float(
            self.settings.pv_forecast_tomorrow_entity,
        )

        # Household consumption (for monitoring)
        house_power = await self._read_float(self.settings.house_power_entity)

        # EV battery SoC (from car, e.g. Audi Connect) — None if not configured
        ev_soc: float | None = None
        if self.settings.ev_soc_entity:
            ev_soc = await self._read_float_optional(
                self.settings.ev_soc_entity,
            )

        ev_battery_capacity = await self._read_float(
            self.settings.ev_battery_capacity_entity, default=77.0,
        )
        ev_target_soc = await self._read_float(
            self.settings.target_soc_entity, default=80.0,
        )

        # --- Overnight grid charging tracker ---
        now = datetime.now(self.tz)
        current_hour = now.hour
        # Start new overnight session at 22:00
        if current_hour == 22 and not self._overnight_session_active:
            self._overnight_session_active = True
            self._overnight_grid_kwh_start = wallbox.session_energy_kwh
            self.logger.info(
                "overnight_session_started",
                session_energy_at_start=wallbox.session_energy_kwh,
            )
        # End overnight session at 08:00 (PV takes over)
        if current_hour >= 8 and current_hour < 22 and self._overnight_session_active:
            self._overnight_session_active = False
            self.logger.info(
                "overnight_session_ended",
                grid_kwh_charged=wallbox.session_energy_kwh - self._overnight_grid_kwh_start,
            )
        overnight_grid_kwh = 0.0
        if self._overnight_session_active or (5 <= current_hour < 8):
            overnight_grid_kwh = max(
                0.0, wallbox.session_energy_kwh - self._overnight_grid_kwh_start,
            )

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
            full_by_morning=full_by_morning,
            departure_time=departure_time,
            target_energy_kwh=target_energy,
            session_energy_kwh=wallbox.session_energy_kwh,
            ev_soc_pct=ev_soc,
            ev_battery_capacity_kwh=ev_battery_capacity,
            ev_target_soc_pct=ev_target_soc,
            overnight_grid_kwh_charged=overnight_grid_kwh,
            now=now,
        )

        # 2) Decide target power
        decision = strategy.decide(ctx)

        # 3) Apply to wallbox (blocked in safe mode)
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

        # 4) Publish status
        self._publish_status(ctx, decision, house_power)
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
        )

    # ------------------------------------------------------------------
    # HA state readers
    # ------------------------------------------------------------------

    async def _read_charge_mode(self) -> ChargeMode:
        try:
            state = await self.ha.get_state(self.settings.charge_mode_entity)
            return ChargeMode(state.get("state", "Off"))
        except (ValueError, KeyError):
            return ChargeMode.OFF

    async def _read_float(self, entity_id: str, default: float = 0.0) -> float:
        try:
            state = await self.ha.get_state(entity_id)
            val = state.get("state", str(default))
            if val in ("unavailable", "unknown"):
                return default
            return float(val)
        except Exception:
            self.logger.warning("read_float_failed", entity_id=entity_id)
            return default

    async def _read_float_optional(self, entity_id: str) -> float | None:
        """Read a float sensor, returning None if unavailable."""
        try:
            state = await self.ha.get_state(entity_id)
            val = state.get("state", "")
            if val in ("unavailable", "unknown", ""):
                return None
            return float(val)
        except Exception:
            self.logger.warning("read_float_optional_failed", entity_id=entity_id)
            return None

    async def _read_bool(self, entity_id: str) -> bool:
        try:
            state = await self.ha.get_state(entity_id)
            return state.get("state", "off") == "on"
        except Exception:
            return False

    async def _read_time(self, entity_id: str) -> dt_time | None:
        try:
            state = await self.ha.get_state(entity_id)
            val = state.get("state", "")
            if not val or val in ("unavailable", "unknown"):
                return dt_time(7, 0)
            parts = val.split(":")
            return dt_time(int(parts[0]), int(parts[1]))
        except Exception:
            return dt_time(7, 0)

    # ------------------------------------------------------------------
    # MQTT publishing
    # ------------------------------------------------------------------

    def _publish_status(
        self,
        ctx: ChargingContext,
        decision: ChargingDecision,
        house_power: float = 0.0,
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
            "ev_soc_pct": round(ctx.ev_soc_pct, 1) if ctx.ev_soc_pct is not None else None,
            "ev_target_soc_pct": round(ctx.ev_target_soc_pct),
            "pv_forecast_remaining_kwh": round(ctx.pv_forecast_remaining_kwh, 1),
            "pv_forecast_tomorrow_kwh": round(ctx.pv_forecast_tomorrow_kwh, 1),
            "overnight_grid_kwh_charged": round(ctx.overnight_grid_kwh_charged, 1),
            "full_by_morning": ctx.full_by_morning,
            "reason": decision.reason,
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
            "reasoning": self._compose_reasoning(ctx, decision, house_power, pv_available),
        }
        self.publish("status", payload)

    def _compose_reasoning(
        self,
        ctx: ChargingContext,
        decision: ChargingDecision,
        house_power: float,
        pv_available: float,
    ) -> str:
        """Compose detailed human-readable reasoning for the current decision."""
        lines: list[str] = []

        # Mode & vehicle
        lines.append(f"Mode: {ctx.mode.value} | Vehicle: {ctx.wallbox.vehicle_state_text}")

        if not ctx.wallbox.vehicle_connected:
            lines.append("→ No vehicle connected, nothing to do.")
            return "\n".join(lines)

        # EV SoC info
        if ctx.ev_soc_pct is not None:
            lines.append(
                f"EV SoC: {ctx.ev_soc_pct:.0f}% → target {ctx.ev_target_soc_pct:.0f}% | "
                f"Energy needed: {ctx.energy_needed_kwh:.1f} kWh"
            )

        # Energy balance
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

        # PV surplus calculation
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

        # Forecast context
        lines.append(
            f"PV forecast remaining: {ctx.pv_forecast_remaining_kwh:.1f} kWh"
        )

        # Full-by-morning / deadline
        if ctx.full_by_morning:
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

        # Final decision
        if decision.skip_control:
            lines.append("→ Manual mode: not controlling wallbox")
        elif decision.target_power_w > 0:
            lines.append(f"→ Charging at {decision.target_power_w} W")
        else:
            lines.append("→ Not charging")
        lines.append(f"Reason: {decision.reason}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # MQTT auto-discovery
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Orchestrator command handler
    # ------------------------------------------------------------------

    def _on_orchestrator_command(self, topic: str, payload: dict) -> None:
        """Handle commands from the orchestrator service."""
        command = payload.get("command", "")
        self.logger.info("orchestrator_command", command=command)

        if command == "refresh":
            # Trigger an immediate control cycle
            self._force_cycle.set()
        else:
            self.logger.debug("unknown_command", command=command)

    def _on_ev_forecast_plan(self, topic: str, payload: dict) -> None:
        """Capture trace_id from ev-forecast plan for cross-service correlation."""
        trace_id = payload.get("trace_id", "")
        if trace_id:
            self._current_trace_id = trace_id
            self.logger.info("ev_forecast_trace_id_received", trace_id=trace_id)

    # ------------------------------------------------------------------
    # MQTT auto-discovery
    # ------------------------------------------------------------------

    def _register_ha_discovery(self) -> None:
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
        self.mqtt.publish_ha_discovery(
            "binary_sensor", "service_status", node_id=node, config={
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
        self.mqtt.publish_ha_discovery(
            "sensor", "charge_mode", node_id=node, config={
                "name": "Charge Mode",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.mode }}",
                "icon": "mdi:ev-station",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "target_power", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "actual_power", node_id=node, config={
                "name": "Actual Power",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.actual_power_w }}",
                "unit_of_measurement": "W",
                "device_class": "power",
                "state_class": "measurement",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "session_energy", node_id=node, config={
                "name": "Session Energy",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.session_energy_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-charging",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "pv_available", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "status_reason", node_id=node, config={
                "name": "Status",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.reason[:250] }}",
                "icon": "mdi:information-outline",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "battery_power", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "battery_soc", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "house_power", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "ev_soc", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "energy_needed", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "pv_surplus", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "battery_assist", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "battery_assist_reason", node_id=node, config={
                "name": "Battery Assist Reason",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.battery_assist_reason[:250] }}",
                "icon": "mdi:battery-heart-variant",
                "entity_category": "diagnostic",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "pv_power", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "grid_power", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "pv_forecast_remaining", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "binary_sensor", "full_by_morning", node_id=node, config={
                "name": "Full by Morning",
                "device": device,
                "state_topic": status_topic,
                "value_template": (
                    "{{ 'ON' if value_json.full_by_morning else 'OFF' }}"
                ),
                "icon": "mdi:clock-alert-outline",
            },
        )

        self.mqtt.publish_ha_discovery(
            "binary_sensor", "vehicle_connected", node_id=node, config={
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

        self.mqtt.publish_ha_discovery(
            "sensor", "energy_remaining", node_id=node, config={
                "name": "Energy Remaining to Target",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.energy_remaining_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:battery-alert-variant-outline",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "target_energy", node_id=node, config={
                "name": "Target Energy",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.target_energy_kwh }}",
                "unit_of_measurement": "kWh",
                "device_class": "energy",
                "icon": "mdi:bullseye-arrow",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "deadline_hours_left", node_id=node, config={
                "name": "Deadline Hours Left",
                "device": device,
                "state_topic": status_topic,
                "value_template": "{{ value_json.deadline_hours_left }}",
                "unit_of_measurement": "h",
                "icon": "mdi:timer-sand",
                "entity_category": "diagnostic",
            },
        )

        self.mqtt.publish_ha_discovery(
            "sensor", "deadline_required_power", node_id=node, config={
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

        # --- Decision reasoning (the key sensor for understanding decisions) ---

        self.mqtt.publish_ha_discovery(
            "sensor", "decision_reasoning", node_id=node, config={
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
                    '"energy_remaining_kwh": value_json.energy_remaining_kwh} | tojson }}'
                ),
                "icon": "mdi:head-cog-outline",
            },
        )

        self.logger.info("ha_discovery_registered", entity_count=24)

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
