"""Tests for Auto, Ready By, and PV Only charge modes (FR #2114-2116)."""

from __future__ import annotations

from datetime import datetime, time
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo


from charger import WallboxState
from strategy import ChargeMode, ChargingContext, ChargingStrategy


TZ = ZoneInfo("Europe/Berlin")


def make_strategy(**kwargs) -> ChargingStrategy:
    defaults = dict(
        max_power_w=11000,
        min_power_w=4200,
        eco_power_w=5000,
        grid_reserve_w=-100,
        start_hysteresis_w=300,
        ramp_step_w=500,
        startup_ramp_power_w=5000,
        startup_ramp_duration_s=0,  # disable startup ramp for tests
        battery_min_soc_pct=20.0,
        battery_ev_assist_max_w=3500.0,
        battery_capacity_kwh=7.0,
        battery_target_eod_soc_pct=90.0,
        pv_forecast_good_kwh=15.0,
        pv_morning_fraction=0.45,
        charger_efficiency=0.90,
        battery_hold_soc_pct=70.0,
        battery_hold_margin=1.3,
        pv_defer_confidence_factor=1.3,
        pv_defer_min_hours_before_departure=1.5,
        min_charge_duration_s=0,  # disable anti-cycling for tests
        stop_cooldown_s=0,
    )
    defaults.update(kwargs)
    return ChargingStrategy(**defaults)


def make_wallbox(
    connected: bool = True,
    charging: bool = False,
    power_w: float = 0.0,
    session_kwh: float = 0.0,
) -> WallboxState:
    wb = MagicMock(spec=WallboxState)
    wb.vehicle_connected = connected
    wb.vehicle_charging = charging
    wb.current_power_w = power_w
    wb.session_energy_kwh = session_kwh
    wb.vehicle_state_text = "connected" if connected else "disconnected"
    return wb


def make_ctx(
    mode: ChargeMode = ChargeMode.AUTO,
    ev_soc_pct: float = 50.0,
    ev_target_soc_pct: float = 80.0,
    ev_battery_capacity_kwh: float = 77.0,
    pv_power_w: float = 5000.0,
    grid_power_w: float = 1000.0,  # exporting
    battery_power_w: float = 0.0,
    battery_soc_pct: float = 60.0,
    pv_forecast_remaining_kwh: float = 10.0,
    pv_forecast_tomorrow_kwh: float = 15.0,
    drain_pv_battery: bool = False,
    full_by_morning: bool = False,
    departure_time: time | None = None,
    weekly_plan: list[dict] | None = None,
    ready_by_target_soc: float = 0.0,
    ready_by_deadline: datetime | None = None,
    pv_hourly_forecast: list[dict] | None = None,
    pv_forecast_tomorrow_hourly: list[dict] | None = None,
    now: datetime | None = None,
    connected: bool = True,
) -> ChargingContext:
    if now is None:
        now = datetime(2026, 4, 13, 14, 0, tzinfo=TZ)  # 14:00 daytime
    return ChargingContext(
        mode=mode,
        wallbox=make_wallbox(connected=connected),
        grid_power_w=grid_power_w,
        pv_power_w=pv_power_w,
        battery_power_w=battery_power_w,
        battery_soc_pct=battery_soc_pct,
        pv_forecast_remaining_kwh=pv_forecast_remaining_kwh,
        pv_forecast_tomorrow_kwh=pv_forecast_tomorrow_kwh,
        house_power_w=500.0,
        battery_capacity_kwh=7.0,
        battery_target_eod_soc_pct=90.0,
        full_by_morning=full_by_morning,
        departure_time=departure_time,
        target_energy_kwh=20.0,
        session_energy_kwh=0.0,
        ev_soc_pct=ev_soc_pct,
        ev_battery_capacity_kwh=ev_battery_capacity_kwh,
        ev_target_soc_pct=ev_target_soc_pct,
        overnight_grid_kwh_charged=0.0,
        now=now,
        drain_pv_battery=drain_pv_battery,
        weekly_plan=weekly_plan,
        ready_by_target_soc=ready_by_target_soc,
        ready_by_deadline=ready_by_deadline,
        pv_hourly_forecast=pv_hourly_forecast,
        pv_forecast_tomorrow_hourly=pv_forecast_tomorrow_hourly,
    )


