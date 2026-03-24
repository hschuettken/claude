"""PV Budget Allocator — Surplus cascade distribution to devices.

Implements Phase 3.2 priority-based power allocation across battery charging,
DHW heating, space heating, supplemental heaters, and EV charging.

Features:
  - PRIORITY_ORDER cascade: battery charging → DHW heating → space heating → 
    supplemental heaters → EV charging
  - Algorithm: allocate available PV surplus sequentially to each tier until
    exhausted or device max capacity reached
  - Database recording: `hems.pv_allocation` table tracks allocations + timestamps
  - Home Assistant integration: calls service to adjust device power setpoints
  - Configurable device registry with per-device max_power_kw, priority tier
  - Execution tracking: time, surplus, allocation result

Typical use:
    allocator = PVAllocator(
        ha_client=ha_client,
        database=hems_db,
        influxdb_api=influxdb_write_api,
        config=config,
    )
    allocation = await allocator.allocate(
        surplus_available_kw=4.5,
        devices=[
            {"device_id": "battery", "priority": 1, "max_power_kw": 5.0, "current_power_kw": 2.0},
            {"device_id": "dhw_heating", "priority": 2, "max_power_kw": 3.0, "current_power_kw": 0.0},
            ...
        ],
        battery_soc_pct=65.0,
    )
    print(allocation)  # {'battery': 2.5, 'dhw_heating': 2.0, ...}
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import httpx

logger = logging.getLogger("hems.pv_allocator")


class DevicePriority(int, Enum):
    """Priority tiers for PV allocation (lower = higher priority)."""

    BATTERY_CHARGING = 1
    DHW_HEATING = 2
    SPACE_HEATING = 3
    SUPPLEMENTAL_HEATERS = 4
    EV_CHARGING = 5


# Global priority order for cascade allocation
PRIORITY_ORDER = [
    DevicePriority.BATTERY_CHARGING,
    DevicePriority.DHW_HEATING,
    DevicePriority.SPACE_HEATING,
    DevicePriority.SUPPLEMENTAL_HEATERS,
    DevicePriority.EV_CHARGING,
]


@dataclass
class Device:
    """A device eligible for PV surplus allocation.

    Attributes:
        device_id: Unique identifier (e.g., "battery", "dhw_heating", "ev_charger")
        priority: Priority tier (DevicePriority enum)
        max_power_kw: Maximum power this device can accept (kW)
        current_power_kw: Current allocated power (optional, for reporting)
        state: Current state ("ready", "charging", "full", "unavailable", etc.)
        entity_id: Home Assistant entity to command (optional, e.g., "switch.dhw_charger")
    """

    device_id: str
    priority: DevicePriority
    max_power_kw: float
    current_power_kw: float = 0.0
    state: str = "ready"
    entity_id: Optional[str] = None

    def allocatable_capacity_kw(self) -> float:
        """Remaining capacity available for allocation (kW)."""
        return max(0.0, self.max_power_kw - self.current_power_kw)


@dataclass
class AllocationResult:
    """Result of a single allocation cycle.

    Attributes:
        allocation_dict: {device_id: allocated_kW}
        total_allocated_kw: Sum of all allocations
        remaining_surplus_kw: Surplus that could not be allocated
        battery_soc_pct: Battery SoC at time of allocation
        timestamp: When allocation was computed
        duration_ms: Time taken to compute allocation
        num_devices: Number of devices evaluated
        errors: List of device IDs that failed allocation
    """

    allocation_dict: dict[str, float]
    total_allocated_kw: float
    remaining_surplus_kw: float
    battery_soc_pct: Optional[float]
    timestamp: datetime
    duration_ms: float
    num_devices: int
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSON/database storage."""
        return {
            "allocation": self.allocation_dict,
            "total_allocated_kw": self.total_allocated_kw,
            "remaining_surplus_kw": self.remaining_surplus_kw,
            "battery_soc_pct": self.battery_soc_pct,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "num_devices": self.num_devices,
            "errors": self.errors,
        }


