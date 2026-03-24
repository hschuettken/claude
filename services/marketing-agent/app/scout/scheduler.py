"""APScheduler-based job scheduler for Scout Engine."""

import hashlib
import json
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from app.scout.events import get_nats_publisher
from app.scout.profiles import get_default_profiles
from app.scout.scorer import score_signal
from app.scout.searxng_client import SearXNGClient
from database import SessionLocal
from models import Signal

logger = logging.getLogger(__name__)


class ScoutScheduler:
    """Manages scheduled search jobs for all profiles."""

    def __init__(self, searxng_url: str = "http://192.168.0.84:8080"):
        self.scheduler = AsyncIOScheduler()
        self.searxng_client = SearXNGClient(base_url=searxng_url)
        self.search_client_initialized = False
        self.is_running = False
        self.last_run_info = {}
        self.dedup_window_days = 30  # Skip URLs seen in last 30 days

    async def start(self):
        """Start the scheduler."""
        if self.is_running:
            logger.warning("Scheduler already running")
            return

        # Check SearXNG health
        health = await self.searxng_client.health_check()
        if not health:
            logger.error("SearXNG health check failed, scheduler startup aborted")
            return

        self.search_client_initialized = True

        # Add jobs for each profile
        profiles = get_default_profiles()
        for profile in profiles:
            job_id = f"scout_{profile.id}"
            logger.info(f"Scheduling profile '{profile.name}' with interval {profile.interval_hours}h")

            self.scheduler.add_job(
                self.run_profile,
                "interval",
                hours=profile.interval_hours,
                id=job_id,
                args=[profile],
                name=f"Scout: {profile.name}",
                coalesce=True,
                max_instances=1,
            )

        self.scheduler.start()
        self.is_running = True
        logger.info("Scout scheduler started")

    async def stop(self):
        """Stop the scheduler."""
        if self.is_running:
            self.scheduler.shutdown(wait=True)
            self.is_running = False
            await self.searxng_client.close()
            logger.info("Scout scheduler stopped")

    async def run_profile(self, profile):
        """Execute a single search profile."""
        logger.info(f"Running profile: {profile.name}")

        db = SessionLocal()
        signals_inserted = 0
        signals_skipped = 0
        results_total = 0

        try:
            for query in profile.queries:
                logger.debug(f"Searching: {query}")

                # Execute search
                results = await self.searxng_client.search(
                    query,
                    engines=profile.engines,
                    max_results=10,
                )
                results_total += len(results)

                # Deduplicate and insert
                for result in results:
                    # Compute URL hash
                    url_hash = hashlib.sha256(result.url.encode()).hexdigest()

                    # Check for existing signal (within last 30 days)
                    cutoff_date = datetime.utcnow() - timedelta(days=self.dedup_window_days)
                    existing = (
                        db.query(Signal)
                        .filter(Signal.url_hash == url_hash)
                        .filter(Signal.created_at >= cutoff_date)
                        .first()
                    )
                    if existing:
                        logger.debug(f"Signal already exists (recent): {result.url}")
                        signals_skipped += 1
                        continue

                    # Score the signal
                    score = score_signal(
                        title=result.title,
                        snippet=result.snippet,
                        url=result.url,
                        pillar_id=profile.pillar_id,
                    )

                    # Create signal
                    signal = Signal(
                        title=result.title,
                        url=result.url,
                        source=result.engine,
                        source_domain=self._extract_domain(result.url),
                        snippet=result.snippet,
                        relevance_score=score,
                        pillar_id=profile.pillar_id,
                        search_profile_id=profile.id,
                        url_hash=url_hash,
                        status="new",
                        raw_json=json.dumps(
                            {
                                "title": result.title,
                                "url": result.url,
                                "snippet": result.snippet,
                                "engine": result.engine,
                            }
                        ),
                        detected_at=datetime.utcnow(),
                    )

                    db.add(signal)
                    db.flush()  # Get the ID
                    db.commit()

                    signals_inserted += 1

                    # Publish NATS event for high-relevance signals (>= 0.7)
                    if signal.relevance_score >= 0.7:
                        try:
                            nats_pub = get_nats_publisher()
                            await nats_pub.publish_signal_detected(
                                signal_id=signal.id,
                                title=signal.title,
                                url=signal.url,
                                pillar_id=signal.pillar_id,
                                relevance_score=signal.relevance_score,
                                detected_at=signal.detected_at,
                            )
                        except Exception as e:
                            logger.warning(f"Failed to publish NATS event: {e}")

            # Record run info
            self.last_run_info[profile.id] = {
                "profile_name": profile.name,
                "run_at": datetime.utcnow().isoformat(),
                "results_found": results_total,
                "signals_inserted": signals_inserted,
                "signals_skipped": signals_skipped,
            }

            logger.info(
                f"Profile '{profile.name}' completed: "
                f"{results_total} results, {signals_inserted} new signals, {signals_skipped} duplicates"
            )

        except Exception as e:
            logger.error(f"Error running profile {profile.id}: {e}", exc_info=True)
        finally:
            db.close()

    async def trigger_refresh(self) -> dict:
        """Manually trigger refresh of all profiles."""
        logger.info("Manual refresh triggered")

        profiles = get_default_profiles()
        for profile in profiles:
            await self.run_profile(profile)

        return {
            "job_id": "manual-refresh",
            "profiles_queued": len(profiles),
            "run_info": self.last_run_info,
        }

    def get_status(self) -> dict:
        """Get scheduler status."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                }
            )

        return {
            "running": self.is_running,
            "searxng_initialized": self.search_client_initialized,
            "jobs": jobs,
            "last_runs": self.last_run_info,
        }

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL."""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = parsed.netloc or parsed.path.split("/")[0]
            return domain
        except Exception:
            return "unknown"


# Global scheduler instance
_scheduler: ScoutScheduler | None = None


def get_scheduler() -> ScoutScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = ScoutScheduler()
    return _scheduler
