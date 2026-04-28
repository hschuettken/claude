"""Tests for the Intent Detection Layer (FR #4 / item #43)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from companion.intent_detector import DetectedIntent, Intent, IntentDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_detector() -> IntentDetector:
    return IntentDetector()


def _at(hour: int) -> datetime:
    """Return a datetime fixed at *hour* on a weekday."""
    return datetime(2026, 4, 28, hour, 0, 0)  # Tuesday


# ---------------------------------------------------------------------------
# 1. Time patterns
# ---------------------------------------------------------------------------


def test_morning_focus_detected():
    d = _make_detector()
    intents = d.detect(now=_at(7))
    assert any(i.intent == Intent.MORNING_FOCUS for i in intents)


def test_work_session_detected_midday():
    d = _make_detector()
    intents = d.detect(now=_at(11))
    assert any(i.intent == Intent.WORK_SESSION for i in intents)


def test_evening_wind_down_detected():
    d = _make_detector()
    intents = d.detect(now=_at(21))
    assert any(i.intent == Intent.EVENING_WIND_DOWN for i in intents)


def test_no_time_intent_midnight():
    d = _make_detector()
    intents = d.detect(now=_at(0))
    time_intents = {Intent.MORNING_FOCUS, Intent.WORK_SESSION, Intent.EVENING_WIND_DOWN}
    assert not any(i.intent in time_intents for i in intents)


def test_morning_focus_confidence():
    d = _make_detector()
    intents = d.detect(now=_at(7))
    mi = next(i for i in intents if i.intent == Intent.MORNING_FOCUS)
    assert mi.confidence >= 0.7


# ---------------------------------------------------------------------------
# 2. Home presence (HA)
# ---------------------------------------------------------------------------


def test_away_mode_from_house_state():
    d = _make_detector()
    hs = {"presence": {"house_state": "away"}}
    intents = d.detect(hot_state=hs, now=_at(14))
    assert any(i.intent == Intent.AWAY_MODE for i in intents)


def test_away_mode_high_confidence():
    d = _make_detector()
    hs = {"presence": {"house_state": "away"}}
    intents = d.detect(hot_state=hs, now=_at(14))
    ai = next(i for i in intents if i.intent == Intent.AWAY_MODE)
    assert ai.confidence >= 0.90


def test_away_mode_all_users_away():
    d = _make_detector()
    hs = {
        "presence": {
            "house_state": "home",  # house state says home
            "users": {
                "henning": {"state": "not_home"},
                "nicole": {"state": "away"},
            },
        }
    }
    intents = d.detect(hot_state=hs, now=_at(14))
    assert any(i.intent == Intent.AWAY_MODE for i in intents)


def test_no_away_mode_when_home():
    d = _make_detector()
    hs = {
        "presence": {
            "house_state": "home",
            "users": {"henning": {"state": "home"}},
        }
    }
    intents = d.detect(hot_state=hs, now=_at(14))
    assert not any(i.intent == Intent.AWAY_MODE for i in intents)


# ---------------------------------------------------------------------------
# 3. Calendar events — Google Calendar
# ---------------------------------------------------------------------------


def test_trip_planning_from_calendar_travel_keyword():
    d = _make_detector()
    hs = {
        "calendar": {
            "upcoming_events": [
                {
                    "summary": "Urlaub Mallorca",
                    "description": "",
                    "start": "2026-05-05T10:00:00+02:00",
                }
            ]
        }
    }
    intents = d.detect(hot_state=hs, now=_at(14))
    assert any(i.intent == Intent.TRIP_PLANNING for i in intents)


def test_trip_planning_high_confidence_near_trip():
    d = _make_detector()
    hs = {
        "calendar": {
            "upcoming_events": [
                {
                    "summary": "Flug nach London",
                    "description": "",
                    "start": "2026-04-29T08:00:00+02:00",  # 1 day away
                }
            ]
        }
    }
    now = datetime(2026, 4, 28, 14, 0, 0, tzinfo=timezone.utc)
    intents = d.detect(hot_state=hs, now=now)
    ti = next((i for i in intents if i.intent == Intent.TRIP_PLANNING), None)
    assert ti is not None
    assert ti.confidence >= 0.85


def test_no_trip_intent_non_travel_calendar():
    d = _make_detector()
    hs = {
        "calendar": {
            "upcoming_events": [
                {"summary": "Zahnarzt", "description": "", "start": "2026-04-29T10:00:00+02:00"}
            ]
        }
    }
    intents = d.detect(hot_state=hs, now=_at(14))
    assert not any(i.intent == Intent.TRIP_PLANNING for i in intents)


def test_no_trip_intent_empty_calendar():
    d = _make_detector()
    hs = {"calendar": {}}
    intents = d.detect(hot_state=hs, now=_at(14))
    assert not any(i.intent == Intent.TRIP_PLANNING for i in intents)


# ---------------------------------------------------------------------------
# 4. Orbit task creation patterns
# ---------------------------------------------------------------------------


def test_trip_planning_from_packing_orbit_task():
    d = _make_detector()
    hs = {
        "orbit": {
            "recent_tasks": [
                {"title": "Koffer packen", "description": "für Reise"},
            ]
        }
    }
    intents = d.detect(hot_state=hs, now=_at(14))
    assert any(i.intent == Intent.TRIP_PLANNING for i in intents)


def test_work_session_from_orbit_task():
    d = _make_detector()
    hs = {
        "orbit": {
            "recent_tasks": [
                {"title": "PR review for deploy pipeline", "description": ""},
            ]
        }
    }
    intents = d.detect(hot_state=hs, now=_at(2))  # 2 AM — no time-based intent
    assert any(i.intent == Intent.WORK_SESSION for i in intents)


def test_no_orbit_intent_empty_tasks():
    d = _make_detector()
    hs = {"orbit": {"recent_tasks": []}}
    intents = d.detect(hot_state=hs, now=_at(2))
    assert intents == []


# ---------------------------------------------------------------------------
# 5. Memora search queries
# ---------------------------------------------------------------------------


def test_research_mode_from_memora_queries():
    d = _make_detector()
    hs = {
        "memora": {
            "recent_queries": [
                {"query": "best practices for solar inverter sizing", "at": "2026-04-28T10:00:00Z"},
                {"query": "off-grid battery storage options", "at": "2026-04-28T10:05:00Z"},
            ]
        }
    }
    intents = d.detect(hot_state=hs, now=_at(2))
    assert any(i.intent == Intent.RESEARCH_MODE for i in intents)


def test_research_mode_not_triggered_with_single_query():
    d = _make_detector()
    hs = {
        "memora": {
            "recent_queries": [
                {"query": "what is the weather", "at": "2026-04-28T10:00:00Z"},
            ]
        }
    }
    intents = d.detect(hot_state=hs, now=_at(2))
    assert not any(i.intent == Intent.RESEARCH_MODE for i in intents)


def test_research_mode_not_triggered_empty_memora():
    d = _make_detector()
    hs: dict = {}
    intents = d.detect(hot_state=hs, now=_at(2))
    assert not any(i.intent == Intent.RESEARCH_MODE for i in intents)


# ---------------------------------------------------------------------------
# 6. Multi-source merging
# ---------------------------------------------------------------------------


def test_multiple_sources_merge_trip_planning():
    """Calendar + Orbit both signal TRIP_PLANNING → merged into one entry."""
    d = _make_detector()
    hs = {
        "calendar": {
            "upcoming_events": [
                {
                    "summary": "Urlaub Toskana",
                    "description": "",
                    "start": "2026-05-10T10:00:00+02:00",
                }
            ]
        },
        "orbit": {
            "recent_tasks": [
                {"title": "Koffer packen", "description": ""},
            ]
        },
    }
    intents = d.detect(hot_state=hs, now=_at(14))
    trip_intents = [i for i in intents if i.intent == Intent.TRIP_PLANNING]
    assert len(trip_intents) == 1, "must be merged into a single entry"
    ti = trip_intents[0]
    assert len(ti.signals) >= 2, "must carry signals from both sources"


def test_sorted_by_confidence_descending():
    d = _make_detector()
    hs = {
        "presence": {"house_state": "away"},  # 0.95
        "memora": {
            "recent_queries": [
                {"query": "q1", "at": "t"},
                {"query": "q2", "at": "t"},
            ]
        },  # 0.60
    }
    intents = d.detect(hot_state=hs, now=_at(2))
    for a, b in zip(intents, intents[1:]):
        assert a.confidence >= b.confidence


# ---------------------------------------------------------------------------
# 7. format_for_prompt
# ---------------------------------------------------------------------------


def test_format_for_prompt_contains_intent_label():
    d = _make_detector()
    hs = {"presence": {"house_state": "away"}}
    section = d.format_for_prompt(hot_state=hs, now=_at(14))
    assert "Away Mode" in section


def test_format_for_prompt_empty_when_no_signals():
    d = _make_detector()
    section = d.format_for_prompt(hot_state={}, now=_at(2))
    assert section == ""


def test_format_for_prompt_max_three_intents():
    """Even with many signals, only top 3 intents are shown."""
    d = _make_detector()
    hs = {
        "presence": {"house_state": "away"},
        "memora": {
            "recent_queries": [
                {"query": "q1", "at": "t"},
                {"query": "q2", "at": "t"},
            ]
        },
        "calendar": {
            "upcoming_events": [
                {
                    "summary": "Urlaub",
                    "description": "",
                    "start": "2026-05-15T10:00:00+02:00",
                }
            ]
        },
    }
    section = d.format_for_prompt(hot_state=hs, now=_at(11))
    # Count entries starting with "- **"
    count = section.count("- **")
    assert count <= 3


# ---------------------------------------------------------------------------
# 8. persona.py integration
# ---------------------------------------------------------------------------


def test_persona_build_includes_intent_section_when_away():
    """PersonaBuilder.build() injects intent context when presence is away."""
    from companion.persona import PersonaBuilder

    pb = PersonaBuilder()
    hs = {"presence": {"house_state": "away"}}
    # Away presence always yields AWAY_MODE regardless of time
    prompt = pb.build(hot_state=hs, date_str="2026-04-28T14:00:00Z")
    assert "Detected Intent Context" in prompt
    assert "Away Mode" in prompt


def test_persona_build_intent_section_present_for_non_empty_hot_state():
    """PersonaBuilder.build() includes intent section when signals are available."""
    from companion.persona import PersonaBuilder

    pb = PersonaBuilder()
    # Calendar event with travel keyword guarantees TRIP_PLANNING regardless of time
    hs = {
        "calendar": {
            "upcoming_events": [
                {
                    "summary": "Urlaub Mallorca",
                    "description": "",
                    "start": "2026-09-01T08:00:00+02:00",
                }
            ]
        }
    }
    prompt = pb.build(hot_state=hs, date_str="2026-04-28T02:00:00Z")
    # Trip planning detected from calendar → section appears
    assert "Detected Intent Context" in prompt
    assert "Trip Planning" in prompt
