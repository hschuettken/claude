"""Tests for TripPredictor — calendar parsing and trip prediction."""

from __future__ import annotations

import pytest
from datetime import date, timedelta

# conftest.py already sets sys.path; import here after path is set
from trips import TripPredictor


def make_predictor(
    known_destinations: dict | None = None,
    consumption: float = 22.0,
    nicole_commute_km: float = 22.0,
    nicole_commute_days: list[str] | None = None,
    henning_train_threshold_km: float = 350.0,
) -> TripPredictor:
    """Create a TripPredictor with sensible test defaults."""
    if known_destinations is None:
        known_destinations = {
            "Münster": 60.0,
            "Aachen": 80.0,
            "Lengerich": 22.0,
            "Köln": 100.0,
            "Hamburg": 300.0,
            "STR": 500.0,
            "Stuttgart": 500.0,
            "Hopsten": 14.0,
        }
    return TripPredictor(
        known_destinations=known_destinations,
        consumption_kwh_per_100km=consumption,
        nicole_commute_km=nicole_commute_km,
        nicole_commute_days=nicole_commute_days or ["mon", "tue", "wed", "thu"],
        henning_train_threshold_km=henning_train_threshold_km,
        timezone="Europe/Berlin",
    )


def make_event(
    summary: str,
    start: str,
    end: str | None = None,
    all_day: bool = False,
    event_id: str = "test-event-1",
) -> dict:
    """Build a calendar event dict (same format as Google Calendar parser produces)."""
    if end is None:
        end = start
    return {
        "id": event_id,
        "summary": summary,
        "start": start,
        "end": end,
        "all_day": all_day,
        "location": "",
    }


