"""Unit tests for pv_budget_allocator.py (#1044).

Tests verify:
  1. Priority cascade allocates in correct order
  2. min_power_w threshold gates activation
  3. max_power_w caps allocation
  4. Disabled consumers are skipped
  5. grid_export_w = unallocated surplus
  6. total_allocated_w accounting
  7. set_consumer_enabled raises on unknown name
  8. get_status() reflects current state
"""

from __future__ import annotations

import pytest

from pv_budget_allocator import PVBudgetAllocator


@pytest.fixture
def allocator():
    return PVBudgetAllocator()


class TestPriorityOrder:
    def test_house_base_gets_allocated_first(self, allocator):
        """house_base (priority=1) gets allocation before all others."""
        result = allocator.allocate(500.0)
        # house_base min=200W, so it should be allocated
        assert result["allocations"]["house_base"] == 500.0
        # Others need more than remaining 0W
        assert result["allocations"]["dhw_heating"] == 0.0

    def test_dhw_heating_gets_remainder_after_base(self, allocator):
        """dhw_heating gets surplus after house_base is satisfied."""
        # house_base: min=200, max=2000. With 2800W:
        # house_base gets min(2000, 2800) = 2000W; remaining = 800W
        # dhw_heating: min=800, max=2000. 800 >= 800, gets min(2000, 800) = 800W
        result = allocator.allocate(2800.0)
        assert result["allocations"]["house_base"] == 2000.0
        assert result["allocations"]["dhw_heating"] == 800.0
        assert result["allocations"]["ev_charging"] == 0.0

    def test_ev_charging_gets_surplus_after_dhw(self, allocator):
        """ev_charging (priority=3) gets power after house_base and dhw are full."""
        # house_base: max 2000W consumed
        # dhw_heating: max 2000W consumed
        # remaining = 6380W → ev_charging min=1380, gets min(11000, 6380) = 6380W
        result = allocator.allocate(10380.0)
        assert result["allocations"]["house_base"] == 2000.0
        assert result["allocations"]["dhw_heating"] == 2000.0
        assert result["allocations"]["ev_charging"] == 6380.0
        assert result["allocations"]["supplemental"] == 0.0

    def test_supplemental_gets_last_slice(self, allocator):
        """supplemental (priority=4) only gets power after all others are full."""
        # house_base 2000 + dhw 2000 + ev 11000 = 15000W then supplemental gets rest
        result = allocator.allocate(16000.0)
        assert result["allocations"]["house_base"] == 2000.0
        assert result["allocations"]["dhw_heating"] == 2000.0
        assert result["allocations"]["ev_charging"] == 11000.0
        assert result["allocations"]["supplemental"] == 1000.0


class TestMinPowerThreshold:
    def test_consumer_skipped_when_below_min_power(self, allocator):
        """Consumer is skipped if remaining power is below its min_power_w."""
        # Give exactly enough for house_base (max 2000W) but not dhw_heating (min 800W)
        result = allocator.allocate(2500.0)
        # house_base gets 2000W, 500W remains, dhw min=800 → skipped
        assert result["allocations"]["house_base"] == 2000.0
        assert result["allocations"]["dhw_heating"] == 0.0

    def test_zero_pv_allocates_nothing(self, allocator):
        """Zero available PV means nothing is allocated."""
        result = allocator.allocate(0.0)
        for name, allocated_w in result["allocations"].items():
            assert allocated_w == 0.0, f"{name} should have 0W allocated"
        assert result["grid_export_w"] == 0.0


class TestMaxPowerCap:
    def test_allocation_capped_at_max_power(self, allocator):
        """Consumer never gets more than max_power_w."""
        # Give unlimited surplus — house_base should cap at 2000W
        result = allocator.allocate(100000.0)
        assert result["allocations"]["house_base"] == 2000.0
        assert result["allocations"]["dhw_heating"] == 2000.0
        assert result["allocations"]["ev_charging"] == 11000.0
        assert result["allocations"]["supplemental"] == 3000.0

    def test_grid_export_captures_unconsumable_surplus(self, allocator):
        """Power that no consumer can absorb goes to grid_export_w."""
        # All consumers full: 2000 + 2000 + 11000 + 3000 = 18000W max
        result = allocator.allocate(20000.0)
        assert result["grid_export_w"] == pytest.approx(2000.0)


class TestDisabledConsumers:
    def test_disabled_consumer_is_skipped(self, allocator):
        """Disabled consumer receives no allocation."""
        allocator.set_consumer_enabled("ev_charging", False)
        result = allocator.allocate(15000.0)
        assert result["allocations"]["ev_charging"] == 0.0

    def test_surplus_passes_through_disabled_consumer(self, allocator):
        """Surplus not consumed by disabled consumer goes to next priority."""
        allocator.set_consumer_enabled("ev_charging", False)
        # house 2000 + dhw 2000 = 4000; ev disabled; supplemental gets remainder up to 3000
        result = allocator.allocate(8000.0)
        assert result["allocations"]["ev_charging"] == 0.0
        assert result["allocations"]["supplemental"] == 3000.0

    def test_set_consumer_enabled_unknown_raises(self, allocator):
        """set_consumer_enabled raises ValueError for unknown consumer names."""
        with pytest.raises(ValueError, match="Unknown consumer"):
            allocator.set_consumer_enabled("nonexistent_device", True)

    def test_re_enable_consumer(self, allocator):
        """Consumer can be disabled then re-enabled."""
        allocator.set_consumer_enabled("dhw_heating", False)
        allocator.set_consumer_enabled("dhw_heating", True)
        result = allocator.allocate(5000.0)
        # dhw should now be active again
        assert result["allocations"]["dhw_heating"] > 0.0


class TestTotalAndExport:
    def test_total_allocated_plus_export_equals_available(self, allocator):
        """total_allocated_w + grid_export_w == available_pv_w always."""
        for pv_w in [0.0, 500.0, 2800.0, 10000.0, 20000.0]:
            result = allocator.allocate(pv_w)
            total = result["total_allocated_w"] + result["grid_export_w"]
            assert total == pytest.approx(pv_w), f"Failed at pv_w={pv_w}"

    def test_available_pv_reflected_in_result(self, allocator):
        """available_pv_w key matches the input value."""
        result = allocator.allocate(3750.0)
        assert result["available_pv_w"] == 3750.0


class TestGetStatus:
    def test_get_status_returns_all_consumers(self, allocator):
        status = allocator.get_status()
        assert "house_base" in status
        assert "dhw_heating" in status
        assert "ev_charging" in status
        assert "supplemental" in status

    def test_get_status_reflects_enabled_state(self, allocator):
        allocator.set_consumer_enabled("ev_charging", False)
        status = allocator.get_status()
        assert status["ev_charging"]["enabled"] is False
        assert status["house_base"]["enabled"] is True

    def test_get_status_reflects_last_allocation(self, allocator):
        allocator.allocate(500.0)
        status = allocator.get_status()
        # house_base should have allocated_w > 0
        assert status["house_base"]["allocated_w"] == 500.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
