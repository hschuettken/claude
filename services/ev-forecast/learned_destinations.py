"""Local cache for learned destinations from the orchestrator.

Subscribes to ``homelab/orchestrator/knowledge-update`` MQTT messages
and persists destination facts locally.  This survives restarts even
if the orchestrator is down — the ev-forecast service can always look
up previously learned destinations.

Data file: ``/app/data/learned_destinations.json``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

LEARNED_FILE = Path("/app/data/learned_destinations.json")


class LearnedDestinations:
    """Persistent cache of destinations learned via orchestrator conversations.

    Each entry maps a normalised destination name to its known distances
    (and optional context).  A destination can have multiple entries
    when the same name maps to different places (e.g. "Sarah" → Bocholt
    80 km, "Sarah" → Ibbenbüren 10 km).
    """

    def __init__(self) -> None:
        # {norm_key: [{distance_km, name, person, notes, disambiguation}, ...]}
        self._destinations: dict[str, list[dict[str, Any]]] = {}
        self._load()

    # ---- Lookup API --------------------------------------------------

    def lookup(self, destination: str) -> float | None:
        """Look up one-way distance for a destination.

        Returns the distance if exactly one match is found, or None
        if unknown or ambiguous (multiple matches — use
        ``lookup_all`` for disambiguation).
        """
        entries = self._get_entries(destination)
        if len(entries) == 1:
            return entries[0].get("distance_km")
        return None

    def lookup_all(self, destination: str) -> list[dict[str, Any]]:
        """Return all known entries for a destination (for disambiguation)."""
        return self._get_entries(destination)

    def is_known(self, destination: str) -> bool:
        """Check if any entries exist for this destination."""
        return len(self._get_entries(destination)) > 0

    # ---- MQTT handler ------------------------------------------------

    def on_knowledge_update(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle a knowledge update from the orchestrator.

        Only processes destination-type facts.
        """
        if payload.get("type") != "destination":
            return

        key = payload.get("key", "").lower().strip()
        data = payload.get("data", {})
        distance_km = data.get("distance_km")

        if not key or not distance_km:
            return

        entry = {
            "distance_km": distance_km,
            "name": data.get("name", key),
            "person": data.get("person", ""),
            "notes": data.get("notes", ""),
            "disambiguation": data.get("disambiguation", ""),
        }

        # Check if this exact entry already exists (same key + distance)
        existing = self._destinations.get(key, [])
        for e in existing:
            if abs(e.get("distance_km", 0) - distance_km) < 1.0:
                # Update existing entry
                e.update(entry)
                self._save()
                logger.info(
                    "learned_destination_updated",
                    key=key,
                    distance_km=distance_km,
                )
                return

        # New entry
        if key not in self._destinations:
            self._destinations[key] = []
        self._destinations[key].append(entry)
        self._save()
        logger.info(
            "learned_destination_stored",
            key=key,
            distance_km=distance_km,
            total_entries=len(self._destinations[key]),
        )

    # ---- Internal ----------------------------------------------------

    def _get_entries(self, destination: str) -> list[dict[str, Any]]:
        """Find entries matching a destination name (exact + partial)."""
        dest_lower = destination.lower().strip()

        # Exact match
        if dest_lower in self._destinations:
            return self._destinations[dest_lower]

        # Partial match
        results: list[dict[str, Any]] = []
        for key, entries in self._destinations.items():
            if key in dest_lower or dest_lower in key:
                results.extend(entries)
        return results

    @property
    def count(self) -> int:
        return sum(len(v) for v in self._destinations.values())

    def _load(self) -> None:
        try:
            raw = json.loads(LEARNED_FILE.read_text(encoding="utf-8"))
            self._destinations = raw.get("destinations", {})
            logger.info("learned_destinations_loaded", count=self.count)
        except (FileNotFoundError, json.JSONDecodeError):
            self._destinations = {}

    def _save(self) -> None:
        LEARNED_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = LEARNED_FILE.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"destinations": self._destinations}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.rename(LEARNED_FILE)
