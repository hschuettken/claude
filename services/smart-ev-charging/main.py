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

    async def run(self) -> None:
        self.mqtt.connect_background()
        self._register_ha_discovery()

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
        )

        self.logger.info(
            "service_ready",
            control_interval=self.settings.control_interval_seconds,
            max_power=self.settings.wallbox_max_power_w,
            min_power=self.settings.wallbox_min_power_w,
            eco_power=self.settings.eco_charge_power_w,
        )

        # Control loop — runs until SIGTERM / SIGINT
        while not self._shutdown_event.is_set():
            try:
                await self._control_cycle(charger, strategy)
            except Exception:
                self.logger.exception("control_cycle_error")

            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.settings.control_interval_seconds,
                )
                break
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
        pv_power = (
            await self._read_float(self.settings.pv_east_power_entity)
            + await self._read_float(self.settings.pv_west_power_entity)
        )
        full_by_morning = await self._read_bool(self.settings.full_by_morning_entity)
        departure_time = await self._read_time(self.settings.departure_time_entity)
        target_energy = await self._read_float(self.settings.target_energy_entity)

        # Optional: home battery state (for monitoring, not control)
        battery_power = await self._read_float_optional(
            self.settings.battery_power_entity
        )
        battery_soc = await self._read_float_optional(
            self.settings.battery_soc_entity
        )

        ctx = ChargingContext(
            mode=mode,
            wallbox=wallbox,
            grid_power_w=grid_power,
            pv_power_w=pv_power,
            full_by_morning=full_by_morning,
            departure_time=departure_time,
            target_energy_kwh=target_energy,
            session_energy_kwh=wallbox.session_energy_kwh,
            now=datetime.now(self.tz),
        )

        # 2) Decide target power
        decision = strategy.decide(ctx)

        # 3) Apply to wallbox
        if not decision.skip_control:
            await charger.set_power_limit(decision.target_power_w)

        # 4) Publish status
        self._publish_status(ctx, decision, battery_power, battery_soc)
        self._touch_healthcheck()

        self.logger.info(
            "cycle",
            mode=mode.value,
            vehicle=wallbox.vehicle_state_text,
            grid_w=round(grid_power),
            pv_w=round(pv_power),
            ev_w=round(wallbox.current_power_w),
            bat_w=round(battery_power) if battery_power is not None else None,
            bat_soc=round(battery_soc) if battery_soc is not None else None,
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
        """Read a float sensor, returning None if the entity is not configured."""
        if not entity_id:
            return None
        try:
            state = await self.ha.get_state(entity_id)
            val = state.get("state", "")
            if val in ("unavailable", "unknown", ""):
                return None
            return float(val)
        except Exception:
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
        battery_power: float | None = None,
        battery_soc: float | None = None,
    ) -> None:
        pv_available = max(
            0,
            ctx.wallbox.current_power_w
            - ctx.grid_power_w
            - self.settings.grid_reserve_w,
        )
        payload: dict = {
            "mode": ctx.mode.value,
            "vehicle": ctx.wallbox.vehicle_state_text,
            "vehicle_connected": ctx.wallbox.vehicle_connected,
            "target_power_w": decision.target_power_w,
            "actual_power_w": round(ctx.wallbox.current_power_w),
            "session_energy_kwh": round(ctx.wallbox.session_energy_kwh, 2),
            "grid_power_w": round(ctx.grid_power_w),
            "pv_power_w": round(ctx.pv_power_w),
            "pv_available_w": round(pv_available),
            "full_by_morning": ctx.full_by_morning,
            "reason": decision.reason,
        }
        if battery_power is not None:
            payload["battery_power_w"] = round(battery_power)
        if battery_soc is not None:
            payload["battery_soc_pct"] = round(battery_soc, 1)
        self.publish("status", payload)

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

        self.mqtt.publish_ha_discovery(
            "binary_sensor", "service_status", node_id=node, config={
                "name": "Service Status",
                "device": device,
                "state_topic": f"homelab/{self.name}/heartbeat",
                "value_template": (
                    "{{ 'ON' if value_json.status == 'online' else 'OFF' }}"
                ),
                "device_class": "connectivity",
                "expire_after": 180,
            },
        )

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

        entity_count = 7

        # Optional battery sensors (only if entity IDs are configured)
        if self.settings.battery_power_entity:
            self.mqtt.publish_ha_discovery(
                "sensor", "battery_power", node_id=node, config={
                    "name": "Home Battery Power",
                    "device": device,
                    "state_topic": status_topic,
                    "value_template": (
                        "{{ value_json.battery_power_w | default(0) }}"
                    ),
                    "unit_of_measurement": "W",
                    "device_class": "power",
                    "state_class": "measurement",
                    "icon": "mdi:home-battery",
                },
            )
            entity_count += 1

        if self.settings.battery_soc_entity:
            self.mqtt.publish_ha_discovery(
                "sensor", "battery_soc", node_id=node, config={
                    "name": "Home Battery SoC",
                    "device": device,
                    "state_topic": status_topic,
                    "value_template": (
                        "{{ value_json.battery_soc_pct | default(0) }}"
                    ),
                    "unit_of_measurement": "%",
                    "device_class": "battery",
                    "state_class": "measurement",
                    "icon": "mdi:battery-medium",
                },
            )
            entity_count += 1

        self.logger.info("ha_discovery_registered", entity_count=entity_count)

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
