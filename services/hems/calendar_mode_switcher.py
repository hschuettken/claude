"""Calendar-driven automatic HEMS mode switching (#1079).

Integrates with iCal calendars to automatically switch heating modes:
- "away"/"vacation"/"holiday" → "away" mode (minimal heating)
- "home office" → "comfort" mode (full heating)
- "boost" → "boost" mode (aggressive heating)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

HEMS_CALENDAR_URL = os.getenv("HEMS_CALENDAR_URL", "")
MQTT_HOST = os.getenv("MQTT_HOST", "192.168.0.73")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))


class CalendarModeSwitcher:
    """Automatic HEMS mode switching based on calendar events."""

    def __init__(
        self,
        calendar_url: str = HEMS_CALENDAR_URL,
        mqtt_host: str = MQTT_HOST,
        mqtt_port: int = MQTT_PORT,
    ):
        self.calendar_url = calendar_url
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self._current_mode: Optional[str] = None
        self._last_mode_publish_time: float = 0.0

    async def get_active_events(self) -> list[dict]:
        """Fetch and parse active calendar events from iCal feed.

        Returns:
            List of dicts with keys: start, end, summary, hems_mode
            Empty list if calendar_url not set or fetch fails.
        """
        if not self.calendar_url:
            return []

        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.calendar_url)
                response.raise_for_status()

            # Try to parse with icalendar, fall back to basic string parsing
            try:
                import icalendar

                cal = icalendar.Calendar.from_ical(response.text)
                events = self._parse_ical_events(cal)
            except ImportError:
                logger.warning("icalendar not installed, using fallback parsing")
                events = self._parse_ical_basic(response.text)

            # Filter to active events (overlapping now)
            now = datetime.now(timezone.utc)
            active = []
            for event in events:
                if event["start"] <= now <= event["end"]:
                    active.append(event)

            return active

        except Exception as e:
            logger.warning("Failed to fetch/parse calendar: %s", e)
            return []

    def _parse_ical_events(self, cal: object) -> list[dict]:
        """Parse events from icalendar.Calendar object."""
        events = []
        try:
            for component in cal.walk():
                if component.name == "VEVENT":
                    start = component.get("dtstart")
                    end = component.get("dtend")
                    summary = component.get("summary", "")

                    # Convert icalendar date/datetime to Python datetime
                    if hasattr(start, "dt"):
                        start_dt = start.dt
                        if not isinstance(start_dt, datetime):
                            # It's a date, convert to datetime at midnight UTC
                            start_dt = datetime.combine(
                                start_dt, datetime.min.time(), tzinfo=timezone.utc
                            )
                        elif start_dt.tzinfo is None:
                            start_dt = start_dt.replace(tzinfo=timezone.utc)
                    else:
                        continue

                    if hasattr(end, "dt"):
                        end_dt = end.dt
                        if not isinstance(end_dt, datetime):
                            end_dt = datetime.combine(
                                end_dt, datetime.min.time(), tzinfo=timezone.utc
                            )
                        elif end_dt.tzinfo is None:
                            end_dt = end_dt.replace(tzinfo=timezone.utc)
                    else:
                        continue

                    # Determine HEMS mode from event summary
                    summary_lower = summary.lower() if summary else ""
                    hems_mode = self._determine_mode_from_summary(summary_lower)

                    events.append(
                        {
                            "start": start_dt,
                            "end": end_dt,
                            "summary": summary,
                            "hems_mode": hems_mode,
                        }
                    )
        except Exception as e:
            logger.warning("Error parsing ical events: %s", e)

        return events

    def _parse_ical_basic(self, ical_text: str) -> list[dict]:
        """Fallback basic parsing for iCal format (no icalendar library)."""
        events = []
        lines = ical_text.split("\n")
        current_event: dict = {}

        for line in lines:
            line = line.strip()

            if line.startswith("BEGIN:VEVENT"):
                current_event = {}
            elif line.startswith("END:VEVENT"):
                if "start" in current_event and "end" in current_event:
                    summary_lower = current_event.get("summary", "").lower()
                    hems_mode = self._determine_mode_from_summary(summary_lower)
                    current_event["hems_mode"] = hems_mode
                    events.append(current_event)
                current_event = {}
            elif line.startswith("DTSTART"):
                # DTSTART:20260410T090000Z or DTSTART;VALUE=DATE:20260410
                dt_str = line.split(":", 1)[1]
                try:
                    if "T" in dt_str:
                        # ISO 8601 datetime
                        dt_str = dt_str.rstrip("Z")
                        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
                    else:
                        # DATE format
                        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
                    current_event["start"] = dt
                except ValueError:
                    pass

            elif line.startswith("DTEND"):
                dt_str = line.split(":", 1)[1]
                try:
                    if "T" in dt_str:
                        dt_str = dt_str.rstrip("Z")
                        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(dt_str).replace(tzinfo=timezone.utc)
                    current_event["end"] = dt
                except ValueError:
                    pass

            elif line.startswith("SUMMARY"):
                summary = line.split(":", 1)[1]
                current_event["summary"] = summary

        return events

    def _determine_mode_from_summary(self, summary_lower: str) -> str:
        """Determine HEMS mode from event summary keywords.

        Args:
            summary_lower: Event summary in lowercase

        Returns:
            One of: "away", "comfort", "boost", or None (no mode)
        """
        if any(
            keyword in summary_lower
            for keyword in ["away", "vacation", "holiday", "travel"]
        ):
            return "away"
        elif any(
            keyword in summary_lower for keyword in ["home office", "wfh", "homeoffice"]
        ):
            return "comfort"
        elif "boost" in summary_lower:
            return "boost"
        else:
            return None

    async def determine_mode_from_calendar(self) -> Optional[str]:
        """Determine target HEMS mode based on currently active events.

        Returns:
            Mode string: "away", "comfort", "boost", or None
        """
        active_events = await self.get_active_events()
        if not active_events:
            return None

        # Prefer "away" > "boost" > "comfort" > None
        modes = [e["hems_mode"] for e in active_events if e["hems_mode"]]
        if not modes:
            return None

        if "away" in modes:
            return "away"
        elif "boost" in modes:
            return "boost"
        elif "comfort" in modes:
            return "comfort"
        else:
            return modes[0]

    async def run_check_loop(
        self,
        check_interval_seconds: int = 300,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        """Run mode check loop every N seconds.

        Publishes to MQTT when mode changes.

        Args:
            check_interval_seconds: How often to check (default 300 = 5 min)
            stop_event: Event to signal loop termination
        """
        logger.info("Calendar mode switcher loop starting")

        while True:
            try:
                mode = await self.determine_mode_from_calendar()

                # Only publish if mode changed
                if mode != self._current_mode:
                    self._current_mode = mode
                    await self._publish_mode_to_mqtt(mode)
                    logger.info("HEMS mode switched to: %s", mode or "None")

            except Exception as e:
                logger.error("Error in calendar mode check: %s", e)

            # Wait for next check or stop signal
            if stop_event:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=check_interval_seconds,
                    )
                    break  # stop_event was set, exit loop
                except asyncio.TimeoutError:
                    pass  # Timeout is expected, continue loop
            else:
                await asyncio.sleep(check_interval_seconds)

    async def _publish_mode_to_mqtt(self, mode: Optional[str]) -> None:
        """Publish HEMS mode change to MQTT topic."""
        try:
            import paho.mqtt.publish as publish

            payload = json.dumps(
                {
                    "mode": mode,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "calendar",
                }
            )

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: publish.single(
                    "homelab/hems/mode",
                    payload=payload,
                    hostname=self.mqtt_host,
                    port=self.mqtt_port,
                    qos=1,
                    retain=False,
                ),
            )
            logger.debug("Published mode to MQTT: %s", mode)

        except Exception as e:
            logger.warning("Failed to publish mode to MQTT: %s", e)
