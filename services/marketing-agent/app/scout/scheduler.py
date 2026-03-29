"""APScheduler-based Scout Engine job scheduler."""

import logging
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio
import hashlib
import json
from pathlib import Path

import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select, desc
from pydantic import BaseModel

from models import Signal, SignalStatus
from app.scout.searxng_client import SearXNGClient, SearchResult
from app.scout.scorer import score_signal
from events import publish_signal_detected

logger = logging.getLogger(__name__)


class SearchProfile(BaseModel):
    """Search profile configuration."""
    id: str
    name: str
    queries: List[str]
    engines: List[str]
    pillar: int  # 1-6
    interval_hours: int


def load_profiles(config_path: Optional[str] = None) -> List[SearchProfile]:
    """
    Load search profiles from YAML config file.
    
    Args:
        config_path: Path to profiles.yaml (default: adjacent to this module)
    
    Returns:
        List of SearchProfile objects
    """
    if config_path is None:
        module_dir = Path(__file__).parent
        config_path = module_dir / "profiles.yaml"
    
    try:
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)
        
        profiles = []
        for profile_data in data.get("profiles", []):
            profile = SearchProfile(**profile_data)
            profiles.append(profile)
        
        logger.info(f"Loaded {len(profiles)} search profiles from {config_path}")
        return profiles
    except Exception as e:
        logger.error(f"Failed to load profiles from {config_path}: {e}")
        return []


async def run_scout_profile(
    profile: SearchProfile,
    db_session: AsyncSession,
    searxng_client: SearXNGClient,
) -> Dict[str, Any]:
    """
    Execute a single scout profile: search queries and ingest results.
    
    Args:
        profile: SearchProfile to run
        db_session: Database session for inserting signals
        searxng_client: SearXNG client instance
    
    Returns:
        Dict with execution stats: found, inserted, duplicates, errors
    """
    results_found = 0
    new_signals = 0
    duplicates_skipped = 0
    errors = 0
    
    logger.info(f"🔍 Scout: Running profile '{profile.name}' (pillar {profile.pillar})")
    
    # Track URLs found in this run to avoid in-run duplication
    seen_urls = set()
    
    for query in profile.queries:
        try:
            # Execute search
            search_results = await searxng_client.search(
                query=query,
                engines=profile.engines,
                max_results=15,
                language="en",
            )
            results_found += len(search_results)
            logger.debug(f"  Query '{query}': {len(search_results)} results")
            
            # Process each result
            for result in search_results:
                try:
                    # Check in-run duplication
                    if result.url in seen_urls:
                        logger.debug(f"    Duplicate (in-run): {result.url}")
                        continue
                    
                    seen_urls.add(result.url)
                    
                    # Check database duplication
                    url_hash = hashlib.sha256(result.url.encode()).hexdigest()
                    existing = await db_session.execute(
                        select(Signal).where(Signal.url_hash == url_hash)
                    )
                    if existing.scalar_one_or_none():
                        logger.debug(f"    Duplicate (DB): {result.url}")
                        duplicates_skipped += 1
                        continue
                    
                    # Score the result
                    relevance = score_signal(result, pillar_id=profile.pillar)
                    
                    # Extract source domain
                    from urllib.parse import urlparse
                    parsed = urlparse(result.url)
                    domain = parsed.netloc or "unknown"
                    
                    # Create signal
                    signal = Signal(
                        title=result.title,
                        url=result.url,
                        snippet=result.content,
                        source_domain=domain,
                        source="scout",
                        relevance_score=relevance,
                        pillar_id=profile.pillar,
                        status=SignalStatus.new,
                        url_hash=url_hash,
                        search_profile_id=profile.id,
                        raw_json=result.model_dump(),
                        detected_at=datetime.utcnow(),
                    )
                    
                    db_session.add(signal)
                    new_signals += 1
                    
                    logger.debug(
                        f"    📌 New signal: {result.title[:60]}... "
                        f"(score: {relevance:.2f}, url: {result.url[:50]})"
                    )
                
                except Exception as e:
                    logger.error(f"    Error processing result: {e}", exc_info=True)
                    errors += 1
                    continue
        
        except asyncio.TimeoutError:
            logger.warning(f"  Query '{query}': Timeout (SearXNG did not respond in time)")
            errors += 1
        except Exception as e:
            logger.warning(f"  Query '{query}': Error: {e}")
            errors += 1
            continue
    
    # Commit all signals for this profile
    try:
        await db_session.commit()
        logger.info(
            f"✅ Profile '{profile.name}': "
            f"found={results_found}, new={new_signals}, dups={duplicates_skipped}, "
            f"errors={errors}"
        )
    except Exception as e:
        logger.error(f"Failed to commit signals for profile '{profile.name}': {e}")
        await db_session.rollback()
    
    # Publish NATS events for new signals (best-effort)
    for _ in range(new_signals):
        try:
            await publish_signal_detected(
                source="scout",
                topic=profile.name,
                score=0.5,  # Would need to track individual scores
                metadata={"profile_id": profile.id, "pillar_id": profile.pillar},
            )
        except Exception as e:
            logger.warning(f"Failed to publish signal event: {e}")
    
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "found": results_found,
        "inserted": new_signals,
        "duplicates": duplicates_skipped,
        "errors": errors,
        "timestamp": datetime.utcnow().isoformat(),
    }


