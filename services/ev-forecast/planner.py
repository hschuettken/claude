"""Smart charging plan generator.

Takes vehicle state, predicted trips, PV forecast, and generates an optimal
charging plan that:
- Ensures enough SoC for each day's driving with safety buffer
- Maximizes PV self-consumption (charge during solar hours)
- Falls back to grid charging when needed (overnight before departure)
- Sets HA input helpers for the smart-ev-charging service

The planner outputs a ChargingPlan with day-by-day recommendations and
directly sets the HA helpers (charge mode, target energy, departure time).
"""

from __future__ import annotations

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
    pv_expected_kwh: float         # PV forecast for the day
    use_pv_charging: bool          # Can we rely on PV?
    reason: str                    # Human-readable explanation

    @property
    def label(self) -> str:
        trips_str = ", ".join(t.label for t in self.trips)
        return (
            f"{self.date}: {self.charge_mode} | "
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

    @property
    def immediate_action(self) -> DayChargingRecommendation | None:
        """The most urgent action (today or tonight for tomorrow)."""
        if self.days:
            return self.days[0]
        return None

    @property
    def total_energy_needed_kwh(self) -> float:
        return sum(d.energy_to_charge_kwh for d in self.days)

    def to_dict(self) -> dict[str, Any]:
        return {
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
                    "pv_expected_kwh": round(d.pv_expected_kwh, 1),
                    "use_pv_charging": d.use_pv_charging,
                    "reason": d.reason,
                }
                for d in self.days
            ],
        }


