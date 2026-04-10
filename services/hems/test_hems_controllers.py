"""Combined unit tests for HEMS controllers (#1033, #1034, #1043, #1046, #1047).

Covers:
  - SupplementalHeatController (supplemental_heat.py): activation, hysteresis, PV gate
  - WoodOvenAdvisor (wood_oven_advisor.py): start-time calculation
  - DHWController (dhw_controller.py): target setpoint, legionella schedule, PV boost

All network and HA calls are mocked so the test suite runs without
external connectivity.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock influxdb_client so supplemental_heat.py imports cleanly without the
# optional influxdb-client package installed.
# ---------------------------------------------------------------------------
sys.modules.setdefault("influxdb_client", MagicMock())
sys.modules.setdefault("influxdb_client.client", MagicMock())
sys.modules.setdefault("influxdb_client.client.write_api", MagicMock())

from supplemental_heat import (
    HeaterState,
    SupplementalHeatConfig,
    SupplementalHeatController,
)
from wood_oven_advisor import WoodOvenAdvisor, WoodOvenConfig
from dhw_controller import DHWConfig, DHWController

# ===========================================================================
# SupplementalHeatController
# ===========================================================================


class TestSupplementalHeatControllerPVGate:
    """Activation only happens when PV surplus is present."""

    @pytest.fixture
    def ctrl(self):
        cfg = SupplementalHeatConfig(
            min_surplus_kw=3.0,
            off_threshold_kw=1.5,
            min_duration_min=1.0,  # 60 s — fast for tests
            max_daily_hours=4.0,
        )
        c = SupplementalHeatController(config=cfg)
        c._turn_on_via_orchestrator = AsyncMock()
        c._turn_off_via_orchestrator = AsyncMock()
        return c

    @pytest.mark.asyncio
    async def test_no_surplus_stays_off(self, ctrl):
        """No PV surplus → stays OFF."""
        result = await ctrl.tick(solar_power_w=500, household_load_w=2000, dt_s=10)
        assert result["state"] == "off"
        assert result["is_on"] is False

    @pytest.mark.asyncio
    async def test_surplus_below_min_stays_off(self, ctrl):
        """Surplus below min_surplus_kw (3 kW) → stays OFF."""
        result = await ctrl.tick(solar_power_w=3500, household_load_w=1000, dt_s=10)
        # 2.5 kW surplus < 3.0 kW → stays OFF
        assert result["state"] == "off"

    @pytest.mark.asyncio
    async def test_surplus_above_min_enters_charging(self, ctrl):
        """Surplus >= min_surplus_kw → enters CHARGING (not yet ON)."""
        result = await ctrl.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        assert result["state"] == "charging"
        assert result["is_on"] is False

    @pytest.mark.asyncio
    async def test_sustained_surplus_activates(self, ctrl):
        """After min_duration (60 s), transitions OFF → CHARGING → ON."""
        # First tick: enter CHARGING
        await ctrl.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        assert ctrl.state == HeaterState.CHARGING

        # Accumulate 61 s of surplus (7 × 10 s = 70 s > 60 s)
        for _ in range(6):
            await ctrl.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)

        result = await ctrl.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        assert result["state"] == "on"
        assert result["is_on"] is True


class TestSupplementalHeatControllerHysteresis:
    """Surplus drop below off_threshold turns heater off."""

    @pytest.fixture
    def ctrl_on(self):
        """Controller pre-placed in ON state."""
        cfg = SupplementalHeatConfig(
            min_surplus_kw=3.0,
            off_threshold_kw=1.5,
            min_duration_min=1.0,
            max_daily_hours=4.0,
        )
        c = SupplementalHeatController(config=cfg)
        c._turn_on_via_orchestrator = AsyncMock()
        c._turn_off_via_orchestrator = AsyncMock()
        return c

    async def _reach_on_state(self, ctrl):
        await ctrl.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        for _ in range(6):
            await ctrl.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        await ctrl.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        assert ctrl.state == HeaterState.ON

    @pytest.mark.asyncio
    async def test_above_off_threshold_stays_on(self, ctrl_on):
        """Surplus between off_threshold and min_surplus → stays ON."""
        await self._reach_on_state(ctrl_on)
        # 2.0 kW > 1.5 kW off_threshold → stays ON
        result = await ctrl_on.tick(solar_power_w=3000, household_load_w=1000, dt_s=10)
        assert result["state"] == "on"
        assert result["is_on"] is True

    @pytest.mark.asyncio
    async def test_below_off_threshold_turns_off(self, ctrl_on):
        """Surplus below off_threshold → turns OFF."""
        await self._reach_on_state(ctrl_on)
        # 0.8 kW < 1.5 kW off_threshold → turn off
        result = await ctrl_on.tick(solar_power_w=1800, household_load_w=1000, dt_s=10)
        assert result["state"] == "off"
        assert result["is_on"] is False

    @pytest.mark.asyncio
    async def test_daily_limit_triggers_cooldown(self, ctrl_on):
        """Exceeding max_daily_hours → transitions to COOLDOWN."""
        cfg = SupplementalHeatConfig(
            min_surplus_kw=3.0,
            off_threshold_kw=1.5,
            min_duration_min=1.0,
            max_daily_hours=0.01,  # ~36 s limit for fast test
        )
        ctrl_on.config = cfg
        await self._reach_on_state(ctrl_on)
        # Force many ticks to exceed the tiny daily limit
        for _ in range(10):
            await ctrl_on.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        result = await ctrl_on.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
        assert result["daily_limit_exceeded"] is True
        assert result["state"] == "cooldown"


# ===========================================================================
# WoodOvenAdvisor
# ===========================================================================


class TestWoodOvenAdvisorStartTime:
    """Calculation of optimal start time."""

    def _future(self, hours: float = 4.0) -> datetime:
        return datetime.now(timezone.utc) + timedelta(hours=hours)

    def test_no_warmup_needed(self):
        """Room already at or above target → warmup time is the minimum floor."""
        advisor = WoodOvenAdvisor()
        result = advisor.calculate_start_time(
            target_temp=20.0,
            current_temp=21.0,
            desired_ready_by=self._future(4),
        )
        assert result["delta_temp"] == 0.0
        assert result["warmup_minutes"] == 30  # floor

    def test_typical_delta(self):
        """3 °C delta with mild outside temp → reasonable warmup time."""
        advisor = WoodOvenAdvisor(WoodOvenConfig(warmup_minutes_per_degree=8.0))
        result = advisor.calculate_start_time(
            target_temp=21.0,
            current_temp=18.0,
            desired_ready_by=self._future(6),
            outside_temp=5.0,
        )
        # 3 °C × 8 min/°C = 24 min, floor = 30
        assert result["warmup_minutes"] == 30
        assert result["urgency"] == "ok"

    def test_large_delta_with_cold_room(self):
        """Large delta and cold room → cold-start overhead is added."""
        advisor = WoodOvenAdvisor(
            WoodOvenConfig(
                warmup_minutes_per_degree=8.0, cold_start_overhead_minutes=30
            )
        )
        result = advisor.calculate_start_time(
            target_temp=22.0,
            current_temp=12.0,  # cold room
            desired_ready_by=self._future(5),
            outside_temp=2.0,
        )
        # 10 °C × 8 × 1.15 = 92 min + 30 overhead = 122 min
        assert result["warmup_minutes"] >= 100
        assert result["delta_temp"] == 10.0

    def test_very_cold_outside_multiplier(self):
        """Below 0 °C outside → 1.3× multiplier applied."""
        advisor = WoodOvenAdvisor(WoodOvenConfig(warmup_minutes_per_degree=10.0))
        result = advisor.calculate_start_time(
            target_temp=20.0,
            current_temp=16.0,
            desired_ready_by=self._future(6),
            outside_temp=-5.0,
        )
        # 4 °C × 10 × 1.3 = 52 min
        assert result["warmup_minutes"] == 52

    def test_overdue_urgency(self):
        """Desired time already in the past → urgency=urgent."""
        advisor = WoodOvenAdvisor()
        result = advisor.calculate_start_time(
            target_temp=21.0,
            current_temp=15.0,
            desired_ready_by=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        assert result["urgency"] == "urgent"

    def test_daily_recommendation_returns_expected_keys(self):
        """get_daily_recommendation returns all required dict keys."""
        advisor = WoodOvenAdvisor()
        result = advisor.get_daily_recommendation(current_temp=17.0, outside_temp=4.0)
        for key in (
            "start_time",
            "warmup_minutes",
            "minutes_until_start",
            "advice",
            "urgency",
        ):
            assert key in result


# ===========================================================================
# DHWController
# ===========================================================================


class TestDHWControllerSetpoint:
    """Target setpoint selection logic."""

    def test_normal_setpoint_no_pv(self):
        """No PV surplus → returns normal setpoint."""
        ctrl = DHWController()
        ctrl.update_pv_surplus(0.0)
        # A weekday at an off-peak hour
        ts = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)  # Thursday
        assert ctrl.get_target_setpoint(ts) == ctrl.config.normal_setpoint

    def test_pv_opportunistic_setpoint(self):
        """PV surplus >= threshold → raises setpoint to pv_opportunistic_setpoint."""
        ctrl = DHWController()
        ctrl.update_pv_surplus(1000.0)  # above default 800 W threshold
        ts = datetime(2026, 4, 10, 14, 0, tzinfo=timezone.utc)
        assert ctrl.get_target_setpoint(ts) == ctrl.config.pv_opportunistic_setpoint

    def test_pv_just_below_threshold_uses_normal(self):
        """Surplus just below threshold → normal setpoint."""
        ctrl = DHWController(DHWConfig(pv_surplus_threshold_w=800.0))
        ctrl.update_pv_surplus(799.9)
        ts = datetime(2026, 4, 10, 14, 0, tzinfo=timezone.utc)
        assert ctrl.get_target_setpoint(ts) == ctrl.config.normal_setpoint

    def test_legionella_schedule(self):
        """Sunday at 02:xx → returns legionella setpoint."""
        ctrl = DHWController()
        # weekday() == 6 → Sunday
        sunday_2am = datetime(2026, 4, 12, 2, 30, tzinfo=timezone.utc)
        assert sunday_2am.weekday() == 6
        assert ctrl.get_target_setpoint(sunday_2am) == ctrl.config.legionella_setpoint

    def test_legionella_not_triggered_other_hours(self):
        """Sunday outside legionella window → normal or PV setpoint."""
        ctrl = DHWController()
        ctrl.update_pv_surplus(0.0)
        sunday_noon = datetime(2026, 4, 12, 12, 0, tzinfo=timezone.utc)
        sp = ctrl.get_target_setpoint(sunday_noon)
        assert sp == ctrl.config.normal_setpoint

    def test_needs_reheat_true_when_cold(self):
        """Temp well below setpoint minus deadband → needs reheat."""
        ctrl = DHWController()
        ctrl.update_temp(40.0)  # well below 55 − 5 = 50
        ctrl.update_pv_surplus(0.0)
        assert ctrl.needs_reheat() is True

    def test_needs_reheat_false_when_warm(self):
        """Temp above setpoint − deadband → no reheat needed."""
        ctrl = DHWController()
        ctrl.update_temp(52.0)  # above 55 − 5 = 50
        ctrl.update_pv_surplus(0.0)
        assert ctrl.needs_reheat() is False

    def test_get_status_keys(self):
        """get_status() returns all expected keys."""
        ctrl = DHWController()
        status = ctrl.get_status()
        for key in (
            "current_temp",
            "target_setpoint",
            "needs_reheat",
            "pv_surplus_w",
            "pv_opportunistic_active",
        ):
            assert key in status
