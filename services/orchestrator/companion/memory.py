"""Two-tier memory manager for Kairos: short-term (Redis) + medium-term (Postgres)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import asyncpg
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Two-layer memory system for Kairos:
    - Short-term: Redis list of recent messages (fast access, max 50 per session, 24h TTL)
    - Medium-term: Postgres companion.messages table (full history)

    Also manages sessions and user profiles in Postgres.
    """

    def __init__(self, pool: asyncpg.Pool, redis_url: str) -> None:
        """Initialize with Postgres pool and Redis URL."""
        self.pool = pool
        self.redis_url = redis_url
        self.redis_client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        try:
            self.redis_client = await redis.from_url(self.redis_url)
            await self.redis_client.ping()
            logger.info("memory_manager_redis_connected", url=self.redis_url)
        except Exception as e:
            logger.error("memory_manager_redis_connect_failed", error=str(e))
            raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self.redis_client:
            try:
                await self.redis_client.close()
                logger.info("memory_manager_redis_closed")
            except Exception as e:
                logger.error("memory_manager_redis_close_error", error=str(e))

    async def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Optional[list[dict[str, Any]]] = None,
        token_count: int = 0,
    ) -> str:
        """
        Save message to both Postgres and Redis short-term cache.

        Args:
            session_id: Session UUID (as string)
            role: "user" | "assistant" | "tool"
            content: Message text
            tool_calls: List of tool call dicts (optional)
            token_count: Token count for this message

        Returns:
            Message ID (UUID as string)
        """
        message_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        if tool_calls is None:
            tool_calls = []

        # Save to Postgres
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO companion.messages
                    (id, session_id, role, content, tool_calls, token_count, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    message_id,
                    session_id,
                    role,
                    content,
                    json.dumps(tool_calls),
                    token_count,
                    now,
                )
            logger.debug("message_saved_postgres", message_id=message_id)
        except Exception as e:
            logger.error("save_message_postgres_failed", error=str(e))
            raise

        # Save to Redis short-term list
        if self.redis_client:
            try:
                redis_key = f"kairos:session:{session_id}:messages"
                msg_obj = {
                    "id": message_id,
                    "role": role,
                    "content": content,
                    "tool_calls": tool_calls,
                    "created_at": now,
                }
                # LPUSH to add to front, LTRIM to keep last 50
                await self.redis_client.lpush(redis_key, json.dumps(msg_obj))
                await self.redis_client.ltrim(redis_key, 0, 49)
                # Reset TTL to 24 hours
                await self.redis_client.expire(redis_key, 86400)
                logger.debug("message_saved_redis", message_id=message_id)
            except Exception as e:
                logger.error("save_message_redis_failed", error=str(e))
                # Don't raise — Redis failure shouldn't block Postgres save

        return message_id

    async def get_recent_messages(
        self, session_id: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """
        Get recent messages, trying Redis first, falling back to Postgres.

        Args:
            session_id: Session UUID (as string)
            limit: Max messages to return

        Returns:
            List of {role, content, tool_calls, created_at} dicts
        """
        messages: list[dict[str, Any]] = []

        # Try Redis first (fast path)
        if self.redis_client:
            try:
                redis_key = f"kairos:session:{session_id}:messages"
                # LRANGE returns newest first (0 to limit-1)
                items = await self.redis_client.lrange(redis_key, 0, limit - 1)
                if items:
                    for item in items:
                        msg = json.loads(item)
                        messages.append(msg)
                    logger.debug(
                        "recent_messages_from_redis",
                        session_id=session_id,
                        count=len(messages),
                    )
                    return messages
            except Exception as e:
                logger.warning(
                    "recent_messages_redis_failed", session_id=session_id, error=str(e)
                )

        # Fallback to Postgres
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, role, content, tool_calls, created_at
                    FROM companion.messages
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    session_id,
                    limit,
                )
            for row in rows:
                messages.append(
                    {
                        "id": str(row["id"]),
                        "role": row["role"],
                        "content": row["content"],
                        "tool_calls": json.loads(row["tool_calls"]),
                        "created_at": row["created_at"].isoformat(),
                    }
                )
            # Reverse to get chronological order (query returns desc)
            messages.reverse()
            logger.debug(
                "recent_messages_from_postgres",
                session_id=session_id,
                count=len(messages),
            )
            return messages
        except Exception as e:
            logger.error("get_recent_messages_postgres_failed", error=str(e))
            return []

    async def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """Get session from Postgres."""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, user_id, title, metadata, created_at, updated_at
                    FROM companion.sessions
                    WHERE id = $1
                    """,
                    session_id,
                )
            if row:
                return {
                    "id": str(row["id"]),
                    "user_id": row["user_id"],
                    "title": row["title"],
                    "metadata": json.loads(row["metadata"]),
                    "created_at": row["created_at"].isoformat(),
                    "updated_at": row["updated_at"].isoformat(),
                }
            return None
        except Exception as e:
            logger.error("get_session_failed", session_id=session_id, error=str(e))
            return None

    async def create_session(
        self,
        user_id: str,
        title: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Create a new session, return session_id."""
        session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        if metadata is None:
            metadata = {}

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO companion.sessions
                    (id, user_id, title, metadata, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    session_id,
                    user_id,
                    title,
                    json.dumps(metadata),
                    now,
                    now,
                )
            logger.info("session_created", session_id=session_id, user_id=user_id)
            return session_id
        except Exception as e:
            logger.error("create_session_failed", user_id=user_id, error=str(e))
            raise

    async def update_profile(
        self,
        user_id: str,
        persona_notes: Optional[str] = None,
        preferences: Optional[dict[str, Any]] = None,
    ) -> None:
        """Upsert user profile (INSERT ... ON CONFLICT ... DO UPDATE)."""
        now = datetime.now(timezone.utc).isoformat()

        if persona_notes is None:
            persona_notes = ""
        if preferences is None:
            preferences = {}

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO companion.user_profiles
                    (user_id, persona_notes, preferences, updated_at)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id)
                    DO UPDATE SET
                        persona_notes = COALESCE($2, persona_notes),
                        preferences = COALESCE($3::jsonb, preferences),
                        updated_at = $4
                    """,
                    user_id,
                    persona_notes if persona_notes else None,
                    json.dumps(preferences) if preferences else None,
                    now,
                )
            logger.debug("profile_updated", user_id=user_id)
        except Exception as e:
            logger.error("update_profile_failed", user_id=user_id, error=str(e))
            raise

    async def get_profile(self, user_id: str) -> Optional[dict[str, Any]]:
        """Get user profile from Postgres."""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT user_id, persona_notes, preferences, updated_at
                    FROM companion.user_profiles
                    WHERE user_id = $1
                    """,
                    user_id,
                )
            if row:
                return {
                    "user_id": row["user_id"],
                    "persona_notes": row["persona_notes"],
                    "preferences": json.loads(row["preferences"]),
                    "updated_at": row["updated_at"].isoformat(),
                }
            return None
        except Exception as e:
            logger.error("get_profile_failed", user_id=user_id, error=str(e))
            return None