class ChargingPlanner:
    """Generates optimal charging plans from vehicle state and trip predictions."""

    def __init__(
        self,
        ha: HomeAssistantClient,
        net_capacity_kwh: float = 76.0,
        min_soc_pct: float = 20.0,
        buffer_soc_pct: float = 10.0,
        min_arrival_soc_pct: float = 15.0,
        timezone: str = "Europe/Berlin",
    ) -> None:
        self._ha = ha
        self._net_capacity = net_capacity_kwh
        self._min_soc = min_soc_pct
        self._buffer_soc = buffer_soc_pct
        self._min_arrival_soc = min_arrival_soc_pct
        self._tz = ZoneInfo(timezone)

    async def generate_plan(
        self,
        vehicle: VehicleState,
        day_plans: list[DayPlan],
        pv_forecast: dict[str, float],
    ) -> ChargingPlan:
        """Generate a multi-day charging plan.

        Args:
            vehicle: Current vehicle state (SoC, plug, etc.)
            day_plans: Trip predictions per day
            pv_forecast: {"today": kWh, "today_remaining": kWh, "tomorrow": kWh}
        """
        now = datetime.now(self._tz)
        current_soc = vehicle.soc_pct
        current_energy = self._soc_to_kwh(current_soc) if current_soc else None

        plan = ChargingPlan(
            generated_at=now,
            current_soc_pct=current_soc,
            current_energy_kwh=current_energy,
            vehicle_plugged_in=vehicle.is_plugged_in,
        )

        # Track running SoC through the planning horizon
        running_soc = current_soc if current_soc is not None else 50.0
        running_energy = current_energy if current_energy is not None else self._soc_to_kwh(50.0)

        for i, day_plan in enumerate(day_plans):
            # Get PV forecast for this day
            if i == 0:
                pv_kwh = pv_forecast.get("today_remaining", 0.0)
                pv_total = pv_forecast.get("today", 0.0)
            elif i == 1:
                pv_kwh = pv_forecast.get("tomorrow", 0.0)
                pv_total = pv_kwh
            else:
                # Beyond tomorrow — estimate from today as rough baseline
                pv_kwh = pv_forecast.get("tomorrow", 0.0) * 0.8
                pv_total = pv_kwh

            rec = self._plan_day(
                day_plan=day_plan,
                running_soc=running_soc,
                running_energy=running_energy,
                pv_kwh=pv_kwh,
                pv_total=pv_total,
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

        # Set full-by-morning
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
                    "value": min(100, round(immediate.energy_to_charge_kwh)),
                })
            except Exception:
                logger.exception("set_target_energy_failed")

        logger.info(
            "plan_applied",
            mode=immediate.charge_mode,
            target_kwh=round(immediate.energy_to_charge_kwh, 1),
            departure=immediate.departure_time.strftime("%H:%M") if immediate.departure_time else "none",
            reason=immediate.reason,
        )

    def _plan_day(
        self,
        day_plan: DayPlan,
        running_soc: float,
        running_energy: float,
        pv_kwh: float,
        pv_total: float,
        is_today: bool,
        is_tomorrow: bool,
        now: datetime,
    ) -> DayChargingRecommendation:
        """Plan charging for a single day."""

        energy_needed = day_plan.total_energy_kwh
        departure_time = day_plan.earliest_departure

        # Calculate SoC needed at departure (trip energy + buffer + minimum)
        buffer_kwh = self._net_capacity * self._buffer_soc / 100.0
        min_kwh = self._net_capacity * self._min_arrival_soc / 100.0
        required_energy = energy_needed + buffer_kwh + min_kwh
        required_soc = self._kwh_to_soc(required_energy)

        # How much energy deficit do we have?
        deficit_kwh = max(0, required_energy - running_energy)
        deficit_soc = max(0, required_soc - running_soc)

        # Determine charge strategy
        if not day_plan.has_trips:
            # No trips — just use PV surplus if available
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=[],
                soc_needed_pct=self._min_soc,
                energy_needed_kwh=0,
                energy_to_charge_kwh=0,
                charge_mode="PV Surplus",
                departure_time=None,
                charge_by=None,
                pv_expected_kwh=pv_kwh,
                use_pv_charging=True,
                reason="No trips planned — opportunistic PV charging",
            )

        if deficit_kwh <= 0:
            # Enough charge already — just top up with PV if available
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=0,
                charge_mode="PV Surplus",
                departure_time=departure_time,
                charge_by=departure_time,
                pv_expected_kwh=pv_kwh,
                use_pv_charging=True,
                reason=f"SoC sufficient ({running_soc:.0f}% >= {required_soc:.0f}% needed)",
            )

        # We need to charge — decide how
        # For today: check if we have time for PV charging
        if is_today:
            return self._plan_today(
                day_plan, departure_time, deficit_kwh, required_soc,
                energy_needed, running_soc, pv_kwh, pv_total, now,
            )

        if is_tomorrow:
            return self._plan_tomorrow(
                day_plan, departure_time, deficit_kwh, required_soc,
                energy_needed, running_soc, pv_kwh,
            )

        # Future days — just note the need, PV Surplus for now
        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode="PV Surplus",
            departure_time=departure_time,
            charge_by=departure_time,
            pv_expected_kwh=pv_kwh,
            use_pv_charging=True,
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
        pv_remaining_kwh: float,
        pv_total_kwh: float,
        now: datetime,
    ) -> DayChargingRecommendation:
        """Plan charging for today."""

        # Check if departure is soon
        hours_until_departure = self._hours_until_time(departure_time, now) if departure_time else 24.0

        if hours_until_departure <= 0:
            # Already past departure — maybe they're still home?
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode="Fast",
                departure_time=departure_time,
                charge_by=departure_time,
                pv_expected_kwh=pv_remaining_kwh,
                use_pv_charging=False,
                reason=f"Past departure time — fast charging {deficit_kwh:.1f} kWh needed",
            )

        # Is there enough PV today to cover the deficit?
        # Assume ~60% of remaining PV can go to EV (rest for house/battery)
        pv_for_ev = pv_remaining_kwh * 0.6

        if pv_for_ev >= deficit_kwh and hours_until_departure > 3:
            # PV should cover it
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode="Smart",
                departure_time=departure_time,
                charge_by=departure_time,
                pv_expected_kwh=pv_remaining_kwh,
                use_pv_charging=True,
                reason=(
                    f"PV surplus expected ({pv_remaining_kwh:.1f} kWh remaining), "
                    f"Smart mode with {departure_time.strftime('%H:%M') if departure_time else '?'} deadline"
                ),
            )

        if hours_until_departure <= 2:
            # Urgent — use fast/eco
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode="Fast" if deficit_kwh > 15 else "Eco",
                departure_time=departure_time,
                charge_by=departure_time,
                pv_expected_kwh=pv_remaining_kwh,
                use_pv_charging=False,
                reason=f"Departure in {hours_until_departure:.1f}h — need {deficit_kwh:.1f} kWh urgently",
            )

        # Use Smart mode: PV surplus + grid fill by departure
        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode="Smart",
            departure_time=departure_time,
            charge_by=departure_time,
            pv_expected_kwh=pv_remaining_kwh,
            use_pv_charging=pv_for_ev >= deficit_kwh * 0.5,
            reason=(
                f"Smart mode: need {deficit_kwh:.1f} kWh by "
                f"{departure_time.strftime('%H:%M') if departure_time else '?'}, "
                f"PV remaining {pv_remaining_kwh:.1f} kWh"
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
        pv_tomorrow_kwh: float,
    ) -> DayChargingRecommendation:
        """Plan charging for tomorrow (affects tonight's charging)."""

        # PV won't help before an early morning departure
        early_departure = departure_time and departure_time.hour < 10
        pv_for_ev = pv_tomorrow_kwh * 0.6

        if early_departure or pv_for_ev < deficit_kwh:
            # Need to charge tonight — Smart mode with full-by-morning
            return DayChargingRecommendation(
                date=day_plan.date,
                trips=day_plan.trips,
                soc_needed_pct=required_soc,
                energy_needed_kwh=energy_needed,
                energy_to_charge_kwh=deficit_kwh,
                charge_mode="Smart",
                departure_time=departure_time,
                charge_by=departure_time,
                pv_expected_kwh=pv_tomorrow_kwh,
                use_pv_charging=False,
                reason=(
                    f"Charge tonight: need {deficit_kwh:.1f} kWh by "
                    f"{departure_time.strftime('%H:%M') if departure_time else 'morning'} "
                    f"(current {running_soc:.0f}%, need {required_soc:.0f}%)"
                ),
            )

        # Late departure tomorrow + good PV → can PV-charge tomorrow morning
        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode="Smart",
            departure_time=departure_time,
            charge_by=departure_time,
            pv_expected_kwh=pv_tomorrow_kwh,
            use_pv_charging=True,
            reason=(
                f"PV + grid tomorrow: {pv_tomorrow_kwh:.1f} kWh PV expected, "
                f"need {deficit_kwh:.1f} kWh, late departure "
                f"{departure_time.strftime('%H:%M') if departure_time else '?'}"
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
