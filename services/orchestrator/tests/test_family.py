"""Tests for Family OS API endpoints (FR #4 / item #41).

Covers:
- GET /api/v1/family          -- full dashboard (mocked HA/calendar/orbit)
- GET /api/v1/family/nicole   -- simplified Nicole view
- GET /api/v1/family/votes    -- vote listing
- POST /api/v1/family/votes   -- cast vote + alignment score

All external dependencies (HA, Google Calendar, Orbit, cook planner) are mocked.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import api.family as family_module


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def isolated_votes(tmp_path):
    """Redirect vote storage to a temp file for each test."""
    votes_file = str(tmp_path / "family_votes.json")
    with patch.object(family_module, "VOTES_PATH", votes_file):
        yield votes_file


@pytest.fixture()
def app_client():
    """Build a TestClient with the family router and mocked dependencies."""
    _app = FastAPI()
    _app.include_router(family_module.router)

    mock_ha = AsyncMock()
    mock_ha.get_state = AsyncMock(
        return_value={"state": "2500", "attributes": {}}
    )
    mock_gcal = MagicMock()
    mock_gcal.available = True
    mock_gcal.get_events = AsyncMock(
        return_value=[{"summary": "Arzttermin", "start": "2026-04-30"}]
    )
    mock_orbit = AsyncMock()
    mock_orbit.orbit_list_lists = AsyncMock(
        return_value={
            "lists": [
                {"id": "list-001", "title": "Einkauf"},
                {"id": "list-002", "title": "Projects"},
            ]
        }
    )
    mock_orbit.orbit_get_list = AsyncMock(
        return_value={
            "id": "list-001",
            "title": "Einkauf",
            "items": [
                {"id": "i1", "content": "Milch", "checked": False},
                {"id": "i2", "content": "Brot", "checked": False},
                {"id": "i3", "content": "Butter", "checked": True},
            ],
        }
    )

    mock_settings = MagicMock()
    mock_settings.timezone = "Europe/Berlin"
    mock_settings.house_power_entity = "sensor.shelly3em_main_channel_total_power"
    mock_settings.google_calendar_family_id = "cal-family-id"

    family_module.configure(
        ha=mock_ha,
        gcal=mock_gcal,
        orbit_tools=mock_orbit,
        energy_tools=None,
        settings=mock_settings,
    )

    with TestClient(_app) as client:
        yield client


# ---------------------------------------------------------------------------
# Tests — alignment score
# ---------------------------------------------------------------------------


def test_calc_alignment_equal_votes():
    score = family_module.calc_alignment(
        {"Henning": {"vote": 8}, "Nicole": {"vote": 8}}
    )
    assert score == 1.0


def test_calc_alignment_max_diff():
    score = family_module.calc_alignment(
        {"Henning": {"vote": 1}, "Nicole": {"vote": 10}}
    )
    assert score == pytest.approx(0.1)


def test_calc_alignment_partial_diff():
    # |8 - 6| / 10 = 0.2  → 1 - 0.2 = 0.8
    score = family_module.calc_alignment(
        {"Henning": {"vote": 8}, "Nicole": {"vote": 6}}
    )
    assert score == pytest.approx(0.8)


def test_calc_alignment_single_user():
    score = family_module.calc_alignment({"Henning": {"vote": 7}})
    assert score is None


def test_alignment_label_strong():
    label = family_module.alignment_label(0.95)
    assert "strongly agree" in label
    assert "95%" in label


def test_alignment_label_none():
    label = family_module.alignment_label(None)
    assert label == "needs votes"


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/family
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_family_dashboard_returns_all_sections(app_client):
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={"meals": []})):
        resp = app_client.get("/api/v1/family")
    assert resp.status_code == 200
    data = resp.json()
    assert "timestamp" in data
    assert "meals_today" in data
    assert "calendar_events" in data
    assert "grocery_list" in data
    assert "energy_status" in data
    assert "shared_items" in data
    assert "context_signals" in data


@pytest.mark.asyncio
async def test_family_energy_status_all_good(app_client):
    # HA returns 2500 W → all_good
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family")
    assert resp.status_code == 200
    energy = resp.json()["energy_status"]
    assert energy["status"] == "all_good"


@pytest.mark.asyncio
async def test_family_energy_status_high_usage(app_client, isolated_votes):
    family_module._ha.get_state = AsyncMock(
        return_value={"state": "7500", "attributes": {}}
    )
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family")
    assert resp.json()["energy_status"]["status"] == "high_usage"


@pytest.mark.asyncio
async def test_family_grocery_list_unchecked_only(app_client):
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family")
    grocery = resp.json()["grocery_list"]
    assert grocery["total"] == 2  # Milch + Brot (Butter is checked)
    contents = [i["content"] for i in grocery["items"]]
    assert "Milch" in contents
    assert "Butter" not in contents


@pytest.mark.asyncio
async def test_family_calendar_events_included(app_client):
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family")
    events = resp.json()["calendar_events"]
    assert len(events) == 1
    assert events[0]["summary"] == "Arzttermin"


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/family/nicole
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nicole_view_has_greeting(app_client):
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family/nicole")
    assert resp.status_code == 200
    data = resp.json()
    assert data["view"] == "nicole"
    assert "Nicole" in data["greeting"]


@pytest.mark.asyncio
async def test_nicole_view_has_date(app_client):
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family/nicole")
    data = resp.json()
    assert data["date"] == "2026-04-28"  # current test date


@pytest.mark.asyncio
async def test_nicole_view_next_vacation_none_when_empty(app_client):
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family/nicole")
    assert resp.json()["next_shared_vacation"] is None


@pytest.mark.asyncio
async def test_nicole_view_shows_top_agreed_vacation(app_client, isolated_votes):
    # Pre-seed two vacations; Japan has higher alignment
    votes_data = {
        "japan-trip": {
            "title": "Japan 2027",
            "type": "vacation",
            "votes": {
                "Henning": {"vote": 9, "importance": 9},
                "Nicole": {"vote": 9, "importance": 9},
            },
        },
        "iceland-trip": {
            "title": "Iceland 2026",
            "type": "vacation",
            "votes": {
                "Henning": {"vote": 9, "importance": 8},
                "Nicole": {"vote": 4, "importance": 7},
            },
        },
    }
    with open(isolated_votes, "w") as f:
        json.dump(votes_data, f)

    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family/nicole")
    vacation = resp.json()["next_shared_vacation"]
    assert vacation is not None
    assert vacation["id"] == "japan-trip"
    assert "strongly agree" in vacation["alignment_label"]


# ---------------------------------------------------------------------------
# Tests — GET /api/v1/family/votes
# ---------------------------------------------------------------------------


def test_votes_empty_when_no_data(app_client):
    resp = app_client.get("/api/v1/family/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["items"] == []


def test_votes_returns_formula(app_client):
    resp = app_client.get("/api/v1/family/votes")
    assert "formula" in resp.json()


def test_votes_sorted_by_alignment_desc(app_client, isolated_votes):
    votes_data = {
        "paris": {
            "title": "Paris",
            "type": "vacation",
            "votes": {
                "Henning": {"vote": 9},
                "Nicole": {"vote": 9},
            },
        },
        "maldives": {
            "title": "Malediven",
            "type": "vacation",
            "votes": {
                "Henning": {"vote": 3},
                "Nicole": {"vote": 9},
            },
        },
    }
    with open(isolated_votes, "w") as f:
        json.dump(votes_data, f)

    resp = app_client.get("/api/v1/family/votes")
    items = resp.json()["items"]
    assert items[0]["id"] == "paris"
    assert items[1]["id"] == "maldives"


# ---------------------------------------------------------------------------
# Tests — POST /api/v1/family/votes
# ---------------------------------------------------------------------------


def test_cast_vote_creates_new_item(app_client):
    payload = {
        "item_id": "japan-2027",
        "user": "Henning",
        "vote": 8,
        "importance": 9,
        "title": "Japan 2027",
        "item_type": "vacation",
    }
    resp = app_client.post("/api/v1/family/votes", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "japan-2027"
    assert data["title"] == "Japan 2027"
    assert data["votes"]["Henning"]["vote"] == 8
    assert data["alignment_score"] is None  # only one vote so far


def test_cast_vote_requires_title_for_new_item(app_client):
    payload = {
        "item_id": "unknown-item",
        "user": "Henning",
        "vote": 5,
    }
    resp = app_client.post("/api/v1/family/votes", json=payload)
    assert resp.status_code == 422


def test_cast_second_vote_computes_alignment(app_client):
    base = {
        "item_id": "japan-2027",
        "title": "Japan 2027",
        "item_type": "vacation",
    }
    app_client.post("/api/v1/family/votes", json={**base, "user": "Henning", "vote": 9})
    resp = app_client.post("/api/v1/family/votes", json={**base, "user": "Nicole", "vote": 9})
    data = resp.json()
    assert data["alignment_score"] == pytest.approx(1.0)
    assert "strongly agree" in data["alignment_label"]


def test_cast_vote_alignment_partial(app_client):
    base = {"item_id": "iceland", "title": "Iceland", "item_type": "vacation"}
    app_client.post("/api/v1/family/votes", json={**base, "user": "Henning", "vote": 9})
    resp = app_client.post("/api/v1/family/votes", json={**base, "user": "Nicole", "vote": 4})
    data = resp.json()
    # |9 - 4| / 10 = 0.5 → alignment = 0.5 → "Some alignment"
    assert data["alignment_score"] == pytest.approx(0.5)
    assert "some alignment" in data["alignment_label"].lower()


def test_cast_vote_updates_existing_title(app_client, isolated_votes):
    # Create item first
    app_client.post(
        "/api/v1/family/votes",
        json={"item_id": "hawaii", "user": "Henning", "vote": 7, "title": "Hawaii"},
    )
    # Update with new title
    resp = app_client.post(
        "/api/v1/family/votes",
        json={"item_id": "hawaii", "user": "Nicole", "vote": 8, "title": "Hawaii 2028"},
    )
    assert resp.json()["title"] == "Hawaii 2028"


def test_votes_persisted_across_requests(app_client):
    app_client.post(
        "/api/v1/family/votes",
        json={"item_id": "x1", "user": "Henning", "vote": 6, "title": "Test Item"},
    )
    resp = app_client.get("/api/v1/family/votes")
    assert resp.json()["count"] == 1
    assert resp.json()["items"][0]["id"] == "x1"


def test_context_signals_has_expected_keys(app_client):
    with patch("api.family._fetch_todays_meals", new=AsyncMock(return_value={})):
        resp = app_client.get("/api/v1/family")
    signals = resp.json()["context_signals"]
    assert "time_of_day" in signals
    assert "day_of_week" in signals
    assert "is_weekend" in signals
