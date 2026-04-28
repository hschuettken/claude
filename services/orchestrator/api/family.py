"""Family OS API — shared system and Nicole view (FR #4 / item #41).

Endpoints:
    GET  /api/v1/family         -- Full family OS dashboard
    GET  /api/v1/family/nicole  -- Nicole's simplified view
    GET  /api/v1/family/votes   -- Shared item votes + alignment scores
    POST /api/v1/family/votes   -- Cast or update a vote

Data:
    Votes are persisted to /app/data/family_votes.json.
    All data sources (HA energy, calendar, Orbit grocery list, cook planner)
    fail gracefully — each section returns an error key instead of crashing.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("api.family")

router = APIRouter(prefix="/api/v1/family", tags=["family-os"])

# Wired up by configure() at startup — avoids circular imports
_ha: Any = None
_gcal: Any = None
_orbit_tools: Any = None
_energy_tools: Any = None
_settings: Any = None

VOTES_PATH = "/app/data/family_votes.json"
NB9OS_BASE = os.environ.get("NB9OS_URL", "http://nb9os-backend:8000")
NB9OS_TOKEN = os.environ.get("NB9OS_SERVICE_TOKEN", "")


def configure(
    ha: Any,
    gcal: Any,
    orbit_tools: Any,
    energy_tools: Any,
    settings: Any,
) -> None:
    """Wire up shared components. Called once during server setup."""
    global _ha, _gcal, _orbit_tools, _energy_tools, _settings
    _ha = ha
    _gcal = gcal
    _orbit_tools = orbit_tools
    _energy_tools = energy_tools
    _settings = settings


# ---------------------------------------------------------------------------
# Vote persistence
# ---------------------------------------------------------------------------


def _load_votes() -> dict[str, Any]:
    if os.path.exists(VOTES_PATH):
        try:
            with open(VOTES_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_votes(votes: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(VOTES_PATH), exist_ok=True)
    with open(VOTES_PATH, "w") as f:
        json.dump(votes, f, indent=2)


def calc_alignment(user_votes: dict[str, dict]) -> float | None:
    """Compute alignment score 0..1 from per-user votes.

    Formula: 1 - abs(v1 - v2) / 10
    Weighted by average importance of both users.
    """
    if len(user_votes) < 2:
        return None
    users = list(user_votes.keys())
    try:
        u1, u2 = users[0], users[1]
        v1 = float(user_votes[u1].get("vote", 5))
        v2 = float(user_votes[u2].get("vote", 5))
        return round(1.0 - abs(v1 - v2) / 10.0, 3)
    except Exception:
        return None


def alignment_label(score: float | None) -> str:
    if score is None:
        return "needs votes"
    pct = int(score * 100)
    if pct >= 90:
        return f"You both strongly agree ({pct}% alignment)"
    elif pct >= 70:
        return f"Good alignment ({pct}%)"
    elif pct >= 50:
        return f"Some alignment ({pct}%)"
    return f"You see it differently ({pct}% alignment)"


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


async def _fetch_energy_status() -> dict[str, Any]:
    """Return a simple house energy status: all_good / normal / high_usage."""
    if _ha is None:
        return {"status": "unknown", "detail": "HA not connected"}
    entity = (
        getattr(_settings, "house_power_entity", "")
        or "sensor.shelly3em_main_channel_total_power"
    )
    try:
        state = await _ha.get_state(entity)
        raw = state.get("state", "0")
        if raw in ("unavailable", "unknown"):
            return {"status": "unknown", "detail": "sensor unavailable"}
        watts = float(raw)
        if watts > 6000:
            status = "high_usage"
        elif watts < 3000:
            status = "all_good"
        else:
            status = "normal"
        return {"status": status, "watts": round(watts, 0), "detail": f"{watts:.0f} W"}
    except Exception as exc:
        return {"status": "unknown", "detail": str(exc)}


async def _fetch_todays_meals() -> dict[str, Any]:
    """Fetch today's meal plan from NB9OS cook planner."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if NB9OS_TOKEN:
        headers["Authorization"] = f"Bearer {NB9OS_TOKEN}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{NB9OS_BASE}/api/v1/cook/today", headers=headers
            )
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"cook planner returned {resp.status_code}"}
    except Exception as exc:
        return {"error": str(exc), "note": "cook planner unavailable"}


async def _fetch_calendar(days_ahead: int = 7) -> list[dict[str, Any]]:
    """Return shared family calendar events."""
    if _gcal is None or not getattr(_gcal, "available", False):
        return []
    cal_id = getattr(_settings, "google_calendar_family_id", "")
    if not cal_id:
        return []
    try:
        return await _gcal.get_events(
            calendar_id=cal_id, days_ahead=days_ahead, max_results=20
        )
    except Exception:
        return []


async def _fetch_grocery_list() -> dict[str, Any]:
    """Return unchecked items from the household grocery list in Orbit."""
    if _orbit_tools is None:
        return {"items": [], "note": "Orbit not connected"}
    try:
        resp = await _orbit_tools.orbit_list_lists()
        # API may return a dict with a "lists" key or a plain list
        if isinstance(resp, dict):
            lists = resp.get("lists", resp.get("items", []))
        else:
            lists = resp or []

        grocery_keywords = {"shopping", "einkauf", "grocery", "groceries", "supermarkt"}
        grocery = next(
            (
                lst
                for lst in lists
                if any(
                    kw in (lst.get("title") or lst.get("name") or "").lower()
                    for kw in grocery_keywords
                )
            ),
            None,
        )
        if grocery is None:
            return {"items": [], "note": "no grocery list found in Orbit"}

        list_id = grocery.get("id")
        if not list_id:
            return {"items": [], "note": "grocery list has no ID"}

        detail = await _orbit_tools.orbit_get_list(list_id)
        items: list[dict] = detail.get("items", [])
        unchecked = [i for i in items if not i.get("checked", False)]
        return {
            "list_id": list_id,
            "list_name": grocery.get("title") or grocery.get("name"),
            "items": unchecked,
            "total": len(unchecked),
        }
    except Exception as exc:
        return {"items": [], "error": str(exc)}


