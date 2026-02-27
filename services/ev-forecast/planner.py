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
    cumulative_deficit_kwh: float = 0.0  # Running total of uncharged energy

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
                    "cumulative_deficit_kwh": round(d.cumulative_deficit_kwh, 1),
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
        pv_forecast_kwh: list[float] | None = None,
    ) -> ChargingPlan:
        """Generate a multi-day charging plan based purely on demand.

        Args:
            vehicle: Current vehicle state (SoC, plug, etc.)
            day_plans: Trip predictions per day
            pv_forecast_kwh: Optional PV forecast (one value per day, starting with today)
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

        # Track running SoC and cumulative deficit through the planning horizon
        default_soc = self._default_assumed_soc
        running_soc = current_soc if current_soc is not None else default_soc
        running_energy = current_energy if current_energy is not None else self._soc_to_kwh(default_soc)
        cumulative_deficit = 0.0

        for i, day_plan in enumerate(day_plans):
            # Get PV forecast for this day if available
            pv_forecast_day = pv_forecast_kwh[i] if pv_forecast_kwh and i < len(pv_forecast_kwh) else None

            rec = self._plan_day(
                day_plan=day_plan,
                running_soc=running_soc,
                running_energy=running_energy,
                is_today=(i == 0),
                is_tomorrow=(i == 1),
                now=now,
                pv_forecast_kwh=pv_forecast_day,
                cumulative_deficit=cumulative_deficit,
            )
            plan.days.append(rec)

            # Update running state: subtract trip energy, add planned charge
            trip_energy = rec.energy_needed_kwh
            charge_energy = rec.energy_to_charge_kwh
            running_energy = running_energy - trip_energy + charge_energy
            running_soc = self._kwh_to_soc(running_energy)

            # Update cumulative deficit
            if rec.energy_to_charge_kwh < rec.energy_needed_kwh:
                cumulative_deficit += (rec.energy_needed_kwh - rec.energy_to_charge_kwh)

        return plan

    async def apply_plan(
        self,
        plan: ChargingPlan,
        charge_mode_entity: str,
        full_by_morning_entity: str,
        departure_time_entity: str,
        target_energy_entity: str,
        audi_vin: str = "",
        audi_set_target_soc: bool = True,
        wallbox_vehicle_state_entity: str = "",
        target_soc_entity: str = "",
    ) -> None:
        """Write the immediate plan to HA input helpers and optionally set Audi target SoC.

        Respects manual overrides: if the current HA departure time or target
        SoC was set to a value that differs from the plan AND from the last
        value this planner wrote, assume manual override and preserve it.
        """
        immediate = plan.immediate_action
        if not immediate:
            return

        if not plan.vehicle_plugged_in:
            logger.info("vehicle_not_plugged_in, skipping_ha_update")
            return

        # --- Detect manual overrides ---
        # Read current HA values to detect if user/orchestrator changed them
        manual_departure = False
        manual_target_soc = False

        try:
            current_departure_state = await self._ha.get_state(departure_time_entity)
            current_dep_str = current_departure_state.get("state", "")
            if current_dep_str and current_dep_str not in ("unavailable", "unknown"):
                parts = current_dep_str.split(":")
                current_dep = time(int(parts[0]), int(parts[1]))
                plan_dep = immediate.departure_time
                last_dep = getattr(self, "_last_applied_departure", None)
                # If current differs from both plan and last-applied → manual override
                if plan_dep and current_dep != plan_dep and current_dep != last_dep:
                    manual_departure = True
                    logger.info(
                        "manual_departure_override_detected",
                        current=current_dep_str,
                        plan=plan_dep.strftime("%H:%M") if plan_dep else None,
                        last_applied=last_dep.strftime("%H:%M") if last_dep else None,
                    )
        except Exception:
            pass

        if target_soc_entity:
            try:
                current_soc_state = await self._ha.get_state(target_soc_entity)
                current_soc_val = current_soc_state.get("state", "")
                if current_soc_val not in ("unavailable", "unknown", ""):
                    current_soc = float(current_soc_val)
                    last_soc = getattr(self, "_last_applied_target_soc", None)
                    if current_soc != last_soc and current_soc > (plan.current_soc_pct + 1):
                        manual_target_soc = True
                        logger.info(
                            "manual_target_soc_override_detected",
                            current=current_soc,
                            last_applied=last_soc,
                        )
            except Exception:
                pass

        # Calculate target SoC for Audi (current SoC + energy needed)
        target_soc_pct = None
        if audi_set_target_soc and immediate.energy_to_charge_kwh > 0:
            # Current energy = current_soc_pct * net_capacity / 100
            # Target energy = current energy + energy_to_charge
            # Target SoC % = (target energy / net_capacity) * 100
            current_energy_kwh = (plan.current_soc_pct / 100.0) * self._net_capacity
            target_energy_kwh = current_energy_kwh + immediate.energy_to_charge_kwh
            target_soc_pct = min(100.0, (target_energy_kwh / self._net_capacity) * 100.0)
            target_soc_pct = round(target_soc_pct)

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

        # Set departure time (respect manual override)
        if immediate.departure_time and not manual_departure:
            try:
                await self._ha.call_service("input_datetime", "set_datetime", {
                    "entity_id": departure_time_entity,
                    "time": immediate.departure_time.strftime("%H:%M:%S"),
                })
                self._last_applied_departure = immediate.departure_time
            except Exception:
                logger.exception("set_departure_time_failed")
        elif manual_departure:
            logger.info("departure_time_preserved_manual_override")

        # Set target energy
        if immediate.energy_to_charge_kwh > 0:
            try:
                await self._ha.call_service("input_number", "set_value", {
                    "entity_id": target_energy_entity,
                    "value": min(self._net_capacity, round(immediate.energy_to_charge_kwh)),
                })
            except Exception:
                logger.exception("set_target_energy_failed")

        # Set Audi target SoC via audiconnect integration
        # Only when: plugged in AT HOME (wallbox) + AI-controlled mode (not Off)
        ai_controlled_modes = {"Smart", "PV Surplus", "Manual"}
        
        # Check if car is plugged in at home wallbox
        plugged_in_at_home = False
        if wallbox_vehicle_state_entity and plan.vehicle_plugged_in:
            try:
                state = await self._ha.get_state(wallbox_vehicle_state_entity)
                wallbox_state = state.get("state", "0")
                # Amtron states: 2=Connected, 3=Charging, 4=Charging with vent
                plugged_in_at_home = wallbox_state in ["2", "3", "4"]
            except Exception:
                logger.warning("wallbox_state_check_failed", entity=wallbox_vehicle_state_entity)
        
        should_set_audi = (
            target_soc_pct is not None
            and audi_set_target_soc
            and plugged_in_at_home  # Must be at home wallbox, not away
            and immediate.charge_mode in ai_controlled_modes
        )
        
        if should_set_audi:
            try:
                service_data = {"target_soc": int(target_soc_pct)}
                if audi_vin:
                    service_data["vin"] = audi_vin
                
                await self._ha.call_service("audiconnect", "set_target_soc", service_data)
                logger.info(
                    "audi_target_soc_set",
                    target_soc=int(target_soc_pct),
                    current_soc=round(plan.current_soc_pct),
                    energy_to_charge=round(immediate.energy_to_charge_kwh, 1),
                    mode=immediate.charge_mode,
                )
            except Exception:
                logger.exception("set_audi_target_soc_failed")
        elif target_soc_pct is not None and audi_set_target_soc:
            # Log why we skipped
            skip_reason = "mode_off" if immediate.charge_mode not in ai_controlled_modes else (
                "not_at_home_wallbox" if not plugged_in_at_home else "unknown"
            )
            logger.info(
                "audi_target_soc_skipped",
                plugged_in=plan.vehicle_plugged_in,
                plugged_in_at_home=plugged_in_at_home,
                mode=immediate.charge_mode,
                reason=skip_reason,
            )

        logger.info(
            "plan_applied",
            mode=immediate.charge_mode,
            target_kwh=round(immediate.energy_to_charge_kwh, 1),
            audi_target_soc=int(target_soc_pct) if target_soc_pct else None,
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
        pv_forecast_kwh: float | None = None,
        cumulative_deficit: float = 0.0,
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
                cumulative_deficit_kwh=cumulative_deficit,
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
                cumulative_deficit_kwh=cumulative_deficit,
            )

        # We need to charge — determine urgency and mode
        if is_today:
            return self._plan_today(
                day_plan, departure_time, deficit_kwh, required_soc,
                energy_needed, running_soc, now, pv_forecast_kwh, cumulative_deficit,
            )

        if is_tomorrow:
            return self._plan_tomorrow(
                day_plan, departure_time, deficit_kwh, required_soc,
                energy_needed, running_soc, pv_forecast_kwh, cumulative_deficit,
            )

        # Future days (3+ days out) — smarter charge mode decision
        # If cumulative deficit is large (>30 kWh) and day is within 3 days, use Smart mode
        # Otherwise if deficit is small and PV forecast good, keep PV Surplus
        days_out = (day_plan.date - now.date()).days
        
        if cumulative_deficit > 30 and days_out <= 3:
            mode = "Smart"
            urgency = "medium"
            reason = (
                f"Large cumulative deficit ({cumulative_deficit:.1f} kWh) — "
                f"need {deficit_kwh:.1f} kWh, Smart mode to ensure coverage"
            )
        elif pv_forecast_kwh and pv_forecast_kwh > 15:
            mode = "PV Surplus"
            urgency = "low"
            reason = (
                f"Good PV forecast ({pv_forecast_kwh:.1f} kWh) — "
                f"need {deficit_kwh:.1f} kWh, PV Surplus mode"
            )
        else:
            mode = "Smart"
            urgency = "low"
            reason = f"Future day — need {deficit_kwh:.1f} kWh, Smart mode for flexibility"

        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode=mode,
            departure_time=departure_time,
            charge_by=departure_time,
            urgency=urgency,
            reason=reason,
            cumulative_deficit_kwh=cumulative_deficit,
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
        pv_forecast_kwh: float | None = None,
        cumulative_deficit: float = 0.0,
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
                cumulative_deficit_kwh=cumulative_deficit,
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
                cumulative_deficit_kwh=cumulative_deficit,
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
                cumulative_deficit_kwh=cumulative_deficit,
            )

        # Plenty of time — consider PV forecast
        # If good PV forecast (>15 kWh) and deficit is small, prefer PV Surplus
        # If poor PV forecast (<5 kWh) and deficit exists, use Smart mode
        if pv_forecast_kwh and pv_forecast_kwh > 15 and deficit_kwh < 20:
            mode = "PV Surplus"
            reason = (
                f"Good PV forecast ({pv_forecast_kwh:.1f} kWh remaining) — "
                f"need {deficit_kwh:.1f} kWh by "
                f"{departure_time.strftime('%H:%M') if departure_time else '?'}, "
                f"PV can cover it"
            )
        elif pv_forecast_kwh and pv_forecast_kwh < 5 and deficit_kwh > 10:
            mode = "Smart"
            reason = (
                f"Low PV forecast ({pv_forecast_kwh:.1f} kWh remaining) — "
                f"need {deficit_kwh:.1f} kWh, Smart mode for reliability"
            )
        else:
            mode = "Smart"
            reason = (
                f"Need {deficit_kwh:.1f} kWh by "
                f"{departure_time.strftime('%H:%M') if departure_time else '?'} "
                f"({hours_until:.0f}h available — PV + grid)"
            )

        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode=mode,
            departure_time=departure_time,
            charge_by=departure_time,
            urgency="medium",
            reason=reason,
            cumulative_deficit_kwh=cumulative_deficit,
        )

    def _plan_tomorrow(
        self,
        day_plan: DayPlan,
        departure_time: time | None,
        deficit_kwh: float,
        required_soc: float,
        energy_needed: float,
        running_soc: float,
        pv_forecast_kwh: float | None = None,
        cumulative_deficit: float = 0.0,
    ) -> DayChargingRecommendation:
        """Plan charging for tomorrow (may need overnight charging)."""

        early_departure = departure_time and departure_time.hour < self._early_departure_hour

        if early_departure:
            # Need to charge tonight — but check PV forecast for tomorrow
            # If tomorrow's PV forecast is poor (<5 kWh), charge overnight
            # If good (>15 kWh), we might wait — but for early departure, safer to charge
            if pv_forecast_kwh and pv_forecast_kwh < 5:
                reason = (
                    f"Charge overnight (poor PV forecast {pv_forecast_kwh:.1f} kWh): "
                    f"need {deficit_kwh:.1f} kWh by "
                    f"{departure_time.strftime('%H:%M') if departure_time else 'morning'}"
                )
            else:
                reason = (
                    f"Charge overnight: need {deficit_kwh:.1f} kWh by "
                    f"{departure_time.strftime('%H:%M') if departure_time else 'morning'} "
                    f"(current {running_soc:.0f}%, need {required_soc:.0f}%)"
                )

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
                reason=reason,
                cumulative_deficit_kwh=cumulative_deficit,
            )

        # Late departure — can charge tomorrow with PV
        # If PV forecast is good (>15 kWh), prefer waiting
        # If poor (<5 kWh), recommend overnight Smart charging
        if pv_forecast_kwh and pv_forecast_kwh > 15:
            mode = "PV Surplus"
            reason = (
                f"Tomorrow: good PV forecast ({pv_forecast_kwh:.1f} kWh), "
                f"need {deficit_kwh:.1f} kWh, late departure "
                f"{departure_time.strftime('%H:%M') if departure_time else '?'} "
                f"— wait for PV"
            )
        elif pv_forecast_kwh and pv_forecast_kwh < 5:
            mode = "Smart"
            reason = (
                f"Tomorrow: poor PV forecast ({pv_forecast_kwh:.1f} kWh), "
                f"need {deficit_kwh:.1f} kWh — recommend overnight charging"
            )
        else:
            mode = "Smart"
            reason = (
                f"Tomorrow: need {deficit_kwh:.1f} kWh, "
                f"late departure {departure_time.strftime('%H:%M') if departure_time else '?'} "
                f"— PV + grid can cover it"
            )

        return DayChargingRecommendation(
            date=day_plan.date,
            trips=day_plan.trips,
            soc_needed_pct=required_soc,
            energy_needed_kwh=energy_needed,
            energy_to_charge_kwh=deficit_kwh,
            charge_mode=mode,
            departure_time=departure_time,
            charge_by=departure_time,
            urgency="low",
            reason=reason,
            cumulative_deficit_kwh=cumulative_deficit,
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
