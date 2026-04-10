"""Unit tests for anti_short_cycle.py (#1042).

Tests verify:
  1. can_turn_on / can_turn_off return correct (bool, reason) tuples
  2. Minimum ON time enforced before turning off
  3. Minimum OFF time enforced before turning on again
  4. State transitions via record_on / record_off
  5. get_status() keys and types
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from anti_short_cycle import AntiShortCycleManager


@pytest.fixture
def manager():
    """Default manager: 10 min ON, 5 min OFF."""
    return AntiShortCycleManager(min_on_minutes=10, min_off_minutes=5)


class TestCanTurnOn:
    def test_can_turn_on_initially(self, manager):
        """Fresh manager should allow turning on."""
        allowed, reason = manager.can_turn_on()
        assert allowed is True
        assert reason == "ok"

    def test_cannot_turn_on_when_already_on(self, manager):
        """Cannot turn on if burner is already on."""
        manager.record_on()
        allowed, reason = manager.can_turn_on()
        assert allowed is False
        assert reason == "already_on"

    def test_cannot_turn_on_within_min_off_period(self, manager):
        """Cannot turn on if minimum OFF time has not elapsed since last off."""
        manager.record_on()
        manager.record_off()
        # Immediately try to turn back on — min_off not met
        allowed, reason = manager.can_turn_on()
        assert allowed is False
        assert reason.startswith("min_off_not_met:")

    def test_can_turn_on_after_min_off_period(self, manager):
        """Can turn on after minimum OFF time has elapsed."""
        fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        with patch("anti_short_cycle.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            manager.record_on()
            manager.record_off()

        # Advance time beyond min_off (5 min)
        after_min_off = fixed_now + timedelta(minutes=6)
        with patch("anti_short_cycle.datetime") as mock_dt:
            mock_dt.now.return_value = after_min_off
            allowed, reason = manager.can_turn_on()

        assert allowed is True
        assert reason == "ok"


class TestCanTurnOff:
    def test_cannot_turn_off_when_already_off(self, manager):
        """Cannot turn off if burner is already off."""
        allowed, reason = manager.can_turn_off()
        assert allowed is False
        assert reason == "already_off"

    def test_cannot_turn_off_within_min_on_period(self, manager):
        """Cannot turn off if minimum ON time has not elapsed since last on."""
        manager.record_on()
        # Immediately try to turn off — min_on not met
        allowed, reason = manager.can_turn_off()
        assert allowed is False
        assert reason.startswith("min_on_not_met:")

    def test_can_turn_off_after_min_on_period(self, manager):
        """Can turn off after minimum ON time has elapsed."""
        fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        with patch("anti_short_cycle.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            manager.record_on()

        # Advance time beyond min_on (10 min)
        after_min_on = fixed_now + timedelta(minutes=11)
        with patch("anti_short_cycle.datetime") as mock_dt:
            mock_dt.now.return_value = after_min_on
            allowed, reason = manager.can_turn_off()

        assert allowed is True
        assert reason == "ok"


class TestStateTransitions:
    def test_record_on_sets_burner_on(self, manager):
        manager.record_on()
        assert manager.is_on is True

    def test_record_off_sets_burner_off(self, manager):
        manager.record_on()
        manager.record_off()
        assert manager.is_on is False

    def test_initial_state_is_off(self, manager):
        assert manager.is_on is False


class TestGetStatus:
    def test_get_status_keys_present(self, manager):
        status = manager.get_status()
        assert "burner_on" in status
        assert "last_on" in status
        assert "last_off" in status
        assert "can_turn_on" in status
        assert "can_turn_off" in status

    def test_get_status_initial_state(self, manager):
        status = manager.get_status()
        assert status["burner_on"] is False
        assert status["last_on"] is None
        assert status["last_off"] is None
        assert status["can_turn_on"] is True
        assert status["can_turn_off"] is False

    def test_get_status_after_record_on(self, manager):
        manager.record_on()
        status = manager.get_status()
        assert status["burner_on"] is True
        assert status["last_on"] is not None
        assert status["can_turn_on"] is False
        # can_turn_off will be False because min_on not met yet
        assert status["can_turn_off"] is False


class TestCustomTimes:
    def test_short_times_enforced(self):
        """Custom min times (1 min ON, 1 min OFF) are respected."""
        mgr = AntiShortCycleManager(min_on_minutes=1, min_off_minutes=1)

        fixed_now = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        with patch("anti_short_cycle.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            mgr.record_on()

        # 30s later — still within 1 min ON
        with patch("anti_short_cycle.datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now + timedelta(seconds=30)
            allowed, reason = mgr.can_turn_off()

        assert allowed is False
        assert "min_on_not_met" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
