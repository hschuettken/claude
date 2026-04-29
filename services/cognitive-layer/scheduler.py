"""Asyncio background scheduler for Cognitive Layer automated tasks.

Fires jobs at wall-clock times without requiring APScheduler:

  02:00 daily  — thread maintenance (mark dormant, detect recurring)
  05:00 daily  — ingest_all (git + calendar + orbit)
  06:00 daily  — daily briefing generation
  22:00 daily  — daily reflection (end-of-day review)
  07:00 Monday — weekly reflection (drift detector)
  07:00 1st    — monthly reflection (momentum report)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

_DAILY_JOBS: list[tuple[int, int, str]] = [
    (2, 0, "maintenance"),
    (5, 0, "ingest"),
    (6, 0, "briefing"),
    (22, 0, "daily_reflection"),
]


class CognitiveScheduler:
    """Asyncio-native scheduler that fires jobs at fixed wall-clock times."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._fired: dict[str, date] = {}  # job_key → last fired date

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="cognitive-scheduler")
        logger.info("cognitive_scheduler_started")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("cognitive_scheduler_stopped")

    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as exc:
                logger.warning("cognitive_scheduler_tick_error error=%s", exc)
            await asyncio.sleep(60)

    async def _tick(self) -> None:
        now = datetime.now()
        today = now.date()
        h, m = now.hour, now.minute

        for job_h, job_m, job_key in _DAILY_JOBS:
            if h == job_h and m == job_m and self._fired.get(job_key) != today:
                self._fired[job_key] = today
                asyncio.create_task(self._run(job_key), name=f"cog-{job_key}")

        # Weekly: Monday 07:00
        if h == 7 and m == 0 and now.weekday() == 0:
            key = "weekly_reflection"
            if self._fired.get(key) != today:
                self._fired[key] = today
                asyncio.create_task(self._run(key), name=f"cog-{key}")

        # Monthly: 1st of month 07:00
        if h == 7 and m == 0 and today.day == 1:
            key = "monthly_reflection"
            if self._fired.get(key) != today:
                self._fired[key] = today
                asyncio.create_task(self._run(key), name=f"cog-{key}")

    async def _run(self, job_key: str) -> None:
        logger.info("cognitive_scheduler_job_start job=%s", job_key)
        try:
            if job_key == "maintenance":
                from . import continuity
                result = await continuity.run_maintenance()
                logger.info("cognitive_scheduler_maintenance result=%s", result)

            elif job_key == "ingest":
                from .ingestion import git_activity, calendar as cal_ingest, orbit as orbit_ingest
                for coro in [
                    git_activity.ingest_git_activity(since_days=1),
                    cal_ingest.ingest_calendar(days_ahead=7, days_behind=1),
                    orbit_ingest.ingest_orbit(days=1),
                ]:
                    try:
                        r = await coro
                        logger.info(
                            "cognitive_scheduler_ingest source=%s nodes=%d edges=%d errors=%d",
                            r.source, r.nodes_created, r.edges_created, len(r.errors),
                        )
                    except Exception as exc:
                        logger.warning("cognitive_scheduler_ingest_error error=%s", exc)

            elif job_key == "briefing":
                from . import briefing
                b = await briefing.generate_briefing()
                logger.info("cognitive_scheduler_briefing date=%s len=%d", b.date, len(b.narrative))

            elif job_key == "daily_reflection":
                from . import reflection
                r = await reflection.get_or_generate_daily()
                logger.info("cognitive_scheduler_daily_reflection period_start=%s", r.period_start)

            elif job_key == "weekly_reflection":
                from . import reflection
                r = await reflection.get_or_generate_weekly()
                logger.info("cognitive_scheduler_weekly_reflection period_start=%s", r.period_start)

            elif job_key == "monthly_reflection":
                from . import reflection
                now = datetime.now()
                r = await reflection.get_or_generate_monthly(now.year, now.month)
                logger.info("cognitive_scheduler_monthly_reflection period_start=%s", r.period_start)

        except Exception as exc:
            logger.error("cognitive_scheduler_job_error job=%s error=%s", job_key, exc)
