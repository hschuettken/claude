"""Ingest Home Assistant events via orchestrator NATS bridge.

Subscribes to `ha.state.*` NATS subjects and creates `ha_event` nodes
for state-change events that are significant (presence, alarm, EV, energy).

Creates:
  - `ha_event` node per state-change
  - RELATES_TO edges when the same entity changes repeatedly (thread)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from .. import knowledge_graph as kg
from ..models import IngestResult, NodeCreate

logger = logging.getLogger(__name__)

# Entity patterns that warrant a KG node
_INTERESTING_DOMAINS = {
    "person", "device_tracker",  # presence
    "binary_sensor",             # door/motion
    "input_boolean",             # mode flags
    "sensor",                    # energy, temperature
    "alarm_control_panel",
}

_ENTITY_BLOCKLIST = {
    # Exclude high-frequency jitter sensors
    "sensor.time",
    "sensor.date",
}


class HaEventsIngester:
    """Subscribes to NATS ha.state.* and creates KG nodes for significant events."""

    def __init__(self, nats_publisher) -> None:
        self._nats = nats_publisher
        self._subscribed = False

    async def start(self) -> None:
        if self._nats is None or not self._nats.connected:
            logger.warning("ha_events_ingester nats_unavailable — skipping")
            return
        await self._nats.subscribe_json("ha.state.>", self._on_ha_state)
        self._subscribed = True
        logger.info("ha_events_ingester subscribed to ha.state.>")

    async def _on_ha_state(self, subject: str, payload: dict[str, Any]) -> None:
        try:
            entity_id = payload.get("entity_id", "")
            if not entity_id:
                return
            domain = entity_id.split(".")[0]
            if domain not in _INTERESTING_DOMAINS:
                return
            if entity_id in _ENTITY_BLOCKLIST:
                return

            new_state = payload.get("new_state", {})
            state_val = new_state.get("state", "unknown") if isinstance(new_state, dict) else str(new_state)
            old_state = payload.get("old_state", {})
            old_val = old_state.get("state", "") if isinstance(old_state, dict) else ""

            # Skip unchanged states
            if state_val == old_val:
                return

            await kg.create_node(NodeCreate(
                node_type="ha_event",
                label=f"{entity_id}: {old_val} → {state_val}",
                properties={
                    "entity_id": entity_id,
                    "domain": domain,
                    "old_state": old_val,
                    "new_state": state_val,
                    "subject": subject,
                },
                source="ha",
                source_id=f"{entity_id}:{payload.get('event_id', '')}",
            ))
        except Exception as exc:
            logger.warning("ha_event_ingest_failed error=%s", exc)


async def ingest_ha_events_bulk(events: list[dict[str, Any]]) -> IngestResult:
    """Batch-ingest a list of HA event dicts (for testing / backfill)."""
    result = IngestResult(source="ha", nodes_created=0, edges_created=0)
    for ev in events:
        entity_id = ev.get("entity_id", "")
        domain = entity_id.split(".")[0] if entity_id else ""
        if domain not in _INTERESTING_DOMAINS or entity_id in _ENTITY_BLOCKLIST:
            continue
        node = await kg.create_node(NodeCreate(
            node_type="ha_event",
            label=f"{entity_id}: {ev.get('old_state', '')} → {ev.get('new_state', '')}",
            properties=ev,
            source="ha",
            source_id=str(ev.get("event_id", entity_id + str(ev.get("timestamp", "")))),
        ))
        if node:
            result.nodes_created += 1
    return result