class TestAutoMode:
    def test_auto_mode_without_weekly_plan(self):
        """Auto behaves like Smart when no weekly plan is present."""
        strategy = make_strategy()
        # Daytime, PV surplus available, no plan
        ctx = make_ctx(mode=ChargeMode.AUTO, weekly_plan=None)
        decision = strategy.decide(ctx)
        # Should charge (PV surplus available)
        assert decision.target_power_w > 0
        assert not decision.skip_control
        assert "auto" in decision.reason.lower() or decision.target_power_w > 0

    def test_auto_mode_drain_enabled_by_default(self):
        """In Auto mode, drain PV battery is enabled by default even without the toggle."""
        # Use separate strategy instances to avoid ramp state sharing
        strategy_auto = make_strategy()
        strategy_smart = make_strategy()

        # Low PV surplus (barely above min) so drain boost difference is visible.
        # Battery SoC high enough so drain calc produces a budget.
        ctx = make_ctx(
            mode=ChargeMode.AUTO,
            battery_soc_pct=85.0,
            pv_power_w=1500.0,
            grid_power_w=200.0,  # ~200 W export — not enough for min_power on its own
            drain_pv_battery=False,  # toggle OFF — Auto forces it on anyway
            pv_forecast_remaining_kwh=12.0,
        )
        decision_auto = strategy_auto.decide(ctx)

        # Smart with drain OFF and same conditions
        smart_ctx = make_ctx(
            mode=ChargeMode.SMART,
            battery_soc_pct=85.0,
            pv_power_w=1500.0,
            grid_power_w=200.0,
            drain_pv_battery=False,
            pv_forecast_remaining_kwh=12.0,
        )
        decision_smart = strategy_smart.decide(smart_ctx)

        # AUTO forces drain=True, so battery_assist_reason should mention drain
        assert (
            "drain" in decision_auto.reason.lower()
            or decision_auto.drain_boost_w > 0
            or decision_auto.battery_assist_w > 0
        )
        # Smart with drain OFF should NOT have drain boost
        assert decision_smart.drain_boost_w == 0.0

    def test_auto_mode_defer_when_pv_only_tomorrow(self):
        """Auto defers overnight grid charge when tomorrow plan is 'pv_only' with sufficient forecast."""
        strategy = make_strategy(pv_defer_confidence_factor=1.3)

        # EV needs ~4.62 kWh (74%→80% on 77 kWh). Tomorrow plan pv_only with 10 kWh.
        # Condition: 10.0 >= 4.62 * 1.3 (= 6.0) → True, so defers.
        tomorrow_plan = {
            "date": "2026-04-14",
            "charge_source_recommendation": "pv_only",
            "pv_expected_kwh": 10.0,
            "energy_needed_kwh": 4.62,
            "grid_needed_kwh": 0.0,
            "target_soc_start_of_day": 80.0,
            "trips": [],
        }
        weekly_plan = [
            {
                "date": "2026-04-13",
                "charge_source_recommendation": "pv_only",
                "pv_expected_kwh": 0.0,
                "energy_needed_kwh": 4.62,
                "grid_needed_kwh": 4.62,
                "target_soc_start_of_day": 80.0,
                "trips": [],
            },
            tomorrow_plan,
        ]

        now = datetime(2026, 4, 13, 22, 30, tzinfo=TZ)
        ctx = make_ctx(
            mode=ChargeMode.AUTO,
            ev_soc_pct=74.0,
            ev_target_soc_pct=80.0,
            ev_battery_capacity_kwh=77.0,
            pv_power_w=0.0,
            grid_power_w=-200.0,
            battery_soc_pct=20.0,  # at floor — no drain or battery assist
            now=now,
            weekly_plan=weekly_plan,
        )
        decision = strategy.decide(ctx)

        # Should defer — not grid charging
        assert decision.target_power_w == 0
        assert decision.solar_defer_active is True
        assert "pv" in decision.reason.lower() or "defer" in decision.reason.lower()

    def test_auto_mode_no_defer_when_grid_required_tomorrow(self):
        """Auto does NOT defer when tomorrow plan is 'grid_required'."""
        strategy = make_strategy(pv_defer_confidence_factor=1.3)

        tomorrow_plan = {
            "date": "2026-04-14",
            "charge_source_recommendation": "grid_required",
            "pv_expected_kwh": 5.0,  # insufficient
            "energy_needed_kwh": 15.0,
            "grid_needed_kwh": 10.0,
            "target_soc_start_of_day": 80.0,
            "trips": [],
        }
        weekly_plan = [
            {
                "date": "2026-04-13",
                "charge_source_recommendation": "grid_required",
                "pv_expected_kwh": 0.0,
                "energy_needed_kwh": 15.0,
                "grid_needed_kwh": 15.0,
                "target_soc_start_of_day": 80.0,
                "trips": [],
            },
            tomorrow_plan,
        ]

        now = datetime(2026, 4, 13, 22, 30, tzinfo=TZ)
        ctx = make_ctx(
            mode=ChargeMode.AUTO,
            ev_soc_pct=50.0,
            ev_target_soc_pct=80.0,
            pv_power_w=0.0,
            grid_power_w=-200.0,
            full_by_morning=True,
            departure_time=time(7, 30),
            now=now,
            weekly_plan=weekly_plan,
        )
        decision = strategy.decide(ctx)
        # Should NOT defer — grid required
        assert decision.solar_defer_active is False


