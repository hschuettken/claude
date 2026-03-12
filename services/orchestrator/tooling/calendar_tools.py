"""Calendar tool definitions and handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shared.log import get_logger
from gcal import GoogleCalendarClient
from config import OrchestratorSettings
from memory import Memory

logger = get_logger("tooling.calendar_tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_calendar_events",
            "description": (
                "Get upcoming events from a household calendar. Use 'family' for the "
                "shared family calendar (absences, business trips, appointments) or "
                "'orchestrator' for the orchestrator's own calendar (reminders, scheduled actions). "
                "Useful for checking if someone is home, planning energy usage around absences, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "calendar": {
                        "type": "string",
                        "enum": ["family", "orchestrator"],
                        "description": "Which calendar to read",
                    },
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days ahead to look (default: 3)",
                        "default": 3,
                    },
                },
                "required": ["calendar"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_household_availability",
            "description": (
                "Check the family calendar to determine who is home today and the next few days. "
                "Looks for absences, business trips, and vacations. "
                "Use this for energy planning (no EV charging if owner is away, "
                "lower heating if nobody home, etc.)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days_ahead": {
                        "type": "integer",
                        "description": "How many days to check (default: 3)",
                        "default": 3,
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": (
                "Create an event on the orchestrator's calendar. Use for reminders, "
                "scheduled energy actions, or notes. ALWAYS confirm with the user before creating. "
                "Only writes to the orchestrator calendar, never to the family calendar."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Event title",
                    },
                    "start": {
                        "type": "string",
                        "description": "Start time in ISO 8601 format (e.g. 2025-01-15T17:00:00+01:00) or YYYY-MM-DD for all-day",
                    },
                    "end": {
                        "type": "string",
                        "description": "End time in ISO 8601 format or YYYY-MM-DD for all-day",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description/notes",
                    },
                    "all_day": {
                        "type": "boolean",
                        "description": "Whether this is an all-day event (default: false)",
                        "default": False,
                    },
                },
                "required": ["summary", "start", "end"],
            },
        },
    },
]


class CalendarTools:
    """Handlers for calendar tools."""

    def __init__(
        self,
        gcal: GoogleCalendarClient | None,
        settings: OrchestratorSettings,
        memory: Memory,
    ) -> None:
        self.gcal = gcal
        self.settings = settings
        self.memory = memory
        self._tz = ZoneInfo(settings.timezone)

    async def get_calendar_events(
        self, calendar: str, days_ahead: int = 3,
    ) -> dict[str, Any]:
        if not self.gcal or not self.gcal.available:
            return {"error": "Google Calendar not configured"}

        cal_id = ""
        if calendar == "family":
            cal_id = self.settings.google_calendar_family_id
        elif calendar == "orchestrator":
            cal_id = self.settings.google_calendar_orchestrator_id

        if not cal_id:
            return {"error": f"Calendar '{calendar}' not configured (no calendar ID set)"}

        events = await self.gcal.get_events(
            calendar_id=cal_id,
            days_ahead=days_ahead,
            max_results=25,
        )
        return {
            "calendar": calendar,
            "days_ahead": days_ahead,
            "event_count": len(events),
            "events": events,
        }

    async def check_household_availability(
        self, days_ahead: int = 3,
    ) -> dict[str, Any]:
        if not self.gcal or not self.gcal.available:
            return {"error": "Google Calendar not configured"}

        cal_id = self.settings.google_calendar_family_id
        if not cal_id:
            return {"error": "Family calendar not configured (GOOGLE_CALENDAR_FAMILY_ID)"}

        events = await self.gcal.get_events(
            calendar_id=cal_id,
            days_ahead=days_ahead,
            max_results=30,
        )

        absence_keywords = {
            "abwesend", "absent", "away", "trip", "reise", "dienstreise",
            "business trip", "urlaub", "vacation", "holiday", "unterwegs",
            "nicht da", "verreist",
        }
        absences: list[dict[str, Any]] = []
        other_events: list[dict[str, Any]] = []

        for event in events:
            summary_lower = (event.get("summary") or "").lower()
            if any(kw in summary_lower for kw in absence_keywords):
                absences.append(event)
            else:
                other_events.append(event)

        now = datetime.now(self._tz)
        return {
            "check_date": now.strftime("%Y-%m-%d"),
            "days_checked": days_ahead,
            "absences": absences,
            "absence_count": len(absences),
            "other_events": other_events[:10],
            "hint": (
                "Absences include events with keywords like 'Dienstreise', 'Urlaub', "
                "'away', or all-day events. Check event summaries for who is absent."
            ),
        }

    async def create_calendar_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        all_day: bool = False,
    ) -> dict[str, Any]:
        if not self.gcal or not self.gcal.available:
            return {"error": "Google Calendar not configured"}

        cal_id = self.settings.google_calendar_orchestrator_id
        if not cal_id:
            return {"error": "Orchestrator calendar not configured (GOOGLE_CALENDAR_ORCHESTRATOR_ID)"}

        event = await self.gcal.create_event(
            calendar_id=cal_id,
            summary=summary,
            start=start,
            end=end,
            description=description,
            all_day=all_day,
        )
        self.memory.log_decision(
            context="Calendar event created",
            decision=f"Created '{summary}' on {start}",
            reasoning="User requested via orchestrator",
        )
        return {"success": True, "event": event}
