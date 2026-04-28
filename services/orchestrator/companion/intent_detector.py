"""Intent Detection Layer — infers user context from multi-source signals.

Five signal categories (acceptance criteria for FR #4 / item #43):
  1. Calendar events   — Google Calendar via hot_state["calendar"]
  2. Orbit task patterns — via hot_state["orbit"]
  3. Memora search queries — via hot_state["memora"]
  4. Home presence     — HA via hot_state["presence"]
  5. Time patterns     — cron-style hour ranges
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Intent(str, Enum):
    MORNING_FOCUS = "morning_focus"
    WORK_SESSION = "work_session"
    EVENING_WIND_DOWN = "evening_wind_down"
    AWAY_MODE = "away_mode"
    TRIP_PLANNING = "trip_planning"
    RESEARCH_MODE = "research_mode"


@dataclass
class DetectedIntent:
    intent: Intent
    confidence: float  # 0.0 – 1.0
    signals: list[str] = field(default_factory=list)
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Keyword sets
# ---------------------------------------------------------------------------

_TRAVEL_KW: frozenset[str] = frozenset({
    "reise", "urlaub", "trip", "travel", "vacation", "flug", "hotel",
    "abroad", "ausland", "fähre", "zug", "bahn", "flughafen", "flugzeug",
    "ferry", "flight",
})

_PACKING_KW: frozenset[str] = frozenset({
    "pack", "koffer", "packen", "buchung", "passport", "reisepass",
    "visum", "gepäck", "einpacken", "suitcase", "luggage",
})

_WORK_KW: frozenset[str] = frozenset({
    "code", "pr", "deploy", "review", "meeting", "call", "sprint",
    "ticket", "bug", "feature", "release", "presentation", "demo",
    "standup", "interview",
})


# ---------------------------------------------------------------------------
# IntentDetector
# ---------------------------------------------------------------------------


class IntentDetector:
    """
    Detects user intent from five signal categories.

    Usage::

        detector = IntentDetector()
        intents = detector.detect(hot_state=hs)
        prompt_section = detector.format_for_prompt(hot_state=hs)
    """

    def detect(
        self,
        hot_state: Optional[dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> list[DetectedIntent]:
        """
        Detect intents from all available signals.

        Returns:
            List of DetectedIntent sorted by confidence (highest first).
            Multiple sources signalling the same intent are merged into one entry
            with the highest confidence and combined signal descriptions.
        """
        if now is None:
            now = datetime.now()
        hs = hot_state or {}

        candidates: dict[Intent, DetectedIntent] = {}

        for di in (
            *self._detect_time(now),
            *self._detect_presence(hs),
            *self._detect_calendar(hs, now),
            *self._detect_orbit(hs),
            *self._detect_memora(hs),
        ):
            if di.intent in candidates:
                existing = candidates[di.intent]
                merged = DetectedIntent(
                    intent=di.intent,
                    confidence=max(existing.confidence, di.confidence),
                    signals=existing.signals + [
                        s for s in di.signals if s not in existing.signals
                    ],
                    detected_at=min(existing.detected_at, di.detected_at),
                )
                candidates[di.intent] = merged
            else:
                candidates[di.intent] = di

        return sorted(candidates.values(), key=lambda x: x.confidence, reverse=True)

    def format_for_prompt(
        self,
        hot_state: Optional[dict[str, Any]] = None,
        now: Optional[datetime] = None,
    ) -> str:
        """
        Return a Markdown section suitable for LLM system-prompt injection.

        Returns empty string when no intents are detected (caller can skip the
        section entirely).
        """
        intents = self.detect(hot_state=hot_state, now=now)
        if not intents:
            return ""

        lines = ["## Detected Intent Context"]
        for di in intents[:3]:  # top 3 to keep the prompt tight
            label = di.intent.value.replace("_", " ").title()
            lines.append(f"- **{label}** ({di.confidence:.0%} confidence)")
            for sig in di.signals[:2]:
                lines.append(f"  - {sig}")
        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Private signal detectors
    # -----------------------------------------------------------------------

    def _detect_time(self, now: datetime) -> list[DetectedIntent]:
        """Time patterns — cron-style hour ranges."""
        h = now.hour
        if 6 <= h < 9:
            return [DetectedIntent(
                intent=Intent.MORNING_FOCUS,
                confidence=0.80,
                signals=[f"Morning focus window ({now.strftime('%H:%M')})"],
            )]
        if 9 <= h < 17:
            return [DetectedIntent(
                intent=Intent.WORK_SESSION,
                confidence=0.50,
                signals=[f"Core work hours ({now.strftime('%H:%M')})"],
            )]
        if 19 <= h < 23:
            return [DetectedIntent(
                intent=Intent.EVENING_WIND_DOWN,
                confidence=0.70,
                signals=[f"Evening wind-down window ({now.strftime('%H:%M')})"],
            )]
        return []

    def _detect_presence(self, hs: dict[str, Any]) -> list[DetectedIntent]:
        """Home presence via HA (stored in hot_state by HotStateSubscriber)."""
        presence = hs.get("presence", {})
        if not presence:
            return []

        house_state = presence.get("house_state", "")
        if house_state in ("away", "vacation", "not_home"):
            return [DetectedIntent(
                intent=Intent.AWAY_MODE,
                confidence=0.95,
                signals=[f"House state: {house_state} (HA presence)"],
            )]

        users = presence.get("users", {})
        if users and all(
            u.get("state") in ("away", "not_home") for u in users.values()
        ):
            return [DetectedIntent(
                intent=Intent.AWAY_MODE,
                confidence=0.90,
                signals=["All residents away (HA device tracking)"],
            )]
        return []

    def _detect_calendar(
        self, hs: dict[str, Any], now: datetime
    ) -> list[DetectedIntent]:
        """Calendar events — travel keywords in upcoming events."""
        cal = hs.get("calendar", {})
        events: list[dict] = (
            cal.get("upcoming_events")
            or cal.get("events")
            or []
        )
        if not events:
            return []

        text = " ".join(
            (e.get("summary", "") + " " + e.get("description", "")).lower()
            for e in events
        )
        if not any(kw in text for kw in _TRAVEL_KW):
            return []

        days = self._days_until_first_event(events, now)
        if days <= 2:
            conf = 0.90
        elif days <= 7:
            conf = 0.75
        else:
            conf = 0.50

        return [DetectedIntent(
            intent=Intent.TRIP_PLANNING,
            confidence=conf,
            signals=[f"Travel event in calendar (~{days:.0f}d away)"],
        )]

    def _detect_orbit(self, hs: dict[str, Any]) -> list[DetectedIntent]:
        """Orbit task creation patterns — title/description keyword matching."""
        orbit = hs.get("orbit", {})
        tasks: list[dict] = (
            orbit.get("recent_tasks")
            or orbit.get("tasks")
            or []
        )
        if not tasks:
            return []

        text = " ".join(
            (t.get("title", "") + " " + t.get("description", "")).lower()
            for t in tasks[:10]
        )

        results: list[DetectedIntent] = []
        if any(kw in text for kw in _PACKING_KW):
            results.append(DetectedIntent(
                intent=Intent.TRIP_PLANNING,
                confidence=0.70,
                signals=["Orbit tasks: travel/packing keywords detected"],
            ))
        if any(kw in text for kw in _WORK_KW):
            results.append(DetectedIntent(
                intent=Intent.WORK_SESSION,
                confidence=0.65,
                signals=["Orbit tasks: active work items detected"],
            ))
        return results

    def _detect_memora(self, hs: dict[str, Any]) -> list[DetectedIntent]:
        """Memora search queries — rolling list stored in hot_state["memora"]."""
        memora = hs.get("memora", {})
        queries: list[dict] = memora.get("recent_queries", [])
        if len(queries) < 2:
            return []

        last_query = (queries[-1].get("query") or "")[:60]
        return [DetectedIntent(
            intent=Intent.RESEARCH_MODE,
            confidence=0.60,
            signals=[
                f"{len(queries)} recent Memora search(es)",
                f'Last: "{last_query}"',
            ],
        )]

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _days_until_first_event(events: list[dict], now: datetime) -> float:
        """Return days until the earliest upcoming event with a parseable start."""
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("Europe/Berlin")
        now_tz = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
        best = 999.0

        for ev in events:
            start = (
                ev.get("start")
                or ev.get("startTime")
                or ev.get("start_time")
            )
            if not start:
                continue
            try:
                if isinstance(start, str):
                    parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
                    parsed = parsed.astimezone(tz)
                    delta = (parsed - now_tz).total_seconds() / 86400
                    if 0 < delta < best:
                        best = delta
            except Exception:  # noqa: BLE001
                pass
        return best