class ScoutScheduler:
    """
    Manages APScheduler jobs for Scout Engine profiles.
    
    Starts in FastAPI lifespan, one job per profile with configured interval.
    """
    
    def __init__(
        self,
        db_url: str,
        searxng_url: str = "http://192.168.0.84:8080",
        profiles: Optional[List[SearchProfile]] = None,
    ):
        """
        Initialize Scout scheduler.
        
        Args:
            db_url: Database URL for AsyncSession
            searxng_url: SearXNG base URL
            profiles: List of SearchProfile objects (default: load from YAML)
        """
        self.db_url = db_url
        self.searxng_url = searxng_url
        self.profiles = profiles or load_profiles()
        self.scheduler = AsyncIOScheduler()
        self.searxng_client = SearXNGClient(base_url=searxng_url)
        self.engine = None
        self.session_maker = None
        self.last_runs: Dict[str, datetime] = {}
        self._started = False
    
    async def start(self):
        """Start the scheduler and register jobs."""
        if self._started:
            logger.warning("Scout scheduler already started")
            return
        
        # Check SearXNG health
        is_healthy = await self.searxng_client.health_check()
        if not is_healthy:
            logger.error("SearXNG is not responding — Scout disabled")
            return
        
        logger.info(f"✅ SearXNG health check passed ({self.searxng_url})")
        
        # Set up database
        self.engine = create_async_engine(self.db_url, echo=False)
        self.session_maker = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        
        # Register job for each profile
        for profile in self.profiles:
            job_id = f"scout_{profile.id}"
            
            # Wrap the runner to inject DB session
            async def run_profile(prof=profile):
                async with self.session_maker() as session:
                    return await run_scout_profile(prof, session, self.searxng_client)
            
            # Add job with interval trigger
            trigger = IntervalTrigger(hours=profile.interval_hours)
            self.scheduler.add_job(
                run_profile,
                trigger=trigger,
                id=job_id,
                name=f"Scout: {profile.name}",
                replace_existing=True,
            )
            
            logger.info(f"  📅 Job '{job_id}' scheduled every {profile.interval_hours} hour(s)")
        
        # Start scheduler
        self.scheduler.start()
        self._started = True
        logger.info(f"🚀 Scout scheduler started with {len(self.profiles)} profiles")
    
    async def stop(self):
        """Stop the scheduler gracefully."""
        if not self._started:
            return
        
        self.scheduler.shutdown(wait=True)
        
        if self.engine:
            await self.engine.dispose()
        
        self._started = False
        logger.info("Scout scheduler stopped")
    
    async def refresh_all(self) -> Dict[str, Any]:
        """
        Trigger immediate run of all profiles (manual refresh).
        
        Returns:
            Dict with job IDs and status
        """
        if not self._started:
            raise RuntimeError("Scout scheduler not started")
        
        logger.info("🔄 Manual Scout refresh triggered")
        
        results = []
        for profile in self.profiles:
            try:
                async with self.session_maker() as session:
                    result = await run_scout_profile(
                        profile, session, self.searxng_client
                    )
                    results.append(result)
            except Exception as e:
                logger.error(f"Error running profile '{profile.id}': {e}", exc_info=True)
                results.append({
                    "profile_id": profile.id,
                    "error": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                })
        
        return {"profiles_run": len(results), "results": results}
    
    async def get_status(self) -> Dict[str, Any]:
        """
        Get current scheduler status.
        
        Returns:
            Dict with profiles, last runs, and signal counts
        """
        profiles_info = []
        
        for profile in self.profiles:
            job_id = f"scout_{profile.id}"
            job = self.scheduler.get_job(job_id)
            
            profiles_info.append({
                "id": profile.id,
                "name": profile.name,
                "interval_hours": profile.interval_hours,
                "pillar": profile.pillar,
                "job_id": job_id,
                "next_run_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
                "last_run": self.last_runs.get(profile.id, {}).get("timestamp"),
            })
        
        # Get signal count from DB
        total_signals = 0
        today_signals = 0
        try:
            async with self.session_maker() as session:
                # Total signals
                result = await session.execute(
                    select(Signal).where(Signal.source == "scout")
                )
                total_signals = len(result.scalars().all())
                
                # Signals from today
                from datetime import timedelta
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                result = await session.execute(
                    select(Signal).where(
                        (Signal.source == "scout") & (Signal.detected_at >= today_start)
                    )
                )
                today_signals = len(result.scalars().all())
        except Exception as e:
            logger.warning(f"Failed to get signal counts: {e}")
        
        return {
            "running": self._started,
            "profiles": profiles_info,
            "total_signals": total_signals,
            "signals_today": today_signals,
            "searxng_url": self.searxng_url,
        }


# Global scheduler singleton
_scheduler_instance = None


def set_scheduler(scheduler) -> None:
    """Register the global ScoutScheduler instance."""
    global _scheduler_instance
    _scheduler_instance = scheduler


def get_scheduler():
    """Get the global ScoutScheduler instance."""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = ScoutScheduler()
    return _scheduler_instance
