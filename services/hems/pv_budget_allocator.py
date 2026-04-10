"""PV Budget Allocator — priority cascade (#1044).

Allocates available PV power to consumers in priority order:
1. House base load (always)
2. DHW heating (opportunistic)
3. EV charging
4. Supplemental heat
5. Export to grid

Each consumer declares a minimum and maximum demand.

Note: this is a simple watts-based facade over the more feature-complete
pv_allocator.py (kW-based, database-backed, HA-enforcing). Use this for
quick rule-based allocation without external dependencies.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
)

# Battery configuration — environment-agnostic
# Set BATTERY_CAPACITY_KWH=19.2 for the planned battery upgrade
BATTERY_CAPACITY_KWH = float(os.getenv("BATTERY_CAPACITY_KWH", "7.0"))
BATTERY_MAX_CHARGE_W = float(os.getenv("BATTERY_MAX_CHARGE_W", "3300.0"))
BATTERY_MAX_DISCHARGE_W = float(os.getenv("BATTERY_MAX_DISCHARGE_W", "3300.0"))


@dataclass
class Consumer:
    name: str
    priority: int  # Lower = higher priority
    min_power_w: float  # Minimum to activate
    max_power_w: float  # Maximum it can use
    enabled: bool = True
    allocated_w: float = 0.0


class PVBudgetAllocator:
    """Allocates PV power to consumers in priority order.

    Any unallocated power is considered grid export.

    Set BATTERY_CAPACITY_KWH=19.2 for the planned battery upgrade. Use the
    battery_capacity_kwh parameter to override per instance.
    """

    def __init__(self, battery_capacity_kwh: float | None = None):
        self.battery_capacity_kwh = battery_capacity_kwh or BATTERY_CAPACITY_KWH
        self.battery_max_charge_w = BATTERY_MAX_CHARGE_W
        self.battery_max_discharge_w = BATTERY_MAX_DISCHARGE_W
        self.consumers: list[Consumer] = [
            Consumer("house_base", priority=1, min_power_w=200, max_power_w=2000),
            Consumer("dhw_heating", priority=2, min_power_w=800, max_power_w=2000),
            Consumer("ev_charging", priority=3, min_power_w=1380, max_power_w=11000),
            Consumer("supplemental", priority=4, min_power_w=500, max_power_w=3000),
        ]

    def allocate(self, available_pv_w: float, grid_import_w: float = 0.0) -> dict:
        """Allocate PV power. Returns allocation dict + grid_export.

        Args:
            available_pv_w: Available PV power in watts.
            grid_import_w: Current grid import power (W). If > 0, heating is zeroed.

        Returns:
            Dictionary with allocations, grid_export, etc.
        """
        remaining = available_pv_w

        # Anti-grid-heat rule: never use grid power for electric heating
        if grid_import_w > 0.0:
            # Disable supplemental and DHW heating when importing from grid
            dhw_consumer = next(
                (c for c in self.consumers if c.name == "dhw_heating"), None
            )
            supp_consumer = next(
                (c for c in self.consumers if c.name == "supplemental"), None
            )
            if dhw_consumer:
                dhw_consumer.enabled = False
            if supp_consumer:
                supp_consumer.enabled = False
            logger.info(
                "grid_to_heat_blocked: grid_import=%.0fW, zeroed heating allocation",
                grid_import_w,
            )

        # Sort by priority
        for consumer in sorted(self.consumers, key=lambda c: c.priority):
            consumer.allocated_w = 0.0
            if not consumer.enabled:
                continue
            if remaining >= consumer.min_power_w:
                alloc = min(consumer.max_power_w, remaining)
                consumer.allocated_w = alloc
                remaining -= alloc
                logger.debug("PV alloc: %s → %.0fW", consumer.name, alloc)
            else:
                logger.debug(
                    "PV alloc: %s skipped (need %.0fW, have %.0fW)",
                    consumer.name,
                    consumer.min_power_w,
                    remaining,
                )

        grid_export = max(0.0, remaining)

        return {
            "available_pv_w": available_pv_w,
            "allocations": {c.name: c.allocated_w for c in self.consumers},
            "grid_export_w": grid_export,
            "total_allocated_w": available_pv_w - grid_export,
        }

    async def log_allocation(self, result: dict) -> None:
        """Write allocation decision to InfluxDB and Postgres (best-effort).

        Call this after allocate() from an async context:

            result = allocator.allocate(pv_w)
            await allocator.log_allocation(result)
        """
        allocations = result["allocations"]
        available_pv_w = result["available_pv_w"]
        grid_export_w = result["grid_export_w"]

        # InfluxDB (best-effort)
        try:
            from influxdb_setup import write_hems_point

            await write_hems_point(
                measurement="pv_budget_allocation",
                fields={
                    "available_pv_w": float(available_pv_w),
                    "house_base_w": float(allocations.get("house_base", 0.0)),
                    "dhw_heating_w": float(allocations.get("dhw_heating", 0.0)),
                    "ev_charging_w": float(allocations.get("ev_charging", 0.0)),
                    "supplemental_heating_w": float(
                        allocations.get("supplemental", 0.0)
                    ),
                    "grid_export_w": float(grid_export_w),
                },
                tags={"mode": "auto"},
            )
        except Exception as e:
            logger.warning("InfluxDB pv_budget_allocation write failed: %s", e)

        # Postgres — single row in hems.energy_allocation
        # Columns: ts (DEFAULT), pv_total_w, house_w, dhw_w, ev_w,
        #          supplemental_w, grid_export_w, self_consumption_pct
        try:
            import asyncpg

            pg_url = DB_URL.replace("postgresql+asyncpg://", "postgresql://").replace(
                "postgresql+psycopg2://", "postgresql://"
            )
            house_w = float(allocations.get("house_base", 0.0))
            dhw_w = float(allocations.get("dhw_heating", 0.0))
            ev_w = float(allocations.get("ev_charging", 0.0))
            supplemental_w = float(allocations.get("supplemental", 0.0))
            pv_total_w = float(available_pv_w)
            grid_w = float(grid_export_w)
            consumed_w = house_w + dhw_w + ev_w + supplemental_w
            self_pct = (consumed_w / pv_total_w * 100.0) if pv_total_w > 0 else 0.0

            conn = await asyncpg.connect(pg_url)
            try:
                await conn.execute(
                    """
                    INSERT INTO hems.energy_allocation
                        (pv_total_w, house_w, dhw_w, ev_w, supplemental_w,
                         grid_export_w, self_consumption_pct)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    pv_total_w,
                    house_w,
                    dhw_w,
                    ev_w,
                    supplemental_w,
                    grid_w,
                    round(self_pct, 2),
                )
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("Postgres pv_budget_allocation write failed: %s", e)

    def set_consumer_enabled(self, name: str, enabled: bool):
        for c in self.consumers:
            if c.name == name:
                c.enabled = enabled
                return
        raise ValueError(f"Unknown consumer: {name}")

    def get_status(self) -> dict:
        return {
            c.name: {"enabled": c.enabled, "allocated_w": c.allocated_w}
            for c in self.consumers
        }

    def should_overheat(
        self,
        room_id: str,
        current_temp: float,
        setpoint: float,
        available_surplus_w: float,
    ) -> bool:
        """Decide if a room should overheat to store thermal energy on PV surplus.

        Strategic overheating: when PV surplus > 500W, allow rooms to reach up to 2°C
        above normal setpoint to store thermal energy as a "thermal battery".

        Args:
            room_id: Room identifier.
            current_temp: Current room temperature (°C).
            setpoint: Normal setpoint temperature (°C).
            available_surplus_w: Available PV surplus power (W).

        Returns:
            True if overheating is beneficial, False otherwise.
        """
        if available_surplus_w > 500 and current_temp < setpoint + 2.0:
            logger.debug(
                "overheat_eligible: room=%s, current=%.1f°C, setpoint=%.1f°C, surplus=%.0fW",
                room_id,
                current_temp,
                setpoint,
                available_surplus_w,
            )
            return True
        return False

    def calculate_overheat_setpoint(self, setpoint: float, surplus_w: float) -> float:
        """Calculate elevated setpoint for thermal battery charging.

        Returns:
            Setpoint + min(2.0, surplus_w / 1000) — up to 2°C bonus per kW of surplus.

        Args:
            setpoint: Normal setpoint temperature (°C).
            surplus_w: Available surplus PV power (W).

        Returns:
            Elevated setpoint temperature (°C).
        """
        bonus = min(2.0, surplus_w / 1000.0)
        overheat_setpoint = setpoint + bonus
        logger.debug(
            "overheat_setpoint: base=%.1f°C, surplus=%.0fW, bonus=%.2f°C, result=%.1f°C",
            setpoint,
            surplus_w,
            bonus,
            overheat_setpoint,
        )
        return overheat_setpoint