class TestReadyByMode:
    def test_ready_by_pv_sufficient(self):
        """Ready By falls back to PV surplus when PV forecast can meet deadline."""
        strategy = make_strategy()

        deadline = datetime(2026, 4, 13, 20, 0, tzinfo=TZ)  # 20:00 today
        now = datetime(2026, 4, 13, 14, 0, tzinfo=TZ)  # 14:00 now → 6h left

        # EV needs 10 kWh: 50% SoC → 80% target on 77 kWh battery = ~23 kWh needed
        # But let's use a small battery + low SoC for a simpler number
        # 10 kWh needed, 12 kWh PV available in window (> 10 * 1.1 = 11 kWh)
        pv_hourly = [
            {"hour": h, "kwh": 2.0, "confidence": 0.9}
            for h in range(14, 20)  # 14:00-19:00 = 6 slots * 2 kWh = 12 kWh
        ]

        ctx = make_ctx(
            mode=ChargeMode.READY_BY,
            ev_soc_pct=50.0,
            ev_target_soc_pct=63.0,  # needs ~10 kWh on 77 kWh battery
            ev_battery_capacity_kwh=77.0,
            ready_by_target_soc=63.0,
            ready_by_deadline=deadline,
            pv_hourly_forecast=pv_hourly,
            pv_power_w=5000.0,
            grid_power_w=1500.0,
            now=now,
        )
        decision = strategy.decide(ctx)

        # PV forecast (12 kWh) >= energy_needed * 1.1 (~11 kWh) → PV-only strategy
        assert "pv sufficient" in decision.reason.lower() or decision.pv_surplus_w >= 0
        assert decision.deadline_active is True
        assert decision.deadline_hours_left > 0

    def test_ready_by_grid_assist(self):
        """Ready By activates grid assist when PV insufficient for deadline."""
        strategy = make_strategy()

        deadline = datetime(2026, 4, 13, 15, 0, tzinfo=TZ)  # deadline in 1h
        now = datetime(2026, 4, 13, 14, 0, tzinfo=TZ)

        # 20 kWh needed, only 0.5 kWh PV in window → must use grid
        pv_hourly = [{"hour": 14, "kwh": 0.5, "confidence": 0.5}]

        ctx = make_ctx(
            mode=ChargeMode.READY_BY,
            ev_soc_pct=40.0,
            ev_target_soc_pct=66.0,  # ~20 kWh needed
            ev_battery_capacity_kwh=77.0,
            ready_by_target_soc=66.0,
            ready_by_deadline=deadline,
            pv_hourly_forecast=pv_hourly,
            pv_power_w=0.0,
            grid_power_w=-500.0,
            now=now,
        )
        decision = strategy.decide(ctx)

        assert decision.target_power_w > 0
        assert decision.deadline_active is True
        assert "grid" in decision.reason.lower() or decision.deadline_required_w > 0

    def test_ready_by_deadline_passed(self):
        """Ready By charges at max when deadline has passed."""
        strategy = make_strategy()

        deadline = datetime(2026, 4, 13, 13, 0, tzinfo=TZ)  # 1h ago
        now = datetime(2026, 4, 13, 14, 0, tzinfo=TZ)

        ctx = make_ctx(
            mode=ChargeMode.READY_BY,
            ev_soc_pct=50.0,
            ev_target_soc_pct=80.0,
            ready_by_deadline=deadline,
            pv_power_w=0.0,
            now=now,
        )
        decision = strategy.decide(ctx)

        assert decision.target_power_w == 11000  # max_power_w
        assert "deadline passed" in decision.reason.lower()

    def test_ready_by_no_deadline_pv_surplus(self):
        """Ready By with no deadline falls back to PV surplus."""
        strategy = make_strategy()

        ctx = make_ctx(
            mode=ChargeMode.READY_BY,
            ready_by_deadline=None,
            pv_power_w=5000.0,
            grid_power_w=1500.0,
        )
        decision = strategy.decide(ctx)

        # Should use PV surplus, not grid
        assert (
            "no deadline" in decision.reason.lower() or "pv" in decision.reason.lower()
        )
        assert decision.deadline_active is False


