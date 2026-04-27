"""Ingest Google Calendar events → KG nodes.

Uses the Orbit/nb9os API as a proxy (Google OAuth already wired there)
or falls back to direct HTTP if GOOGLE_CALENDAR_API_URL is set.

Creates:
  - `calendar_event` node per event
  - `meeting` node if attendees > 1
  - RELATES_TO edges between overlapping events
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..config import settings
from .. import knowledge_graph as kg
from ..models import EdgeCreate, IngestResult, NodeCreate

logger = logging.getLogger(__name__)


async def ingest_calendar(days_ahead: int = 7, days_behind: int = 7) -> IngestResult:
    """Fetch calendar events from the Orbit API and create KG nodes."""
    result = IngestResult(source="calendar", nodes_created=0, edges_created=0)
    try:
        events = await _fetch_events(days_ahead, days_behind)
    except Exception as exc:
        result.errors.append(f"Calendar fetch failed: {exc}")
        return result

    created_nodes: list[Any] = []
    for ev in events:
        node = await _event_to_node(ev, result)
        if node:
            created_nodes.append((ev, node))

    # Create RELATES_TO edges for events that share the same day
    from itertools import combinations
    day_groups: dict[str, list] = {}
    for ev, node in created_nodes:
        day = _event_date(ev)
        day_groups.setdefault(day, []).append((ev, node))

    for day, group in day_groups.items():
        for (ev_a, node_a), (ev_b, node_b) in combinations(group, 2):
            edge = await kg.create_edge(EdgeCreate(
                source_id=node_a.id,
                target_id=node_b.id,
                relation_type="RELATES_TO",
                properties={"same_day": day},
            ))
            if edge:
                result.edges_created += 1

    logger.info(
        "calendar_ingested nodes=%d edges=%d errors=%d",
        result.nodes_created, result.edges_created, len(result.errors),
    )
    return result


async def _fetch_events(days_ahead: int, days_behind: int) -> list[dict[str, Any]]:
    """Fetch events via the Orbit/nb9os calendar proxy endpoint."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    time_min = (now - timedelta(days=days_behind)).isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    url = f"{settings.orbit_url}/api/calendar/events"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params={"time_min": time_min, "time_max": time_max})
        if resp.status_code == 404:
            logger.debug("calendar_proxy_not_found url=%s", url)
            return []
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else data.get("events", [])


async def _event_to_node(ev: dict[str, Any], result: IngestResult):
    event_id = str(ev.get("id") or ev.get("event_id") or "")
    summary = ev.get("summary") or ev.get("title") or "Untitled"
    attendees = ev.get("attendees", [])
    node_type = "meeting" if len(attendees) > 1 else "calendar_event"

    node = await kg.create_node(NodeCreate(
        node_type=node_type,
        label=summary,
        properties={
            "start": ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", ""),
            "end": ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date", ""),
            "attendees": [a.get("email", "") for a in attendees],
            "location": ev.get("location", ""),
            "description": (ev.get("description") or "")[:500],
        },
        source="calendar",
        source_id=event_id,
    ))
    if node:
        result.nodes_created += 1
    return node


def _event_date(ev: dict[str, Any]) -> str:
    start = ev.get("start", {})
    return start.get("date") or (start.get("dateTime") or "")[:10]
