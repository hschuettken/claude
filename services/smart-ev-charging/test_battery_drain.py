"""Tier-based battery-drain gate tests (S3a, FR #3061).

Covers ``ChargingStrategy._battery_assist_decision`` directly so we can
unit-test each tier (PV harvest / battery full / deadline imminent /
opportunistic) plus the gate set (drain disabled, EV not plugged, SoC
floor) without simulating the whole charging context.
"""

from __future__ import annotations

import pytest

from strategy import ChargingStrategy


def make_strategy() -> ChargingStrategy:
    return ChargingStrategy(
        max_power_w=11000,
        min_power_w=4200,
    )


def _decide(strategy: ChargingStrategy, **kwargs):
    base = dict(
        home_battery_soc_pct=85,
        pv_producing_w=2000,
        ev_plugged=True,
        ev_deadline_hours=8.0,
        user_drain_disabled=False,
        wallbox_max_w=11000,
    )
    base.update(kwargs)
    return strategy._battery_assist_decision(**base)


# ── Gates ─────────────────────────────────────────────────────────────


def test_no_drain_when_user_disabled():
    s = make_strategy()
    cap, reason, tier = _decide(s, user_drain_disabled=True)
    assert cap == 0
    assert tier == "disabled"
    assert "user disabled" in reason.lower()


def test_no_drain_when_ev_not_plugged():
    s = make_strategy()
    cap, reason, tier = _decide(s, ev_plugged=False)
    assert cap == 0
    assert tier == "no_ev"
    assert "not plugged" in reason.lower()


def test_no_drain_when_battery_below_50():
    s = make_strategy()
    cap, reason, tier = _decide(s, home_battery_soc_pct=45)
    assert cap == 0
    assert tier == "soc_floor"
    assert "below 50%" in reason


# ── Tier 1: battery full + PV producing ──────────────────────────────


def test_full_drain_when_battery_high_and_pv_producing():
    s = make_strategy()
    cap, reason, tier = _decide(s)
    assert cap == 11000
    assert tier == "battery_full"
    assert "full drain" in reason


def test_full_drain_at_pv_min_wallbox_threshold():
    s = make_strategy()
    # Boundary: PV exactly at min wallbox threshold (1500 W) still triggers Tier 1
    cap, _, tier = _decide(s, pv_producing_w=1500)
    assert tier == "battery_full"
    assert cap == 11000


def test_no_full_drain_when_pv_below_min_wallbox():
    s = make_strategy()
    cap, _, tier = _decide(s, pv_producing_w=800)
    # Falls through to opportunistic (Tier 3) since SoC>50% and PV>0 but small
    assert tier == "opportunistic"
    assert cap == 2000


# ── Tier 2: deadline imminent ─────────────────────────────────────────


def test_partial_drain_on_deadline_imminent():
    s = make_strategy()
    # SoC moderate (60%, below Tier 1 threshold of 80), deadline 1.5h
    cap, reason, tier = _decide(
        s,
        home_battery_soc_pct=60,
        pv_producing_w=500,  # below min wallbox so Tier 1 + 3 don't trigger first
        ev_deadline_hours=1.5,
    )
    # Tier 3 (opportunistic) actually wins because battery>50, pv>0 and pv<1500
    # — so route through SoC=60 + deadline=1.5h with no PV
    cap, reason, tier = _decide(
        s,
        home_battery_soc_pct=60,
        pv_producing_w=0,
        ev_deadline_hours=1.5,
    )
    assert cap == 5000
    assert tier == "deadline_imminent"
    assert "imminent" in reason


# ── Tier 3: opportunistic ─────────────────────────────────────────────


def test_opportunistic_drain_when_battery_above_50_pv_low():
    s = make_strategy()
    cap, reason, tier = _decide(
        s,
        home_battery_soc_pct=60,
        pv_producing_w=800,  # below 1500 min, but >0
        ev_deadline_hours=8.0,
    )
    assert cap == 2000
    assert tier == "opportunistic"
    assert "opportunistic" in reason


def test_no_drain_when_no_conditions_met():
    s = make_strategy()
    # Battery 70 (no Tier 1), PV 0 (no Tier 3), no imminent deadline
    cap, reason, tier = _decide(
        s,
        home_battery_soc_pct=70,
        pv_producing_w=0,
        ev_deadline_hours=12.0,
    )
    assert cap == 0
    assert tier == "none"
    assert "no drain conditions" in reason


# ── Tier 0: PV harvest ────────────────────────────────────────────────


def test_pv_harvest_when_post_deadline_pv_covers_battery_refill():
    s = make_strategy()
    # Battery at 60% (below Tier 1 threshold), deadline at 8h (e.g. 2pm),
    # post-deadline PV (10 kWh) covers battery refill (3 kWh) + buffer.
    cap, reason, tier = _decide(
        s,
        home_battery_soc_pct=60,
        pv_producing_w=3000,
        ev_deadline_hours=8.0,
        pv_post_deadline_kwh=10.0,
        home_battery_refill_kwh=3.0,
    )
    assert cap == 11000
    assert tier == "pv_harvest"
    assert "PV-harvest" in reason


def test_pv_harvest_skipped_when_post_deadline_pv_too_low():
    s = make_strategy()
    # Post-deadline PV (1 kWh) does NOT cover refill (5 kWh) + buffer (1.5)
    cap, reason, tier = _decide(
        s,
        home_battery_soc_pct=85,
        pv_producing_w=2000,  # Tier 1 should still kick in
        ev_deadline_hours=8.0,
        pv_post_deadline_kwh=1.0,
        home_battery_refill_kwh=5.0,
    )
    # Tier 1 still wins because battery>80 and pv>1500
    assert tier == "battery_full"
    assert cap == 11000


def test_pv_harvest_skipped_when_no_hourly_forecast():
    s = make_strategy()
    cap, reason, tier = _decide(
        s,
        home_battery_soc_pct=60,
        pv_producing_w=800,
        ev_deadline_hours=8.0,
        pv_post_deadline_kwh=None,  # no hourly forecast available
        home_battery_refill_kwh=3.0,
    )
    # Falls through to Tier 3 (opportunistic, PV<1500)
    assert tier == "opportunistic"
    assert cap == 2000


def test_pv_harvest_skipped_when_deadline_at_night():
    s = make_strategy()
    # Deadline 14h away → outside the 0-10h "daytime" window
    cap, _, tier = _decide(
        s,
        home_battery_soc_pct=60,
        pv_producing_w=800,
        ev_deadline_hours=14.0,
        pv_post_deadline_kwh=10.0,
        home_battery_refill_kwh=3.0,
    )
    # Falls through to Tier 3
    assert tier == "opportunistic"


# ── Helper coverage ───────────────────────────────────────────────────


def test_pv_kwh_after_hour_sums_correctly():
    s = make_strategy()

    class _Ctx:
        pv_hourly_forecast = [
            {"hour": 10, "kwh": 1.5},
            {"hour": 11, "kwh": 2.0},
            {"hour": 14, "kwh": 3.0},
            {"hour": 15, "kwh": 2.5},
        ]

    total = s._pv_kwh_after_hour(_Ctx(), 14)
    assert total == pytest.approx(5.5)


def test_pv_kwh_after_hour_returns_none_when_no_forecast():
    s = make_strategy()

    class _Ctx:
        pv_hourly_forecast = None

    assert s._pv_kwh_after_hour(_Ctx(), 14) is None
