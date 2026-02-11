"""Google Calendar integration for the orchestrator.

Uses a Google Service Account to read/write calendars.  Setup:

1. Create a project in Google Cloud Console
2. Enable the Google Calendar API
3. Create a Service Account and download the JSON key
4. Share your family calendar with the service account email (read-only)
5. Create/share an orchestrator calendar with the service account email (editor)
6. Set ``GOOGLE_CALENDAR_CREDENTIALS_FILE`` and calendar IDs in ``.env``

All API calls are synchronous and run via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import json
import base64
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from shared.log import get_logger

logger = get_logger("calendar")

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar",
]


class GoogleCalendarClient:
    """Async wrapper around the Google Calendar API (v3)."""

    def __init__(
        self,
        credentials_file: str = "",
        credentials_json: str = "",
        timezone: str = "Europe/Berlin",
    ) -> None:
        self._tz = ZoneInfo(timezone)
        self._service: Any = None
        self._credentials_file = credentials_file
        self._credentials_json = credentials_json

    def _get_service(self) -> Any:
        """Lazily initialize the Google Calendar API service."""
        if self._service is not None:
            return self._service

        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build

        if self._credentials_file and Path(self._credentials_file).exists():
            creds = Credentials.from_service_account_file(
                self._credentials_file, scopes=SCOPES,
            )
        elif self._credentials_json:
            # Support base64-encoded JSON for Docker env var convenience
            try:
                raw = base64.b64decode(self._credentials_json)
                info = json.loads(raw)
            except Exception:
                # Try plain JSON string
                info = json.loads(self._credentials_json)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            raise RuntimeError(
                "No Google Calendar credentials configured. "
                "Set GOOGLE_CALENDAR_CREDENTIALS_FILE or GOOGLE_CALENDAR_CREDENTIALS_JSON."
            )

        self._service = build("calendar", "v3", credentials=creds)
        logger.info("google_calendar_initialized")
        return self._service

    @property
    def available(self) -> bool:
        """Check if calendar credentials are configured."""
        return bool(self._credentials_file or self._credentials_json)

    # ------------------------------------------------------------------
    # Read events
    # ------------------------------------------------------------------

    async def get_events(
        self,
        calendar_id: str,
        days_ahead: int = 1,
        days_back: int = 0,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """Fetch events from a calendar.

        Args:
            calendar_id: Google Calendar ID (email-like string).
            days_ahead: Number of days into the future to look.
            days_back: Number of days into the past to look.
            max_results: Maximum number of events to return.

        Returns:
            List of simplified event dicts.
        """
        return await asyncio.to_thread(
            self._get_events_sync,
            calendar_id, days_ahead, days_back, max_results,
        )

    def _get_events_sync(
        self,
        calendar_id: str,
        days_ahead: int,
        days_back: int,
        max_results: int,
    ) -> list[dict[str, Any]]:
        service = self._get_service()
        now = datetime.now(self._tz)
        time_min = (now - timedelta(days=days_back)).isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()

        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )

        events: list[dict[str, Any]] = []
        for item in result.get("items", []):
            events.append(self._simplify_event(item))
        return events

    # ------------------------------------------------------------------
    # Create events
    # ------------------------------------------------------------------

    async def create_event(
        self,
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        all_day: bool = False,
    ) -> dict[str, Any]:
        """Create an event on a calendar.

        Args:
            calendar_id: Target calendar ID.
            summary: Event title.
            start: Start time as ISO 8601 string, or YYYY-MM-DD for all-day.
            end: End time as ISO 8601 string, or YYYY-MM-DD for all-day.
            description: Optional event description.
            all_day: If True, treat start/end as dates (not datetimes).

        Returns:
            Simplified event dict of the created event.
        """
        return await asyncio.to_thread(
            self._create_event_sync,
            calendar_id, summary, start, end, description, all_day,
        )

    def _create_event_sync(
        self,
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        description: str,
        all_day: bool,
    ) -> dict[str, Any]:
        service = self._get_service()

        if all_day:
            body: dict[str, Any] = {
                "summary": summary,
                "start": {"date": start},
                "end": {"date": end},
            }
        else:
            tz_str = str(self._tz)
            body = {
                "summary": summary,
                "start": {"dateTime": start, "timeZone": tz_str},
                "end": {"dateTime": end, "timeZone": tz_str},
            }

        if description:
            body["description"] = description

        created = (
            service.events()
            .insert(calendarId=calendar_id, body=body)
            .execute()
        )
        logger.info("calendar_event_created", calendar=calendar_id, summary=summary)
        return self._simplify_event(created)

    # ------------------------------------------------------------------
    # Delete events
    # ------------------------------------------------------------------

    async def delete_event(
        self,
        calendar_id: str,
        event_id: str,
    ) -> bool:
        """Delete an event from a calendar.

        Returns True if deleted, False on error.
        """
        return await asyncio.to_thread(
            self._delete_event_sync, calendar_id, event_id,
        )

    def _delete_event_sync(self, calendar_id: str, event_id: str) -> bool:
        service = self._get_service()
        try:
            service.events().delete(
                calendarId=calendar_id, eventId=event_id,
            ).execute()
            logger.info("calendar_event_deleted", calendar=calendar_id, event_id=event_id)
            return True
        except Exception:
            logger.debug("calendar_event_delete_failed", event_id=event_id)
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _simplify_event(item: dict[str, Any]) -> dict[str, Any]:
        """Extract the most useful fields from a Google Calendar event."""
        start = item.get("start", {})
        end = item.get("end", {})
        return {
            "id": item.get("id", ""),
            "summary": item.get("summary", "(no title)"),
            "start": start.get("dateTime") or start.get("date", ""),
            "end": end.get("dateTime") or end.get("date", ""),
            "all_day": "date" in start,
            "location": item.get("location", ""),
            "description": (item.get("description") or "")[:200],
            "status": item.get("status", ""),
            "creator": item.get("creator", {}).get("email", ""),
        }
