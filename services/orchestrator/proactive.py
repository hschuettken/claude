"""Proactive engine — scheduled suggestions, briefings, and anomaly alerts.

Runs periodic checks and uses the Brain to generate context-aware
notifications that are sent via the communication channels.

Features:
- Morning briefing (daily energy plan, weather, PV forecast)
- Evening summary (today's energy recap, savings)
- Periodic optimization suggestions (EV charging, appliance scheduling)
- Anomaly detection (unusual consumption, offline services)
"""

from __future__ import annotations

import asyncio
from datetime import date as date_type, datetime, time as dt_time, timedelta
from typing import TYPE_CHECKING, Any

from shared.log import get_logger

if TYPE_CHECKING:
    from brain import Brain
    from gcal import GoogleCalendarClient
    from channels.telegram import TelegramChannel
    from config import OrchestratorSettings

# Avoid circular import — ActivityTracker is injected at runtime

logger = get_logger("proactive")


MORNING_BRIEFING_PROMPT = """\
Generate a concise morning briefing for the household. Use the available tools to gather data, then produce a summary covering:

1. **Weather** — Today's conditions and temperature range
2. **PV Forecast** — Expected solar production today (kWh), comparison to a typical day
3. **Energy Plan** — Suggestions for today based on PV forecast:
   - Best hours for high-consumption appliances (dishwasher, washing machine)
   - EV charging recommendation (PV surplus vs grid)
   - Battery strategy
4. **Reminders** — Check user preferences for any regular activities today (sauna days, etc.)

Keep it brief and actionable. Use bullet points. Include specific numbers.
End with a friendly note appropriate for the time of day.
"""

EVENING_SUMMARY_PROMPT = """\
Generate a brief evening energy summary. Use tools to gather today's data:

1. **Today's PV Production** — How much solar energy was generated?
2. **Grid Usage** — Net import/export today
3. **Battery Status** — Current SoC
4. **EV Charging** — Session energy added today
5. **Cost/Savings** — Rough estimate of savings from PV self-consumption

Keep it concise. If it was a good solar day, celebrate it briefly.
"""

OPTIMIZATION_CHECK_PROMPT = """\
Analyze the current home energy state and identify any optimization opportunities.
Check:
1. Is there excess PV that could be used (EV charging, battery, appliances)?
2. Is the battery fully charged while still exporting to grid?
3. Is the EV plugged in but not charging during good PV production?
4. Are there any energy waste patterns?

Only report if you find actionable suggestions. If everything looks optimal, respond with exactly: "NO_SUGGESTIONS"
"""


