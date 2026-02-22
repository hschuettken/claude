"""Smart charging plan generator.

Takes vehicle state and predicted trips to generate a demand-focused
charging plan. The planner calculates:
- How much energy is needed for each day's trips
- When the car needs to be ready (departure time)
- The urgency level based on current SoC vs. required SoC

It then sets the HA input helpers (charge mode, target energy, departure
time, full-by-morning) for the smart-ev-charging service, which handles
the actual PV surplus optimization and wallbox control.

Design principle: This service expresses DEMAND ("need X kWh by time Y"),
not supply decisions. The smart-ev-charging service and orchestrator
handle the supply side (PV surplus, grid charging, timing).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from shared.ha_client import HomeAssistantClient

from trips import DayPlan, Trip
from vehicle import VehicleState

logger = structlog.get_logger()


@dataclass
class DayChargingRecommendation:
    """Charging recommendation for a single day."""

    date: date
    trips: list[Trip]
    soc_needed_pct: float          # SoC needed at start of day
    energy_needed_kwh: float       # Energy needed for the day's trips
    energy_to_charge_kwh: float    # How much to charge (considering current SoC)
    charge_mode: str               # Recommended charge mode
    departure_time: time | None    # When car leaves
    charge_by: time | None         # Must be charged by this time
    urgency: str                   # "none" | "low" | "medium" | "high" | "critical"
    reason: str                    # Human-readable explanation

    @property
    def label(self) -> str:
        trips_str = ", ".join(t.label for t in self.trips)
        return (
            f"{self.date}: {self.charge_mode} [{self.urgency}] | "
            f"need {self.energy_needed_kwh:.1f} kWh, "
            f"charge {self.energy_to_charge_kwh:.1f} kWh | "
            f"{trips_str or 'no trips'}"
        )


@dataclass
class ChargingPlan:
    """Multi-day charging plan."""

    generated_at: datetime
    current_soc_pct: float | None
    current_energy_kwh: float | None
    vehicle_plugged_in: bool
    days: list[DayChargingRecommendation] = field(default_factory=list)
    trace_id: str = ""

    @property
    def immediate_action(self) -> DayChargingRecommendation | None:
        """The most urgent action to take now.

        Returns today's recommendation unless today is just PV Surplus
        and tomorrow needs active charging (overnight scenario).
        """
        if not self.days:
            return None
        today = self.days[0]
        # If today already requires active charging, use it
        if today.charge_mode != "PV Surplus":
            return today
        # Today is PV Surplus — check if tomorrow needs overnight charging
        if len(self.days) > 1:
            tomorrow = self.days[1]
            if (
                tomorrow.energy_to_charge_kwh > 0
                and tomorrow.charge_mode != "PV Surplus"
            ):
                return tomorrow
        return today

    @property
    def total_energy_needed_kwh(self) -> float:
        return sum(d.energy_to_charge_kwh for d in self.days)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "generated_at": self.generated_at.isoformat(),
            "current_soc_pct": self.current_soc_pct,
            "current_energy_kwh": self.current_energy_kwh,
            "vehicle_plugged_in": self.vehicle_plugged_in,
            "total_energy_needed_kwh": round(self.total_energy_needed_kwh, 1),
            "days": [
                {
                    "date": d.date.isoformat(),
                    "trips": [
                        {
                            "person": t.person,
                            "destination": t.destination,
                            "distance_km": t.round_trip_km,
                            "energy_kwh": round(t.energy_kwh, 1),
                            "is_commute": t.is_commute,
                        }
                        for t in d.trips
                    ],
                    "soc_needed_pct": round(d.soc_needed_pct, 1),
                    "energy_needed_kwh": round(d.energy_needed_kwh, 1),
                    "energy_to_charge_kwh": round(d.energy_to_charge_kwh, 1),
                    "charge_mode": d.charge_mode,
                    "departure_time": d.departure_time.strftime("%H:%M") if d.departure_time else None,
                    "urgency": d.urgency,
                    "reason": d.reason,
                }
                for d in self.days
            ],
        }


class ChargingPlanner:
    """Generates demand-focused charging plans from vehicle state and trips."""

    def __init__(
        self,
        ha: HomeAssistantClient,
        net_capacity_kwh: float = 76.0,
        min_soc_pct: float = 20.0,
        buffer_soc_pct: float = 10.0,
        min_arrival_soc_pct: float = 15.0,
        timezone: str = "Europe/Berlin",
        default_assumed_soc_pct: float = 50.0,
        critical_urgency_hours: float = 2.0,
        high_urgency_hours: float = 6.0,
        fast_mode_threshold_kwh: float = 15.0,
        early_departure_hour: int = 10,
    ) -> None:
        self._ha = ha
        self._net_capacity = net_capacity_kwh
        self._min_soc = min_soc_pct
        self._buffer_soc = buffer_soc_pct
        self._min_arrival_soc = min_arrival_soc_pct
        self._tz = ZoneInfo(timezone)
        self._default_assumed_soc = default_assumed_soc_pct
        self._critical_urgency_hours = critical_urgency_hours
        self._high_urgency_hours = high_urgency_hours
        self._fast_mode_threshold_kwh = fast_mode_threshold_kwh
        self._early_departure_hour = early_departure_hour

    async def generate_plan(
        self,
        vehicle: VehicleState,
        day_plans: list[DayPlan],
    ) -> ChargingPlan:
        """Generate a multi-day charging plan based purely on demand.

        Args:
            vehicle: Current vehicle state (SoC, plug, etc.)
            day_plans: Trip predictions per day
        """
        now = datetime.now(self._tz)
        current_soc = vehicle.soc_pct
        current_energy = self._soc_to_kwh(current_soc) if current_soc else None
        trace_id = str(uuid.uuid4())[:8]

        plan = ChargingPlan(
            generated_at=now,
            current_soc_pct=current_soc,
            current_energy_kwh=current_energy,
            vehicle_plugged_in=vehicle.is_plugged_in,
            trace_id=trace_id,
        )

        # Track running SoC through the planning horizon
        default_soc = self._default_assumed_soc
        running_soc = current_soc if current_soc is not None else default_soc
        running_energy = current_energy if current_energy is not None else self._soc_to_kwh(default_soc)

        for i, day_plan in enumerate(day_plans):
            rec = self._plan_day(
                day_plan=day_plan,
                running_soc=running_soc,
                running_energy=running_energy,
                is_today=(i == 0),
                is_tomorrow=(i == 1),
                now=now,
            )
            plan.days.append(rec)

            # Update running state: subtract trip energy, add planned charge
            trip_energy = rec.energy_needed_kwh
            charge_energy = rec.energy_to_charge_kwh
            running_energy = running_energy - trip_energy + charge_energy
            running_soc = self._kwh_to_soc(running_energy)

        return plan

    async def apply_plan(
        self,
        plan: ChargingPlan,
        charge_mode_entity: str,
        full_by_morning_entity: str,
        departure_time_entity: str,
        target_energy_entity: str,
    ) -> None:
        """Write the immediate plan to HA input helpers."""
        immediate = plan.immediate_action
        if not immediate:
            return

        if not plan.vehicle_plugged_in:
            logger.info("vehicle_not_plugged_in, skipping_ha_update")
            return

        # Set charge mode
        try:
            await self._ha.call_service("input_select", "select_option", {
                "entity_id": charge_mode_entity,
                "option": immediate.charge_mode,
            })
        except Exception:
            logger.exception("set_charge_mode_failed")

        # Set full-by-morning (enable when Smart mode needs charging)
        enable_fbm = immediate.charge_mode == "Smart" and immediate.energy_to_charge_kwh > 0
        try:
            service = "turn_on" if enable_fbm else "turn_off"
            await self._ha.call_service("input_boolean", service, {
                "entity_id": full_by_morning_entity,
            })
        except Exception:
            logger.exception("set_full_by_morning_failed")

        # Set departure time
        if immediate.departure_time:
            try:
                await self._ha.call_service("input_datetime", "set_datetime", {
                    "entity_id": departure_time_entity,
                    "time": immediate.departure_time.strftime("%H:%M:%S"),
                })
            except Exception:
                logger.exception("set_departure_time_failed")

        # Set target energy
        if immediate.energy_to_charge_kwh > 0:
            try:
                await self._ha.call_service("input_number", "set_value", {
                    "entity_id": target_energy_entity,
                    "value": min(self._net_capacity, round(immediate.energy_to_charge_kwh)),
                })
            except Exception:
                logger.exception("set_target_energy_failed")

        logger.info(
            "plan_applied",
            mode=immediate.charge_mode,
            target_kwh=round(immediate.energy_to_charge_kwh, 1),
            departure=immediate.departure_time.strftime("%H:%M") if immediate.departure_time else "none",
            urgency=immediate.urgency,
            reason=immediate.reason,
        )

    def _plan_day(
        self,
        day_plan: DayPlan,
        running_soc: float,
        running_energy: float,
        is_today: bool,
        is_tomorrow: bool,
        now: datetime,
    ) -> DayChargingRecommendation:
        """Plan charging for a single day based on demand."""

        energy_needed = day_plan.total_energy_kwh
        departure_time = day_plan.earliest_departure

        # Calculate SoC needed at departure (trip energy + buffer + minimum)
        buffer_kwh = self._net_capacity * self._buffer_soc / 100.0
        min_kwh = self._net_capacity * self._min_arrival_soc / 100.0
        required_energy = energy_needed + buffer_kwh + min_kwh
        required_soc = self._kwh_to_soc(required_energy)

        # How much energy deficit do we have?
        deficit_kwh = max(0, required_energy - running_energy)

        # No trips — opportunistic PV charging
        if not day_plan.has_trips:
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=[],
                soc_needed_pct=self._min_soc,
                energy_needed_kwh=0,
                energy_to_charge_kwh=0,
                charge_mode="PV Surplus",
                departure_time=None,
                charge_by=None,
                urgency="none",
                reason="No trips planned — opportunistic PV charging",
            )

        # SoC already sufficient
        if deficit_kwh <= 0:
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=0,
                charge_mode="PV Surplus",
                departure_time=departure_time,
                charge_by=departure_time,
                urgency="none",
                reason=f"SoC sufficient ({running_soc:.0f}% >= {required_soc:.0f}% needed)",
            )

        # We need to charge — determine urgency and mode
        if is_today:
            return self._plan_today(
                day_plan, departure_time, deficit_kwh, required_soc,
                energy_needed, running_soc, now,
            )

        if is_tomorrow:
            return self._plan_tomorrow(
                day_plan, departure_time, deficit_kwh, required_soc,
                energy_needed, running_soc,
            )

        # Future days — note demand, use Smart mode
        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode="PV Surplus",
            departure_time=departure_time,
            charge_by=departure_time,
            urgency="low",
            reason=f"Future day — need {deficit_kwh:.1f} kWh, planning ahead",
        )

    def _plan_today(
        self,
        day_plan: DayPlan,
        departure_time: time | None,
        deficit_kwh: float,
        required_soc: float,
        energy_needed: float,
        running_soc: float,
        now: datetime,
    ) -> DayChargingRecommendation:
        """Plan charging for today based on time until departure."""

        hours_until = self._hours_until_time(departure_time, now) if departure_time else 24.0

        # Already past departure
        if hours_until <= 0:
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode="Fast",
                departure_time=departure_time,
                charge_by=departure_time,
                urgency="critical",
                reason=f"Past departure — need {deficit_kwh:.1f} kWh urgently",
            )

        # Critical urgency — departure imminent
        if hours_until <= self._critical_urgency_hours:
            mode = "Fast" if deficit_kwh > self._fast_mode_threshold_kwh else "Eco"
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode=mode,
                departure_time=departure_time,
                charge_by=departure_time,
                urgency="critical",
                reason=(
                    f"Departure in {hours_until:.1f}h — "
                    f"need {deficit_kwh:.1f} kWh ({mode} mode)"
                ),
            )

        # High urgency — Smart mode with deadline
        if hours_until <= self._high_urgency_hours:
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode="Smart",
                departure_time=departure_time,
                charge_by=departure_time,
                urgency="high",
                reason=(
                    f"Need {deficit_kwh:.1f} kWh by "
                    f"{departure_time.strftime('%H:%M') if departure_time else '?'} "
                    f"({hours_until:.1f}h remaining)"
                ),
            )

        # Plenty of time — Smart mode, PV can help
        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode="Smart",
            departure_time=departure_time,
            charge_by=departure_time,
            urgency="medium",
            reason=(
                f"Need {deficit_kwh:.1f} kWh by "
                f"{departure_time.strftime('%H:%M') if departure_time else '?'} "
                f"({hours_until:.0f}h available — PV + grid)"
            ),
        )

    def _plan_tomorrow(
        self,
        day_plan: DayPlan,
        departure_time: time | None,
        deficit_kwh: float,
        required_soc: float,
        energy_needed: float,
        running_soc: float,
    ) -> DayChargingRecommendation:
        """Plan charging for tomorrow (may need overnight charging)."""

        early_departure = departure_time and departure_time.hour < self._early_departure_hour

        if early_departure:
            # Need to charge tonight
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode="Smart",
                departure_time=departure_time,
                charge_by=departure_time,
                urgency="medium",
                reason=(
                    f"Charge overnight: need {deficit_kwh:.1f} kWh by "
                    f"{departure_time.strftime('%H:%M') if departure_time else 'morning'} "
                    f"(current {running_soc:.0f}%, need {required_soc:.0f}%)"
                ),
            )

        # Late departure — can charge tomorrow with PV
        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode="Smart",
            departure_time=departure_time,
            charge_by=departure_time,
            urgency="low",
            reason=(
                f"Tomorrow: need {deficit_kwh:.1f} kWh, "
                f"late departure {departure_time.strftime('%H:%M') if departure_time else '?'} "
                f"— PV + grid can cover it"
            ),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _soc_to_kwh(self, soc_pct: float | None) -> float:
        if soc_pct is None:
            return 0.0
        return soc_pct / 100.0 * self._net_capacity

    def _kwh_to_soc(self, kwh: float) -> float:
        return max(0, min(100, kwh / self._net_capacity * 100.0))

    def _hours_until_time(self, target: time, now: datetime) -> float:
        target_dt = now.replace(
            hour=target.hour, minute=target.minute, second=0, microsecond=0,
        )
        if target_dt <= now:
            return 0.0  # Already past
        return (target_dt - now).total_seconds() / 3600
