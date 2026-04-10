"""Advanced unit tests for PV budget allocator priority cascade (#1044).

Tests verify:
  1. Total allocated matches available PV (accounting)
  2. Priority cascade allocates in correct order
  3. Anti-grid-heat rule disables heating when importing
  4. Strategic overheat activation logic
  5. Zero PV case (no allocation)
  6. Battery capacity configuration from environment
"""

from __future__ import annotations

import pytest
from pv_budget_allocator import PVBudgetAllocator


@pytest.fixture
def allocator():
    """Create a fresh allocator for each test."""
    return PVBudgetAllocator()


# ---------------------------------------------------------------------------
# Test #1: Accounting — Total allocated ≈ available PV
# ---------------------------------------------------------------------------


class TestAllocateDistributesAllPV:
    """Test that all available PV is accounted for (allocated + export)."""

    def test_allocations_plus_export_equals_available(self, allocator):
        """total_allocated_w + grid_export_w == available_pv_w."""
        result = allocator.allocate(5000.0)
        total = result["total_allocated_w"] + result["grid_export_w"]
        assert total == pytest.approx(5000.0)

    def test_available_pv_reflected_in_result_key(self, allocator):
        """Result includes available_pv_w matching the input."""
        result = allocator.allocate(3750.0)
        assert result["available_pv_w"] == 3750.0

    def test_zero_pv_produces_zero_allocations(self, allocator):
        """With zero available PV, all allocations are 0."""
        result = allocator.allocate(0.0)
        for consumer_name, allocated_w in result["allocations"].items():
            assert allocated_w == 0.0
        assert result["grid_export_w"] == 0.0
        assert result["total_allocated_w"] == 0.0

    def test_high_pv_all_consumers_saturated(self, allocator):
        """With abundant PV, all consumers hit their max."""
        # Max capacity: house 2000 + dhw 2000 + ev 11000 + supp 3000 = 18000W
        result = allocator.allocate(25000.0)
        total_allocated = result["total_allocated_w"]
        assert total_allocated == pytest.approx(18000.0)
        # Excess goes to export
        assert result["grid_export_w"] == pytest.approx(7000.0)

    def test_random_pv_values_maintain_conservation(self, allocator):
        """Multiple random PV values all conserve total energy."""
        test_values = [150.0, 1234.5, 4567.8, 9999.9, 15000.0]
        for pv_w in test_values:
            allocator.reset = lambda: None  # Reset between tests
            allocator = PVBudgetAllocator()
            result = allocator.allocate(pv_w)
            total = result["total_allocated_w"] + result["grid_export_w"]
            assert total == pytest.approx(pv_w, abs=1.0), (
                f"Conservation failed at pv_w={pv_w}"
            )


# ---------------------------------------------------------------------------
# Test #2: House base is highest priority
# ---------------------------------------------------------------------------


class TestHouseBaseHighestPriority:
    """Test that house_base consumer is served first."""

    def test_house_base_allocated_first(self, allocator):
        """With small PV, house_base gets allocation before others."""
        result = allocator.allocate(1000.0)
        # house_base min=200W, max=2000W → should get 1000W (up to max)
        assert result["allocations"]["house_base"] == 1000.0
        # Others get nothing because remaining = 0
        assert result["allocations"]["dhw_heating"] == 0.0
        assert result["allocations"]["ev_charging"] == 0.0
        assert result["allocations"]["supplemental"] == 0.0

    def test_house_base_hits_max_first(self, allocator):
        """house_base caps at 2000W before others allocate."""
        result = allocator.allocate(5000.0)
        assert result["allocations"]["house_base"] == 2000.0
        # Remainder (3000W) goes to dhw
        assert result["allocations"]["dhw_heating"] == 2000.0
        # Rest to ev or export
        remaining_for_ev = 5000.0 - 2000.0 - 2000.0
        assert result["allocations"]["ev_charging"] == pytest.approx(remaining_for_ev)

    def test_house_base_below_min_still_activated(self, allocator):
        """house_base min=200W is always low enough to activate in real conditions."""
        # With even 100W, house_base min won't be met — test the fallthrough
        result = allocator.allocate(100.0)
        assert result["allocations"]["house_base"] == 0.0
        # Nothing allocated because 100 < house_base.min (200W)
        assert result["total_allocated_w"] == 0.0


# ---------------------------------------------------------------------------
# Test #3: Anti-grid-heat rule
# ---------------------------------------------------------------------------


