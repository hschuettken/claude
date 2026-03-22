"""Supplemental heat controller for PV surplus heater control.

Detects PV surplus (solar.current_power - household_load > threshold) and
controls IR heaters via Home Assistant when surplus is available.

Features:
  - Monitors PV surplus vs household load
  - Activates IR heaters when surplus > min_surplus_kw for min_duration_min
  - Deactivates when surplus drops below off_threshold_kw or daily max hours exceeded
  - Logs all events to InfluxDB
  - Configurable via SupplementalHeatConfig

Typical use:
    config = SupplementalHeatConfig(
        min_surplus_kw=3.0,
        off_threshold_kw=1.5,
        min_duration_min=15,
        max_daily_hours=4.0,
    )
    controller = SupplementalHeatController(ha_client, influxdb_api, config)
    await controller.tick(solar_power_w=5500, household_load_w=2000)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger("hems.supplemental_heat")


class HeaterState(str, Enum):
    """Heater operational states."""

    OFF = "off"
    CHARGING = "charging"  # Surplus detected, charging up duration
    ON = "on"  # Active heating
    COOLDOWN = "cooldown"  # Daily limit exceeded, cooling down


@dataclass
class SupplementalHeatConfig:
    """Configuration for supplemental heat controller.

    Attributes:
        min_surplus_kw: Minimum PV surplus to activate heaters (kW). Default 3.0 kW.
        off_threshold_kw: Surplus level below which heaters turn off (kW). Default 1.5 kW.
        min_duration_min: Minimum surplus duration before activation (minutes). Default 15 min.
        max_daily_hours: Maximum daily runtime for heaters (hours). Default 4.0 h.
        entity_names: List of Home Assistant switch entity names for IR heaters.
            Default: ["switch.ir_heater_1", "switch.ir_heater_2"]
        ha_url: Home Assistant URL. Default "http://192.168.0.100:8123"
        ha_token: Home Assistant token (from env or config). Default "" (will use orchestrator).
        use_orchestrator: If True, call orchestrator for HA service calls. Default True.
        orchestrator_url: Orchestrator service URL. Default "http://orchestrator:8100"
    """

    min_surplus_kw: float = 3.0
    off_threshold_kw: float = 1.5
    min_duration_min: float = 15.0
    max_daily_hours: float = 4.0
    entity_names: list[str] = field(
        default_factory=lambda: ["switch.ir_heater_1", "switch.ir_heater_2"]
    )
    ha_url: str = "http://192.168.0.100:8123"
    ha_token: str = ""
    use_orchestrator: bool = True
    orchestrator_url: str = "http://orchestrator:8100"


@dataclass
class HeaterStats:
    """Runtime statistics for a heater session."""

    runtime_s: float = 0.0  # Total seconds on in current session
    daily_runtime_s: float = 0.0  # Total seconds on today
    surplus_on_time_s: float = 0.0  # Time accumulating surplus duration
    daily_reset_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SupplementalHeatController:
    """Controls IR heaters based on PV surplus.

    Attributes:
        config: SupplementalHeatConfig instance
        state: Current HeaterState
        stats: HeaterStats for runtime tracking
        last_tick_time: Timestamp of last tick() call
        is_on: Whether heaters are currently energized
    """

    def __init__(
        self,
        config: SupplementalHeatConfig | None = None,
        ha_client: httpx.AsyncClient | None = None,
        influxdb_write_api: Optional[object] = None,
    ):
        """Initialize supplemental heat controller.

        Args:
            config: SupplementalHeatConfig (if None, uses defaults)
            ha_client: httpx.AsyncClient for direct HA calls (optional if use_orchestrator=True)
            influxdb_write_api: InfluxDB write API (optional, for logging)
        """
        self.config = config or SupplementalHeatConfig()
        self.ha_client = ha_client
        self.influxdb_write_api = influxdb_write_api

        self.state = HeaterState.OFF
        self.stats = HeaterStats()
        self.is_on = False

        logger.info(
            "SupplementalHeatController initialized: min_surplus=%.1f kW, "
            "off_threshold=%.1f kW, min_duration=%.1f min, max_daily=%.1f h, "
            "heaters=%s",
            self.config.min_surplus_kw,
            self.config.off_threshold_kw,
            self.config.min_duration_min,
            self.config.max_daily_hours,
            self.config.entity_names,
        )

    async def tick(
        self,
        solar_power_w: float,
        household_load_w: float,
        dt_s: float = 10.0,
    ) -> dict:
        """Execute one control iteration.

        Args:
            solar_power_w: Current solar generation (watts)
            household_load_w: Current household consumption (watts)
            dt_s: Time delta since last tick (seconds, default 10)

        Returns:
            Dictionary with tick results:
                {
                    "state": "off|charging|on|cooldown",
                    "is_on": bool,
                    "surplus_kw": float,
                    "runtime_s": float,
                    "daily_runtime_s": float,
                    "daily_runtime_h": float,
                    "daily_remaining_h": float,
                    "surplus_on_time_min": float,
                    "daily_limit_exceeded": bool,
                    "log_message": str,
                }
        """
        now = time.monotonic()
        now_utc = datetime.now(timezone.utc)

        # Check for daily reset (midnight UTC)
        if (now_utc.date() != self.stats.daily_reset_time.date()):
            self.stats.daily_runtime_s = 0.0
            self.stats.daily_reset_time = now_utc
            logger.info("Daily runtime reset at midnight UTC")

        # Calculate PV surplus
        surplus_w = solar_power_w - household_load_w
        surplus_kw = surplus_w / 1000.0

        # Use provided dt_s for time advancement (for both testing and real operation)
        # dt_s parameter is the actual time delta since last call
        actual_dt = dt_s

        # Accumulate daily runtime if currently on
        if self.is_on:
            self.stats.runtime_s += actual_dt
            self.stats.daily_runtime_s += actual_dt

        # Calculate daily limit status
        daily_limit_s = self.config.max_daily_hours * 3600.0
        daily_remaining_s = max(0.0, daily_limit_s - self.stats.daily_runtime_s)
        daily_remaining_h = daily_remaining_s / 3600.0
        daily_limit_exceeded = self.stats.daily_runtime_s >= daily_limit_s

        # State machine
        old_state = self.state
        decision = False
        log_msg = ""

        if self.state == HeaterState.OFF:
            # OFF → look for surplus
            if surplus_kw >= self.config.min_surplus_kw:
                # Surplus detected, start charging
                self.state = HeaterState.CHARGING
                self.stats.surplus_on_time_s = 0.0
                logger.info("Surplus %.1f kW detected, entering CHARGING state", surplus_kw)
            decision = False

        elif self.state == HeaterState.CHARGING:
            # CHARGING → accumulate time until min_duration reached
            # Accumulate dt_s into surplus_on_time_s
            self.stats.surplus_on_time_s += actual_dt
            
            if surplus_kw < self.config.min_surplus_kw:
                # Surplus dropped below threshold during charging, back to OFF
                self.state = HeaterState.OFF
                self.stats.surplus_on_time_s = 0.0
                logger.info("Surplus dropped below threshold, returning to OFF")
                decision = False
            elif self.stats.surplus_on_time_s >= self.config.min_duration_min * 60.0:
                # Min duration reached, transition to ON
                if not daily_limit_exceeded:
                    self.state = HeaterState.ON
                    self.stats.runtime_s = 0.0  # Reset session runtime
                    logger.info(
                        "Min surplus duration (%.0f min) reached, turning ON heaters",
                        self.config.min_duration_min,
                    )
                    decision = True
                else:
                    # Daily limit already exceeded, go to COOLDOWN
                    self.state = HeaterState.COOLDOWN
                    logger.info("Daily limit exceeded, entering COOLDOWN")
                    decision = False
            else:
                # Still charging
                decision = False

        elif self.state == HeaterState.ON:
            # ON → check for shutdown conditions
            if daily_limit_exceeded:
                # Daily limit reached, must stop
                self.state = HeaterState.COOLDOWN
                logger.info("Daily max hours (%.1f h) reached, entering COOLDOWN", self.config.max_daily_hours)
                decision = False
            elif surplus_kw < self.config.off_threshold_kw:
                # Surplus dropped below OFF threshold
                self.state = HeaterState.OFF
                logger.info("Surplus dropped to %.1f kW (threshold %.1f kW), turning OFF", surplus_kw, self.config.off_threshold_kw)
                decision = False
            else:
                # Continue heating
                decision = True

        elif self.state == HeaterState.COOLDOWN:
            # COOLDOWN → wait until next day or surplus drops
            if not daily_limit_exceeded:
                # Daily limit reset (new day)
                self.state = HeaterState.OFF
                logger.info("Daily reset complete, returning to OFF")
                decision = False
            else:
                decision = False

        # Perform HA service call if decision changed
        if decision != self.is_on:
            try:
                if decision:
                    await self._turn_on_heaters()
                    log_msg = f"Turned ON heaters (surplus {surplus_kw:.1f} kW, session {self.stats.runtime_s:.0f}s)"
                else:
                    await self._turn_off_heaters()
                    log_msg = f"Turned OFF heaters (surplus {surplus_kw:.1f} kW)"
                self.is_on = decision
            except Exception as e:
                logger.error("Failed to control heaters: %s", e)
                log_msg = f"ERROR: Failed to control heaters: {e}"

        # Log to InfluxDB if available
        if self.influxdb_write_api:
            try:
                self._write_to_influxdb(
                    surplus_kw=surplus_kw,
                    state=self.state.value,
                    is_on=self.is_on,
                    daily_runtime_h=self.stats.daily_runtime_s / 3600.0,
                )
            except Exception as e:
                logger.warning("Failed to write to InfluxDB: %s", e)

        daily_runtime_h = self.stats.daily_runtime_s / 3600.0

        result = {
            "state": self.state.value,
            "is_on": self.is_on,
            "surplus_kw": surplus_kw,
            "runtime_s": self.stats.runtime_s,
            "daily_runtime_s": self.stats.daily_runtime_s,
            "daily_runtime_h": daily_runtime_h,
            "daily_remaining_h": daily_remaining_h,
            "surplus_on_time_min": self.stats.surplus_on_time_s / 60.0 if self.stats.surplus_on_time_s > 0 else 0.0,
            "daily_limit_exceeded": daily_limit_exceeded,
            "log_message": log_msg or f"State={self.state.value}, surplus={surplus_kw:.1f} kW, daily={daily_runtime_h:.2f}h",
        }

        if old_state != self.state:
            logger.info(
                "State transition: %s → %s (surplus=%.1f kW, daily=%.2f h)",
                old_state.value,
                self.state.value,
                surplus_kw,
                daily_runtime_h,
            )

        return result

    async def _turn_on_heaters(self) -> None:
        """Turn on all configured IR heater switches via Home Assistant."""
        if self.config.use_orchestrator:
            await self._turn_on_via_orchestrator()
        else:
            await self._turn_on_via_ha_client()

    async def _turn_off_heaters(self) -> None:
        """Turn off all configured IR heater switches via Home Assistant."""
        if self.config.use_orchestrator:
            await self._turn_off_via_orchestrator()
        else:
            await self._turn_off_via_ha_client()

    async def _turn_on_via_orchestrator(self) -> None:
        """Turn on heaters via orchestrator tool."""
        for entity_id in self.config.entity_names:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        f"{self.config.orchestrator_url}/tools/execute",
                        json={
                            "tool": "call_ha_service",
                            "params": {
                                "domain": "switch",
                                "service": "turn_on",
                                "data": {"entity_id": entity_id},
                            },
                        },
                    )
                    if response.status_code != 200:
                        logger.warning(
                            "Orchestrator returned %d for turn_on %s",
                            response.status_code,
                            entity_id,
                        )
                    else:
                        logger.info("Turned ON %s via orchestrator", entity_id)
            except Exception as e:
                logger.error("Failed to turn on %s via orchestrator: %s", entity_id, e)
                raise

    async def _turn_off_via_orchestrator(self) -> None:
        """Turn off heaters via orchestrator tool."""
        for entity_id in self.config.entity_names:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        f"{self.config.orchestrator_url}/tools/execute",
                        json={
                            "tool": "call_ha_service",
                            "params": {
                                "domain": "switch",
                                "service": "turn_off",
                                "data": {"entity_id": entity_id},
                            },
                        },
                    )
                    if response.status_code != 200:
                        logger.warning(
                            "Orchestrator returned %d for turn_off %s",
                            response.status_code,
                            entity_id,
                        )
                    else:
                        logger.info("Turned OFF %s via orchestrator", entity_id)
            except Exception as e:
                logger.error("Failed to turn off %s via orchestrator: %s", entity_id, e)
                raise

    async def _turn_on_via_ha_client(self) -> None:
        """Turn on heaters via direct HA REST client."""
        if not self.ha_client:
            raise RuntimeError("HA client not configured")
        
        for entity_id in self.config.entity_names:
            try:
                await self.ha_client.post(
                    f"/services/switch/turn_on",
                    json={"entity_id": entity_id},
                )
                logger.info("Turned ON %s via HA REST", entity_id)
            except Exception as e:
                logger.error("Failed to turn on %s via HA REST: %s", entity_id, e)
                raise

    async def _turn_off_via_ha_client(self) -> None:
        """Turn off heaters via direct HA REST client."""
        if not self.ha_client:
            raise RuntimeError("HA client not configured")
        
        for entity_id in self.config.entity_names:
            try:
                await self.ha_client.post(
                    f"/services/switch/turn_off",
                    json={"entity_id": entity_id},
                )
                logger.info("Turned OFF %s via HA REST", entity_id)
            except Exception as e:
                logger.error("Failed to turn off %s via HA REST: %s", entity_id, e)
                raise

    def _write_to_influxdb(
        self,
        surplus_kw: float,
        state: str,
        is_on: bool,
        daily_runtime_h: float,
    ) -> None:
        """Write supplemental heater metrics to InfluxDB."""
        try:
            from influxdb_client import Point

            point = Point("supplemental_heat_controller")
            point.tag("state", state)
            point.field("surplus_kw", surplus_kw)
            point.field("is_on", is_on)
            point.field("daily_runtime_h", daily_runtime_h)
            point.field("surplus_on_time_min", self.stats.surplus_on_time_s / 60.0)
            point.field("session_runtime_s", self.stats.runtime_s)

            self.influxdb_write_api.write(
                bucket="hems",
                org="homelab",
                record=point,
            )
            logger.debug("Wrote supplemental_heat metrics to InfluxDB")
        except Exception as e:
            logger.warning("Failed to write to InfluxDB: %s", e)

    def get_status(self) -> dict:
        """Get current status summary."""
        daily_limit_s = self.config.max_daily_hours * 3600.0
        daily_remaining_s = max(0.0, daily_limit_s - self.stats.daily_runtime_s)

        return {
            "state": self.state.value,
            "is_on": self.is_on,
            "runtime_s": self.stats.runtime_s,
            "daily_runtime_s": self.stats.daily_runtime_s,
            "daily_runtime_h": self.stats.daily_runtime_s / 3600.0,
            "daily_remaining_h": daily_remaining_s / 3600.0,
            "daily_max_h": self.config.max_daily_hours,
            "surplus_on_time_min": self.stats.surplus_on_time_s / 60.0 if self.stats.surplus_on_time_s else 0.0,
            "config": {
                "min_surplus_kw": self.config.min_surplus_kw,
                "off_threshold_kw": self.config.off_threshold_kw,
                "min_duration_min": self.config.min_duration_min,
                "max_daily_hours": self.config.max_daily_hours,
                "entity_names": self.config.entity_names,
            },
        }
