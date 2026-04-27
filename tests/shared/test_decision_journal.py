"""Tests for shared.decision_journal."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared.decision_journal import DecisionJournal


@pytest.fixture
def mock_influx():
    return MagicMock()


@pytest.fixture
def mock_nats():
    n = MagicMock()
    n.connected = True
    n.publish = AsyncMock()
    return n


async def test_write_happy_path(mock_influx, mock_nats):
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    await j.write(
        decision_kind="plan_generated",
        outcome="Charge 5.2 kWh from PV",
        reason="commute",
        current_soc_pct=42.0,
        energy_needed_kwh=5.2,
    )
    mock_influx.write_point.assert_called_once()
    _, kwargs = mock_influx.write_point.call_args
    assert kwargs["measurement"] == "ev_decisions"
    assert kwargs["bucket"] == "analytics"
    assert kwargs["tags"]["decision_kind"] == "plan_generated"
    assert kwargs["tags"]["service"] == "ev-forecast"
    assert kwargs["tags"]["vehicle"] == "audi_a6_etron"
    assert kwargs["fields"]["outcome"] == "Charge 5.2 kWh from PV"
    assert kwargs["fields"]["reason"] == "commute"
    assert kwargs["fields"]["current_soc_pct"] == 42.0
    assert kwargs["fields"]["energy_needed_kwh"] == 5.2
    assert "trace_id" in kwargs["fields"]
    mock_nats.publish.assert_awaited_once()
    subj, payload = mock_nats.publish.await_args.args
    assert subj == "energy.ev.decision.plan"
    assert payload["decision_kind"] == "plan_generated"
    assert payload["service"] == "ev-forecast"


async def test_invalid_kind_silently_skips(mock_influx, mock_nats):
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    await j.write(decision_kind="garbage", outcome="x", reason="y")
    mock_influx.write_point.assert_not_called()
    mock_nats.publish.assert_not_called()


async def test_invalid_outcome_class_silently_skips(mock_influx, mock_nats):
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    await j.write(
        decision_kind="plan_generated",
        outcome="x",
        reason="y",
        outcome_class="bogus",
    )
    mock_influx.write_point.assert_not_called()
    mock_nats.publish.assert_not_called()


async def test_influx_failure_does_not_raise(mock_influx, mock_nats):
    mock_influx.write_point.side_effect = RuntimeError("influx down")
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    # Must not raise even when Influx is broken.
    await j.write(decision_kind="plan_generated", outcome="x", reason="y")
    # NATS still attempted
    mock_nats.publish.assert_awaited_once()


async def test_nats_failure_does_not_raise(mock_influx, mock_nats):
    mock_nats.publish.side_effect = RuntimeError("nats hiccup")
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    # Must not raise when NATS is broken either.
    await j.write(decision_kind="plan_generated", outcome="x", reason="y")
    mock_influx.write_point.assert_called_once()


async def test_skips_nats_when_not_connected(mock_influx, mock_nats):
    mock_nats.connected = False
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    await j.write(decision_kind="plan_generated", outcome="x", reason="y")
    mock_influx.write_point.assert_called_once()
    mock_nats.publish.assert_not_called()


async def test_control_decision_uses_control_subject(mock_influx, mock_nats):
    j = DecisionJournal(mock_influx, mock_nats, service="smart-ev-charging")
    await j.write(
        decision_kind="target_power_set",
        outcome="5.2 kW",
        reason="x",
    )
    subj = mock_nats.publish.await_args.args[0]
    assert subj == "energy.ev.decision.control"


async def test_battery_drain_decision_uses_control_subject(mock_influx, mock_nats):
    j = DecisionJournal(mock_influx, mock_nats, service="smart-ev-charging")
    await j.write(
        decision_kind="battery_drain_decided",
        outcome="drain at 5kW",
        reason="excess pv",
        outcome_class="drain_battery",
    )
    subj = mock_nats.publish.await_args.args[0]
    assert subj == "energy.ev.decision.control"


async def test_inputs_and_alternatives_serialized_as_json(mock_influx, mock_nats):
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    await j.write(
        decision_kind="plan_generated",
        outcome="x",
        reason="y",
        inputs={"trips": [{"person": "nicole", "km": 60}]},
        alternatives=[{"mode": "Eco", "would_cost_eur": 1.20}],
    )
    _, kwargs = mock_influx.write_point.call_args
    fields = kwargs["fields"]
    assert isinstance(fields["inputs_json"], str)
    assert "nicole" in fields["inputs_json"]
    assert isinstance(fields["alternatives_json"], str)
    assert "Eco" in fields["alternatives_json"]


async def test_explicit_trace_id_propagates(mock_influx, mock_nats):
    j = DecisionJournal(mock_influx, mock_nats, service="ev-forecast")
    await j.write(
        decision_kind="plan_generated",
        outcome="x",
        reason="y",
        trace_id="abc123def",
    )
    _, kwargs = mock_influx.write_point.call_args
    assert kwargs["fields"]["trace_id"] == "abc123def"


async def test_works_without_nats(mock_influx):
    j = DecisionJournal(mock_influx, nats=None, service="ev-forecast")
    # Must not raise even with no NATS publisher passed in.
    await j.write(decision_kind="plan_generated", outcome="x", reason="y")
    mock_influx.write_point.assert_called_once()


def test_new_trace_id_returns_short_hex():
    tid = DecisionJournal.new_trace_id()
    assert isinstance(tid, str)
    assert len(tid) == 12
    int(tid, 16)  # must be valid hex
