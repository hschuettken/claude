"""Simplified unit tests for supplemental_heat.py - avoids numpy/influxdb issues.

Tests cover core state machine logic without requiring influxdb imports.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# Direct import of classes without triggering influxdb
import sys
from pathlib import Path

# Mock out influxdb before importing supplemental_heat
sys.modules['influxdb_client'] = MagicMock()
sys.modules['influxdb_client.client'] = MagicMock()
sys.modules['influxdb_client.client.write_api'] = MagicMock()

from supplemental_heat import (
    SupplementalHeatController,
    SupplementalHeatConfig,
    HeaterState,
)


def test_default_config():
    """Test default configuration values."""
    config = SupplementalHeatConfig()
    assert config.min_surplus_kw == 3.0
    assert config.off_threshold_kw == 1.5
    assert config.min_duration_min == 15.0
    assert config.max_daily_hours == 4.0
    assert config.entity_names == ["switch.ir_heater_1", "switch.ir_heater_2"]
    assert config.use_orchestrator is True
    print("✓ test_default_config passed")


def test_custom_config():
    """Test custom configuration."""
    config = SupplementalHeatConfig(
        min_surplus_kw=2.5,
        off_threshold_kw=1.0,
        min_duration_min=10.0,
        max_daily_hours=6.0,
        entity_names=["switch.heater_main"],
    )
    assert config.min_surplus_kw == 2.5
    assert config.off_threshold_kw == 1.0
    assert config.min_duration_min == 10.0
    assert config.max_daily_hours == 6.0
    assert config.entity_names == ["switch.heater_main"]
    print("✓ test_custom_config passed")


def test_initialization():
    """Test controller initializes correctly."""
    config = SupplementalHeatConfig()
    controller = SupplementalHeatController(config=config)
    assert controller.config == config
    assert controller.state == HeaterState.OFF
    assert controller.is_on is False
    assert controller.stats.runtime_s == 0.0
    assert controller.stats.daily_runtime_s == 0.0
    print("✓ test_initialization passed")


async def test_off_state_no_surplus():
    """Test OFF state with no surplus stays OFF."""
    config = SupplementalHeatConfig()
    controller = SupplementalHeatController(config=config)
    result = await controller.tick(solar_power_w=1000, household_load_w=2000, dt_s=10)
    assert result["state"] == "off"
    assert result["is_on"] is False
    assert result["surplus_kw"] == -1.0
    assert controller.state == HeaterState.OFF
    print("✓ test_off_state_no_surplus passed")


async def test_off_to_charging_transition():
    """Test OFF → CHARGING when surplus > min_surplus_kw."""
    config = SupplementalHeatConfig(min_duration_min=1.0)
    controller = SupplementalHeatController(config=config)
    # Surplus = 4 kW (above 3 kW threshold)
    result = await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert result["state"] == "charging"
    assert controller.state == HeaterState.CHARGING
    assert result["is_on"] is False  # Not yet ON, just charging
    print("✓ test_off_to_charging_transition passed")


async def test_charging_to_off_transition():
    """Test CHARGING → OFF when surplus drops during charging."""
    config = SupplementalHeatConfig(min_duration_min=1.0)
    controller = SupplementalHeatController(config=config)
    # Enter CHARGING
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert controller.state == HeaterState.CHARGING

    # Surplus drops
    result = await controller.tick(solar_power_w=2000, household_load_w=1000, dt_s=10)
    assert result["state"] == "off"
    assert controller.state == HeaterState.OFF
    print("✓ test_charging_to_off_transition passed")


async def test_charging_to_on_transition():
    """Test CHARGING → ON when min_duration reached with sufficient surplus."""
    config = SupplementalHeatConfig(min_duration_min=1.0)  # 60 seconds
    controller = SupplementalHeatController(config=config)
    
    # Mock HA calls to avoid connection errors
    controller._turn_on_via_orchestrator = AsyncMock()
    controller._turn_off_via_orchestrator = AsyncMock()
    
    # Enter CHARGING
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert controller.state == HeaterState.CHARGING

    # Simulate 61 seconds of surplus (min_duration is 60s)
    for _ in range(6):
        await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)

    # Should be ON now
    result = await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert result["state"] == "on"
    assert controller.state == HeaterState.ON
    assert result["is_on"] is True
    print("✓ test_charging_to_on_transition passed")


async def test_on_to_off_below_threshold():
    """Test ON → OFF when surplus drops below off_threshold."""
    config = SupplementalHeatConfig(min_duration_min=1.0)
    controller = SupplementalHeatController(config=config)
    
    # Mock HA calls
    controller._turn_on_via_orchestrator = AsyncMock()
    controller._turn_off_via_orchestrator = AsyncMock()
    
    # Get to ON state
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    for _ in range(6):
        await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert controller.state == HeaterState.ON

    # Drop surplus below off_threshold (1.5 kW)
    result = await controller.tick(solar_power_w=2300, household_load_w=1000, dt_s=10)
    assert result["state"] == "off"
    assert controller.state == HeaterState.OFF
    assert result["is_on"] is False
    print("✓ test_on_to_off_below_threshold passed")


async def test_daily_runtime_accumulation():
    """Test daily runtime accumulates while ON."""
    config = SupplementalHeatConfig(min_duration_min=1.0)
    controller = SupplementalHeatController(config=config)
    
    # Mock HA calls
    controller._turn_on_via_orchestrator = AsyncMock()
    controller._turn_off_via_orchestrator = AsyncMock()
    
    # Get to ON state
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    for _ in range(6):
        await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert controller.state == HeaterState.ON
    initial_daily = controller.stats.daily_runtime_s

    # Tick 100 more times with 10s intervals (1000s total)
    for _ in range(100):
        await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)

    # Daily runtime should have increased
    assert controller.stats.daily_runtime_s > initial_daily
    assert controller.stats.daily_runtime_s > 1000
    print("✓ test_daily_runtime_accumulation passed")


async def test_daily_limit_enforcement():
    """Test ON → COOLDOWN when daily max hours exceeded."""
    config = SupplementalHeatConfig(min_duration_min=1.0, max_daily_hours=1.0)
    controller = SupplementalHeatController(config=config)
    
    # Mock HA calls
    controller._turn_on_via_orchestrator = AsyncMock()
    controller._turn_off_via_orchestrator = AsyncMock()
    
    # Get to ON state
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    for _ in range(6):
        await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert controller.state == HeaterState.ON

    # Simulate 3600+ seconds (1+ hour) of runtime
    # Daily limit is 1 hour (3600s)
    for _ in range(362):  # 362 × 10s = 3620s > 3600s limit
        await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)

    # Should now be in COOLDOWN
    result = await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert result["state"] == "cooldown"
    assert controller.state == HeaterState.COOLDOWN
    assert result["daily_limit_exceeded"] is True
    print("✓ test_daily_limit_enforcement passed")


async def test_surplus_calculation():
    """Test PV surplus calculation."""
    config = SupplementalHeatConfig()
    controller = SupplementalHeatController(config=config)
    result = await controller.tick(solar_power_w=5000, household_load_w=1500, dt_s=10)
    expected_surplus = (5000 - 1500) / 1000
    assert result["surplus_kw"] == expected_surplus
    assert result["surplus_kw"] == 3.5
    print("✓ test_surplus_calculation passed")


async def test_negative_surplus():
    """Test negative surplus (consumption > generation)."""
    config = SupplementalHeatConfig()
    controller = SupplementalHeatController(config=config)
    result = await controller.tick(solar_power_w=1000, household_load_w=5000, dt_s=10)
    expected_surplus = (1000 - 5000) / 1000
    assert result["surplus_kw"] == expected_surplus
    assert result["surplus_kw"] == -4.0
    assert result["state"] == "off"
    print("✓ test_negative_surplus passed")


def test_get_status():
    """Test status reporting."""
    config = SupplementalHeatConfig()
    controller = SupplementalHeatController(config=config)
    status = controller.get_status()
    assert status["state"] == "off"
    assert status["is_on"] is False
    assert status["daily_runtime_h"] == 0.0
    assert status["config"]["min_surplus_kw"] == 3.0
    print("✓ test_get_status passed")


async def test_result_keys():
    """Test tick result contains all expected keys."""
    config = SupplementalHeatConfig()
    controller = SupplementalHeatController(config=config)
    result = await controller.tick(solar_power_w=5000, household_load_w=1000, dt_s=10)
    assert "state" in result
    assert "is_on" in result
    assert "surplus_kw" in result
    assert "runtime_s" in result
    assert "daily_runtime_s" in result
    assert "daily_runtime_h" in result
    assert "daily_remaining_h" in result
    assert "surplus_on_time_min" in result
    assert "daily_limit_exceeded" in result
    assert "log_message" in result
    print("✓ test_result_keys passed")


async def run_async_tests():
    """Run all async tests."""
    await test_off_state_no_surplus()
    await test_off_to_charging_transition()
    await test_charging_to_off_transition()
    await test_charging_to_on_transition()
    await test_on_to_off_below_threshold()
    await test_daily_runtime_accumulation()
    await test_daily_limit_enforcement()
    await test_surplus_calculation()
    await test_negative_surplus()
    await test_result_keys()


def main():
    """Run all tests."""
    print("Running supplemental_heat tests...\n")
    
    # Sync tests
    test_default_config()
    test_custom_config()
    test_initialization()
    test_get_status()
    
    # Async tests
    asyncio.run(run_async_tests())
    
    print("\n✅ All tests passed!")


if __name__ == "__main__":
    main()
