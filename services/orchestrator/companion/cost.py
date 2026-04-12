"""Daily token budget tracker for Kairos companion agent using Redis."""

import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Redis key templates
_DAILY_KEY = "kairos:tokens:daily:{user_id}:{date}"
_SESSION_KEY = "kairos:tokens:session:{session_id}"

_DAILY_TTL = 60 * 60 * 48  # 48 hours
_SESSION_TTL = 60 * 60 * 24  # 24 hours


class CostStatus(BaseModel):
    daily_tokens: int
    session_tokens: int
    daily_cap: int
    pct_used: float
    warning: bool  # True if >= warning_pct
    capped: bool  # True if >= 100%


class CostTracker:
    """Tracks daily and per-session token budgets in Redis.

    Uses today's UTC date as part of daily keys so counters auto-expire.
    All Redis errors are non-fatal — errors are logged and a safe default is returned.
    """

    def __init__(
        self,
        redis_client: Any,  # redis.asyncio client
        daily_cap: int = 500_000,
        warning_pct: float = 0.80,
    ) -> None:
        self._redis = redis_client
        self._daily_cap = daily_cap
        self._warning_pct = warning_pct

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _daily_key(self, user_id: str) -> str:
        return _DAILY_KEY.format(user_id=user_id, date=self._today())

    @staticmethod
    def _session_key(session_id: str) -> str:
        return _SESSION_KEY.format(session_id=session_id)

    async def record(self, user_id: str, session_id: str, tokens: int) -> CostStatus:
        """Increment daily and session counters. Return CostStatus."""
        daily_key = self._daily_key(user_id)
        session_key = self._session_key(session_id)

        daily_tokens = 0
        session_tokens = 0

        try:
            pipe = self._redis.pipeline()
            pipe.incrby(daily_key, tokens)
            pipe.expire(daily_key, _DAILY_TTL)
            pipe.incrby(session_key, tokens)
            pipe.expire(session_key, _SESSION_TTL)
            results = await pipe.execute()
            daily_tokens = int(results[0])
            session_tokens = int(results[2])
        except Exception as exc:
            logger.warning(
                "cost_tracker_record_failed",
                user_id=user_id,
                session_id=session_id,
                error=str(exc),
            )

        pct_used = (daily_tokens / self._daily_cap) if self._daily_cap > 0 else 0.0
        return CostStatus(
            daily_tokens=daily_tokens,
            session_tokens=session_tokens,
            daily_cap=self._daily_cap,
            pct_used=pct_used,
            warning=pct_used >= self._warning_pct,
            capped=daily_tokens >= self._daily_cap,
        )

    async def get_daily_usage(self, user_id: str) -> int:
        """Get today's token count for user_id."""
        try:
            val = await self._redis.get(self._daily_key(user_id))
            return int(val) if val is not None else 0
        except Exception as exc:
            logger.warning(
                "cost_tracker_get_daily_usage_failed",
                user_id=user_id,
                error=str(exc),
            )
            return 0

    async def get_session_usage(self, session_id: str) -> int:
        """Get token count for session."""
        try:
            val = await self._redis.get(self._session_key(session_id))
            return int(val) if val is not None else 0
        except Exception as exc:
            logger.warning(
                "cost_tracker_get_session_usage_failed",
                session_id=session_id,
                error=str(exc),
            )
            return 0

    async def is_cap_reached(self, user_id: str) -> bool:
        """True if daily cap is hit."""
        daily = await self.get_daily_usage(user_id)
        return daily >= self._daily_cap
