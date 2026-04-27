"""Room registry CRUD operations backed by PostgreSQL."""
from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

from . import db
from .models import RoomCreate, RoomResponse, RoomUpdate

logger = logging.getLogger(__name__)

# Default room registry loaded when DB is empty or unavailable
DEFAULT_ROOMS: list[dict] = [
    {
        "room_id": "living_room",
        "name": "Living Room",
        "floor": "ground",
        "area_m2": 35.0,
        "ha_temperature_entity": "sensor.temperature_living_room",
        "ha_humidity_entity": "sensor.humidity_living_room",
        "ha_occupancy_entity": None,
        "ha_heating_entity": "climate.living_room",
        "extra_entities": [],
        "metadata": {},
    },
    {
        "room_id": "kitchen",
        "name": "Kitchen",
        "floor": "ground",
        "area_m2": 18.0,
        "ha_temperature_entity": "sensor.temperature_kitchen",
        "ha_humidity_entity": None,
        "ha_occupancy_entity": None,
        "ha_heating_entity": "climate.kitchen",
        "extra_entities": [],
        "metadata": {},
    },
    {
        "room_id": "bedroom_master",
        "name": "Master Bedroom",
        "floor": "upper",
        "area_m2": 22.0,
        "ha_temperature_entity": "sensor.temperature_bedroom",
        "ha_humidity_entity": "sensor.humidity_bedroom",
        "ha_occupancy_entity": None,
        "ha_heating_entity": "climate.bedroom",
        "extra_entities": [],
        "metadata": {},
    },
    {
        "room_id": "office",
        "name": "Home Office",
        "floor": "upper",
        "area_m2": 14.0,
        "ha_temperature_entity": "sensor.temperature_office",
        "ha_humidity_entity": None,
        "ha_occupancy_entity": "binary_sensor.office_motion",
        "ha_heating_entity": "climate.office",
        "extra_entities": [],
        "metadata": {},
    },
    {
        "room_id": "garage",
        "name": "Garage",
        "floor": "ground",
        "area_m2": 28.0,
        "ha_temperature_entity": None,
        "ha_humidity_entity": None,
        "ha_occupancy_entity": None,
        "ha_heating_entity": None,
        "extra_entities": ["sensor.amtron_meter_total_power_w"],
        "metadata": {"contains_ev_charger": True},
    },
]


def _row_to_response(row: dict) -> RoomResponse:
    extra = row.get("extra_entities", [])
    if isinstance(extra, str):
        extra = json.loads(extra)
    meta = row.get("metadata", {})
    if isinstance(meta, str):
        meta = json.loads(meta)
    return RoomResponse(
        id=row["id"],
        room_id=row["room_id"],
        name=row["name"],
        floor=row.get("floor"),
        area_m2=row.get("area_m2"),
        ha_temperature_entity=row.get("ha_temperature_entity"),
        ha_humidity_entity=row.get("ha_humidity_entity"),
        ha_occupancy_entity=row.get("ha_occupancy_entity"),
        ha_heating_entity=row.get("ha_heating_entity"),
        extra_entities=list(extra),
        metadata=dict(meta),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def seed_defaults_if_empty() -> None:
    """Insert default rooms if the table is empty."""
    rows = await db.fetch("SELECT 1 FROM dt_rooms LIMIT 1")
    if rows:
        return
    for r in DEFAULT_ROOMS:
        try:
            await db.execute(
                """
                INSERT INTO dt_rooms
                    (room_id, name, floor, area_m2,
                     ha_temperature_entity, ha_humidity_entity,
                     ha_occupancy_entity, ha_heating_entity,
                     extra_entities, metadata)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb)
                ON CONFLICT (room_id) DO NOTHING
                """,
                r["room_id"], r["name"], r.get("floor"), r.get("area_m2"),
                r.get("ha_temperature_entity"), r.get("ha_humidity_entity"),
                r.get("ha_occupancy_entity"), r.get("ha_heating_entity"),
                json.dumps(r["extra_entities"]), json.dumps(r["metadata"]),
            )
        except Exception as exc:
            logger.warning("room_seed_failed room_id=%s error=%s", r["room_id"], exc)
    logger.info("rooms_seeded count=%d", len(DEFAULT_ROOMS))


async def list_rooms() -> list[RoomResponse]:
    rows = await db.fetch(
        "SELECT * FROM dt_rooms ORDER BY floor NULLS LAST, name"
    )
    if not rows:
        return _default_room_responses()
    return [_row_to_response(dict(r)) for r in rows]


async def get_room(room_id: str) -> Optional[RoomResponse]:
    if db.get_pool() is None:
        for r in _default_room_responses():
            if r.room_id == room_id:
                return r
        return None
    row = await db.fetchrow("SELECT * FROM dt_rooms WHERE room_id = $1", room_id)
    if row is None:
        return None
    return _row_to_response(dict(row))


async def create_room(data: RoomCreate) -> RoomResponse:
    if db.get_pool() is None:
        raise RuntimeError("Database unavailable — cannot persist new rooms")
    row = await db.fetchrow(
        """
        INSERT INTO dt_rooms
            (room_id, name, floor, area_m2,
             ha_temperature_entity, ha_humidity_entity,
             ha_occupancy_entity, ha_heating_entity,
             extra_entities, metadata)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb)
        RETURNING *
        """,
        data.room_id, data.name, data.floor, data.area_m2,
        data.ha_temperature_entity, data.ha_humidity_entity,
        data.ha_occupancy_entity, data.ha_heating_entity,
        json.dumps(data.extra_entities), json.dumps(data.metadata),
    )
    if row is None:
        raise RuntimeError("DB insert returned no row")
    return _row_to_response(dict(row))


async def update_room(room_id: str, data: RoomUpdate) -> Optional[RoomResponse]:
    existing = await get_room(room_id)
    if existing is None:
        return None
    # Build SET clause from non-None fields
    updates = data.model_dump(exclude_none=True)
    if not updates:
        return existing
    set_clauses = []
    values = []
    for i, (key, val) in enumerate(updates.items(), start=1):
        if key in ("extra_entities", "metadata"):
            set_clauses.append(f"{key} = ${i}::jsonb")
            values.append(json.dumps(val))
        else:
            set_clauses.append(f"{key} = ${i}")
            values.append(val)
    values.append(room_id)
    idx = len(values)
    query = (
        f"UPDATE dt_rooms SET {', '.join(set_clauses)}, updated_at = now() "
        f"WHERE room_id = ${idx} RETURNING *"
    )
    row = await db.fetchrow(query, *values)
    if row is None:
        return None
    return _row_to_response(dict(row))


async def delete_room(room_id: str) -> bool:
    result = await db.execute("DELETE FROM dt_rooms WHERE room_id = $1", room_id)
    return result != "DELETE 0"


def _default_room_responses() -> list[RoomResponse]:
    """Fallback when DB is unavailable — return in-memory defaults."""
    from datetime import datetime, timezone
    from uuid import uuid4
    now = datetime.now(timezone.utc)
    out = []
    for r in DEFAULT_ROOMS:
        out.append(
            RoomResponse(
                id=uuid4(),
                room_id=r["room_id"],
                name=r["name"],
                floor=r.get("floor"),
                area_m2=r.get("area_m2"),
                ha_temperature_entity=r.get("ha_temperature_entity"),
                ha_humidity_entity=r.get("ha_humidity_entity"),
                ha_occupancy_entity=r.get("ha_occupancy_entity"),
                ha_heating_entity=r.get("ha_heating_entity"),
                extra_entities=r["extra_entities"],
                metadata=r["metadata"],
                created_at=now,
                updated_at=now,
            )
        )
    return out
