"""Charging strategy — decides target wallbox power each control cycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum

import structlog

from charger import WallboxState

logger = structlog.get_logger()


class ChargeMode(str, Enum):
    OFF = "Off"
    PV_SURPLUS = "PV Surplus"
    SMART = "Smart"
    ECO = "Eco"
    FAST = "Fast"
    MANUAL = "Manual"


@dataclass
class ChargingContext:
    """All inputs for a single charging decision."""

    mode: ChargeMode
    wallbox: WallboxState
    grid_power_w: float        # positive = importing, negative = exporting
    pv_power_w: float          # total PV production (east + west)
    full_by_morning: bool
    departure_time: time | None
    target_energy_kwh: float
    session_energy_kwh: float
    now: datetime


@dataclass
class ChargingDecision:
    """Output: what the wallbox should do."""

    target_power_w: int        # 0 = pause, >0 = charge at this power
    reason: str                # human-readable explanation
    skip_control: bool = False # True = don't touch wallbox (Manual mode)


class ChargingStrategy:
    """Calculates target charging power based on mode and conditions.

    PV surplus formula:
        available_for_ev = current_ev_power - grid_power - grid_reserve

    This works because grid_power = house + ev - pv, so:
        available_for_ev = ev - (house + ev - pv) - reserve = pv - house - reserve
    """

    def __init__(
        self,
        max_power_w: int = 11000,
        min_power_w: int = 4200,
        eco_power_w: int = 5000,
        grid_reserve_w: int = 200,
        start_hysteresis_w: int = 300,
        ramp_step_w: int = 500,
    ) -> None:
        self.max_power_w = max_power_w
        self.min_power_w = min_power_w
        self.eco_power_w = eco_power_w
        self.grid_reserve_w = grid_reserve_w
        self.start_hysteresis_w = start_hysteresis_w
        self.ramp_step_w = ramp_step_w

        self._was_pv_charging = False
        self._last_target_w: int = 0

    def decide(self, ctx: ChargingContext) -> ChargingDecision:
        """Calculate the target charging power for this cycle."""

        # --- Off / Manual ---
        if ctx.mode == ChargeMode.OFF:
            self._reset()
            return ChargingDecision(0, "Charging off")

        if ctx.mode == ChargeMode.MANUAL:
            return ChargingDecision(
                0, "Manual mode — service not controlling wallbox",
                skip_control=True,
            )

        # --- No vehicle ---
        if not ctx.wallbox.vehicle_connected:
            self._reset()
            return ChargingDecision(0, "No vehicle connected")

        # --- Target reached (when full-by-morning is set) ---
        if ctx.full_by_morning and ctx.session_energy_kwh >= ctx.target_energy_kwh:
            self._reset()
            return ChargingDecision(
                0,
                f"Target reached ({ctx.session_energy_kwh:.1f}"
                f"/{ctx.target_energy_kwh:.0f} kWh)",
            )

        # --- Mode-specific strategy ---
        if ctx.mode == ChargeMode.FAST:
            decision = self._fixed(self.max_power_w, "Fast")
        elif ctx.mode == ChargeMode.ECO:
            decision = self._fixed(self.eco_power_w, "Eco")
        elif ctx.mode == ChargeMode.PV_SURPLUS:
            decision = self._pv_surplus(ctx)
        elif ctx.mode == ChargeMode.SMART:
            decision = self._smart(ctx)
        else:
            decision = ChargingDecision(0, f"Unknown mode: {ctx.mode}")

        # --- Full-by-morning deadline escalation ---
        if ctx.full_by_morning and ctx.mode in (
            ChargeMode.PV_SURPLUS, ChargeMode.SMART,
        ):
            decision = self._apply_deadline_escalation(ctx, decision)

        # --- Ramp limiting (smooth power transitions) ---
        decision = self._apply_ramp(decision)

        # --- Update state ---
        self._was_pv_charging = decision.target_power_w > 0
        self._last_target_w = decision.target_power_w

        return decision

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    def _fixed(self, power_w: int, label: str) -> ChargingDecision:
        return ChargingDecision(power_w, f"{label} charging at {power_w} W")

    def _pv_surplus(self, ctx: ChargingContext) -> ChargingDecision:
        """Track PV surplus — charge only from solar excess."""
        available = self._calc_pv_available(ctx)

        # Hysteresis: require more surplus to START than to KEEP charging
        threshold = (
            self.min_power_w
            if self._was_pv_charging
            else self.min_power_w + self.start_hysteresis_w
        )

        if available >= threshold:
            target = self._clamp(available)
            return ChargingDecision(
                target,
                f"PV surplus charging ({available:.0f} W available)",
            )

        if self._was_pv_charging:
            return ChargingDecision(
                0,
                f"PV surplus below minimum ({available:.0f} W < {self.min_power_w} W)",
            )

        return ChargingDecision(
            0,
            f"Waiting for PV surplus ({available:.0f}/{threshold} W)",
        )

    def _smart(self, ctx: ChargingContext) -> ChargingDecision:
        """PV surplus during the day; deadline logic handles grid fill."""
        pv = self._pv_surplus(ctx)
        if pv.target_power_w > 0:
            return ChargingDecision(pv.target_power_w, f"Smart: {pv.reason}")
        return ChargingDecision(0, f"Smart: {pv.reason}")

    # ------------------------------------------------------------------
    # Full-by-morning deadline escalation
    # ------------------------------------------------------------------

    def _apply_deadline_escalation(
        self,
        ctx: ChargingContext,
        base: ChargingDecision,
    ) -> ChargingDecision:
        """If the deadline is approaching, escalate to grid charging."""
        if not ctx.departure_time:
            return base

        remaining_kwh = max(0.0, ctx.target_energy_kwh - ctx.session_energy_kwh)
        if remaining_kwh <= 0:
            return base  # already handled by target-reached check above

        hours_left = self._hours_until(ctx.departure_time, ctx.now)
        if hours_left <= 0:
            return ChargingDecision(
                self.max_power_w,
                "Past departure — fast charging remaining "
                f"{remaining_kwh:.1f} kWh",
            )

        # Required average power to finish on time (+ 10 % margin)
        required_w = (remaining_kwh / hours_left) * 1000 * 1.1

        if required_w <= base.target_power_w:
            return base  # current power is sufficient

        escalated = self._clamp(int(required_w))
        if escalated <= 0:
            # Required power is below wallbox minimum but > 0.
            # This means we have lots of time — no escalation needed.
            return base

        return ChargingDecision(
            max(base.target_power_w, escalated),
            f"Deadline: {remaining_kwh:.1f} kWh in {hours_left:.1f} h "
            f"→ {required_w:.0f} W needed",
        )

    # ------------------------------------------------------------------
    # Ramp limiting
    # ------------------------------------------------------------------

    def _apply_ramp(self, decision: ChargingDecision) -> ChargingDecision:
        """Limit power step size between cycles for smooth transitions."""
        if decision.skip_control:
            return decision

        target = decision.target_power_w
        last = self._last_target_w

        # Only ramp between two non-zero values (instant on/off is fine)
        if last > 0 and target > 0 and abs(target - last) > self.ramp_step_w:
            if target > last:
                ramped = last + self.ramp_step_w
            else:
                ramped = last - self.ramp_step_w
            ramped = max(0, ramped)
            return ChargingDecision(
                ramped,
                f"{decision.reason} (ramping {last}→{ramped} W)",
            )

        return decision

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _calc_pv_available(self, ctx: ChargingContext) -> float:
        """Power available from PV surplus for the EV.

        The grid meter (Shelly 3EM) sees the net of everything behind it,
        including a home battery.  When the battery charges, it reduces the
        visible surplus; when it discharges, it increases it.  This means
        the formula automatically gives the EV whatever surplus is left
        *after* the battery BMS has taken its share — no explicit battery
        handling is needed here.
        """
        return ctx.wallbox.current_power_w - ctx.grid_power_w - self.grid_reserve_w

    def _clamp(self, power_w: float) -> int:
        """Clamp to valid wallbox range or 0 if below minimum."""
        p = int(power_w)
        if p < self.min_power_w:
            return 0
        return min(p, self.max_power_w)

    def _reset(self) -> None:
        self._was_pv_charging = False
        self._last_target_w = 0

    @staticmethod
    def _hours_until(target_time: time, now: datetime) -> float:
        """Hours from *now* until *target_time* (today or tomorrow)."""
        target_dt = now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )
        if target_dt <= now:
            target_dt += timedelta(days=1)
        return (target_dt - now).total_seconds() / 3600
