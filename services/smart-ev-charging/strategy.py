"""Charging strategy — decides target wallbox power each control cycle."""

from __future__ import annotations

import time as _time
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
    MANUAL_UNTIL = "Manual Until"


@dataclass
class ChargingContext:
    """All inputs for a single charging decision."""

    mode: ChargeMode
    wallbox: WallboxState
    grid_power_w: float  # positive = exporting to grid, negative = importing
    pv_power_w: float  # total PV production (DC input)
    battery_power_w: float  # positive = charging, negative = discharging
    battery_soc_pct: float  # 0–100 %
    pv_forecast_remaining_kwh: float  # remaining PV kWh expected today
    pv_forecast_tomorrow_kwh: float  # total PV forecast for tomorrow (kWh)
    house_power_w: float  # current household consumption (W)
    battery_capacity_kwh: float  # home battery usable capacity (kWh)
    battery_target_eod_soc_pct: float  # acceptable end-of-day battery SoC %
    full_by_morning: bool
    departure_time: time | None
    target_energy_kwh: float  # manual fallback target (kWh to add)
    session_energy_kwh: float
    ev_soc_pct: float | None  # EV battery SoC from car (None = unavailable)
    ev_battery_capacity_kwh: float  # EV battery capacity (e.g. 77 kWh)
    ev_target_soc_pct: float  # target SoC % (e.g. 80)
    overnight_grid_kwh_charged: (
        float  # kWh already charged from grid this overnight session
    )
    now: datetime
    departure_passed: bool = False  # True when departure time is in the past
    # Manual Until mode targets
    manual_target_kwh: float = 0.0  # manual target kWh to charge (Manual Until mode)
    manual_target_soc: float = 0.0  # manual target SoC % (Manual Until mode)
    # Forecast-based sensors (from ev-forecast service)
    forecast_needed_kwh: float = 0.0  # kWh needed to reach forecast target SoC
    forecast_needed_soc: float = 0.0  # SoC% needed according to forecast

    @property
    def energy_needed_kwh(self) -> float:
        """kWh still needed to reach target."""
        if self.ev_soc_pct is not None and self.ev_battery_capacity_kwh > 0:
            delta_pct = max(0.0, self.ev_target_soc_pct - self.ev_soc_pct)
            return delta_pct / 100.0 * self.ev_battery_capacity_kwh
        return max(0.0, self.target_energy_kwh - self.session_energy_kwh)

    @property
    def kwh_tocharge_left(self) -> float:
        """kWh still to charge for Manual Until mode = max(0, manual_target_kwh - session_energy_kwh)."""
        return max(0.0, self.manual_target_kwh - self.session_energy_kwh)

    @property
    def target_reached(self) -> bool:
        """Whether the charging target has been reached."""
        if self.ev_soc_pct is not None:
            return self.ev_soc_pct >= self.ev_target_soc_pct
        return self.session_energy_kwh >= self.target_energy_kwh

    @property
    def manual_until_target_reached(self) -> bool:
        """Whether Manual Until stop conditions are met."""
        if self.manual_target_soc > 0 and self.ev_soc_pct is not None:
            if self.ev_soc_pct >= self.manual_target_soc:
                return True
        if self.kwh_tocharge_left <= 0 and self.manual_target_kwh > 0:
            return True
        return False


@dataclass
class ChargingDecision:
    """Output: what the wallbox should do."""

    target_power_w: int  # 0 = pause, >0 = charge at this power
    reason: str  # human-readable explanation
    skip_control: bool = False  # True = don't touch wallbox (Manual mode)

    # --- Detailed context for HA sensors ---
    pv_surplus_w: float = 0.0
    battery_assist_w: float = 0.0
    battery_assist_reason: str = ""
    deadline_active: bool = False
    deadline_hours_left: float = -1.0
    deadline_required_w: float = 0.0
    energy_remaining_kwh: float = 0.0
    kwh_tocharge_left: float = 0.0

    # --- Solar defer (Phase 2) ---
    solar_defer_active: bool = False  # True = deferring overnight grid charge to PV
    solar_defer_pv_kwh: float = 0.0  # Forecast PV available before departure (kWh)
    solar_defer_needed_kwh: float = 0.0  # Energy still needed (kWh)


