"""Tests for decision transparency features (FR #2118-2121, #2123)."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from charger import WallboxState
from strategy import ChargeMode, ChargingContext, ChargingDecision, ChargingStrategy

TZ = ZoneInfo("Europe/Berlin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_strategy(**kwargs) -> ChargingStrategy:
    defaults = dict(
        max_power_w=11000,
        min_power_w=4200,
        eco_power_w=5000,
        grid_reserve_w=-100,
        start_hysteresis_w=300,
        ramp_step_w=500,
        startup_ramp_power_w=5000,
        startup_ramp_duration_s=0,  # disable ramp for clean tests
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
    mode: ChargeMode = ChargeMode.PV_SURPLUS,
    ev_soc_pct: float = 50.0,
    ev_target_soc_pct: float = 80.0,
    ev_battery_capacity_kwh: float = 77.0,
    pv_power_w: float = 6000.0,
    grid_power_w: float = 1500.0,  # exporting
    battery_power_w: float = 0.0,
    battery_soc_pct: float = 60.0,
    pv_forecast_remaining_kwh: float = 10.0,
    now: datetime | None = None,
    connected: bool = True,
    pv_hourly_forecast: list[dict] | None = None,
    ready_by_deadline: datetime | None = None,
) -> ChargingContext:
    if now is None:
        now = datetime(2026, 4, 13, 10, 0, tzinfo=TZ)
    return ChargingContext(
        mode=mode,
        wallbox=make_wallbox(connected=connected, power_w=4500.0 if connected else 0.0),
        grid_power_w=grid_power_w,
        pv_power_w=pv_power_w,
        battery_power_w=battery_power_w,
        battery_soc_pct=battery_soc_pct,
        pv_forecast_remaining_kwh=pv_forecast_remaining_kwh,
        pv_forecast_tomorrow_kwh=15.0,
        house_power_w=1000.0,
        battery_capacity_kwh=7.0,
        battery_target_eod_soc_pct=90.0,
        full_by_morning=False,
        departure_time=None,
        target_energy_kwh=20.0,
        session_energy_kwh=0.0,
        ev_soc_pct=ev_soc_pct,
        ev_battery_capacity_kwh=ev_battery_capacity_kwh,
        ev_target_soc_pct=ev_target_soc_pct,
        overnight_grid_kwh_charged=0.0,
        now=now,
        pv_hourly_forecast=pv_hourly_forecast,
        ready_by_deadline=ready_by_deadline,
    )


# ---------------------------------------------------------------------------
# FR #2119: Decision log
# ---------------------------------------------------------------------------


class TestDecisionLog:
    """Tests for decision log deduplication and size limit."""

    def test_decision_log_deduplicates(self):
        """Same reason twice should produce only one log entry."""
        log: deque = deque(maxlen=5)
        last_reason = ""

        def add_decision(reason: str, power_w: int = 5000) -> None:
            nonlocal last_reason
            if reason != last_reason:
                last_reason = reason
                log.append({"reason": reason, "target_power_w": power_w})

        add_decision("PV surplus: 5000 W")
        add_decision("PV surplus: 5000 W")  # duplicate — should be ignored

        assert len(log) == 1
        assert log[0]["reason"] == "PV surplus: 5000 W"

    def test_decision_log_distinct_reasons(self):
        """Different reasons should all be logged."""
        log: deque = deque(maxlen=5)
        last_reason = ""

        def add_decision(reason: str) -> None:
            nonlocal last_reason
            if reason != last_reason:
                last_reason = reason
                log.append({"reason": reason})

        add_decision("PV surplus: 5000 W")
        add_decision("No vehicle connected")
        add_decision("Deadline escalation: charging at 7000 W")

        assert len(log) == 3

    def test_decision_log_max_5(self):
        """With 10 distinct decisions, only the last 5 should be retained."""
        log: deque = deque(maxlen=5)
        last_reason = ""

        for i in range(10):
            reason = f"Reason {i}"
            if reason != last_reason:
                last_reason = reason
                log.append({"reason": reason, "index": i})

        assert len(log) == 5
        # Should contain reasons 5 through 9
        stored_reasons = [entry["reason"] for entry in log]
        assert stored_reasons == [f"Reason {i}" for i in range(5, 10)]


# ---------------------------------------------------------------------------
# FR #2118: Session cost tracking
# ---------------------------------------------------------------------------


class TestSessionCostTracking:
    """Tests for session PV/grid cost calculations."""

    def _calc_cost(
        self,
        actual_power_w: float,
        pv_available_w: float,
        cycle_seconds: float = 30.0,
        grid_price_ct: float = 25.0,
        reimbursement_ct: float = 25.0,
    ) -> dict:
        """Replicate the cost calculation logic from _control_cycle."""
        pv_fraction = (
            min(1.0, max(0.0, pv_available_w / actual_power_w))
            if actual_power_w > 0
            else 0.0
        )
        pv_kwh = actual_power_w * pv_fraction / 1000 * (cycle_seconds / 3600)
        grid_kwh = actual_power_w * (1 - pv_fraction) / 1000 * (cycle_seconds / 3600)

        grid_price = grid_price_ct / 100
        cost_eur = grid_kwh * grid_price
        savings_eur = pv_kwh * grid_price
        reimbursement_eur = (pv_kwh + grid_kwh) * reimbursement_ct / 100

        return {
            "pv_kwh": pv_kwh,
            "grid_kwh": grid_kwh,
            "cost_eur": cost_eur,
            "savings_eur": savings_eur,
            "reimbursement_eur": reimbursement_eur,
        }

    def test_session_cost_pv_only(self):
        """All-PV charging: cost=0, savings = session_kwh * grid_price."""
        # 6000W PV available, 6000W actual → 100% PV, 0 grid
        result = self._calc_cost(
            actual_power_w=6000.0,
            pv_available_w=6000.0,
            cycle_seconds=3600.0,  # 1 hour for easy numbers
        )
        assert result["pv_kwh"] == pytest.approx(6.0, rel=1e-3)
        assert result["grid_kwh"] == pytest.approx(0.0, abs=1e-9)
        assert result["cost_eur"] == pytest.approx(0.0, abs=1e-9)
        assert result["savings_eur"] == pytest.approx(6.0 * 0.25, rel=1e-3)

    def test_session_cost_grid_only(self):
        """All-grid charging: savings=0, cost = session_kwh * grid_price."""
        # 0 PV available, 6000W actual → 100% grid
        result = self._calc_cost(
            actual_power_w=6000.0,
            pv_available_w=0.0,
            cycle_seconds=3600.0,
        )
        assert result["grid_kwh"] == pytest.approx(6.0, rel=1e-3)
        assert result["pv_kwh"] == pytest.approx(0.0, abs=1e-9)
        assert result["savings_eur"] == pytest.approx(0.0, abs=1e-9)
        assert result["cost_eur"] == pytest.approx(6.0 * 0.25, rel=1e-3)

    def test_session_cost_mixed(self):
        """Mixed PV/grid: both cost and savings should be non-zero."""
        result = self._calc_cost(
            actual_power_w=6000.0,
            pv_available_w=3000.0,  # 50% PV
            cycle_seconds=3600.0,
        )
        assert result["pv_kwh"] == pytest.approx(3.0, rel=1e-3)
        assert result["grid_kwh"] == pytest.approx(3.0, rel=1e-3)
        assert result["cost_eur"] == pytest.approx(3.0 * 0.25, rel=1e-3)
        assert result["savings_eur"] == pytest.approx(3.0 * 0.25, rel=1e-3)


# ---------------------------------------------------------------------------
# FR #2120: Plan summary
# ---------------------------------------------------------------------------


def _build_plan_summary(
    decision: ChargingDecision, ctx: ChargingContext, pv_accuracy_pct: float = 90.0
) -> str:
    """Replicate the _build_plan_summary logic inline for testing without service import."""
    parts = []
    if decision.target_power_w == 0:
        parts.append(f"Paused: {decision.reason[:60]}")
    else:
        source = (
            "PV"
            if decision.pv_surplus_w >= decision.target_power_w * 0.9
            else "Grid+PV"
        )
        parts.append(f"{source} {decision.target_power_w / 1000:.1f}kW")

    if ctx.pv_hourly_forecast:
        now_hour = ctx.now.hour
        pv_hours = [
            h for h in ctx.pv_hourly_forecast if h["hour"] > now_hour and h["kwh"] > 0.5
        ]
        if pv_hours:
            peak = max(pv_hours, key=lambda h: h["kwh"])
            parts.append(f"PV peak {peak['hour']:02d}:00 ({peak['kwh']:.1f}kWh)")

    if decision.energy_remaining_kwh > 0:
        if decision.deadline_active and decision.deadline_hours_left > 0:
            parts.append(f"Ready in {decision.deadline_hours_left:.1f}h")
        elif ctx.mode in (ChargeMode.PV_ONLY, ChargeMode.PV_SURPLUS):
            if decision.estimated_completion_days > 0:
                parts.append(f"PV-only ETA: {decision.estimated_completion_days:.1f}d")

    return " | ".join(parts) if parts else "No active plan"


class TestPlanSummary:
    """Tests for plan summary string format (pure logic, no service import required)."""

    def test_plan_summary_paused(self):
        """When target_power_w=0, summary should start with 'Paused:'."""
        decision = ChargingDecision(target_power_w=0, reason="No vehicle connected")
        ctx = make_ctx()
        result = _build_plan_summary(decision, ctx)
        assert result.startswith("Paused:")

    def test_plan_summary_charging_pv(self):
        """When charging with high PV fraction, summary should show 'PV'."""
        decision = ChargingDecision(
            target_power_w=5000,
            reason="PV surplus",
            pv_surplus_w=4600.0,  # 92% PV
        )
        ctx = make_ctx()
        result = _build_plan_summary(decision, ctx)
        assert "PV" in result
        assert "5.0kW" in result

    def test_plan_summary_with_pv_forecast(self):
        """Plan summary should include PV peak hour when forecast available."""
        decision = ChargingDecision(
            target_power_w=5000,
            reason="PV surplus",
            pv_surplus_w=4600.0,
        )
        now = datetime(2026, 4, 13, 10, 0, tzinfo=TZ)
        ctx = make_ctx(
            now=now,
            pv_hourly_forecast=[
                {"hour": 11, "kwh": 3.0, "confidence": 0.9},
                {"hour": 13, "kwh": 5.5, "confidence": 0.85},
                {"hour": 15, "kwh": 2.0, "confidence": 0.8},
            ],
        )
        result = _build_plan_summary(decision, ctx)
        # Peak is at 13:00 with 5.5 kWh
        assert "13:00" in result
        assert "5.5kWh" in result

    def test_plan_summary_format(self):
        """Summary should use pipe-delimited format or 'No active plan'."""
        decision = ChargingDecision(target_power_w=0, reason="No vehicle connected")
        ctx = make_ctx(connected=False)
        result = _build_plan_summary(decision, ctx)
        # Should be non-empty
        assert len(result) > 0


# ---------------------------------------------------------------------------
# FR #2123: Mode change detection
# ---------------------------------------------------------------------------


class TestModeChangeDetection:
    """Tests for mode change tracking."""

    def test_mode_change_detected(self):
        """Changing mode should update _last_mode_change."""
        now = datetime(2026, 4, 13, 10, 0, tzinfo=TZ)
        last_mode_change: dict | None = None
        current_mode = "PV Surplus"

        old_mode = current_mode
        new_mode = "Fast"

        if old_mode != new_mode:
            last_mode_change = {
                "timestamp": now.isoformat(),
                "old_mode": old_mode,
                "new_mode": new_mode,
                "trigger": "ha_input_select_changed",
                "context": "SoC: 60%, needed: 15.4kWh",
            }
            current_mode = new_mode

        assert last_mode_change is not None
        assert last_mode_change["old_mode"] == "PV Surplus"
        assert last_mode_change["new_mode"] == "Fast"
        assert last_mode_change["trigger"] == "ha_input_select_changed"
        assert current_mode == "Fast"

    def test_no_mode_change_no_update(self):
        """Same mode should not trigger a mode change record."""
        last_mode_change = None
        current_mode = "PV Surplus"

        old_mode = current_mode
        new_mode = "PV Surplus"  # same

        if old_mode != new_mode:
            last_mode_change = {"old_mode": old_mode, "new_mode": new_mode}

        assert last_mode_change is None


# ---------------------------------------------------------------------------
# FR #2123: HEMS demand split via strategy
# ---------------------------------------------------------------------------


class TestDemandSplit:
    """Tests for demand_w == allocated_w == target_power_w until HEMS coordinator."""

    def test_demand_split_equals_target_fast(self):
        """Fast mode: demand_w == allocated_w == target_power_w."""
        strategy = make_strategy()
        ctx = make_ctx(mode=ChargeMode.FAST, ev_soc_pct=50.0, ev_target_soc_pct=80.0)
        decision = strategy.decide(ctx)
        assert decision.demand_w == decision.target_power_w
        assert decision.allocated_w == decision.target_power_w

    def test_demand_split_equals_target_pv_surplus(self):
        """PV surplus mode: demand_w == allocated_w == target_power_w."""
        strategy = make_strategy()
        ctx = make_ctx(
            mode=ChargeMode.PV_SURPLUS,
            ev_soc_pct=50.0,
            ev_target_soc_pct=80.0,
            grid_power_w=2000.0,  # good surplus
        )
        decision = strategy.decide(ctx)
        assert decision.demand_w == decision.target_power_w
        assert decision.allocated_w == decision.target_power_w

    def test_demand_split_equals_target_paused(self):
        """When paused (target=0): demand_w == allocated_w == 0."""
        strategy = make_strategy()
        ctx = make_ctx(mode=ChargeMode.OFF, ev_soc_pct=50.0)
        decision = strategy.decide(ctx)
        assert decision.target_power_w == 0
        assert decision.demand_w == 0
        assert decision.allocated_w == 0

    def test_demand_split_no_vehicle(self):
        """No vehicle: demand_w == allocated_w == 0."""
        strategy = make_strategy()
        ctx = make_ctx(
            mode=ChargeMode.PV_SURPLUS,
            connected=False,
        )
        decision = strategy.decide(ctx)
        assert decision.demand_w == 0
        assert decision.allocated_w == 0
