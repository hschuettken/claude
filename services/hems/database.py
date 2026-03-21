"""HEMS database access layer."""

from __future__ import annotations

import json
import logging
from datetime import datetime, time
from typing import Optional
from uuid import UUID

import asyncpg
from pydantic import BaseModel

logger = logging.getLogger("hems.database")


class ScheduleRecord(BaseModel):
    id: UUID
    room_id: str
    day_of_week: int
    start_time: time
    end_time: time
    target_temp: float
    mode: str
    active: bool
    created_at: datetime
    updated_at: datetime


class ConfigRecord(BaseModel):
    id: UUID
    key: str
    value: str
    updated_at: datetime


class AuditLogRecord(BaseModel):
    id: UUID
    timestamp: datetime
    action: str
    room_id: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    source: str
    details: Optional[str]


class HEMSDatabase:
    """Async PostgreSQL client for HEMS."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url
        self.pool: Optional[asyncpg.pool.Pool] = None

    async def init(self) -> None:
        """Initialize connection pool."""
        try:
            self.pool = await asyncpg.create_pool(
                self.db_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )
            logger.info("HEMS database pool initialized: %s", self.db_url)
        except Exception as e:
            logger.error("Failed to initialize database: %s", e)
            raise

    async def close(self) -> None:
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("HEMS database pool closed")

    async def get_current_schedule(self, room_id: str, dow: int, current_time: time) -> Optional[ScheduleRecord]:
        """Get the current active schedule for a room.

        Args:
            room_id: Room identifier (e.g., 'living_room')
            dow: Day of week (0=Monday, 6=Sunday)
            current_time: Current time of day

        Returns:
            ScheduleRecord if found, None otherwise
        """
        if not self.pool:
            logger.warning("Database pool not initialized")
            return None

        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(
                    """
                    SELECT id, room_id, day_of_week, start_time, end_time, target_temp, mode, active, created_at, updated_at
                    FROM public.hems_schedules
                    WHERE room_id = $1
                      AND day_of_week = $2
                      AND start_time <= $3
                      AND end_time > $3
                      AND active = true
                    ORDER BY start_time DESC
                    LIMIT 1
                    """,
                    room_id,
                    dow,
                    current_time,
                )
                if record:
                    return ScheduleRecord(
                        id=record["id"],
                        room_id=record["room_id"],
                        day_of_week=record["day_of_week"],
                        start_time=record["start_time"],
                        end_time=record["end_time"],
                        target_temp=float(record["target_temp"]),
                        mode=record["mode"],
                        active=record["active"],
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                    )
                return None
        except Exception as e:
            logger.error("Error fetching current schedule for %s: %s", room_id, e)
            return None

    async def get_schedule(self, schedule_id: UUID) -> Optional[ScheduleRecord]:
        """Fetch a single schedule by ID."""
        if not self.pool:
            return None

        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(
                    """
                    SELECT id, room_id, day_of_week, start_time, end_time, target_temp, mode, active, created_at, updated_at
                    FROM public.hems_schedules
                    WHERE id = $1
                    """,
                    schedule_id,
                )
                if record:
                    return ScheduleRecord(
                        id=record["id"],
                        room_id=record["room_id"],
                        day_of_week=record["day_of_week"],
                        start_time=record["start_time"],
                        end_time=record["end_time"],
                        target_temp=float(record["target_temp"]),
                        mode=record["mode"],
                        active=record["active"],
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                    )
                return None
        except Exception as e:
            logger.error("Error fetching schedule %s: %s", schedule_id, e)
            return None

    async def list_schedules(self, room_id: Optional[str] = None) -> list[ScheduleRecord]:
        """List all schedules, optionally filtered by room."""
        if not self.pool:
            return []

        try:
            async with self.pool.acquire() as conn:
                if room_id:
                    records = await conn.fetch(
                        """
                        SELECT id, room_id, day_of_week, start_time, end_time, target_temp, mode, active, created_at, updated_at
                        FROM public.hems_schedules
                        WHERE room_id = $1
                        ORDER BY day_of_week, start_time
                        """,
                        room_id,
                    )
                else:
                    records = await conn.fetch(
                        """
                        SELECT id, room_id, day_of_week, start_time, end_time, target_temp, mode, active, created_at, updated_at
                        FROM public.hems_schedules
                        ORDER BY room_id, day_of_week, start_time
                        """
                    )
                return [
                    ScheduleRecord(
                        id=r["id"],
                        room_id=r["room_id"],
                        day_of_week=r["day_of_week"],
                        start_time=r["start_time"],
                        end_time=r["end_time"],
                        target_temp=float(r["target_temp"]),
                        mode=r["mode"],
                        active=r["active"],
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                    )
                    for r in records
                ]
        except Exception as e:
            logger.error("Error listing schedules: %s", e)
            return []

    async def create_schedule(
        self,
        room_id: str,
        day_of_week: int,
        start_time: time,
        end_time: time,
        target_temp: float,
        mode: str,
        active: bool = True,
    ) -> Optional[ScheduleRecord]:
        """Create a new schedule."""
        if not self.pool:
            return None

        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchrow(
                    """
                    INSERT INTO public.hems_schedules
                    (room_id, day_of_week, start_time, end_time, target_temp, mode, active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id, room_id, day_of_week, start_time, end_time, target_temp, mode, active, created_at, updated_at
                    """,
                    room_id,
                    day_of_week,
                    start_time,
                    end_time,
                    target_temp,
                    mode,
                    active,
                )
                await self._audit_log(
                    conn,
                    action="schedule_created",
                    room_id=room_id,
                    new_value=json.dumps(
                        {
                            "room_id": room_id,
                            "day_of_week": day_of_week,
                            "start_time": str(start_time),
                            "end_time": str(end_time),
                            "target_temp": target_temp,
                            "mode": mode,
                        }
                    ),
                    source="api",
                )
                return ScheduleRecord(
                    id=record["id"],
                    room_id=record["room_id"],
                    day_of_week=record["day_of_week"],
                    start_time=record["start_time"],
                    end_time=record["end_time"],
                    target_temp=float(record["target_temp"]),
                    mode=record["mode"],
                    active=record["active"],
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                )
        except Exception as e:
            logger.error("Error creating schedule: %s", e)
            return None

    async def update_schedule(
        self,
        schedule_id: UUID,
        target_temp: Optional[float] = None,
        mode: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> Optional[ScheduleRecord]:
        """Update an existing schedule."""
        if not self.pool:
            return None

        try:
            async with self.pool.acquire() as conn:
                # Fetch old values for audit
                old_record = await conn.fetchrow(
                    "SELECT * FROM public.hems_schedules WHERE id = $1",
                    schedule_id,
                )
                if not old_record:
                    return None

                updates = []
                params = []
                param_idx = 1

                if target_temp is not None:
                    updates.append(f"target_temp = ${param_idx}")
                    params.append(target_temp)
                    param_idx += 1

                if mode is not None:
                    updates.append(f"mode = ${param_idx}")
                    params.append(mode)
                    param_idx += 1

                if active is not None:
                    updates.append(f"active = ${param_idx}")
                    params.append(active)
                    param_idx += 1

                if not updates:
                    return await self.get_schedule(schedule_id)

                updates.append(f"updated_at = NOW()")
                params.append(schedule_id)

                query = f"UPDATE public.hems_schedules SET {', '.join(updates)} WHERE id = ${param_idx} RETURNING id, room_id, day_of_week, start_time, end_time, target_temp, mode, active, created_at, updated_at"

                record = await conn.fetchrow(query, *params)

                # Log the change
                new_values = {}
                if target_temp is not None:
                    new_values["target_temp"] = target_temp
                if mode is not None:
                    new_values["mode"] = mode
                if active is not None:
                    new_values["active"] = active

                await self._audit_log(
                    conn,
                    action="schedule_updated",
                    room_id=old_record["room_id"],
                    old_value=json.dumps(
                        {
                            "target_temp": float(old_record["target_temp"]),
                            "mode": old_record["mode"],
                            "active": old_record["active"],
                        }
                    ),
                    new_value=json.dumps(new_values),
                    source="api",
                )

                return ScheduleRecord(
                    id=record["id"],
                    room_id=record["room_id"],
                    day_of_week=record["day_of_week"],
                    start_time=record["start_time"],
                    end_time=record["end_time"],
                    target_temp=float(record["target_temp"]),
                    mode=record["mode"],
                    active=record["active"],
                    created_at=record["created_at"],
                    updated_at=record["updated_at"],
                )
        except Exception as e:
            logger.error("Error updating schedule %s: %s", schedule_id, e)
            return None

    async def get_config(self, key: str) -> Optional[str]:
        """Get a config value."""
        if not self.pool:
            return None

        try:
            async with self.pool.acquire() as conn:
                record = await conn.fetchval(
                    "SELECT value FROM public.hems_config WHERE key = $1",
                    key,
                )
                return record
        except Exception as e:
            logger.error("Error fetching config %s: %s", key, e)
            return None

    async def set_config(self, key: str, value: str) -> bool:
        """Set or update a config value."""
        if not self.pool:
            return False

        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO public.hems_config (key, value) VALUES ($1, $2)
                    ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
                    """,
                    key,
                    value,
                )
                return True
        except Exception as e:
            logger.error("Error setting config %s: %s", key, e)
            return False

    async def log_audit(
        self,
        action: str,
        room_id: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        source: str = "api",
        details: Optional[str] = None,
    ) -> bool:
        """Log an audit event."""
        if not self.pool:
            return False

        try:
            async with self.pool.acquire() as conn:
                await self._audit_log(
                    conn,
                    action=action,
                    room_id=room_id,
                    old_value=old_value,
                    new_value=new_value,
                    source=source,
                    details=details,
                )
                return True
        except Exception as e:
            logger.error("Error logging audit event: %s", e)
            return False

    async def _audit_log(
        self,
        conn: asyncpg.Connection,
        action: str,
        room_id: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        source: str = "api",
        details: Optional[str] = None,
    ) -> None:
        """Internal helper to log an audit event within a transaction."""
        await conn.execute(
            """
            INSERT INTO public.hems_audit_log (action, room_id, old_value, new_value, source, details)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            action,
            room_id,
            old_value,
            new_value,
            source,
            details,
        )
