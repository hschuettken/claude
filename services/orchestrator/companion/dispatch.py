"""Claude Code dispatch management for Kairos companion agent."""

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

import asyncpg

logger = logging.getLogger(__name__)


class DispatchManager:
    """
    Manages Claude Code dispatch records in companion.dispatches.

    Each dispatch represents a dev task delegated from Kairos to Claude Code.
    Status lifecycle: pending → running → success | failed | cancelled
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def create_dispatch(
        self,
        session_id: str,
        prompt_excerpt: str,
        branch: Optional[str] = None,
    ) -> str:
        """
        Create a dispatch record in companion.dispatches.

        Args:
            session_id: Parent companion session UUID (as string)
            prompt_excerpt: Short description of the dev task
            branch: Optional git branch name for the dispatch

        Returns:
            dispatch_id (UUID as string)
        """
        dispatch_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO companion.dispatches
                    (id, session_id, prompt_excerpt, branch, status, created_at)
                    VALUES ($1, $2, $3, $4, 'pending', $5)
                    """,
                    dispatch_id,
                    session_id,
                    prompt_excerpt,
                    branch,
                    now,
                )
            logger.info(
                "dispatch_created",
                dispatch_id=dispatch_id,
                session_id=session_id,
            )
            return dispatch_id
        except Exception as exc:
            logger.error(
                "create_dispatch_failed",
                session_id=session_id,
                error=str(exc),
            )
            raise

    async def get_dispatch(self, dispatch_id: str) -> Optional[dict[str, Any]]:
        """
        Fetch a dispatch record by ID.

        Returns:
            Dict with dispatch fields, or None if not found.
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id, session_id, prompt_excerpt, branch, worktree_path,
                           status, pr_url, token_used, created_at, completed_at
                    FROM companion.dispatches
                    WHERE id = $1
                    """,
                    dispatch_id,
                )
            if not row:
                return None
            return {
                "id": str(row["id"]),
                "session_id": str(row["session_id"]) if row["session_id"] else None,
                "prompt_excerpt": row["prompt_excerpt"],
                "branch": row["branch"],
                "worktree_path": row["worktree_path"],
                "status": row["status"],
                "pr_url": row["pr_url"],
                "token_used": row["token_used"],
                "created_at": row["created_at"].isoformat()
                if row["created_at"]
                else None,
                "completed_at": row["completed_at"].isoformat()
                if row["completed_at"]
                else None,
            }
        except Exception as exc:
            logger.error(
                "get_dispatch_failed",
                dispatch_id=dispatch_id,
                error=str(exc),
            )
            return None

    async def update_dispatch_status(
        self,
        dispatch_id: str,
        status: str,
        pr_url: Optional[str] = None,
        token_used: Optional[int] = None,
        completed: bool = False,
    ) -> None:
        """
        Update dispatch status and optional metadata fields.

        Args:
            dispatch_id: UUID of the dispatch (as string)
            status: New status ('pending'|'running'|'success'|'failed'|'cancelled')
            pr_url: URL of the pull request (if created)
            token_used: Token count consumed by Claude Code
            completed: If True, sets completed_at to now
        """
        now = datetime.now(timezone.utc).isoformat()
        completed_at = now if completed else None

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE companion.dispatches
                    SET
                        status       = $2,
                        pr_url       = COALESCE($3, pr_url),
                        token_used   = COALESCE($4, token_used),
                        completed_at = COALESCE($5::TIMESTAMPTZ, completed_at)
                    WHERE id = $1
                    """,
                    dispatch_id,
                    status,
                    pr_url,
                    token_used,
                    completed_at,
                )
            logger.info(
                "dispatch_status_updated",
                dispatch_id=dispatch_id,
                status=status,
                completed=completed,
            )
        except Exception as exc:
            logger.error(
                "update_dispatch_status_failed",
                dispatch_id=dispatch_id,
                error=str(exc),
            )
            raise

    async def list_dispatches(self, session_id: str) -> list[dict[str, Any]]:
        """
        List all dispatches for a session, newest first.

        Args:
            session_id: Session UUID (as string)

        Returns:
            List of dispatch dicts.
        """
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT id, session_id, prompt_excerpt, branch, worktree_path,
                           status, pr_url, token_used, created_at, completed_at
                    FROM companion.dispatches
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    """,
                    session_id,
                )
            result = []
            for row in rows:
                result.append(
                    {
                        "id": str(row["id"]),
                        "session_id": str(row["session_id"])
                        if row["session_id"]
                        else None,
                        "prompt_excerpt": row["prompt_excerpt"],
                        "branch": row["branch"],
                        "worktree_path": row["worktree_path"],
                        "status": row["status"],
                        "pr_url": row["pr_url"],
                        "token_used": row["token_used"],
                        "created_at": row["created_at"].isoformat()
                        if row["created_at"]
                        else None,
                        "completed_at": row["completed_at"].isoformat()
                        if row["completed_at"]
                        else None,
                    }
                )
            return result
        except Exception as exc:
            logger.error(
                "list_dispatches_failed",
                session_id=session_id,
                error=str(exc),
            )
            return []
