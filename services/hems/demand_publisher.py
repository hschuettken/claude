"""HEMS demand publisher for the Energy Allocator (S3b, FR #3061).

Publishes energy.demand.heating every 60 s with the current heating energy
demand expressed as kWh-needed-by-deadline. The Energy Allocator uses this
together with energy.demand.ev + energy.pv.forecast.hourly to produce
per-slot allocation hints.

Advisory only: HEMS continues to function without the allocator. This
publisher is purely additive — it never blocks the control loop and never
raises.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from shared.nats_client import NatsPublisher

logger = logging.getLogger("hems.demand")

NATS_URL = os.getenv("NATS_URL", "nats://192.168.0.50:4222")

INTERVAL_SECONDS = 60
# Oil-equivalent energy value (EUR/kWh). Roughly 1 L oil ≈ 10 kWh @ ~85
# ct/L → ~0.085 EUR/kWh raw, + boiler losses ~10 ct/kWh effective.
HEATING_VALUE_PER_KWH_EUR = 0.10
# Look-ahead horizon for the heating-demand "deadline" (hours).
DEADLINE_HORIZON_H = 1.0


class DemandPublisher:
    """Publishes the heating demand of the household to NATS every minute.

    The demand_provider callable returns the instantaneous heating demand in
    Watts; the publisher converts it to kWh-needed for the look-ahead horizon
    and publishes alongside a deadline_iso.
    """

    def __init__(self, demand_provider) -> None:
        self._nats: NatsPublisher = NatsPublisher(url=NATS_URL)
        self._demand_provider = demand_provider
        self._connected = False

    async def _ensure_connected(self) -> None:
        if not self._connected:
            try:
                await self._nats.connect()
                self._connected = True
            except Exception:
                logger.warning("hems_demand_nats_connect_failed", exc_info=True)

    async def _publish_tick(self) -> None:
        try:
            await self._ensure_connected()
            if not self._connected:
                return
            demand_w = await self._demand_provider()
            if demand_w is None:
                demand_w = 0.0
            kwh_needed = float(demand_w) / 1000.0 * DEADLINE_HORIZON_H
            deadline_iso = (
                datetime.now(timezone.utc) + timedelta(hours=DEADLINE_HORIZON_H)
            ).isoformat()
            payload = {
                "kwh_needed": round(max(0.0, kwh_needed), 3),
                "deadline_iso": deadline_iso,
                "value_per_kwh_eur": HEATING_VALUE_PER_KWH_EUR,
                "instant_demand_w": float(demand_w),
                "horizon_hours": DEADLINE_HORIZON_H,
            }
            await self._nats.publish("energy.demand.heating", payload)
        except Exception:
            logger.warning("hems_demand_publish_failed", exc_info=True)

    async def run_forever(self) -> None:
        while True:
            await self._publish_tick()
            await asyncio.sleep(INTERVAL_SECONDS)


class AllocationCache:
    """Subscribes to energy.allocation.heating and caches the latest hints.

    Advisory: HEMS may consult ``current_slot_kwh`` to shape its heating ramp
    when the cache is non-stale, but never blocks on it. Stale after 10 min.
    """

    def __init__(self, stale_seconds: int = 600) -> None:
        self._nats: NatsPublisher = NatsPublisher(url=NATS_URL)
        self._stale = timedelta(seconds=stale_seconds)
        self._received_at: datetime | None = None
        self._slots: list[dict] = []

    async def start(self) -> None:
        try:
            await self._nats.connect()
            await self._nats.subscribe_json(
                "energy.allocation.heating", self._on_allocation
            )
            logger.info("hems_allocation_subscribed")
        except Exception:
            logger.warning("hems_allocation_subscribe_failed", exc_info=True)

    async def _on_allocation(self, subject: str, payload: dict) -> None:
        try:
            self._received_at = datetime.now(timezone.utc)
            self._slots = list(payload.get("slots", []))
        except Exception:
            logger.warning("hems_allocation_parse_failed", exc_info=True)

    def is_fresh(self) -> bool:
        if self._received_at is None:
            return False
        return datetime.now(timezone.utc) - self._received_at < self._stale

    def current_slot_kwh(self) -> float | None:
        """kWh allowed for the current hour, or None if no fresh hint."""
        if not self.is_fresh():
            return None
        now_hour_iso = (
            datetime.now(timezone.utc)
            .replace(minute=0, second=0, microsecond=0)
            .isoformat()
        )
        for slot in self._slots:
            slot_iso = str(slot.get("slot_iso", ""))
            if slot_iso[:13] == now_hour_iso[:13]:
                try:
                    return float(slot.get("allowed_kwh", 0.0))
                except (TypeError, ValueError):
                    return None
        return None