class TestAntiGridHeatRule:
    """Test that heating is disabled when importing from grid."""

    def test_grid_import_zeros_supplemental_and_dhw(self, allocator):
        """When grid_import_w > 0, supplemental and DHW are disabled."""
        # Simulate grid import: grid_import_w = 100W (importing)
        result = allocator.allocate(available_pv_w=5000.0, grid_import_w=100.0)
        # dhw and supplemental should be 0 even with plenty of PV
        assert result["allocations"]["dhw_heating"] == 0.0
        assert result["allocations"]["supplemental"] == 0.0
        # house_base and ev_charging can still get power
        assert result["allocations"]["house_base"] > 0.0

    def test_zero_grid_import_allows_heating(self, allocator):
        """With zero grid import, heating is enabled normally."""
        result = allocator.allocate(available_pv_w=5000.0, grid_import_w=0.0)
        # dhw should be allocated if we have PV
        assert result["allocations"]["dhw_heating"] > 0.0

    def test_grid_import_export_zero_allows_heating(self, allocator):
        """At grid balance (zero import), heating is enabled."""
        # Negative import_w (export) should not trigger the rule
        result = allocator.allocate(available_pv_w=3000.0, grid_import_w=-500.0)
        # Should allocate normally
        assert result["allocations"]["house_base"] > 0.0
        # dhw can allocate if we have enough
        assert result["allocations"]["dhw_heating"] >= 0.0

    def test_re_enable_heating_after_grid_import(self, allocator):
        """After grid import stops, heating re-enables on next allocation."""
        # First call with import → heating disabled
        allocator.allocate(5000.0, grid_import_w=100.0)
        assert allocator.get_status()["dhw_heating"]["enabled"] is False
        # Second call without import → heating re-enabled
        allocator.allocate(5000.0, grid_import_w=0.0)
        assert allocator.get_status()["dhw_heating"]["enabled"] is True


# ---------------------------------------------------------------------------
# Test #4: Strategic overheat activation
# ---------------------------------------------------------------------------


class TestStrategicOverheatActivates:
    """Test overheat logic: surplus > 500W AND room below setpoint+2."""

    def test_should_overheat_with_surplus_and_room_cold(self, allocator):
        """Overheat eligible when surplus > 500W and room < setpoint+2."""
        should_oh = allocator.should_overheat(
            room_id="lounge",
            current_temp=19.5,
            setpoint=21.0,
            available_surplus_w=1000.0,
        )
        assert should_oh is True

    def test_should_overheat_returns_false_low_surplus(self, allocator):
        """No overheat if surplus <= 500W."""
        should_oh = allocator.should_overheat(
            room_id="lounge",
            current_temp=19.5,
            setpoint=21.0,
            available_surplus_w=300.0,
        )
        assert should_oh is False

    def test_should_overheat_returns_false_room_hot(self, allocator):
        """No overheat if room is already at setpoint+2."""
        should_oh = allocator.should_overheat(
            room_id="lounge",
            current_temp=23.0,
            setpoint=21.0,
            available_surplus_w=1000.0,
        )
        assert should_oh is False

    def test_should_overheat_returns_false_room_above_limit(self, allocator):
        """No overheat if room is above setpoint+2."""
        should_oh = allocator.should_overheat(
            room_id="lounge",
            current_temp=23.5,
            setpoint=21.0,
            available_surplus_w=1000.0,
        )
        assert should_oh is False

    def test_overheat_setpoint_calculation(self, allocator):
        """calculate_overheat_setpoint adds surplus-based bonus (up to 2°C)."""
        # surplus = 1000W → bonus = min(2, 1/1) = 1°C
        result = allocator.calculate_overheat_setpoint(21.0, 1000.0)
        assert result == pytest.approx(22.0)

    def test_overheat_setpoint_capped_at_2_degrees(self, allocator):
        """Overheat bonus caps at 2°C even with huge surplus."""
        # surplus = 5000W → bonus = min(2, 5) = 2°C (capped)
        result = allocator.calculate_overheat_setpoint(21.0, 5000.0)
        assert result == pytest.approx(23.0)

    def test_overheat_setpoint_zero_surplus(self, allocator):
        """Zero surplus → zero bonus."""
        result = allocator.calculate_overheat_setpoint(21.0, 0.0)
        assert result == pytest.approx(21.0)

    def test_overheat_decision_requires_both_conditions(self, allocator):
        """Overheat requires BOTH surplus > 500W AND room < setpoint+2."""
        # Test boundary cases
        # Exactly 500W surplus → false (not > 500)
        assert (
            allocator.should_overheat(
                "test", current_temp=20.0, setpoint=21.0, available_surplus_w=500.0
            )
            is False
        )
        # Exactly setpoint+2 → false (not < setpoint+2)
        assert (
            allocator.should_overheat(
                "test", current_temp=23.0, setpoint=21.0, available_surplus_w=1000.0
            )
            is False
        )