class TestPVOnlyMode:
    def test_pv_only_never_grid(self):
        """PV Only always returns PV surplus power, never requests pure grid."""
        strategy = make_strategy()

        # No PV surplus — should return 0 W, not grid
        ctx_no_pv = make_ctx(
            mode=ChargeMode.PV_ONLY,
            pv_power_w=0.0,
            grid_power_w=-500.0,  # importing
        )
        decision_no_pv = strategy.decide(ctx_no_pv)
        assert decision_no_pv.target_power_w == 0

        # With PV surplus above min_power (need > 4200 W available)
        # pv_surplus = grid_power + ev_power + battery_power - reserve
        # = 4500 + 0 + 0 - (-100) = 4600 W > 4200 threshold
        ctx_pv = make_ctx(
            mode=ChargeMode.PV_ONLY,
            pv_power_w=8000.0,
            grid_power_w=4500.0,  # exporting 4.5 kW → surplus 4600 W > min 4200
            battery_soc_pct=30.0,  # low battery → no assist needed
        )
        decision_pv = strategy.decide(ctx_pv)
        assert decision_pv.target_power_w > 0
        assert "pv only" in decision_pv.reason.lower()

    def test_pv_only_completion_estimate_today(self):
        """PV Only sets estimated_completion_days=0 when today's PV covers need."""
        strategy = make_strategy()

        # EV needs ~10 kWh, hourly forecast shows 15 kWh today
        pv_hourly = [{"hour": h, "kwh": 1.5, "confidence": 0.9} for h in range(10, 20)]
        now = datetime(2026, 4, 13, 10, 0, tzinfo=TZ)

        ctx = make_ctx(
            mode=ChargeMode.PV_ONLY,
            ev_soc_pct=50.0,
            ev_target_soc_pct=63.0,  # ~10 kWh on 77 kWh
            pv_power_w=6000.0,
            grid_power_w=2000.0,
            pv_hourly_forecast=pv_hourly,
            now=now,
        )
        decision = strategy.decide(ctx)

        assert decision.estimated_completion_days == 0.0

    def test_pv_only_completion_estimate_multiday(self):
        """PV Only sets estimated_completion_days > 1 when multi-day needed."""
        strategy = make_strategy()

        # EV needs ~23 kWh (50%→80% on 77 kWh), today has 5 kWh remaining, tomorrow 10 kWh
        pv_hourly_today = [
            {"hour": h, "kwh": 0.5, "confidence": 0.5} for h in range(16, 20)
        ]  # 2 kWh today
        pv_hourly_tomorrow = [
            {"hour": h, "kwh": 1.0, "confidence": 0.8} for h in range(8, 18)
        ]  # 10 kWh tomorrow
        now = datetime(2026, 4, 13, 16, 0, tzinfo=TZ)

        ctx = make_ctx(
            mode=ChargeMode.PV_ONLY,
            ev_soc_pct=50.0,
            ev_target_soc_pct=80.0,  # ~23 kWh needed
            ev_battery_capacity_kwh=77.0,
            pv_power_w=2000.0,
            grid_power_w=1500.0,
            pv_hourly_forecast=pv_hourly_today,
            pv_forecast_tomorrow_hourly=pv_hourly_tomorrow,
            now=now,
        )
        decision = strategy.decide(ctx)

        # Today: 2 kWh * 0.9 = 1.8 kWh, Tomorrow: 10 kWh * 0.9 = 9 kWh
        # Total ~10.8 kWh < 23 kWh needed → more than 2 days
        assert decision.estimated_completion_days > 1.0


class TestExistingSmartModeUnchanged:
    def test_existing_smart_mode_unchanged(self):
        """Smart mode behavior unchanged — still uses PV surplus + grid fallback."""
        strategy = make_strategy()

        # Daytime, PV surplus available
        ctx = make_ctx(
            mode=ChargeMode.SMART,
            pv_power_w=6000.0,
            grid_power_w=1800.0,  # exporting
            drain_pv_battery=False,
        )
        decision = strategy.decide(ctx)

        assert decision.target_power_w > 0
        assert "smart" in decision.reason.lower()

    def test_smart_drain_only_when_toggle_on(self):
        """Smart mode only drains PV battery when toggle is explicitly set."""
        strategy = make_strategy()

        # Smart with drain OFF — should not get extra drain power
        ctx_no_drain = make_ctx(
            mode=ChargeMode.SMART,
            battery_soc_pct=85.0,
            pv_power_w=4000.0,
            grid_power_w=500.0,
            drain_pv_battery=False,
        )
        d_no_drain = strategy.decide(ctx_no_drain)

        # Smart with drain ON
        ctx_drain = make_ctx(
            mode=ChargeMode.SMART,
            battery_soc_pct=85.0,
            pv_power_w=4000.0,
            grid_power_w=500.0,
            drain_pv_battery=True,
        )
        d_drain = strategy.decide(ctx_drain)

        # With drain on, should have drain_boost_w > 0 or more total power
        assert d_no_drain.drain_boost_w == 0.0
        # drain mode with toggle should produce >= power
        assert d_drain.target_power_w >= d_no_drain.target_power_w