class ProactiveEngine:
    """Scheduled proactive notifications and optimization suggestions."""

    def __init__(
        self,
        brain: Brain,
        telegram: TelegramChannel,
        settings: OrchestratorSettings,
        gcal: GoogleCalendarClient | None = None,
        ev_state: dict[str, Any] | None = None,
    ) -> None:
        self._brain = brain
        self._telegram = telegram
        self._settings = settings
        self._gcal = gcal
        self._ev_state = ev_state or {}
        self._tasks: list[asyncio.Task] = []
        self._last_morning_date: str = ""
        self._last_evening_date: str = ""
        self._last_consolidation_date: str = ""
        # Track calendar events created for EV charging: {date_str: {event_id, summary}}
        self._ev_events: dict[str, dict[str, str]] = {}

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """Start all proactive background tasks."""
        if self._settings.enable_morning_briefing or self._settings.enable_evening_briefing:
            self._tasks.append(
                asyncio.create_task(self._briefing_scheduler(shutdown_event))
            )

        if self._settings.enable_proactive_suggestions:
            self._tasks.append(
                asyncio.create_task(self._optimization_loop(shutdown_event))
            )

        if self._settings.enable_semantic_memory:
            self._tasks.append(
                asyncio.create_task(self._memory_consolidation_loop(shutdown_event))
            )

        logger.info(
            "proactive_started",
            morning=self._settings.enable_morning_briefing,
            evening=self._settings.enable_evening_briefing,
            suggestions=self._settings.enable_proactive_suggestions,
        )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    # ------------------------------------------------------------------
    # Briefing scheduler
    # ------------------------------------------------------------------

    async def _briefing_scheduler(self, shutdown_event: asyncio.Event) -> None:
        """Check once per minute if it's time for a briefing."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(self._settings.timezone)

        while not shutdown_event.is_set():
            try:
                now = datetime.now(tz)
                today_str = now.strftime("%Y-%m-%d")
                current_time = now.strftime("%H:%M")

                # Morning briefing
                if (
                    self._settings.enable_morning_briefing
                    and current_time == self._settings.morning_briefing_time
                    and self._last_morning_date != today_str
                ):
                    self._last_morning_date = today_str
                    await self._send_briefing(MORNING_BRIEFING_PROMPT)

                # Evening briefing
                if (
                    self._settings.enable_evening_briefing
                    and current_time == self._settings.evening_briefing_time
                    and self._last_evening_date != today_str
                ):
                    self._last_evening_date = today_str
                    await self._send_briefing(EVENING_SUMMARY_PROMPT)

            except Exception:
                logger.exception("briefing_scheduler_error")

            # Check every 60 seconds
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=60)
                break
            except asyncio.TimeoutError:
                pass

    async def _send_briefing(self, prompt: str) -> None:
        """Generate a briefing and send to all allowed chats."""
        logger.info("generating_briefing")
        try:
            message = await self._brain.generate_proactive_message(prompt)
            for chat_id in self._settings.allowed_chat_ids:
                await self._telegram.send_message(chat_id, message)
            if self._activity_tracker:
                self._activity_tracker.record_suggestion(message)
            logger.info("briefing_sent", recipients=len(self._settings.allowed_chat_ids))
        except Exception:
            logger.exception("briefing_failed")

    # ------------------------------------------------------------------
    # Optimization loop
    # ------------------------------------------------------------------

    async def _optimization_loop(self, shutdown_event: asyncio.Event) -> None:
        """Periodically check for energy optimization opportunities."""
        interval = self._settings.proactive_check_interval_minutes * 60

        # Initial delay — don't fire immediately on startup
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=120)
            return
        except asyncio.TimeoutError:
            pass

        while not shutdown_event.is_set():
            try:
                message = await self._brain.generate_proactive_message(
                    OPTIMIZATION_CHECK_PROMPT
                )
                # Only send if there are actual suggestions
                if message and "NO_SUGGESTIONS" not in message:
                    for chat_id in self._settings.allowed_chat_ids:
                        await self._telegram.send_message(chat_id, message)
                    if self._activity_tracker:
                        self._activity_tracker.record_suggestion(message)
                    logger.info("optimization_suggestion_sent")
                else:
                    logger.debug("no_optimization_suggestions")
            except Exception:
                logger.exception("optimization_check_error")

            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # Memory consolidation (nightly)
    # ------------------------------------------------------------------

    async def _memory_consolidation_loop(
        self, shutdown_event: asyncio.Event,
    ) -> None:
        """Run memory consolidation once per day at 3 AM."""
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(self._settings.timezone)

        # Initial delay — let the service stabilize
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=300)
            return
        except asyncio.TimeoutError:
            pass

        while not shutdown_event.is_set():
            try:
                now = datetime.now(tz)
                today_str = now.strftime("%Y-%m-%d")

                # Run at 3 AM, once per day
                if now.hour == 3 and self._last_consolidation_date != today_str:
                    self._last_consolidation_date = today_str
                    logger.info("memory_consolidation_starting")
                    merged = await self._brain.consolidate_memories()
                    logger.info("memory_consolidation_done", merged=merged)
            except Exception:
                logger.exception("memory_consolidation_error")

            # Check every 10 minutes
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=600)
                break
            except asyncio.TimeoutError:
                pass

    # ------------------------------------------------------------------
    # EV forecast integration
    # ------------------------------------------------------------------

    async def on_ev_plan_update(self, plan_data: dict[str, Any]) -> None:
        """Create/update calendar events for significant EV charging needs.

        Called when the ev-forecast service publishes a new plan via MQTT.
        Creates all-day events on the orchestrator calendar so the household
        can see upcoming charging requirements.
        """
        if not self._gcal or not self._settings.google_calendar_orchestrator_id:
            return

        cal_id = self._settings.google_calendar_orchestrator_id
        days = plan_data.get("days", [])
        active_dates: set[str] = set()

        for day in days:
            date_str = day.get("date", "")
            urgency = day.get("urgency", "none")
            charge_kwh = day.get("energy_to_charge_kwh", 0)

            # Only create events for days that actually need charging
            if urgency == "none" or charge_kwh <= 0:
                continue

            active_dates.add(date_str)

            # Build summary
            trips = day.get("trips", [])
            trip_parts = [f"{t['person']} \u2192 {t['destination']}" for t in trips]
            departure = day.get("departure_time")

            summary = f"EV: {charge_kwh:.0f} kWh laden"
            if departure:
                summary += f" bis {departure}"
            if trip_parts:
                summary += f" ({', '.join(trip_parts)})"

            # Skip if event already exists with the same summary
            existing = self._ev_events.get(date_str, {})
            if existing.get("summary") == summary:
                continue

            # Delete old event if exists (plan changed)
            if existing.get("event_id"):
                try:
                    await self._gcal.delete_event(cal_id, existing["event_id"])
                except Exception:
                    pass

            # Create new all-day event
            try:
                d = date_type.fromisoformat(date_str)
                next_day = (d + timedelta(days=1)).isoformat()

                description = (
                    f"Lademodus: {day.get('charge_mode', '?')}\n"
                    f"Dringlichkeit: {urgency}\n"
                    f"Energiebedarf Fahrten: {day.get('energy_needed_kwh', 0):.1f} kWh\n"
                    f"Zu laden: {charge_kwh:.1f} kWh\n"
                    f"Grund: {day.get('reason', '')}\n\n"
                    f"Automatisch erstellt vom EV Forecast Service."
                )

                event = await self._gcal.create_event(
                    calendar_id=cal_id,
                    summary=summary,
                    start=date_str,
                    end=next_day,
                    description=description,
                    all_day=True,
                )
                self._ev_events[date_str] = {
                    "event_id": event.get("id", ""),
                    "summary": summary,
                }
                logger.info("ev_calendar_event_created", date=date_str, summary=summary)
            except Exception:
                logger.exception("ev_calendar_event_failed", date=date_str)

        # Clean up events for dates no longer needing charging
        for date_str in list(self._ev_events):
            if date_str not in active_dates:
                existing = self._ev_events.pop(date_str, {})
                if existing.get("event_id"):
                    try:
                        await self._gcal.delete_event(cal_id, existing["event_id"])
                        logger.info("ev_calendar_event_removed", date=date_str)
                    except Exception:
                        pass

    async def on_ev_clarification_needed(
        self, clarifications: list[dict[str, Any]],
    ) -> None:
        """Forward EV trip clarification questions to users via Telegram.

        The ev-forecast service sends these when it can't determine if someone
        will use the EV (e.g., Hans for medium-distance trips). The user's
        response is processed by the Brain, which calls the
        respond_to_ev_trip_clarification tool.
        """
        for c in clarifications:
            question = c.get("question", "")
            if not question:
                continue

            message = (
                f"\U0001f697 *EV-Planer braucht eine Antwort:*\n\n"
                f"{question}\n\n"
                f"_Antworte einfach in diesem Chat._"
            )

            for chat_id in self._settings.allowed_chat_ids:
                try:
                    await self._telegram.send_message(chat_id, message)
                except Exception:
                    logger.exception(
                        "ev_clarification_send_failed", chat_id=chat_id,
                    )

            logger.info(
                "ev_clarification_sent",
                person=c.get("person"),
                destination=c.get("destination"),
                date=c.get("date"),
            )