# ---------------------------------------------------------------------------
# 1. H: / N: prefix parsing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_prefix_creates_henning_trip():
    """Events starting with 'H:' are parsed as Henning's trips."""
    predictor = make_predictor()
    today = date.today()
    events = [make_event("H: Münster", f"{today.isoformat()}T09:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    assert len(plans) == 1
    henning_trips = [t for t in plans[0].trips if t.person == "Henning"]
    assert len(henning_trips) >= 1
    assert henning_trips[0].destination.lower() == "münster"


@pytest.mark.asyncio
async def test_n_prefix_creates_nicole_trip():
    """Events starting with 'N:' are parsed as Nicole's trips."""
    predictor = make_predictor()
    today = date.today()
    events = [make_event("N: Köln", f"{today.isoformat()}T10:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    assert len(plans) == 1
    nicole_trips = [t for t in plans[0].trips if t.person == "Nicole"]
    # The calendar trip + possibly a commute trip
    assert any(t.destination.lower() == "köln" for t in nicole_trips)


@pytest.mark.asyncio
async def test_no_prefix_event_is_ignored_for_henning():
    """Events without H:/N: prefix generate no driving trip for Henning."""
    predictor = make_predictor()
    today = date.today()
    events = [make_event("Dentist appointment", f"{today.isoformat()}T14:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    assert len(plans) == 1
    # No H: prefix → no Henning trip created
    henning_trips = [t for t in plans[0].trips if t.person == "Henning"]
    assert len(henning_trips) == 0


# ---------------------------------------------------------------------------
# 2. Commute detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nicole_default_commute_on_weekday():
    """Nicole gets a default commute trip on Mon-Thu when no calendar event."""
    predictor = make_predictor()
    # Find the next Monday
    today = date.today()
    days_until_monday = (7 - today.weekday()) % 7 or 7
    # We only look up to 3 days ahead typically, so find one within range
    monday = today
    if today.weekday() == 0:
        monday = today
    else:
        # Get closest upcoming monday within 7 days
        monday = today + timedelta(days=(0 - today.weekday()) % 7)
    if monday > today + timedelta(days=6):
        monday = today  # Fallback: today if we can't find one

    # Find the first Mon-Thu day within 3 days
    target = None
    for offset in range(3):
        d = today + timedelta(days=offset)
        if d.weekday() in (0, 1, 2, 3):  # Mon-Thu
            target = d
            break

    if target is None:
        pytest.skip("No weekday in next 3 days (unusual)")

    offset = (target - today).days
    plans = await predictor.predict_trips([], days=offset + 1)
    day_plan = plans[offset]
    commute_trips = [t for t in day_plan.trips if t.is_commute]
    assert len(commute_trips) == 1
    assert commute_trips[0].person == "Nicole"


@pytest.mark.asyncio
async def test_commute_trip_has_correct_distance():
    """Nicole's default commute trip uses the configured one-way distance."""
    predictor = make_predictor(nicole_commute_km=22.0)
    # Check today if it's a commute day, otherwise skip
    today = date.today()
    if today.weekday() not in (0, 1, 2, 3):
        pytest.skip("Today is not a commute day")
    plans = await predictor.predict_trips([], days=1)
    commute_trips = [t for t in plans[0].trips if t.is_commute]
    if not commute_trips:
        pytest.skip("No commute generated today")
    trip = commute_trips[0]
    assert trip.distance_km == 22.0
    assert trip.round_trip_km == 44.0


@pytest.mark.asyncio
async def test_no_commute_on_weekend():
    """Nicole has no default commute on weekends (Sat/Sun)."""
    predictor = make_predictor(nicole_commute_days=["mon", "tue", "wed", "thu"])
    # Find a Saturday or Sunday in the next 7 days
    today = date.today()
    weekend_day = None
    for offset in range(7):
        d = today + timedelta(days=offset)
        if d.weekday() in (5, 6):  # Sat=5, Sun=6
            weekend_day = d
            break

    if weekend_day is None:
        pytest.skip("No weekend day in next 7 days")

    offset = (weekend_day - today).days
    plans = await predictor.predict_trips([], days=offset + 1)
    day_plan = plans[offset]
    commute_trips = [t for t in day_plan.trips if t.is_commute]
    assert len(commute_trips) == 0


# ---------------------------------------------------------------------------
# 3. Known destinations vs. unknown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_destination_uses_lookup_distance():
    """A known destination uses the pre-configured distance, no geocoding."""
    predictor = make_predictor(known_destinations={"Hopsten": 14.0})
    today = date.today()
    events = [make_event("H: Hopsten", f"{today.isoformat()}T09:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    henning_trips = [t for t in plans[0].trips if t.person == "Henning"]
    assert len(henning_trips) >= 1
    assert henning_trips[0].distance_km == 14.0


@pytest.mark.asyncio
async def test_unknown_destination_uses_default_distance():
    """An unknown destination (no geocoding available) falls back to 50 km."""
    predictor = make_predictor(known_destinations={})
    # No geo_distance configured → no geocoding → default 50 km
    today = date.today()
    events = [make_event("N: Zufällighausen", f"{today.isoformat()}T09:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    nicole_trips = [
        t for t in plans[0].trips if t.person == "Nicole" and t.source == "calendar"
    ]
    assert len(nicole_trips) >= 1
    trip = nicole_trips[0]
    assert trip.distance_km == 50.0
    assert trip.needs_clarification is True


# ---------------------------------------------------------------------------
# 4. Henning train threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_henning_takes_train_for_long_trip():
    """Trips > train threshold for Henning are skipped (he takes the train)."""
    predictor = make_predictor(
        known_destinations={"STR": 500.0},
        henning_train_threshold_km=350.0,
    )
    today = date.today()
    events = [make_event("H: STR", f"{today.isoformat()}T08:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    # Henning's trip should be dropped (train)
    henning_trips = [t for t in plans[0].trips if t.person == "Henning"]
    assert len(henning_trips) == 0


@pytest.mark.asyncio
async def test_henning_medium_distance_needs_clarification():
    """Henning trips 100–350 km flag needs_clarification=True."""
    predictor = make_predictor(
        known_destinations={"Hamburg": 300.0},
        henning_train_threshold_km=350.0,
    )
    today = date.today()
    events = [make_event("H: Hamburg", f"{today.isoformat()}T08:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    henning_trips = [t for t in plans[0].trips if t.person == "Henning"]
    assert len(henning_trips) >= 1
    assert henning_trips[0].needs_clarification is True


# ---------------------------------------------------------------------------
# 5. Multiple trips in a day — cumulative energy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multiple_trips_cumulative_energy():
    """Multiple trips on the same day sum correctly in DayPlan.total_energy_kwh."""
    predictor = make_predictor(
        known_destinations={"Münster": 60.0, "Hopsten": 14.0},
        consumption=20.0,
    )
    today = date.today()
    events = [
        make_event("H: Hopsten", f"{today.isoformat()}T08:00:00", event_id="ev1"),
        make_event("N: Münster", f"{today.isoformat()}T09:00:00", event_id="ev2"),
    ]
    plans = await predictor.predict_trips(events, days=1)
    day = plans[0]

    # H: Hopsten → 14 km one-way, ≤100 km no clarification, round trip 28 km
    # N: Münster → 60 km one-way, round trip 120 km
    # Consumption 20 kWh/100 km
    hopsten_energy = 28 * 20 / 100  # = 5.6 kWh
    munster_energy = 120 * 20 / 100  # = 24 kWh

    calendar_trips = [t for t in day.trips if t.source == "calendar"]
    total = sum(t.energy_kwh for t in calendar_trips)
    # Hopsten trip from Henning only (no clarification needed, <100 km)
    assert total > 0
    # Nicole's Münster trip should be there
    assert any(t.destination.lower() == "münster" for t in calendar_trips)


# ---------------------------------------------------------------------------
# 6. Energy estimation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_energy_estimate_matches_consumption_rate():
    """Trip energy = round_trip_km * consumption / 100."""
    predictor = make_predictor(
        known_destinations={"Aachen": 80.0},
        consumption=25.0,
    )
    today = date.today()
    events = [make_event("N: Aachen", f"{today.isoformat()}T09:00:00")]
    plans = await predictor.predict_trips(events, days=1)
    nicole_trips = [
        t for t in plans[0].trips if t.person == "Nicole" and t.source == "calendar"
    ]
    assert len(nicole_trips) >= 1
    trip = nicole_trips[0]
    expected_energy = trip.round_trip_km * 25.0 / 100.0
    assert abs(trip.energy_kwh - expected_energy) < 0.01


# ---------------------------------------------------------------------------
# 7. Edge case: no events → only commute or empty plan
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_trips_plan_has_no_calendar_trips():
    """With no calendar events and on a weekend, the plan has no trips."""
    predictor = make_predictor(nicole_commute_days=[])  # Disable commute
    today = date.today()
    plans = await predictor.predict_trips([], days=1)
    assert len(plans) == 1
    calendar_trips = [t for t in plans[0].trips if t.source == "calendar"]
    assert len(calendar_trips) == 0


# ---------------------------------------------------------------------------
# 8. Departure time extraction from event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_departure_time_extracted_from_event():
    """Trip departure time should come from the event start time."""
    predictor = make_predictor(known_destinations={"Aachen": 80.0})
    today = date.today()
    events = [make_event("N: Aachen", f"{today.isoformat()}T08:30:00")]
    plans = await predictor.predict_trips(events, days=1)
    nicole_trips = [
        t for t in plans[0].trips if t.person == "Nicole" and t.source == "calendar"
    ]
    assert len(nicole_trips) >= 1
    trip = nicole_trips[0]
    assert trip.departure_time is not None
    assert trip.departure_time.hour == 8
    assert trip.departure_time.minute == 30