def _context_signals() -> dict[str, Any]:
    """Return stress-inference signals (calendar density requires separate query)."""
    now = datetime.now()
    return {
        "time_of_day": now.strftime("%H:%M"),
        "day_of_week": now.strftime("%A"),
        "hour": now.hour,
        "is_weekend": now.weekday() >= 5,
    }


def _build_shared_items(votes_data: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for item_id, item in votes_data.items():
        score = calc_alignment(item.get("votes", {}))
        items.append(
            {
                "id": item_id,
                "title": item.get("title", item_id),
                "type": item.get("type", "vacation"),
                "votes": item.get("votes", {}),
                "alignment_score": score,
                "alignment_label": alignment_label(score),
            }
        )
    items.sort(key=lambda x: x["alignment_score"] or 0.0, reverse=True)
    return items


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class VoteRequest(BaseModel):
    item_id: str = Field(..., description="Slug or UUID of the shared item")
    user: str = Field(..., description="Voter's name, e.g. 'Henning' or 'Nicole'")
    vote: int = Field(..., ge=1, le=10, description="Vote 1-10")
    importance: int = Field(default=5, ge=1, le=10, description="Importance to this person 1-10")
    title: str = Field(default="", description="Item title — required when creating a new item")
    item_type: str = Field(
        default="vacation",
        description="Item type: vacation, purchase, or project",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("")
async def get_family_dashboard() -> dict[str, Any]:
    """Full Family OS dashboard — aggregates meals, calendar, grocery, energy, and votes."""
    import asyncio

    tz_str = (
        getattr(_settings, "timezone", "Europe/Berlin") if _settings else "Europe/Berlin"
    )
    now = datetime.now(ZoneInfo(tz_str))

    energy, meals, calendar_events, grocery = await asyncio.gather(
        _fetch_energy_status(),
        _fetch_todays_meals(),
        _fetch_calendar(days_ahead=7),
        _fetch_grocery_list(),
    )

    return {
        "timestamp": now.isoformat(),
        "meals_today": meals,
        "calendar_events": calendar_events,
        "grocery_list": grocery,
        "energy_status": energy,
        "shared_items": _build_shared_items(_load_votes()),
        "context_signals": _context_signals(),
    }


@router.get("/nicole")
async def get_nicole_view() -> dict[str, Any]:
    """Nicole's simplified view — meals, today's events, grocery, energy, next agreed trip."""
    import asyncio

    tz_str = (
        getattr(_settings, "timezone", "Europe/Berlin") if _settings else "Europe/Berlin"
    )
    now = datetime.now(ZoneInfo(tz_str))

    energy, meals, calendar_events, grocery = await asyncio.gather(
        _fetch_energy_status(),
        _fetch_todays_meals(),
        _fetch_calendar(days_ahead=1),
        _fetch_grocery_list(),
    )

    # Top vacation by alignment score
    votes_data = _load_votes()
    vacations = [
        {
            "id": k,
            "title": v.get("title", k),
            "alignment_score": calc_alignment(v.get("votes", {})),
            "alignment_label": alignment_label(calc_alignment(v.get("votes", {}))),
        }
        for k, v in votes_data.items()
        if v.get("type") == "vacation"
    ]
    vacations.sort(key=lambda x: x["alignment_score"] or 0.0, reverse=True)

    hour = now.hour
    if hour < 12:
        greeting = "Guten Morgen, Nicole!"
    elif hour < 18:
        greeting = "Guten Tag, Nicole!"
    else:
        greeting = "Guten Abend, Nicole!"

    return {
        "date": now.date().isoformat(),
        "view": "nicole",
        "greeting": greeting,
        "meals_today": meals,
        "todays_events": calendar_events,
        "grocery_list": grocery,
        "energy_status": energy,
        "next_shared_vacation": vacations[0] if vacations else None,
    }


@router.get("/votes")
async def get_votes() -> dict[str, Any]:
    """Return all shared item votes with alignment scores."""
    votes_data = _load_votes()
    items = _build_shared_items(votes_data)
    return {
        "items": items,
        "count": len(items),
        "formula": "alignment = 1 - abs(vote_a - vote_b) / 10",
    }


@router.post("/votes")
async def cast_vote(req: VoteRequest) -> dict[str, Any]:
    """Cast or update a vote for a shared item (vacation, purchase, or project)."""
    votes_data = _load_votes()

    if req.item_id not in votes_data:
        if not req.title:
            raise HTTPException(
                status_code=422,
                detail="title is required when creating a new shared item",
            )
        votes_data[req.item_id] = {
            "title": req.title,
            "type": req.item_type,
            "votes": {},
        }
    elif req.title:
        votes_data[req.item_id]["title"] = req.title

    votes_data[req.item_id]["votes"][req.user] = {
        "vote": req.vote,
        "importance": req.importance,
        "updated_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    _save_votes(votes_data)

    item = votes_data[req.item_id]
    score = calc_alignment(item.get("votes", {}))
    return {
        "id": req.item_id,
        "title": item["title"],
        "type": item["type"],
        "votes": item["votes"],
        "alignment_score": score,
        "alignment_label": alignment_label(score),
    }
