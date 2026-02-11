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
    grid_power_w: float        # positive = exporting to grid, negative = importing
    pv_power_w: float          # total PV production (DC input)
    battery_power_w: float     # positive = charging, negative = discharging
    battery_soc_pct: float     # 0–100 %
    pv_forecast_remaining_kwh: float  # remaining PV kWh expected today
    full_by_morning: bool
    departure_time: time | None
    target_energy_kwh: float   # manual fallback target (kWh to add)
    session_energy_kwh: float
    ev_soc_pct: float | None           # EV battery SoC from car (None = unavailable)
    ev_battery_capacity_kwh: float     # EV battery capacity (e.g. 77 kWh)
    ev_target_soc_pct: float           # target SoC % (e.g. 80)
    now: datetime

    @property
    def energy_needed_kwh(self) -> float:
        """kWh still needed to reach target.

        Prefers SoC-based calculation when EV SoC is available;
        falls back to manual target_energy_kwh vs session_energy_kwh.
        """
        if self.ev_soc_pct is not None and self.ev_battery_capacity_kwh > 0:
            delta_pct = max(0.0, self.ev_target_soc_pct - self.ev_soc_pct)
            return delta_pct / 100.0 * self.ev_battery_capacity_kwh
        return max(0.0, self.target_energy_kwh - self.session_energy_kwh)

    @property
    def target_reached(self) -> bool:
        """Whether the charging target has been reached."""
        if self.ev_soc_pct is not None:
            return self.ev_soc_pct >= self.ev_target_soc_pct
        return self.session_energy_kwh >= self.target_energy_kwh


@dataclass
class ChargingDecision:
    """Output: what the wallbox should do."""

    target_power_w: int        # 0 = pause, >0 = charge at this power
    reason: str                # human-readable explanation
    skip_control: bool = False # True = don't touch wallbox (Manual mode)


class ChargingStrategy:
    """Calculates target charging power based on mode and conditions.

    PV surplus formula (grid meter: positive = exporting, negative = importing):

        pv_available = grid_power + ev_power + battery_charge_power - reserve

    The grid meter reflects the net of everything behind it:
        grid = pv - house - ev - battery_charge  (when exporting)

    So: pv_available = pv - house - reserve  (which is what we want).

    When the home battery is charging (battery_power > 0), this formula
    "reclaims" that power for the EV — the EV takes priority over storage.

    When the battery is discharging (battery_power < 0), the available power
    is reduced, because we only want real PV surplus, not battery energy.

    Battery assist: On top of the PV-only surplus, we can allow limited
    battery discharge for the EV if the PV forecast looks good and the
    battery has enough charge. This is capped to protect battery longevity.
    """

    def __init__(
        self,
        max_power_w: int = 11000,
        min_power_w: int = 4200,
        eco_power_w: int = 5000,
        grid_reserve_w: int = 200,
        start_hysteresis_w: int = 300,
        ramp_step_w: int = 500,
        battery_min_soc_pct: float = 20.0,
        battery_ev_assist_max_w: float = 2000.0,
        pv_forecast_good_kwh: float = 15.0,
    ) -> None:
        self.max_power_w = max_power_w
        self.min_power_w = min_power_w
        self.eco_power_w = eco_power_w
        self.grid_reserve_w = grid_reserve_w
        self.start_hysteresis_w = start_hysteresis_w
        self.ramp_step_w = ramp_step_w
        self.battery_min_soc_pct = battery_min_soc_pct
        self.battery_ev_assist_max_w = battery_ev_assist_max_w
        self.pv_forecast_good_kwh = pv_forecast_good_kwh

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

        # --- Target SoC reached (applies to all modes when SoC is available) ---
        if ctx.target_reached:
            self._reset()
            if ctx.ev_soc_pct is not None:
                return ChargingDecision(
                    0,
                    f"Target SoC reached ({ctx.ev_soc_pct:.0f}%"
                    f" >= {ctx.ev_target_soc_pct:.0f}%)",
                )
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
        """Track PV surplus — charge primarily from solar excess.

        May add limited battery assist if forecast is good and SoC allows.
        """
        pv_only = self._calc_pv_only_available(ctx)
        assist = self._calc_battery_assist(ctx, pv_only)
        available = pv_only + assist

        # Hysteresis: require more surplus to START than to KEEP charging
        threshold = (
            self.min_power_w
            if self._was_pv_charging
            else self.min_power_w + self.start_hysteresis_w
        )

        if available >= threshold:
            target = self._clamp(available)
            parts = [f"PV surplus {pv_only:.0f} W"]
            if assist > 0:
                parts.append(f"+ {assist:.0f} W battery assist")
            return ChargingDecision(target, f"{' '.join(parts)} → {target} W")

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

        remaining_kwh = ctx.energy_needed_kwh
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
    # PV surplus & battery assist
    # ------------------------------------------------------------------

    def _calc_pv_only_available(self, ctx: ChargingContext) -> float:
        """Power available from PV surplus only (no battery discharge).

        Formula: grid_power + ev_power + battery_power - reserve

        grid_power is positive when exporting.  When the home battery is
        charging (battery_power > 0) that power is "reclaimed" — the EV
        takes priority over filling the battery.  When the battery is
        discharging (battery_power < 0), available is reduced so we don't
        count battery energy as PV surplus.
        """
        return (
            ctx.grid_power_w
            + ctx.wallbox.current_power_w
            + ctx.battery_power_w
            - self.grid_reserve_w
        )

    def _calc_battery_assist(
        self, ctx: ChargingContext, pv_only_available: float,
    ) -> float:
        """Extra power the home battery can contribute for EV charging.

        Rules:
        - Only assist when battery SoC is above the floor (battery_min_soc_pct)
        - Cap discharge rate at battery_ev_assist_max_w (protect longevity)
        - Scale assist by PV forecast: good forecast → more aggressive
        - Only assist when there IS some PV surplus (just not enough alone)
        - Never assist if battery is already discharging heavily for the house
        """
        # No assist if battery SoC too low
        if ctx.battery_soc_pct <= self.battery_min_soc_pct:
            return 0.0

        # No assist if there's zero PV (e.g. nighttime) — save battery
        if ctx.pv_power_w < 100:
            return 0.0

        # No assist if PV surplus is negative (house consuming more than PV)
        if pv_only_available < 0:
            return 0.0

        # Scale assist limit by PV forecast quality
        # Good forecast → allow up to max assist; poor forecast → reduce
        forecast_factor = min(
            1.0, ctx.pv_forecast_remaining_kwh / self.pv_forecast_good_kwh,
        )

        # Scale by SoC: full battery → full assist, at floor → zero
        soc_headroom = (
            (ctx.battery_soc_pct - self.battery_min_soc_pct)
            / (100.0 - self.battery_min_soc_pct)
        )
        soc_factor = min(1.0, max(0.0, soc_headroom))

        max_assist = self.battery_ev_assist_max_w * forecast_factor * soc_factor

        # How much more we need to reach wallbox minimum
        shortfall = self.min_power_w - pv_only_available
        if shortfall <= 0:
            return 0.0  # PV alone is already enough

        return min(shortfall, max_assist)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
