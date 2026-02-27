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
    house_power_w: float           # current household consumption (W)
    battery_capacity_kwh: float    # home battery usable capacity (kWh)
    battery_target_eod_soc_pct: float  # acceptable end-of-day battery SoC %
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

    # --- Detailed context for HA sensors ---
    pv_surplus_w: float = 0.0           # PV-only available power (before battery assist)
    battery_assist_w: float = 0.0       # Battery assist contribution (W)
    battery_assist_reason: str = ""     # Why battery is/isn't assisting
    deadline_active: bool = False       # Whether deadline escalation is active
    deadline_hours_left: float = -1.0   # Hours until departure (-1 = no deadline)
    deadline_required_w: float = 0.0    # Required avg power to meet deadline
    energy_remaining_kwh: float = 0.0   # kWh still needed (target - session)


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
        min_power_w: int = 3600,
        eco_power_w: int = 5000,
        grid_reserve_w: int = 200,
        start_hysteresis_w: int = 300,
        ramp_step_w: int = 500,
        battery_min_soc_pct: float = 20.0,
        battery_ev_assist_max_w: float = 3500.0,
        battery_capacity_kwh: float = 7.0,
        battery_target_eod_soc_pct: float = 90.0,
        pv_forecast_good_kwh: float = 15.0,
        night_charging_buffer_hours: float = 1.0,
    ) -> None:
        self.max_power_w = max_power_w
        self.min_power_w = min_power_w
        self.eco_power_w = eco_power_w
        self.grid_reserve_w = grid_reserve_w
        self.start_hysteresis_w = start_hysteresis_w
        self.ramp_step_w = ramp_step_w
        self.battery_min_soc_pct = battery_min_soc_pct
        self.battery_ev_assist_max_w = battery_ev_assist_max_w
        self.battery_capacity_kwh = battery_capacity_kwh
        self.battery_target_eod_soc_pct = battery_target_eod_soc_pct
        self.pv_forecast_good_kwh = pv_forecast_good_kwh
        self.night_charging_buffer_hours = night_charging_buffer_hours

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

        # --- Target SoC reached — continue topping up with PV surplus ---
        if ctx.target_reached:
            # Plan target met — but in PV Surplus/Smart modes, continue topping up
            # to 80% SoC (or ev_target_soc_pct) if PV surplus is available.
            # Economics: PV → EV saves 7ct/kWh vs exporting.
            if ctx.mode in (ChargeMode.PV_SURPLUS, ChargeMode.SMART) and ctx.pv_power_w > 100:
                # Check if we're below the actual target SoC (80% default)
                if ctx.ev_soc_pct is not None and ctx.ev_soc_pct < ctx.ev_target_soc_pct:
                    surplus_decision = self._pv_surplus(ctx)
                    if surplus_decision.target_power_w > 0:
                        surplus_decision.reason = (
                            f"Plan target reached — topping up to {ctx.ev_target_soc_pct:.0f}% "
                            f"(currently {ctx.ev_soc_pct:.0f}%): {surplus_decision.reason}"
                        )
                        return surplus_decision
                else:
                    # Already at target SoC (80%) — try PV surplus one more time
                    surplus_decision = self._pv_surplus(ctx)
                    if surplus_decision.target_power_w > 0:
                        surplus_decision.reason = (
                            f"Plan target reached — opportunistic PV surplus: "
                            f"{surplus_decision.reason}"
                        )
                        return surplus_decision

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

        Economics: PV → EV saves 7ct/kWh vs exporting (employer reimburses 25ct,
        feed-in only 7ct). So be MORE aggressive about PV charging:
        - Lower hysteresis when EV SoC < 50% (car needs charge more urgently)
        - Continue topping up to target SoC even after plan target is met
        - When home battery >80%, prioritize EV over further battery charging
        """
        pv_only = self._calc_pv_only_available(ctx)
        assist, assist_reason = self._calc_battery_assist_detailed(ctx, pv_only)
        available = pv_only + assist

        # Economic hysteresis: lower start threshold when EV SoC is low
        # (more valuable to charge car than export to grid)
        ev_soc_low = ctx.ev_soc_pct is not None and ctx.ev_soc_pct < 50
        hysteresis_reduction = 150 if ev_soc_low else 0

        threshold = (
            self.min_power_w
            if self._was_pv_charging
            else self.min_power_w + self.start_hysteresis_w - hysteresis_reduction
        )

        base_fields = {
            "pv_surplus_w": round(pv_only, 1),
            "battery_assist_w": round(assist, 1),
            "battery_assist_reason": assist_reason,
        }

        if available >= threshold:
            target = self._clamp(available)
            parts = [f"PV surplus {pv_only:.0f} W"]
            if assist > 0:
                parts.append(f"+ {assist:.0f} W battery assist")
            # Add economic reasoning when relevant
            if ctx.battery_soc_pct > 80 and ctx.battery_power_w > 0:
                parts.append("(prioritize EV over battery)")
            if ev_soc_low:
                parts.append("(low EV SoC — economic priority)")
            return ChargingDecision(
                target, f"{' '.join(parts)} → {target} W", **base_fields,
            )

        if self._was_pv_charging:
            return ChargingDecision(
                0,
                f"PV surplus below minimum ({available:.0f} W < {self.min_power_w} W)",
                **base_fields,
            )

        return ChargingDecision(
            0,
            f"Waiting for PV surplus ({available:.0f}/{threshold} W)",
            **base_fields,
        )

    def _smart(self, ctx: ChargingContext) -> ChargingDecision:
        """PV surplus during the day; night charging window when full_by_morning=ON.

        Key principle: NEVER export to grid when the EV target isn't reached.
        Use battery to supplement PV if needed. Charging the EV at 25ct/kWh
        reimbursement is always better than exporting at 7ct/kWh.
        """
        # During nighttime (22:00-05:00) with full_by_morning and a deadline, use smart timing
        current_hour = ctx.now.hour
        is_nighttime = current_hour >= 22 or current_hour < 5

        if is_nighttime and ctx.full_by_morning and ctx.departure_time:
            return self._nighttime_smart(ctx)

        # Daytime: try PV surplus first
        pv = self._pv_surplus(ctx)
        if pv.target_power_w > 0:
            return ChargingDecision(
                pv.target_power_w, f"Smart: {pv.reason}",
                pv_surplus_w=pv.pv_surplus_w,
                battery_assist_w=pv.battery_assist_w,
                battery_assist_reason=pv.battery_assist_reason,
            )

        # Grid export prevention: if we're exporting to grid and target
        # isn't reached, charge at min power using battery + PV.
        # This is the core "smart" logic — don't waste energy to the grid.
        if ctx.grid_power_w > 200 and not ctx.target_reached:
            return self._grid_export_prevention(ctx, pv)

        return ChargingDecision(
            0, f"Smart: {pv.reason}",
            pv_surplus_w=pv.pv_surplus_w,
            battery_assist_w=pv.battery_assist_w,
            battery_assist_reason=pv.battery_assist_reason,
        )

    def _grid_export_prevention(
        self, ctx: ChargingContext, pv_decision: ChargingDecision,
    ) -> ChargingDecision:
        """Prevent grid export by using battery + PV to charge the EV.

        When we're exporting to grid and the EV needs charging, it makes
        zero economic sense to export at 7ct when we can charge the EV at 25ct.
        Use the home battery to bridge the gap to min_power_w.
        """
        # How much power is being exported + what PV surplus exists
        pv_only = self._calc_pv_only_available(ctx)
        total_available = max(0.0, pv_only)

        # How much more do we need from battery to reach min charging power?
        battery_needed = self.min_power_w - total_available

        # Check battery constraints
        if ctx.battery_soc_pct <= self.battery_min_soc_pct:
            return ChargingDecision(
                0,
                f"Smart: exporting {ctx.grid_power_w:.0f} W but battery too low "
                f"({ctx.battery_soc_pct:.0f}% <= {self.battery_min_soc_pct:.0f}%)",
                pv_surplus_w=pv_decision.pv_surplus_w,
                battery_assist_w=0,
                battery_assist_reason=f"SoC at floor ({ctx.battery_soc_pct:.0f}%)",
            )

        # Can we get enough from battery?
        battery_available = min(battery_needed, self.battery_ev_assist_max_w)

        if total_available + battery_available >= self.min_power_w:
            target = self._clamp(total_available + battery_available)
            if target > 0:
                return ChargingDecision(
                    target,
                    f"Smart: grid export prevention — PV {total_available:.0f} W "
                    f"+ battery {battery_available:.0f} W → {target} W "
                    f"(prevent {ctx.grid_power_w:.0f} W export)",
                    pv_surplus_w=round(pv_only, 1),
                    battery_assist_w=round(battery_available, 1),
                    battery_assist_reason=(
                        f"Export prevention: {battery_needed:.0f} W needed from battery, "
                        f"SoC {ctx.battery_soc_pct:.0f}%"
                    ),
                )

        # Can't reach min_power_w even with battery — still exporting though
        return ChargingDecision(
            0,
            f"Smart: exporting {ctx.grid_power_w:.0f} W but can't reach min "
            f"({total_available:.0f} + {battery_available:.0f} < {self.min_power_w} W)",
            pv_surplus_w=pv_decision.pv_surplus_w,
            battery_assist_w=0,
            battery_assist_reason="Insufficient combined power for min charge rate",
        )

    def _nighttime_smart(self, ctx: ChargingContext) -> ChargingDecision:
        """Smart nighttime charging: charge as late as possible before departure.

        Calculate required charging time and start charging only when necessary
        to meet the deadline (with a safety buffer).
        """
        energy_needed = ctx.energy_needed_kwh
        if energy_needed <= 0:
            return ChargingDecision(0, "Nighttime: target already reached")

        hours_until_departure = self._hours_until(ctx.departure_time, ctx.now)

        # Calculate required charging time at eco power
        charging_power_kw = self.eco_power_w / 1000.0
        hours_needed = energy_needed / charging_power_kw

        # Add buffer for safety
        hours_needed_with_buffer = hours_needed + self.night_charging_buffer_hours

        # If we're within the charging window, start charging
        if hours_until_departure <= hours_needed_with_buffer:
            return ChargingDecision(
                self.eco_power_w,
                f"Night charging window: need {energy_needed:.1f} kWh in "
                f"{hours_until_departure:.1f}h ({hours_needed:.1f}h + buffer)",
            )

        # Too early — wait to minimize grid usage
        wait_hours = hours_until_departure - hours_needed_with_buffer
        return ChargingDecision(
            0,
            f"Nighttime: waiting {wait_hours:.1f}h before charging "
            f"({energy_needed:.1f} kWh needed, starts at "
            f"{(ctx.now + timedelta(hours=wait_hours)).strftime('%H:%M')})",
        )

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

        # Populate deadline context on the base decision regardless of escalation
        base.deadline_active = True
        base.deadline_hours_left = round(hours_left, 2)
        base.energy_remaining_kwh = round(remaining_kwh, 2)

        if hours_left <= 0:
            d = ChargingDecision(
                self.max_power_w,
                "Past departure — fast charging remaining "
                f"{remaining_kwh:.1f} kWh",
                pv_surplus_w=base.pv_surplus_w,
                battery_assist_w=base.battery_assist_w,
                battery_assist_reason=base.battery_assist_reason,
                deadline_active=True,
                deadline_hours_left=0.0,
                deadline_required_w=float(self.max_power_w),
                energy_remaining_kwh=round(remaining_kwh, 2),
            )
            return d

        # Required average power to finish on time (+ 10 % margin)
        required_w = (remaining_kwh / hours_left) * 1000 * 1.1
        base.deadline_required_w = round(required_w, 1)

        if required_w <= base.target_power_w:
            return base  # current power is sufficient

        escalated = self._clamp(int(required_w))
        if escalated <= 0:
            # Required power is below wallbox minimum but > 0.
            # This means we have lots of time — no escalation needed.
            return base

        d = ChargingDecision(
            max(base.target_power_w, escalated),
            f"Deadline: {remaining_kwh:.1f} kWh in {hours_left:.1f} h "
            f"→ {required_w:.0f} W needed",
            pv_surplus_w=base.pv_surplus_w,
            battery_assist_w=base.battery_assist_w,
            battery_assist_reason=base.battery_assist_reason,
            deadline_active=True,
            deadline_hours_left=round(hours_left, 2),
            deadline_required_w=round(required_w, 1),
            energy_remaining_kwh=round(remaining_kwh, 2),
        )
        return d

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
                pv_surplus_w=decision.pv_surplus_w,
                battery_assist_w=decision.battery_assist_w,
                battery_assist_reason=decision.battery_assist_reason,
                deadline_active=decision.deadline_active,
                deadline_hours_left=decision.deadline_hours_left,
                deadline_required_w=decision.deadline_required_w,
                energy_remaining_kwh=decision.energy_remaining_kwh,
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
        """Extra power the home battery can contribute for EV charging."""
        assist, _ = self._calc_battery_assist_detailed(ctx, pv_only_available)
        return assist

    def _calc_battery_assist_detailed(
        self, ctx: ChargingContext, pv_only_available: float,
    ) -> tuple[float, str]:
        """Extra power the home battery can contribute for EV charging.

        Returns (assist_w, reason) tuple with explanation.

        Philosophy: It's ALWAYS better to charge the EV than export to grid.
        The employer reimburses 25ct/kWh; grid feed-in pays only 7ct/kWh.
        So we aggressively use the battery to keep EV charging, as long as
        the battery can be refilled to an acceptable level by end of day.

        Rules:
        - Battery SoC must be above the floor (battery_min_soc_pct)
        - Cap discharge rate at battery_ev_assist_max_w (hardware limit)
        - Check if forecast PV can refill the battery by end of day
        - If battery is high (>80%) or forecast is good: full assist
        - If battery can't be fully refilled: still assist if we'd
          end above battery_target_eod_soc_pct (default 90%)
        """
        # Hard floor — never drain below this
        if ctx.battery_soc_pct <= self.battery_min_soc_pct:
            return 0.0, f"SoC {ctx.battery_soc_pct:.0f}% <= floor {self.battery_min_soc_pct:.0f}%"

        # PV surplus already sufficient — no assist needed
        if pv_only_available >= self.min_power_w:
            return 0.0, "PV surplus sufficient (no assist needed)"

        # How much battery power we need to bridge to min_power_w
        # (can be negative pv_only → need full bridge; can be positive but < min → partial bridge)
        shortfall = self.min_power_w - max(0.0, pv_only_available)

        # Calculate whether battery can be refilled by end of day
        can_refill, refill_reason = self._can_battery_refill(ctx)

        # SoC headroom factor: full battery → full assist, at floor → zero
        soc_headroom = (
            (ctx.battery_soc_pct - self.battery_min_soc_pct)
            / (100.0 - self.battery_min_soc_pct)
        )
        soc_factor = min(1.0, max(0.0, soc_headroom))

        # Determine max assist based on refill outlook
        if can_refill:
            # Forecast shows battery can be refilled — go full power
            max_assist = self.battery_ev_assist_max_w * soc_factor
            strategy = "refill OK"
        elif ctx.battery_soc_pct > 80:
            # Battery is high — use it even if we can't fully refill.
            # Better 90% EOD battery + charged EV than 100% battery + grid export.
            max_assist = self.battery_ev_assist_max_w * soc_factor
            strategy = f"SoC {ctx.battery_soc_pct:.0f}% > 80% (accept partial drain)"
        else:
            # Battery not that full AND can't refill — be conservative
            # Scale by forecast quality
            forecast_factor = min(
                1.0, ctx.pv_forecast_remaining_kwh / self.pv_forecast_good_kwh,
            )
            max_assist = self.battery_ev_assist_max_w * forecast_factor * soc_factor * 0.5
            strategy = f"conservative (forecast {forecast_factor:.0%})"

        if max_assist < 100:
            return 0.0, f"Assist too small ({max_assist:.0f} W) — {strategy}, {refill_reason}"

        assist = min(shortfall, max_assist)
        reason = (
            f"Shortfall {shortfall:.0f} W, assist {assist:.0f}/{max_assist:.0f} W "
            f"— {strategy}, {refill_reason}"
        )
        return assist, reason

    def _can_battery_refill(self, ctx: ChargingContext) -> tuple[bool, str]:
        """Check if remaining PV forecast can refill the battery by end of day.

        Returns (can_refill, reason).
        """
        # Energy needed to reach target EOD SoC
        target_soc = ctx.battery_target_eod_soc_pct
        current_soc = ctx.battery_soc_pct
        capacity = ctx.battery_capacity_kwh

        # If battery is already above target, trivially yes
        if current_soc >= target_soc:
            return True, f"SoC {current_soc:.0f}% >= target {target_soc:.0f}%"

        energy_to_refill = (target_soc - current_soc) / 100.0 * capacity

        # Estimate remaining household consumption
        # Use current house_power as proxy; assume ~5h remaining daylight
        # (conservative for Germany afternoon)
        hours_remaining = max(0.5, self._estimate_daylight_hours_remaining(ctx.now))
        household_kwh = (ctx.house_power_w / 1000.0) * hours_remaining

        # Available PV for battery = forecast remaining - household
        available_for_battery = ctx.pv_forecast_remaining_kwh - household_kwh

        can_refill = available_for_battery >= energy_to_refill
        reason = (
            f"need {energy_to_refill:.1f} kWh to reach {target_soc:.0f}%, "
            f"forecast {ctx.pv_forecast_remaining_kwh:.1f} kWh - "
            f"house {household_kwh:.1f} kWh = {available_for_battery:.1f} kWh available"
        )
        return can_refill, reason

    @staticmethod
    def _estimate_daylight_hours_remaining(now: datetime) -> float:
        """Rough estimate of productive PV hours remaining today.

        Uses a simple seasonal model for central Europe (50°N).
        Returns hours of useful PV production remaining.
        """
        # Approximate sunset hour by month (Germany)
        month = now.month
        sunset_hours = {
            1: 16.5, 2: 17.5, 3: 18.5, 4: 20.0, 5: 21.0, 6: 21.5,
            7: 21.5, 8: 20.5, 9: 19.5, 10: 18.5, 11: 17.0, 12: 16.5,
        }
        # PV production drops off ~1h before actual sunset
        effective_end = sunset_hours.get(month, 18.0) - 1.0
        current_hour = now.hour + now.minute / 60.0
        return max(0.0, effective_end - current_hour)

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
