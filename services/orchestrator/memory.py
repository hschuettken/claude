"""Persistent memory — conversation history, user profiles, and preferences.

Data is stored as JSON files under ``/app/data/memory/``.  The directory
layout is::

    /app/data/memory/
      profiles.json          — user profiles & learned preferences
      conversations/
        <chat_id>.json       — per-user conversation history
      decisions.json         — log of orchestrator decisions (for learning)

All writes are atomic (write-tmp + rename) to avoid corruption on crash.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from shared.log import get_logger

logger = get_logger("memory")

DATA_DIR = Path("/app/data/memory")
PROFILES_FILE = DATA_DIR / "profiles.json"
DECISIONS_FILE = DATA_DIR / "decisions.json"
CONVERSATIONS_DIR = DATA_DIR / "conversations"

DEFAULT_MAX_DECISIONS = 500


class Memory:
    """Manages persistent orchestrator memory."""

    def __init__(self, max_history: int = 50, max_decisions: int = DEFAULT_MAX_DECISIONS) -> None:
        self._max_history = max_history
        self._max_decisions = max_decisions
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)

        self._profiles: dict[str, Any] = self._load_json(PROFILES_FILE, default={})
        self._decisions: list[dict[str, Any]] = self._load_json(DECISIONS_FILE, default=[])

    # ------------------------------------------------------------------
    # User profiles
    # ------------------------------------------------------------------

    def get_profile(self, user_id: str) -> dict[str, Any]:
        """Return profile for a user (creates empty if missing)."""
        if user_id not in self._profiles:
            self._profiles[user_id] = {
                "name": "",
                "preferences": {},
                "learned_patterns": {},
                "created_at": time.time(),
            }
            self._save_profiles()
        return self._profiles[user_id]

    def set_user_name(self, user_id: str, name: str) -> None:
        profile = self.get_profile(user_id)
        profile["name"] = name
        self._save_profiles()

    def get_user_name(self, user_id: str) -> str:
        return self.get_profile(user_id).get("name", "")

    def set_preference(self, user_id: str, key: str, value: Any) -> None:
        """Store a user preference (e.g. ``sauna_days``, ``wake_time``)."""
        profile = self.get_profile(user_id)
        profile["preferences"][key] = value
        profile["preferences"]["_updated_at"] = time.time()
        self._save_profiles()
        logger.info("preference_set", user=user_id, key=key, value=value)

    def get_preference(self, user_id: str, key: str, default: Any = None) -> Any:
        return self.get_profile(user_id).get("preferences", {}).get(key, default)

    def get_all_preferences(self, user_id: str) -> dict[str, Any]:
        prefs = dict(self.get_profile(user_id).get("preferences", {}))
        prefs.pop("_updated_at", None)
        return prefs

    def set_learned_pattern(self, user_id: str, key: str, value: Any) -> None:
        """Store a learned pattern (e.g. ``typical_departure_weekday``)."""
        profile = self.get_profile(user_id)
        profile["learned_patterns"][key] = value
        self._save_profiles()

    def get_all_profiles_summary(self) -> str:
        """Return a human-readable summary of all user profiles for the LLM."""
        if not self._profiles:
            return "No user profiles yet."
        lines: list[str] = []
        for uid, profile in self._profiles.items():
            name = profile.get("name", uid)
            prefs = profile.get("preferences", {})
            prefs_clean = {k: v for k, v in prefs.items() if not k.startswith("_")}
            patterns = profile.get("learned_patterns", {})
            parts = [f"- **{name}** (chat_id: {uid})"]
            if prefs_clean:
                parts.append(f"  Preferences: {json.dumps(prefs_clean, ensure_ascii=False)}")
            if patterns:
                parts.append(f"  Patterns: {json.dumps(patterns, ensure_ascii=False)}")
            lines.append("\n".join(parts))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Conversation history
    # ------------------------------------------------------------------

    def get_history(self, chat_id: str) -> list[dict[str, Any]]:
        """Load conversation history for a chat (list of message dicts)."""
        path = CONVERSATIONS_DIR / f"{chat_id}.json"
        history: list[dict[str, Any]] = self._load_json(path, default=[])
        return history

    def save_history(self, chat_id: str, messages: list[dict[str, Any]]) -> None:
        """Persist conversation history, trimming to max length."""
        # Only keep the most recent messages (skip system prompt in count)
        non_system = [m for m in messages if m.get("role") != "system"]
        if len(non_system) > self._max_history:
            non_system = non_system[-self._max_history :]
        path = CONVERSATIONS_DIR / f"{chat_id}.json"
        self._save_json(path, non_system)

    def append_message(self, chat_id: str, role: str, content: str) -> None:
        """Convenience — append a single message and save."""
        history = self.get_history(chat_id)
        history.append({"role": role, "content": content, "timestamp": time.time()})
        self.save_history(chat_id, history)

    def clear_history(self, chat_id: str) -> None:
        path = CONVERSATIONS_DIR / f"{chat_id}.json"
        self._save_json(path, [])

    # ------------------------------------------------------------------
    # Decision log
    # ------------------------------------------------------------------

    def log_decision(self, context: str, decision: str, reasoning: str = "") -> None:
        """Record an orchestrator decision for future learning."""
        entry = {
            "timestamp": time.time(),
            "context": context,
            "decision": decision,
            "reasoning": reasoning,
        }
        self._decisions.append(entry)
        # Trim old entries
        if len(self._decisions) > self._max_decisions:
            self._decisions = self._decisions[-self._max_decisions:]
        self._save_json(DECISIONS_FILE, self._decisions)

    def get_recent_decisions(self, n: int = 10) -> list[dict[str, Any]]:
        return self._decisions[-n:]

    # ------------------------------------------------------------------
    # JSON I/O helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_json(path: Path, default: Any = None) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default if default is not None else {}

    @staticmethod
    def _save_json(path: Path, data: Any) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(path)

    def _save_profiles(self) -> None:
        self._save_json(PROFILES_FILE, self._profiles)