@dataclass
class PVAllocatorConfig:
    """Configuration for PV allocator.

    Attributes:
        min_allocation_kw: Minimum surplus to trigger allocation (kW). Default 0.5 kW.
        battery_charge_limit_pct: Do not charge battery above this SoC (%). Default 80%.
        battery_reserve_pct: Keep battery above this as backup reserve (%). Default 20%.
        dhw_priority_window_start_hour: Hour (UTC) to prioritize DHW (morning). Default 6.
        dhw_priority_window_end_hour: Hour (UTC) to de-prioritize DHW. Default 12.
        use_orchestrator: Use orchestrator for HA service calls. Default True.
        orchestrator_url: Orchestrator service URL. Default "http://orchestrator:8100".
        ha_url: Direct HA URL (if not using orchestrator). Default "http://192.168.0.100:8123".
        ha_token: HA token (if not using orchestrator).
        execution_timeout_s: Max time for allocation enforcement calls. Default 10s.
    """

    min_allocation_kw: float = 0.5
    battery_charge_limit_pct: float = 80.0
    battery_reserve_pct: float = 20.0
    dhw_priority_window_start_hour: int = 6
    dhw_priority_window_end_hour: int = 12
    use_orchestrator: bool = True
    orchestrator_url: str = "http://orchestrator:8100"
    ha_url: str = "http://192.168.0.100:8123"
    ha_token: str = ""
    execution_timeout_s: float = 10.0