class ChargingStrategy:
    """Calculates target charging power based on mode and conditions."""

    def __init__(
        self,
        max_power_w: int = 11000,
        min_power_w: int = 4200,
        eco_power_w: int = 5000,
        grid_reserve_w: int = -100,
        start_hysteresis_w: int = 300,
        ramp_step_w: int = 500,
        startup_ramp_power_w: int = 5000,
        startup_ramp_duration_s: int = 180,
        battery_min_soc_pct: float = 20.0,
        battery_ev_assist_max_w: float = 3500.0,
        battery_capacity_kwh: float = 7.0,
        battery_target_eod_soc_pct: float = 90.0,
        pv_forecast_good_kwh: float = 15.0,
        night_charging_buffer_hours: float = 1.0,
        pv_morning_fraction: float = 0.45,
        charger_efficiency: float = 0.90,
        morning_escalation_hour: int = 11,
        min_charge_duration_s: int = 300,  # keep charging for at least 5 min
        stop_cooldown_s: int = 300,  # wait at least 5 min before restarting
        battery_hold_soc_pct: float = 70.0,  # hold battery at this SoC while EV charges
        battery_hold_margin: float = 1.3,  # 30% safety margin for refill forecast
        # Phase 2: Solar defer
        pv_defer_confidence_factor: float = 1.3,  # PV must exceed need by this factor to defer
        pv_defer_min_hours_before_departure: float = 1.5,  # abort defer if departure < N hours away
    ) -> None:
        self.max_power_w = max_power_w
        self.min_power_w = min_power_w
        self.eco_power_w = eco_power_w
        self.grid_reserve_w = grid_reserve_w
        self.start_hysteresis_w = start_hysteresis_w
        self.ramp_step_w = ramp_step_w
        self.startup_ramp_power_w = startup_ramp_power_w
        self.startup_ramp_duration_s = startup_ramp_duration_s
        self.battery_min_soc_pct = battery_min_soc_pct
        self.battery_ev_assist_max_w = battery_ev_assist_max_w
        self.battery_capacity_kwh = battery_capacity_kwh
        self.battery_target_eod_soc_pct = battery_target_eod_soc_pct
        self.pv_forecast_good_kwh = pv_forecast_good_kwh
        self.night_charging_buffer_hours = night_charging_buffer_hours
        self.pv_morning_fraction = pv_morning_fraction
        self.charger_efficiency = charger_efficiency
        self.morning_escalation_hour = morning_escalation_hour
        self.min_charge_duration_s = min_charge_duration_s
        self.stop_cooldown_s = stop_cooldown_s
        self.battery_hold_soc_pct = battery_hold_soc_pct
        self.battery_hold_margin = battery_hold_margin
        self.pv_defer_confidence_factor = pv_defer_confidence_factor
        self.pv_defer_min_hours_before_departure = pv_defer_min_hours_before_departure

        self._was_pv_charging = False
        self._last_target_w: int = 0
        self._charge_started_at: float | None = None  # monotonic timestamp
        self._charge_stopped_at: float | None = None  # monotonic timestamp

    def decide(self, ctx: ChargingContext) -> ChargingDecision:
        """Calculate the target charging power for this cycle."""

        # --- Off / Manual ---
        if ctx.mode == ChargeMode.OFF:
            self._reset()
            return ChargingDecision(0, "Charging off")

        if ctx.mode == ChargeMode.MANUAL:
            return ChargingDecision(
                0,
                "Manual mode — service not controlling wallbox",
                skip_control=True,
            )

        # --- No vehicle ---
        if not ctx.wallbox.vehicle_connected:
            self._reset()
            return ChargingDecision(0, "No vehicle connected")

        # --- Target SoC reached — continue topping up with PV surplus ---
        if ctx.target_reached:
            if (
                ctx.mode in (ChargeMode.PV_SURPLUS, ChargeMode.SMART)
                and ctx.pv_power_w > 100
            ):
                if (
                    ctx.ev_soc_pct is not None
                    and ctx.ev_soc_pct < ctx.ev_target_soc_pct
                ):
                    surplus_decision = self._pv_surplus(ctx)
                    if surplus_decision.target_power_w > 0:
                        surplus_decision.reason = (
                            f"Plan target reached — topping up to {ctx.ev_target_soc_pct:.0f}% "
                            f"(currently {ctx.ev_soc_pct:.0f}%): {surplus_decision.reason}"
                        )
                        return surplus_decision
                else:
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

        # --- R6: Universal PV surplus rule (apply before mode-specific logic for MANUAL_UNTIL/SMART/PV_SURPLUS) ---
        # If car is plugged in AND pv_surplus_w > min_power_w → always use it
        # This is checked per-mode to allow each mode's logic to apply it appropriately.

        # --- Mode-specific strategy ---
        if ctx.mode == ChargeMode.FAST:
            decision = self._fixed(self.max_power_w, "Fast")
        elif ctx.mode == ChargeMode.ECO:
            decision = self._fixed(self.eco_power_w, "Eco")
        elif ctx.mode == ChargeMode.PV_SURPLUS:
            decision = self._pv_surplus(ctx)
        elif ctx.mode == ChargeMode.SMART:
            decision = self._smart(ctx)
        elif ctx.mode == ChargeMode.MANUAL_UNTIL:
            decision = self._manual_until(ctx)
        else:
            decision = ChargingDecision(0, f"Unknown mode: {ctx.mode}")

        # --- Full-by-morning deadline escalation ---
        # BUG #4 FIX: Skip deadline escalation if departure has passed
        # BUG #1 FIX: Don't escalate with "waiting for tomorrow" when departure is today and imminent
        if (
            ctx.full_by_morning
            and not ctx.departure_passed
            and ctx.mode
            in (
                ChargeMode.PV_SURPLUS,
                ChargeMode.SMART,
            )
        ):
            # Skip deadline escalation during morning PV-wait window
            is_pv_wait_window = (
                ctx.mode == ChargeMode.SMART
                and 5 <= ctx.now.hour < self.morning_escalation_hour
                and ctx.overnight_grid_kwh_charged > 0
                and decision.target_power_w == 0
                and "waiting for" in decision.reason.lower()
            )
            if not is_pv_wait_window:
                decision = self._apply_deadline_escalation(ctx, decision)

        # --- Startup ramp: hold elevated power for first N seconds ---
        decision = self._apply_startup_ramp(decision)

        # --- Ramp limiting ---
        decision = self._apply_ramp(decision)

        # --- Anti-cycling: min charge duration + stop cooldown ---
        decision = self._apply_anti_cycling(decision)

        # --- Update state ---
        now_mono = _time.monotonic()
        if decision.target_power_w > 0 and not self._was_pv_charging:
            self._charge_started_at = now_mono
            self._charge_stopped_at = None
        elif decision.target_power_w == 0 and self._was_pv_charging:
            self._charge_stopped_at = now_mono
            self._charge_started_at = None
        self._was_pv_charging = decision.target_power_w > 0
        self._last_target_w = decision.target_power_w

        return decision

    # ------------------------------------------------------------------
    # Mode implementations
    # ------------------------------------------------------------------

    def _fixed(self, power_w: int, label: str) -> ChargingDecision:
        return ChargingDecision(power_w, f"{label} charging at {power_w} W")

    def _manual_until(self, ctx: ChargingContext) -> ChargingDecision:
        """Manual Until SoC or kWh mode — charges until target is reached.

        R5: Target is whichever hits first — manual_target_soc OR manual_target_kwh.
        R6: Universal PV surplus rule — if PV surplus > min_power, always use it.
        Nighttime/no-surplus: charge at deadline-required rate or min_power.
        """
        kwh_left = ctx.kwh_tocharge_left

        # Stop condition
        if ctx.manual_until_target_reached:
            reason_parts = []
            if (
                ctx.manual_target_soc > 0
                and ctx.ev_soc_pct is not None
                and ctx.ev_soc_pct >= ctx.manual_target_soc
            ):
                reason_parts.append(
                    f"SoC target reached ({ctx.ev_soc_pct:.0f}% >= {ctx.manual_target_soc:.0f}%)"
                )
            if ctx.kwh_tocharge_left <= 0 and ctx.manual_target_kwh > 0:
                reason_parts.append(
                    f"kWh target reached ({ctx.session_energy_kwh:.1f} kWh charged)"
                )
            self._reset()
            return ChargingDecision(
                0, f"Manual Until: {' | '.join(reason_parts) or 'target reached'}"
            )

        # R6: Universal PV surplus rule — always use solar if available
        pv_only = self._calc_pv_only_available(ctx)
        if pv_only > self.min_power_w:
            pv_decision = self._pv_surplus(ctx)
            if pv_decision.target_power_w > 0:
                return ChargingDecision(
                    pv_decision.target_power_w,
                    f"Manual Until: PV surplus {pv_only:.0f} W → {pv_decision.target_power_w} W (kWh left: {kwh_left:.1f})",
                    pv_surplus_w=pv_decision.pv_surplus_w,
                    battery_assist_w=pv_decision.battery_assist_w,
                    battery_assist_reason=pv_decision.battery_assist_reason,
                    kwh_tocharge_left=kwh_left,
                )

        # No PV surplus — compute deadline-based minimum power
        hours_to_departure = None
        if ctx.departure_time:
            hours_to_departure = self._hours_until_departure(
                ctx.departure_time, ctx.now
            )

        if hours_to_departure is not None and hours_to_departure > 0 and kwh_left > 0:
            required_w = (kwh_left / hours_to_departure) * 1000
            required_w = max(self.min_power_w, min(self.max_power_w, required_w))
            return ChargingDecision(
                int(required_w),
                f"Manual Until: deadline-based {required_w:.0f} W "
                f"({kwh_left:.1f} kWh in {hours_to_departure:.1f}h)",
                kwh_tocharge_left=kwh_left,
                deadline_active=True,
                deadline_hours_left=round(hours_to_departure, 2),
                deadline_required_w=round(required_w, 1),
                energy_remaining_kwh=round(kwh_left, 2),
            )

        # No departure time set → charge at min_power continuously
        return ChargingDecision(
            self.min_power_w,
            f"Manual Until: min power {self.min_power_w} W (no departure time, {kwh_left:.1f} kWh left)",
            kwh_tocharge_left=kwh_left,
        )

    def _pv_surplus(self, ctx: ChargingContext) -> ChargingDecision:
        """Track PV surplus — charge primarily from solar excess."""
        pv_only = self._calc_pv_only_available(ctx)
        assist, assist_reason = self._calc_battery_assist_detailed(ctx, pv_only)

        # Battery hold boost: when battery SoC >= hold threshold during daytime,
        # redirect battery charging power to EV instead.  Released in the evening
        # so the battery can top off to 100% for overnight use.
        hold_boost, hold_reason = self._calc_battery_hold_boost(ctx)
        available = pv_only + assist + hold_boost

        ev_soc_low = ctx.ev_soc_pct is not None and ctx.ev_soc_pct < 50
        battery_high = ctx.battery_soc_pct >= 80
        # When battery can be refilled by sundown AND SoC is reasonable (>50%),
        # there's no risk — remove hysteresis entirely to start charging sooner.
        can_refill, _ = self._can_battery_refill(ctx)
        battery_refill_safe = can_refill and ctx.battery_soc_pct >= 30
        if battery_high or battery_refill_safe:
            hysteresis_reduction = self.start_hysteresis_w
        elif ev_soc_low:
            hysteresis_reduction = 150
        else:
            hysteresis_reduction = 0

        threshold = (
            self.min_power_w
            if self._was_pv_charging
            else self.min_power_w + self.start_hysteresis_w - hysteresis_reduction
        )

        base_fields = {
            "pv_surplus_w": round(pv_only, 1),
            "battery_assist_w": round(assist + hold_boost, 1),
            "battery_assist_reason": (
                f"{assist_reason} | Hold: {hold_reason}"
                if hold_boost > 0
                else assist_reason
            ),
        }

        if available >= threshold:
            target = self._clamp(available)
            parts = [f"PV surplus {pv_only:.0f} W"]
            if assist > 0:
                parts.append(f"+ {assist:.0f} W battery assist")
            if hold_boost > 0:
                parts.append(f"+ {hold_boost:.0f} W battery hold boost")
            if ctx.battery_soc_pct > 80 and ctx.battery_power_w > 0:
                parts.append("(prioritize EV over battery)")
            if ev_soc_low:
                parts.append("(low EV SoC — economic priority)")
            return ChargingDecision(
                target,
                f"{' '.join(parts)} → {target} W",
                **base_fields,
            )

        if self._was_pv_charging:
            # Before stopping: if battery SoC is high enough, use full battery
            # discharge to bridge the gap. Better to drain battery than to cycle
            # the wallbox on/off (which triggers anti-cycling cooldowns).
            if ctx.battery_soc_pct > self.battery_min_soc_pct + 10:
                bridge_shortfall = self.min_power_w - available
                bridge_available = min(bridge_shortfall, self.battery_ev_assist_max_w)
                bridged = available + bridge_available
                if bridged >= self.min_power_w:
                    target = self._clamp(bridged)
                    return ChargingDecision(
                        target,
                        f"PV dip bridged by battery ({available:.0f} W + {bridge_available:.0f} W "
                        f"battery bridge → {target} W, bat {ctx.battery_soc_pct:.0f}%)",
                        pv_surplus_w=round(pv_only, 1),
                        battery_assist_w=round(
                            assist + hold_boost + bridge_available, 1
                        ),
                        battery_assist_reason=f"Bridge: {bridge_available:.0f} W to prevent stop",
                    )

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
        """PV surplus during the day; overnight grid+PV split when full_by_morning=ON.

        BUG #1/#4 FIX: When departure has passed, fall back to pure PV surplus mode.
        No deadline logic, no "waiting for tomorrow's PV".
        """
        current_hour = ctx.now.hour
        # Overnight charging window: 20:00-05:00 (extended for post-departure handling)
        is_nighttime = current_hour >= 20 or current_hour < 5

        # Departure passed — but if full_by_morning is ON and car still needs
        # charging, treat departure_time as TOMORROW's departure and use
        # overnight charging logic. This ensures the car charges at minimum
        # power overnight instead of waiting for PV that won't come.
        if ctx.departure_passed:
            if (
                is_nighttime
                and ctx.full_by_morning
                and ctx.departure_time
                and ctx.energy_needed_kwh > 0
            ):
                # Only use overnight grid charging logic at night (20:00-05:00).
                # During daytime, fall through to PV surplus below.
                return self._nighttime_smart(ctx)
            # Daytime or no deadline — PV surplus only
            pv = self._pv_surplus(ctx)
            if pv.target_power_w > 0:
                return ChargingDecision(
                    pv.target_power_w,
                    f"Smart (post-departure): {pv.reason}",
                    pv_surplus_w=pv.pv_surplus_w,
                    battery_assist_w=pv.battery_assist_w,
                    battery_assist_reason=pv.battery_assist_reason,
                )
            # Grid export prevention still applies
            if ctx.grid_power_w > 50 and not ctx.target_reached:
                return self._grid_export_prevention(ctx, pv)
            return ChargingDecision(
                0,
                f"Smart (post-departure): PV surplus mode — {pv.reason}",
                pv_surplus_w=pv.pv_surplus_w,
                battery_assist_w=pv.battery_assist_w,
                battery_assist_reason=pv.battery_assist_reason,
            )

        # --- Overnight: grid+PV split strategy ---
        if is_nighttime and ctx.full_by_morning and ctx.departure_time:
            return self._nighttime_smart(ctx)

        # --- Early morning (05:00-08:00): waiting for PV phase ---
        is_morning_wait = 5 <= current_hour < 8
        if is_morning_wait and ctx.full_by_morning and ctx.departure_time:
            energy_needed = ctx.energy_needed_kwh
            if energy_needed > 0 and ctx.overnight_grid_kwh_charged > 0:
                # BUG #1 FIX: Use TODAY's remaining PV forecast, not "tomorrow's"
                hours_left = self._hours_until_departure(ctx.departure_time, ctx.now)
                if hours_left is not None and hours_left < 3:
                    # Departure is within 3 hours — escalate, don't wait
                    required_w = (energy_needed / max(0.5, hours_left)) * 1000 * 1.1
                    escalated = self._clamp(int(required_w))
                    if escalated > 0:
                        return ChargingDecision(
                            escalated,
                            f"Morning urgent: departure in {hours_left:.1f}h, "
                            f"{energy_needed:.1f} kWh needed → {escalated} W",
                            deadline_active=True,
                            deadline_hours_left=round(hours_left, 2),
                            deadline_required_w=round(required_w, 1),
                            energy_remaining_kwh=round(energy_needed, 2),
                        )

                pv_today_remaining = ctx.pv_forecast_remaining_kwh
                pv_morning_usable = pv_today_remaining * self.charger_efficiency
                # Use tomorrow forecast only at night; in morning use today's remaining
                pv_tomorrow_total = ctx.pv_forecast_tomorrow_kwh
                pv_morning_from_tomorrow = (
                    pv_tomorrow_total
                    * self.pv_morning_fraction
                    * self.charger_efficiency
                )
                # Pick whichever is more relevant based on time
                pv_usable = max(pv_morning_usable, pv_morning_from_tomorrow)

                grid_portion_kwh = (
                    max(
                        0.0,
                        (energy_needed + ctx.overnight_grid_kwh_charged) - pv_usable,
                    )
                    * 1.10
                )
                if (
                    pv_usable >= 3.0
                    and ctx.overnight_grid_kwh_charged >= grid_portion_kwh * 0.95
                ):
                    pv = self._pv_surplus(ctx)
                    if pv.target_power_w > 0:
                        return ChargingDecision(
                            pv.target_power_w,
                            f"Morning PV resume: {pv.reason}",
                            pv_surplus_w=pv.pv_surplus_w,
                            battery_assist_w=pv.battery_assist_w,
                            battery_assist_reason=pv.battery_assist_reason,
                        )
                    return ChargingDecision(
                        0,
                        f"Morning: grid portion done ({ctx.overnight_grid_kwh_charged:.1f} kWh), "
                        f"waiting for PV ({energy_needed:.1f} kWh remaining, "
                        f"forecast {pv_usable:.1f} kWh usable)",
                    )

        # --- Morning escalation check (11:00+) ---
        escalation = self._morning_pv_escalation(ctx)
        if escalation is not None:
            return escalation

        # --- Daytime: PV surplus first ---
        pv = self._pv_surplus(ctx)
        if pv.target_power_w > 0:
            return ChargingDecision(
                pv.target_power_w,
                f"Smart: {pv.reason}",
                pv_surplus_w=pv.pv_surplus_w,
                battery_assist_w=pv.battery_assist_w,
                battery_assist_reason=pv.battery_assist_reason,
            )

        # Grid export prevention
        if ctx.grid_power_w > 50 and not ctx.target_reached:
            return self._grid_export_prevention(ctx, pv)

        # --- Dynamic grid charging fallback ---
        pv_only_check = self._calc_pv_only_available(ctx)
        assist_check, _ = self._calc_battery_assist_detailed(ctx, pv_only_check)
        pv_total_available = pv_only_check + assist_check

        if (
            not ctx.target_reached
            and (ctx.full_by_morning or ctx.departure_time is not None)
            and pv_total_available < self.min_power_w
            and ctx.energy_needed_kwh > 0
        ):
            fallback = self._dynamic_grid_fallback(ctx)
            if fallback is not None:
                return fallback

        return ChargingDecision(
            0,
            f"Smart: {pv.reason}",
            pv_surplus_w=pv.pv_surplus_w,
            battery_assist_w=pv.battery_assist_w,
            battery_assist_reason=pv.battery_assist_reason,
        )

    def _grid_export_prevention(
        self,
        ctx: ChargingContext,
        pv_decision: ChargingDecision,
    ) -> ChargingDecision:
        """Prevent grid export by using battery + PV to charge the EV."""
        pv_only = self._calc_pv_only_available(ctx)
        total_available = max(0.0, pv_only)
        battery_needed = self.min_power_w - total_available

        if ctx.battery_soc_pct <= self.battery_min_soc_pct:
            return ChargingDecision(
                0,
                f"Smart: exporting {ctx.grid_power_w:.0f} W but battery too low "
                f"({ctx.battery_soc_pct:.0f}% <= {self.battery_min_soc_pct:.0f}%)",
                pv_surplus_w=pv_decision.pv_surplus_w,
                battery_assist_w=0,
                battery_assist_reason=f"SoC at floor ({ctx.battery_soc_pct:.0f}%)",
            )

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

        return ChargingDecision(
            0,
            f"Smart: exporting {ctx.grid_power_w:.0f} W but can't reach min "
            f"({total_available:.0f} + {battery_available:.0f} < {self.min_power_w} W)",
            pv_surplus_w=pv_decision.pv_surplus_w,
            battery_assist_w=0,
            battery_assist_reason="Insufficient combined power for min charge rate",
        )

    def _can_defer_to_solar(
        self,
        ctx: ChargingContext,
    ) -> tuple[bool, float, str]:
        """Evaluate whether overnight grid charging can be deferred entirely to tomorrow's PV.

        Returns (can_defer, pv_usable_kwh, reason).

        Deferral is safe when:
        1. Tomorrow's PV forecast (adjusted for morning fraction, efficiency, and max
           chargeable before departure) exceeds needed energy by pv_defer_confidence_factor.
        2. Departure is more than pv_defer_min_hours_before_departure hours away
           (so there's time to recover if the forecast was optimistic).
        3. The energy needed is non-zero and departure time is known.
        """
        energy_needed = ctx.energy_needed_kwh
        if energy_needed <= 0:
            return False, 0.0, "target already reached"

        if not ctx.departure_time:
            return False, 0.0, "no departure time set"

        hours_until_departure = self._hours_until_departure(ctx.departure_time, ctx.now)
        if hours_until_departure is None or hours_until_departure <= 0:
            return False, 0.0, "departure already passed"

        # Require a minimum window before departure so we can recover if PV disappoints
        if hours_until_departure <= self.pv_defer_min_hours_before_departure:
            return (
                False,
                0.0,
                f"departure in {hours_until_departure:.1f}h — too close to defer "
                f"(min {self.pv_defer_min_hours_before_departure}h)",
            )

        pv_tomorrow_total = ctx.pv_forecast_tomorrow_kwh
        if pv_tomorrow_total <= 0:
            return False, 0.0, "no PV forecast for tomorrow"

        departure_hour = ctx.departure_time.hour + ctx.departure_time.minute / 60.0
        pv_start_hour = 8.0
        pv_hours = max(0.0, departure_hour - pv_start_hour)
        if pv_hours < 1.0:
            return (
                False,
                0.0,
                f"departure at {departure_hour:.1f}h — too early for solar",
            )

        # Max chargeble kWh from PV before departure (power-limited)
        max_pv_charge_kw = (self.max_power_w / 1000.0) * pv_hours
        # Fraction of total forecast available before departure * efficiency
        pv_usable = min(
            pv_tomorrow_total * self.pv_morning_fraction * self.charger_efficiency,
            max_pv_charge_kw,
        )

        required_with_margin = energy_needed * self.pv_defer_confidence_factor
        if pv_usable >= required_with_margin:
            return (
                True,
                round(pv_usable, 1),
                (
                    f"PV forecast {pv_tomorrow_total:.1f} kWh → {pv_usable:.1f} kWh usable "
                    f"before {departure_hour:.0f}:00 (need {energy_needed:.1f} kWh × "
                    f"{self.pv_defer_confidence_factor:.0%} = {required_with_margin:.1f} kWh) "
                    f"— defer to solar"
                ),
            )

        return (
            False,
            round(pv_usable, 1),
            (
                f"PV forecast {pv_tomorrow_total:.1f} kWh → {pv_usable:.1f} kWh usable "
                f"< {required_with_margin:.1f} kWh required with margin — use grid"
            ),
        )

    def _nighttime_smart(self, ctx: ChargingContext) -> ChargingDecision:
        """Smart overnight charging: split between grid (overnight) and PV (morning).

        Phase 2: When tomorrow's PV forecast is strong enough to cover all energy
        needed before departure (with a confidence margin), defers overnight grid
        charging entirely.  The solar defer check runs first; the legacy PV/grid
        split only activates when deferral is not safe.
        """
        energy_needed = ctx.energy_needed_kwh
        if energy_needed <= 0:
            return ChargingDecision(0, "Nighttime: target already reached")

        # --- Phase 2: Solar defer check ---
        can_defer, pv_usable, defer_reason = self._can_defer_to_solar(ctx)
        if can_defer:
            logger.info(
                "solar_defer_active",
                energy_needed=round(energy_needed, 1),
                pv_usable=pv_usable,
                reason=defer_reason,
            )
            return ChargingDecision(
                0,
                f"Solar defer: {defer_reason}",
                solar_defer_active=True,
                solar_defer_pv_kwh=pv_usable,
                solar_defer_needed_kwh=round(energy_needed, 1),
            )

        pv_tomorrow_total = ctx.pv_forecast_tomorrow_kwh
        pv_morning_usable = (
            pv_tomorrow_total * self.pv_morning_fraction * self.charger_efficiency
        )

        departure_hour = (
            ctx.departure_time.hour + ctx.departure_time.minute / 60.0
            if ctx.departure_time
            else 13.0
        )
        pv_start_hour = 8.0
        pv_hours = max(0.0, departure_hour - pv_start_hour)
        max_pv_charge = (self.max_power_w / 1000.0) * pv_hours
        pv_morning_usable = min(pv_morning_usable, max_pv_charge, energy_needed)

        grid_portion_kwh = max(0.0, energy_needed - pv_morning_usable)
        grid_portion_kwh *= 1.10

        if pv_morning_usable < 3.0:
            grid_portion_kwh = energy_needed
            pv_morning_usable = 0.0

        logger.info(
            "overnight_pv_split",
            energy_needed=round(energy_needed, 1),
            pv_tomorrow_total=round(pv_tomorrow_total, 1),
            pv_morning_usable=round(pv_morning_usable, 1),
            grid_portion=round(grid_portion_kwh, 1),
            overnight_grid_charged=round(ctx.overnight_grid_kwh_charged, 1),
        )

        if ctx.overnight_grid_kwh_charged >= grid_portion_kwh:
            remaining_for_pv = energy_needed - ctx.overnight_grid_kwh_charged
            if remaining_for_pv <= 0:
                return ChargingDecision(
                    0,
                    "Overnight grid charging complete — target reached",
                )
            return ChargingDecision(
                0,
                f"Grid portion done ({ctx.overnight_grid_kwh_charged:.1f}/"
                f"{grid_portion_kwh:.1f} kWh) — waiting for morning PV "
                f"({remaining_for_pv:.1f} kWh remaining, "
                f"forecast {pv_morning_usable:.1f} kWh usable)",
            )

        grid_remaining = grid_portion_kwh - ctx.overnight_grid_kwh_charged
        hours_until_departure = self._hours_until_departure(ctx.departure_time, ctx.now)
        if hours_until_departure is None:
            hours_until_departure = 12.0

        # Use MINIMUM power to spread charging over maximum time
        charging_power_kw = self.min_power_w / 1000.0
        hours_for_grid = grid_remaining / charging_power_kw

        grid_deadline_hour = min(6.0, departure_hour - pv_hours)
        hours_until_grid_deadline = self._hours_until_hour(grid_deadline_hour, ctx.now)
        effective_deadline = min(hours_until_departure, hours_until_grid_deadline)

        # If we have enough time at minimum power, use it; otherwise escalate
        if hours_for_grid <= effective_deadline:
            return ChargingDecision(
                self.min_power_w,
                f"Overnight min-power: {grid_remaining:.1f}/{grid_portion_kwh:.1f} kWh "
                f"at {self.min_power_w}W (~{hours_for_grid:.1f}h, finish ~"
                f"{(ctx.now + timedelta(hours=hours_for_grid)).strftime('%H:%M')}) | "
                f"PV: {pv_morning_usable:.1f} kWh morning",
            )
        else:
            # Not enough time at min power — escalate
            return ChargingDecision(
                self.eco_power_w,
                f"Overnight (escalated {self.eco_power_w}W): "
                f"{grid_remaining:.1f} kWh, need {hours_for_grid:.1f}h but "
                f"only {effective_deadline:.1f}h available",
            )

    def _dynamic_grid_fallback(self, ctx: ChargingContext) -> ChargingDecision | None:
        """Dynamic grid charging fallback — season-independent.

        BUG #1 FIX: Use _hours_until_departure which returns None when
        departure has passed, instead of _hours_until which wraps to tomorrow.
        """
        energy_needed = ctx.energy_needed_kwh
        departure = ctx.departure_time

        # BUG #1/#4: If departure has passed, don't do grid fallback
        if ctx.departure_passed:
            return None

        pv_tomorrow_total = ctx.pv_forecast_tomorrow_kwh
        pv_morning_usable = (
            pv_tomorrow_total * self.pv_morning_fraction * self.charger_efficiency
        )

        if departure:
            departure_hour = departure.hour + departure.minute / 60.0
        else:
            departure_hour = 13.0
        pv_start_hour = 8.0
        pv_hours = max(0.0, departure_hour - pv_start_hour)
        max_pv_charge = (self.max_power_w / 1000.0) * pv_hours
        pv_morning_usable = min(pv_morning_usable, max_pv_charge, energy_needed)

        if pv_morning_usable < 3.0:
            pv_morning_usable = 0.0

        grid_portion = max(0.0, energy_needed - pv_morning_usable)

        # Also consider today's remaining PV
        pv_today = ctx.pv_forecast_remaining_kwh * self.charger_efficiency
        if pv_today >= energy_needed:
            # Today's PV can still cover it — wait
            return ChargingDecision(
                0,
                f"Smart: today's PV forecast can cover it "
                f"({energy_needed:.1f} kWh needed, "
                f"{pv_today:.1f} kWh remaining today)",
            )

        logger.info(
            "dynamic_grid_fallback",
            energy_needed=round(energy_needed, 1),
            pv_tomorrow_total=round(pv_tomorrow_total, 1),
            pv_morning_usable=round(pv_morning_usable, 1),
            grid_portion=round(grid_portion, 1),
            hour=ctx.now.hour,
        )

        if grid_portion > 0:
            hours_left = (
                self._hours_until_departure(departure, ctx.now) if departure else 12.0
            )
            if hours_left is None:
                hours_left = 12.0
            return ChargingDecision(
                self.min_power_w,
                f"Smart: Dynamic grid fallback — no PV available, "
                f"{energy_needed:.1f} kWh needed "
                f"(grid portion {grid_portion:.1f} kWh, "
                f"tomorrow PV {pv_morning_usable:.1f} kWh usable, "
                f"departure in {hours_left:.1f}h)",
            )

        # PV can cover everything tomorrow — wait
        hours_left = (
            self._hours_until_departure(departure, ctx.now) if departure else 12.0
        )
        if hours_left is None:
            hours_left = 12.0
        return ChargingDecision(
            0,
            f"Smart: PV forecast sufficient "
            f"({energy_needed:.1f} kWh needed, "
            f"forecast {pv_morning_usable:.1f} kWh usable morning, "
            f"departure in {hours_left:.1f}h)",
        )

    def _morning_pv_escalation(self, ctx: ChargingContext) -> ChargingDecision | None:
        """Deadline escalation: if by 11:00 we're not on track, go full grid power."""
        if not ctx.full_by_morning or not ctx.departure_time:
            return None
        # BUG #4: Don't escalate if departure has passed
        if ctx.departure_passed:
            return None

        current_hour = ctx.now.hour
        if current_hour < self.morning_escalation_hour:
            return None

        energy_needed = ctx.energy_needed_kwh
        if energy_needed <= 0:
            return None

        hours_left = self._hours_until_departure(ctx.departure_time, ctx.now)
        if hours_left is None or hours_left <= 0:
            # Departure passed — don't max-charge
            return None

        required_w = (energy_needed / hours_left) * 1000 * 1.1

        pv_only = self._calc_pv_only_available(ctx)
        if pv_only >= required_w:
            return None

        escalated = self._clamp(int(required_w))
        if escalated <= 0:
            return None

        return ChargingDecision(
            escalated,
            f"Morning escalation ({current_hour}:00): {energy_needed:.1f} kWh "
            f"in {hours_left:.1f}h → need {required_w:.0f} W "
            f"(PV only provides {pv_only:.0f} W, adding grid)",
            deadline_active=True,
            deadline_hours_left=round(hours_left, 2),
            deadline_required_w=round(required_w, 1),
            energy_remaining_kwh=round(energy_needed, 2),
        )

    @staticmethod
    def _hours_until_hour(target_hour: float, now: datetime) -> float:
        """Hours from now until a given hour (today or tomorrow)."""
        current = now.hour + now.minute / 60.0
        if target_hour > current:
            return target_hour - current
        return (24.0 - current) + target_hour

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
            return base

        # BUG #1 FIX: Use _hours_until_departure (returns None if passed)
        hours_left = self._hours_until_departure(ctx.departure_time, ctx.now)
        if hours_left is None:
            # Departure passed — no escalation (handled by departure_passed flag)
            return base

        base.deadline_active = True
        base.deadline_hours_left = round(hours_left, 2)
        base.energy_remaining_kwh = round(remaining_kwh, 2)

        if hours_left <= 0:
            return base  # departure_passed should have caught this

        required_w = (remaining_kwh / hours_left) * 1000 * 1.1
        base.deadline_required_w = round(required_w, 1)

        if required_w <= base.target_power_w:
            return base

        escalated = self._clamp(int(required_w))
        if escalated <= 0:
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
    # Startup ramp
    # ------------------------------------------------------------------

    def _apply_startup_ramp(self, decision: ChargingDecision) -> ChargingDecision:
        """Hold an elevated minimum power for the first N seconds after start.

        This ensures the wallbox/car handshake stabilises at a solid power
        level before we start tracking PV surplus more tightly.
        """
        if decision.target_power_w <= 0 or decision.skip_control:
            return decision

        if self._charge_started_at is None:
            return decision

        elapsed = _time.monotonic() - self._charge_started_at
        if elapsed >= self.startup_ramp_duration_s:
            return decision

        if decision.target_power_w < self.startup_ramp_power_w:
            return ChargingDecision(
                self.startup_ramp_power_w,
                f"{decision.reason} (startup ramp: {elapsed:.0f}/{self.startup_ramp_duration_s}s → {self.startup_ramp_power_w} W)",
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
    # Ramp limiting
    # ------------------------------------------------------------------

    def _apply_ramp(self, decision: ChargingDecision) -> ChargingDecision:
        """Limit power step size between cycles for smooth transitions."""
        if decision.skip_control:
            return decision

        target = decision.target_power_w
        last = self._last_target_w

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
    # Anti-cycling protection
    # ------------------------------------------------------------------

    def _apply_anti_cycling(self, decision: ChargingDecision) -> ChargingDecision:
        """Prevent rapid start/stop cycling that upsets the wallbox/car.

        Rules:
        - Once charging starts, keep going for at least min_charge_duration_s
          (even if surplus briefly drops).
        - After stopping, wait at least stop_cooldown_s before restarting
          (to allow cloud transients to pass).
        """
        now_mono = _time.monotonic()

        # Currently charging → decision says stop: enforce minimum run time
        if self._was_pv_charging and decision.target_power_w == 0:
            if self._charge_started_at is not None:
                elapsed = now_mono - self._charge_started_at
                if elapsed < self.min_charge_duration_s:
                    remaining = self.min_charge_duration_s - elapsed
                    return ChargingDecision(
                        self._last_target_w,
                        f"Anti-cycling: keeping charge at {self._last_target_w} W "
                        f"(min duration, {remaining:.0f}s remaining)",
                        pv_surplus_w=decision.pv_surplus_w,
                        battery_assist_w=decision.battery_assist_w,
                        battery_assist_reason=decision.battery_assist_reason,
                    )

        # Currently stopped → decision says start: enforce cooldown
        if not self._was_pv_charging and decision.target_power_w > 0:
            if self._charge_stopped_at is not None:
                elapsed = now_mono - self._charge_stopped_at
                if elapsed < self.stop_cooldown_s:
                    remaining = self.stop_cooldown_s - elapsed
                    return ChargingDecision(
                        0,
                        f"Anti-cycling: cooldown after stop "
                        f"({remaining:.0f}s remaining, would charge at "
                        f"{decision.target_power_w} W)",
                        pv_surplus_w=decision.pv_surplus_w,
                        battery_assist_w=decision.battery_assist_w,
                        battery_assist_reason=decision.battery_assist_reason,
                    )

        return decision

    # ------------------------------------------------------------------
    # PV surplus & battery assist
    # ------------------------------------------------------------------

    def _calc_pv_only_available(self, ctx: ChargingContext) -> float:
        """Power available from PV surplus only (no battery discharge).

        When the wallbox was recently charging but current power reads 0
        (charger briefly paused between cycles), use the last target power
        instead. Otherwise the surplus calculation drops and creates a
        feedback loop: low surplus → low target → charger stops → even
        lower surplus → stays stopped.
        """
        ev_power = ctx.wallbox.current_power_w
        if self._was_pv_charging and ev_power < 100 and self._last_target_w > 0:
            # Charger paused briefly — use last target as estimate
            ev_power = self._last_target_w
        return ctx.grid_power_w + ev_power + ctx.battery_power_w - self.grid_reserve_w

    def _calc_battery_assist(
        self,
        ctx: ChargingContext,
        pv_only_available: float,
    ) -> float:
        assist, _ = self._calc_battery_assist_detailed(ctx, pv_only_available)
        return assist

    def _calc_battery_assist_detailed(
        self,
        ctx: ChargingContext,
        pv_only_available: float,
    ) -> tuple[float, str]:
        """Extra power the home battery can contribute for EV charging."""
        if ctx.battery_soc_pct <= self.battery_min_soc_pct:
            return (
                0.0,
                f"SoC {ctx.battery_soc_pct:.0f}% <= floor {self.battery_min_soc_pct:.0f}%",
            )

        if pv_only_available >= self.min_power_w:
            return 0.0, "PV surplus sufficient (no assist needed)"

        shortfall = self.min_power_w - max(0.0, pv_only_available)
        can_refill, refill_reason = self._can_battery_refill(ctx)

        soc_headroom = (ctx.battery_soc_pct - self.battery_min_soc_pct) / (
            100.0 - self.battery_min_soc_pct
        )
        soc_factor = min(1.0, max(0.0, soc_headroom))

        if can_refill:
            # When PV forecast guarantees battery refill by sundown,
            # use full assist power above a reasonable SoC floor (~50%).
            # The soc_factor alone is too conservative — at 58% SoC with
            # 35 kWh forecast remaining, there's zero risk.
            if ctx.battery_soc_pct >= 50:
                soc_factor = 1.0
            max_assist = self.battery_ev_assist_max_w * soc_factor
            strategy = "refill OK"
        elif ctx.battery_soc_pct > 80:
            max_assist = self.battery_ev_assist_max_w * soc_factor
            strategy = f"SoC {ctx.battery_soc_pct:.0f}% > 80% (accept partial drain)"
        else:
            forecast_factor = min(
                1.0,
                ctx.pv_forecast_remaining_kwh / self.pv_forecast_good_kwh,
            )
            max_assist = (
                self.battery_ev_assist_max_w * forecast_factor * soc_factor * 0.5
            )
            strategy = f"conservative (forecast {forecast_factor:.0%})"

        if max_assist < 100:
            return (
                0.0,
                f"Assist too small ({max_assist:.0f} W) — {strategy}, {refill_reason}",
            )

        assist = min(shortfall, max_assist)
        reason = (
            f"Shortfall {shortfall:.0f} W, assist {assist:.0f}/{max_assist:.0f} W "
            f"— {strategy}, {refill_reason}"
        )
        return assist, reason

    def _calc_battery_hold_boost(
        self,
        ctx: ChargingContext,
    ) -> tuple[float, str]:
        """Hold battery at ~70% SoC, redirecting charge power to EV.

        When the battery is above the hold threshold and there's enough
        PV forecast remaining to fill the battery later (from hold_soc
        to 100%), we "over-request" from the wallbox. The inverter will
        then reduce battery charging to compensate, effectively holding
        the battery SoC steady while maximizing EV charging.

        The boost is released when remaining PV drops below what's needed
        to refill the battery, allowing the battery to charge normally
        and reach 100% by sundown.
        """
        # Only active when EV is connected and battery is charging
        if ctx.battery_power_w <= 0:
            return 0.0, "Battery not charging"

        if not ctx.wallbox.vehicle_connected:
            return 0.0, "No EV connected"

        # Night time: no hold boost (no PV production)
        current_hour = ctx.now.hour
        if current_hour >= 21 or current_hour < 6:
            return 0.0, "Night time — no hold boost"

        # Below hold threshold — let battery charge normally
        if ctx.battery_soc_pct < self.battery_hold_soc_pct:
            return 0.0, (
                f"Battery {ctx.battery_soc_pct:.0f}% < hold "
                f"{self.battery_hold_soc_pct:.0f}%"
            )

        # Energy-based release: can remaining PV still fill battery to 100%
        # while covering household consumption? If not, release the hold.
        SAFETY_BUFFER_KWH = 1.5  # kWh safety margin

        # Energy needed to fill battery from CURRENT SoC to 100%
        energy_to_full = (
            (100.0 - ctx.battery_soc_pct)
            / 100.0
            * ctx.battery_capacity_kwh  # use runtime context, not config default
        )
        hours_remaining = max(0.5, self._estimate_daylight_hours_remaining(ctx.now))
        household_kwh = (ctx.house_power_w / 1000.0) * hours_remaining

        # Can we physically charge the battery fast enough?
        max_battery_charge_kwh = (
            self.battery_ev_assist_max_w / 1000.0
        ) * hours_remaining
        energy_to_full = min(energy_to_full, max_battery_charge_kwh)

        # PV energy surplus available after household consumption
        pv_surplus_kwh = ctx.pv_forecast_remaining_kwh - household_kwh

        # Release if PV surplus can't cover battery top-off + safety buffer
        if pv_surplus_kwh < energy_to_full + SAFETY_BUFFER_KWH:
            return 0.0, (
                f"Energy-based release: PV surplus ({pv_surplus_kwh:.1f} kWh) "
                f"< battery needs ({energy_to_full:.1f} kWh) + "
                f"buffer ({SAFETY_BUFFER_KWH} kWh). "
                f"Releasing hold so battery can top off."
            )

        # Redirect battery charging power to EV.
        # The pv_only calc already includes battery_power_w, but only accounts
        # for the current state. The boost requests ADDITIONAL power beyond
        # what pv_only calculated, forcing the inverter to reduce battery charge.
        # We boost by the difference between battery's current charge rate and
        # a small trickle to maintain SoC (accounting for self-discharge).
        boost = max(0.0, ctx.battery_power_w - 100)  # keep ~100W trickle

        if boost < 200:
            return 0.0, "Battery charge rate too low for meaningful boost"

        logger.info(
            "battery_hold_active",
            battery_soc=round(ctx.battery_soc_pct),
            hold_soc=self.battery_hold_soc_pct,
            battery_charge_w=round(ctx.battery_power_w),
            boost_w=round(boost),
            pv_surplus_kwh=round(pv_surplus_kwh, 1),
            energy_to_full=round(energy_to_full, 1),
            safety_buffer=SAFETY_BUFFER_KWH,
            hours_remaining=round(hours_remaining, 1),
        )

        return boost, (
            f"Battery hold at {self.battery_hold_soc_pct:.0f}%: "
            f"SoC {ctx.battery_soc_pct:.0f}%, redirecting "
            f"{boost:.0f} W to EV "
            f"(PV surplus: {pv_surplus_kwh:.1f} kWh, "
            f"battery needs: {energy_to_full:.1f} kWh + "
            f"{SAFETY_BUFFER_KWH} kWh buffer)"
        )

    def _can_battery_refill(self, ctx: ChargingContext) -> tuple[bool, str]:
        """Check if remaining PV forecast can refill the battery by end of day."""
        target_soc = ctx.battery_target_eod_soc_pct
        current_soc = ctx.battery_soc_pct
        capacity = ctx.battery_capacity_kwh

        if current_soc >= target_soc:
            return True, f"SoC {current_soc:.0f}% >= target {target_soc:.0f}%"

        energy_to_refill = (target_soc - current_soc) / 100.0 * capacity
        hours_remaining = max(0.5, self._estimate_daylight_hours_remaining(ctx.now))
        household_kwh = (ctx.house_power_w / 1000.0) * hours_remaining
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
        """Rough estimate of productive PV hours remaining today."""
        month = now.month
        sunset_hours = {
            1: 16.5,
            2: 17.5,
            3: 18.5,
            4: 20.0,
            5: 21.0,
            6: 21.5,
            7: 21.5,
            8: 20.5,
            9: 19.5,
            10: 18.5,
            11: 17.0,
            12: 16.5,
        }
        effective_end = sunset_hours.get(month, 18.0) - 1.0
        current_hour = now.hour + now.minute / 60.0
        return max(0.0, effective_end - current_hour)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clamp(self, power_w: float) -> int:
        p = int(power_w)
        if p < self.min_power_w:
            return 0
        return min(p, self.max_power_w)

    def _reset(self) -> None:
        self._was_pv_charging = False
        self._last_target_w = 0
        self._charge_started_at = None
        self._charge_stopped_at = None

    @staticmethod
    def _hours_until(target_time: time, now: datetime) -> float:
        """Hours from *now* until *target_time* (today or tomorrow).
        Always returns positive (wraps to next day if time has passed).
        """
        target_dt = now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )
        if target_dt <= now:
            target_dt += timedelta(days=1)
        return (target_dt - now).total_seconds() / 3600

    @staticmethod
    def _hours_until_departure(target_time: time | None, now: datetime) -> float | None:
        """Hours from *now* until departure *target_time* TODAY only.

        Returns None if departure time has already passed today.
        This is the BUG #1 fix — never wraps to tomorrow.
        """
        if target_time is None:
            return None
        target_dt = now.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )
        if target_dt <= now:
            return None  # Departure has passed
        return (target_dt - now).total_seconds() / 3600