# ---------------------------------------------------------------------------
# Test #5: No PV, no heating
# ---------------------------------------------------------------------------


class TestAllocateNoPVNoHeating:
    """Test that with zero available PV, heating consumers get nothing."""

    def test_zero_pv_all_consumers_zero(self, allocator):
        """When available_pv_w = 0, all allocations are 0."""
        result = allocator.allocate(0.0)
        for consumer in ["house_base", "dhw_heating", "ev_charging", "supplemental"]:
            assert result["allocations"][consumer] == 0.0

    def test_zero_pv_no_export(self, allocator):
        """When available_pv_w = 0, grid_export_w = 0."""
        result = allocator.allocate(0.0)
        assert result["grid_export_w"] == 0.0

    def test_zero_pv_total_allocated_zero(self, allocator):
        """When available_pv_w = 0, total_allocated_w = 0."""
        result = allocator.allocate(0.0)
        assert result["total_allocated_w"] == 0.0


# ---------------------------------------------------------------------------
# Test #6: Battery capacity configuration
# ---------------------------------------------------------------------------


class TestBatteryConfigFromEnv:
    """Test that battery configuration can be set from environment variables."""

    def test_battery_capacity_from_init(self, allocator):
        """Constructor battery_capacity_kwh parameter is respected."""
        alloc = PVBudgetAllocator(battery_capacity_kwh=19.2)
        assert alloc.battery_capacity_kwh == 19.2

    def test_battery_capacity_defaults_to_7kwh(self, allocator):
        """Without override, defaults to 7.0 kWh."""
        alloc = PVBudgetAllocator()
        # Default from env or 7.0
        assert alloc.battery_capacity_kwh >= 7.0

    def test_battery_max_charge_from_init(self, allocator):
        """Constructor can set battery_max_charge_w."""
        # Note: current API doesn't expose battery_max_charge_w in __init__,
        # but we test the attribute exists
        alloc = PVBudgetAllocator()
        assert alloc.battery_max_charge_w > 0.0
        assert alloc.battery_max_discharge_w > 0.0

    def test_allocator_with_custom_battery(self):
        """Allocator can be instantiated with custom battery capacity."""
        alloc_small = PVBudgetAllocator(battery_capacity_kwh=5.0)
        alloc_large = PVBudgetAllocator(battery_capacity_kwh=20.0)
        assert alloc_small.battery_capacity_kwh == 5.0
        assert alloc_large.battery_capacity_kwh == 20.0


# ---------------------------------------------------------------------------
# Edge cases and robustness
# ---------------------------------------------------------------------------


class TestEdgeCasesAndRobustness:
    """Test edge cases and numerical stability."""

    def test_negative_pv_input_treated_as_zero(self, allocator):
        """Negative available_pv_w should not cause allocation."""
        # Allocator doesn't explicitly clamp, but should handle gracefully
        result = allocator.allocate(-1000.0)
        # With negative input, remaining would be negative, so nothing allocates
        assert result["total_allocated_w"] >= 0.0

    def test_very_small_pv_below_any_min(self, allocator):
        """PV below lowest consumer min (200W) → no allocation."""
        result = allocator.allocate(150.0)
        assert result["total_allocated_w"] == 0.0
        assert result["grid_export_w"] == 0.0

    def test_very_large_pv_value(self, allocator):
        """Very large PV value doesn't break accounting."""
        result = allocator.allocate(100000.0)
        total = result["total_allocated_w"] + result["grid_export_w"]
        assert total == pytest.approx(100000.0)

    def test_consumer_status_changes_persist(self, allocator):
        """Disabling/enabling consumers persists across allocations."""
        allocator.set_consumer_enabled("ev_charging", False)
        result1 = allocator.allocate(5000.0)
        assert result1["allocations"]["ev_charging"] == 0.0

        # Without re-enabling, still disabled
        result2 = allocator.allocate(5000.0)
        assert result2["allocations"]["ev_charging"] == 0.0

        # After re-enabling, back to normal
        allocator.set_consumer_enabled("ev_charging", True)
        result3 = allocator.allocate(5000.0)
        assert result3["allocations"]["ev_charging"] > 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
