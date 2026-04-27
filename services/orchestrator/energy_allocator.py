"""Energy Allocator — advisory cross-domain PV surplus arbitration (S3b, FR #3061).

Subscribes to demand publishers (energy.demand.ev, energy.demand.heating) and
the hourly PV forecast (energy.pv.forecast.hourly). Emits per-slot allocation
hints on energy.allocation.ev / energy.allocation.heating. Services may honor
the hint or ignore it; messages stale > 10 minutes are treated as missing.

This module is **advisory** — never blocking. If the allocator dies, both
services fall back to current independent behavior.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from shared.log import get_logger

logger = get_logger("energy_allocator")


@dataclass
class Demand:
    service: str  # "ev" or "heating"
    kwh_needed: float
    deadline_iso: str | None
    value_per_kwh_eur: float
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class HourlySlot:
    time_iso: str
    pv_kwh_low: float  # conservative (conf_low if available)


class EnergyAllocator:
    """Advisory PV-surplus arbiter across EV charging + heating.

    On each demand or PV-forecast update, recomputes per-slot allocation
    hints and publishes them to the per-service subjects.
    """

    def __init__(self, nats: Any, stale_threshold_seconds: int = 600) -> None:
        self._nats = nats
        self._stale = timedelta(seconds=stale_threshold_seconds)
        self._demands: dict[str, Demand] = {}
        self._hourly_pv: list[HourlySlot] = []

    async def on_demand_ev(self, subject: str, payload: dict) -> None:
        self._demands["ev"] = Demand(
            service="ev",
            kwh_needed=float(payload.get("kwh_needed", 0.0)),
            deadline_iso=payload.get("deadline_iso"),
            value_per_kwh_eur=float(payload.get("value_per_kwh_eur", 0.18)),
        )
        await self._reallocate()

    async def on_demand_heating(self, subject: str, payload: dict) -> None:
        self._demands["heating"] = Demand(
            service="heating",
            kwh_needed=float(payload.get("kwh_needed", 0.0)),
            deadline_iso=payload.get("deadline_iso"),
            value_per_kwh_eur=float(payload.get("value_per_kwh_eur", 0.10)),
        )
        await self._reallocate()

    async def on_pv_forecast_hourly(self, subject: str, payload: dict) -> None:
        slots: list[HourlySlot] = []
        for s in payload.get("hourly", []):
            time_iso = s.get("time_iso")
            if not time_iso:
                continue
            slots.append(
                HourlySlot(
                    time_iso=time_iso,
                    pv_kwh_low=float(s.get("conf_low", s.get("kwh", 0.0))),
                )
            )
        self._hourly_pv = slots
        await self._reallocate()

    async def _reallocate(self) -> None:
        now = datetime.now(timezone.utc)
        live = {
            k: d for k, d in self._demands.items() if now - d.received_at < self._stale
        }
        if not live or not self._hourly_pv:
            return

        per_service_kwh: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for slot in self._hourly_pv[:24]:
            budget = max(0.0, slot.pv_kwh_low)
            if budget <= 0:
                continue

            ranked = sorted(live.values(), key=lambda d: -d.value_per_kwh_eur)
            remaining = budget
            for demand in ranked:
                if remaining <= 0 or demand.kwh_needed <= 0:
                    continue
                allocate = min(remaining, demand.kwh_needed / 24.0)
                per_service_kwh[demand.service].append(
                    {"slot_iso": slot.time_iso, "allowed_kwh": round(allocate, 3)}
                )
                remaining -= allocate

        for service, slots in per_service_kwh.items():
            subject = f"energy.allocation.{service}"
            payload = {
                "generated_at": now.isoformat(),
                "stale_after_seconds": int(self._stale.total_seconds()),
                "slots": slots,
                "reason": "advisory PV-surplus allocation",
            }
            try:
                await self._nats.publish(subject, payload)
                logger.debug("allocation_published", service=service, slots=len(slots))
            except Exception:
                logger.warning(
                    "allocation_publish_failed", service=service, exc_info=True
                )