class PVAllocator:
    """Distributes PV surplus across devices using priority cascade.

    Usage:
        allocator = PVAllocator(
            ha_client=httpx.AsyncClient(...),
            database=hems_db,
            config=PVAllocatorConfig(...),
        )
        result = await allocator.allocate(
            surplus_available_kw=4.5,
            devices=[...],
            battery_soc_pct=65.0,
        )
    """

    def __init__(
        self,
        ha_client: Optional[httpx.AsyncClient] = None,
        database: Optional[object] = None,
        influxdb_write_api: Optional[object] = None,
        config: Optional[PVAllocatorConfig] = None,
    ):
        """Initialize PV allocator.

        Args:
            ha_client: httpx.AsyncClient for direct HA calls (optional if use_orchestrator=True)
            database: HEMSDatabase instance for persistence
            influxdb_write_api: InfluxDB write API for metrics
            config: PVAllocatorConfig (if None, uses defaults)
        """
        self.ha_client = ha_client
        self.database = database
        self.influxdb_write_api = influxdb_write_api
        self.config = config or PVAllocatorConfig()

        logger.info(
            "PVAllocator initialized: min_allocation=%.1f kW, "
            "battery_charge_limit=%.0f%%, battery_reserve=%.0f%%, "
            "DHW priority window %02d:00–%02d:00 UTC",
            self.config.min_allocation_kw,
            self.config.battery_charge_limit_pct,
            self.config.battery_reserve_pct,
            self.config.dhw_priority_window_start_hour,
            self.config.dhw_priority_window_end_hour,
        )

    async def allocate(
        self,
        surplus_available_kw: float,
        devices: list[dict] | list[Device],
        battery_soc_pct: Optional[float] = None,
    ) -> AllocationResult:
        """Allocate PV surplus across devices using priority cascade.

        Algorithm:
          1. Skip if surplus < min_allocation_kw
          2. For each priority tier in PRIORITY_ORDER:
             a. For each device in tier:
                - Calculate allocatable capacity (max - current)
                - Allocate min(remaining_surplus, capacity)
                - Deduct from remaining_surplus
             b. If surplus exhausted, stop
          3. Record allocation to database
          4. Call HA services to enforce setpoints
          5. Return result

        Args:
            surplus_available_kw: Available PV surplus to allocate (kW)
            devices: List of Device objects or dicts with device_id, priority, max_power_kw, etc.
            battery_soc_pct: Battery state of charge (optional, for logic/database)

        Returns:
            AllocationResult with allocation_dict, total allocated, remaining surplus, etc.
        """
        start_time = time.monotonic()
        now_utc = datetime.now(timezone.utc)

        # Convert dict devices to Device objects
        device_objs = self._normalize_devices(devices)

        allocation_dict: dict[str, float] = {}
        remaining_surplus = surplus_available_kw
        errors: list[str] = []

        # Step 1: Check if allocation is worthwhile
        if surplus_available_kw < self.config.min_allocation_kw:
            logger.debug(
                "Surplus %.2f kW below minimum %.2f kW, skipping allocation",
                surplus_available_kw,
                self.config.min_allocation_kw,
            )
            duration_ms = (time.monotonic() - start_time) * 1000
            return AllocationResult(
                allocation_dict={},
                total_allocated_kw=0.0,
                remaining_surplus_kw=surplus_available_kw,
                battery_soc_pct=battery_soc_pct,
                timestamp=now_utc,
                duration_ms=duration_ms,
                num_devices=len(device_objs),
                errors=errors,
            )

        # Step 2: Apply priority cascade
        for priority_tier in PRIORITY_ORDER:
            if remaining_surplus <= 0.0:
                break

            # Get devices in this priority tier
            tier_devices = [d for d in device_objs if d.priority == priority_tier]

            if not tier_devices:
                continue

            # Adjust priority for DHW during priority window (morning)
            if priority_tier == DevicePriority.DHW_HEATING:
                in_priority_window = (
                    self.config.dhw_priority_window_start_hour
                    <= now_utc.hour
                    < self.config.dhw_priority_window_end_hour
                )
                if not in_priority_window:
                    logger.debug(
                        "DHW outside priority window (%02d:00–%02d:00 UTC), deprioritizing",
                        self.config.dhw_priority_window_start_hour,
                        self.config.dhw_priority_window_end_hour,
                    )
                    # Skip DHW during off-peak window
                    continue

            # Apply battery SoC limits for battery charging
            if priority_tier == DevicePriority.BATTERY_CHARGING:
                if battery_soc_pct is not None:
                    if battery_soc_pct >= self.config.battery_charge_limit_pct:
                        logger.debug(
                            "Battery SoC %.1f%% at/above limit %.0f%%, skipping battery charging",
                            battery_soc_pct,
                            self.config.battery_charge_limit_pct,
                        )
                        continue

            # Allocate to each device in tier sequentially
            for device in tier_devices:
                if remaining_surplus <= 0.0:
                    break

                allocatable = device.allocatable_capacity_kw()
                allocated = min(remaining_surplus, allocatable)

                if allocated > 0.0:
                    allocation_dict[device.device_id] = allocated
                    remaining_surplus -= allocated
                    logger.debug(
                        "Allocated %.2f kW to %s (priority %d, capacity %.2f kW)",
                        allocated,
                        device.device_id,
                        device.priority.value,
                        device.max_power_kw,
                    )

        # Step 3: Record allocation to database
        total_allocated = surplus_available_kw - remaining_surplus
        duration_ms = (time.monotonic() - start_time) * 1000

        try:
            await self._record_allocation(
                timestamp=now_utc,
                surplus_available_kw=surplus_available_kw,
                allocation_dict=allocation_dict,
                battery_soc_pct=battery_soc_pct,
                duration_ms=duration_ms,
            )
        except Exception as e:
            logger.error("Failed to record allocation to database: %s", e)
            errors.append(f"database_error: {e}")

        # Step 4: Enforce allocation via HA service calls
        try:
            await self._enforce_allocation(allocation_dict)
        except Exception as e:
            logger.error("Failed to enforce allocation via HA: %s", e)
            errors.append(f"enforcement_error: {e}")

        # Step 5: Log to InfluxDB
        if self.influxdb_write_api:
            try:
                self._write_to_influxdb(
                    surplus_available_kw=surplus_available_kw,
                    total_allocated_kw=total_allocated,
                    remaining_surplus_kw=remaining_surplus,
                    allocation_dict=allocation_dict,
                    duration_ms=duration_ms,
                )
            except Exception as e:
                logger.warning("Failed to write to InfluxDB: %s", e)

        result = AllocationResult(
            allocation_dict=allocation_dict,
            total_allocated_kw=total_allocated,
            remaining_surplus_kw=remaining_surplus,
            battery_soc_pct=battery_soc_pct,
            timestamp=now_utc,
            duration_ms=duration_ms,
            num_devices=len(device_objs),
            errors=errors,
        )

        logger.info(
            "Allocation complete: surplus=%.2f kW, allocated=%.2f kW, remaining=%.2f kW, "
            "battery_soc=%.1f%%, duration=%.1f ms, num_devices=%d, errors=%d",
            surplus_available_kw,
            total_allocated,
            remaining_surplus,
            battery_soc_pct or -1.0,
            duration_ms,
            len(device_objs),
            len(errors),
        )

        return result

    def _normalize_devices(self, devices: list[dict] | list[Device]) -> list[Device]:
        """Convert dict or Device objects to Device list."""
        result = []
        for dev in devices:
            if isinstance(dev, Device):
                result.append(dev)
            elif isinstance(dev, dict):
                # Convert dict to Device
                priority_val = dev.get("priority")
                if isinstance(priority_val, int):
                    priority = DevicePriority(priority_val)
                else:
                    priority = priority_val
                
                device_obj = Device(
                    device_id=dev["device_id"],
                    priority=priority,
                    max_power_kw=dev["max_power_kw"],
                    current_power_kw=dev.get("current_power_kw", 0.0),
                    state=dev.get("state", "ready"),
                    entity_id=dev.get("entity_id"),
                )
                result.append(device_obj)
        return result

    async def _record_allocation(
        self,
        timestamp: datetime,
        surplus_available_kw: float,
        allocation_dict: dict[str, float],
        battery_soc_pct: Optional[float],
        duration_ms: float,
    ) -> None:
        """Record allocation to hems.pv_allocation and pv_allocation_history tables."""
        if not self.database or not self.database.pool:
            logger.warning("Database not available, skipping allocation record")
            return

        try:
            async with self.database.pool.acquire() as conn:
                # Insert to pv_allocation table
                await conn.execute(
                    """
                    INSERT INTO hems.pv_allocation (timestamp, surplus_available_kw, allocation_dict, battery_soc_pct)
                    VALUES ($1, $2, $3, $4)
                    """,
                    timestamp,
                    surplus_available_kw,
                    json.dumps(allocation_dict),
                    battery_soc_pct,
                )

                # Insert to pv_allocation_history
                total_allocated = sum(allocation_dict.values())
                remaining = surplus_available_kw - total_allocated

                history_json = {
                    device_id: {
                        "allocated_kW": power,
                        "priority": "N/A",
                    }
                    for device_id, power in allocation_dict.items()
                }

                await conn.execute(
                    """
                    INSERT INTO hems.pv_allocation_history 
                    (tick_timestamp, surplus_available_kw, allocated_total_kw, remaining_kw, allocation_json, execution_time_ms)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    timestamp,
                    surplus_available_kw,
                    total_allocated,
                    remaining,
                    json.dumps(history_json),
                    duration_ms,
                )

                logger.debug("Recorded allocation to database: %s", allocation_dict)
        except Exception as e:
            logger.error("Failed to record allocation: %s", e)
            raise

    async def _enforce_allocation(self, allocation_dict: dict[str, float]) -> None:
        """Call Home Assistant services to enforce device power setpoints."""
        if not allocation_dict:
            logger.debug("No allocation to enforce")
            return

        enforcement_tasks = []

        for device_id, allocated_kw in allocation_dict.items():
            # Map device_id to HA entity and service call
            task = self._enforce_device_allocation(device_id, allocated_kw)
            enforcement_tasks.append(task)

        if enforcement_tasks:
            try:
                results = await asyncio.gather(*enforcement_tasks, return_exceptions=True)
                for device_id, result in zip(allocation_dict.keys(), results):
                    if isinstance(result, Exception):
                        logger.error("Failed to enforce allocation for %s: %s", device_id, result)
                    else:
                        logger.debug("Enforced allocation for %s: %s", device_id, result)
            except Exception as e:
                logger.error("Error during enforcement: %s", e)
                raise

    async def _enforce_device_allocation(self, device_id: str, allocated_kw: float) -> dict:
        """Enforce allocation for a single device via HA service call."""
        # Map device_id to HA entity and service
        entity_map = {
            "battery": {
                "entity_id": "number.battery_charger_setpoint",
                "service": "number.set_value",
                "value_key": "value",
            },
            "dhw_heating": {
                "entity_id": "number.dhw_heater_target_power",
                "service": "number.set_value",
                "value_key": "value",
            },
            "space_heating": {
                "entity_id": "climate.living_room",
                "service": "climate.set_temperature",
                "value_key": "temperature",
            },
            "supplemental_heaters": {
                "entity_id": "switch.ir_heaters",
                "service": "switch.turn_on",
            },
            "ev_charging": {
                "entity_id": "number.ev_charger_power_limit",
                "service": "number.set_value",
                "value_key": "value",
            },
        }

        if device_id not in entity_map:
            logger.warning("Unknown device_id for enforcement: %s", device_id)
            return {"device_id": device_id, "status": "unknown_device"}

        mapping = entity_map[device_id]
        entity_id = mapping["entity_id"]

        try:
            if self.config.use_orchestrator:
                return await self._enforce_via_orchestrator(
                    device_id=device_id,
                    entity_id=entity_id,
                    service=mapping["service"],
                    allocated_kw=allocated_kw,
                    value_key=mapping.get("value_key"),
                )
            else:
                return await self._enforce_via_ha_client(
                    device_id=device_id,
                    entity_id=entity_id,
                    service=mapping["service"],
                    allocated_kw=allocated_kw,
                    value_key=mapping.get("value_key"),
                )
        except Exception as e:
            logger.error("Failed to enforce %s: %s", device_id, e)
            raise

    async def _enforce_via_orchestrator(
        self,
        device_id: str,
        entity_id: str,
        service: str,
        allocated_kw: float,
        value_key: Optional[str],
    ) -> dict:
        """Call orchestrator tool to enforce allocation."""
        try:
            async with httpx.AsyncClient(timeout=self.config.execution_timeout_s) as client:
                service_parts = service.split(".")
                domain, service_name = service_parts[0], service_parts[1]

                data = {"entity_id": entity_id}
                if value_key:
                    data[value_key] = allocated_kw

                response = await client.post(
                    f"{self.config.orchestrator_url}/tools/execute",
                    json={
                        "tool": "call_ha_service",
                        "params": {
                            "domain": domain,
                            "service": service_name,
                            "data": data,
                        },
                    },
                )

                if response.status_code != 200:
                    logger.warning(
                        "Orchestrator returned %d for %s enforcement",
                        response.status_code,
                        device_id,
                    )
                    return {
                        "device_id": device_id,
                        "status": "failed",
                        "http_code": response.status_code,
                    }

                logger.info("Enforced %s via orchestrator: %.2f kW", device_id, allocated_kw)
                return {"device_id": device_id, "status": "success", "allocated_kw": allocated_kw}
        except Exception as e:
            logger.error("Orchestrator enforcement failed for %s: %s", device_id, e)
            raise

    async def _enforce_via_ha_client(
        self,
        device_id: str,
        entity_id: str,
        service: str,
        allocated_kw: float,
        value_key: Optional[str],
    ) -> dict:
        """Call HA directly via REST client."""
        if not self.ha_client:
            raise RuntimeError("HA client not configured")

        try:
            service_parts = service.split(".")
            domain, service_name = service_parts[0], service_parts[1]
            service_path = f"/api/services/{domain}/{service_name}"

            data = {"entity_id": entity_id}
            if value_key:
                data[value_key] = allocated_kw

            response = await self.ha_client.post(service_path, json=data)

            if response.status_code != 200:
                logger.warning(
                    "HA returned %d for %s enforcement",
                    response.status_code,
                    device_id,
                )
                return {
                    "device_id": device_id,
                    "status": "failed",
                    "http_code": response.status_code,
                }

            logger.info("Enforced %s via HA REST: %.2f kW", device_id, allocated_kw)
            return {"device_id": device_id, "status": "success", "allocated_kw": allocated_kw}
        except Exception as e:
            logger.error("HA enforcement failed for %s: %s", device_id, e)
            raise

    def _write_to_influxdb(
        self,
        surplus_available_kw: float,
        total_allocated_kw: float,
        remaining_surplus_kw: float,
        allocation_dict: dict[str, float],
        duration_ms: float,
    ) -> None:
        """Write PV allocation metrics to InfluxDB."""
        try:
            from influxdb_client import Point

            point = Point("pv_allocator")
            point.field("surplus_available_kw", surplus_available_kw)
            point.field("total_allocated_kw", total_allocated_kw)
            point.field("remaining_surplus_kw", remaining_surplus_kw)
            point.field("duration_ms", duration_ms)

            # Add per-device allocations as fields
            for device_id, power_kw in allocation_dict.items():
                point.field(f"allocated_{device_id}_kw", power_kw)

            self.influxdb_write_api.write(
                bucket="hems",
                org="homelab",
                record=point,
            )
            logger.debug("Wrote PV allocator metrics to InfluxDB")
        except Exception as e:
            logger.warning("Failed to write to InfluxDB: %s", e)

    def get_priority_order(self) -> list[tuple[int, str]]:
        """Get current priority order for reference."""
        return [(p.value, p.name) for p in PRIORITY_ORDER]
