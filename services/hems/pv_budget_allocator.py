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

from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


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
    """

    def __init__(self):
        self.consumers: list[Consumer] = [
            Consumer("house_base", priority=1, min_power_w=200, max_power_w=2000),
            Consumer("dhw_heating", priority=2, min_power_w=800, max_power_w=2000),
            Consumer("ev_charging", priority=3, min_power_w=1380, max_power_w=11000),
            Consumer("supplemental", priority=4, min_power_w=500, max_power_w=3000),
        ]

    def allocate(self, available_pv_w: float) -> dict:
        """Allocate PV power. Returns allocation dict + grid_export."""
        remaining = available_pv_w

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
