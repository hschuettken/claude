"""Memory tool definitions and handlers (preferences, semantic memory, knowledge store)."""

from __future__ import annotations

import json
from typing import Any

from shared.log import get_logger
from memory import Memory
from semantic_memory import SemanticMemory
from knowledge import KnowledgeStore, MemoryDocument

logger = get_logger("tooling.memory_tools")

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_user_preferences",
            "description": (
                "Retrieve stored preferences for a user. Use to personalize responses "
                "and suggestions based on known habits and settings."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user's chat ID or name",
                    },
                },
                "required": ["user_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_user_preference",
            "description": (
                "Store a user preference for future reference. Examples: "
                "sauna_days=['friday','saturday'], wake_time='06:30', "
                "ev_departure_weekday='07:30', preferred_room_temp=21."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user's chat ID",
                    },
                    "key": {
                        "type": "string",
                        "description": "Preference key (snake_case)",
                    },
                    "value": {
                        "type": "string",
                        "description": "Preference value (will be parsed as JSON if possible)",
                    },
                },
                "required": ["user_id", "key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": (
                "Search your long-term semantic memory for relevant past conversations, "
                "learned facts, and previous decisions. Use this when the user references "
                "something from the past ('last time', 'remember when', 'as I said before') "
                "or when you need historical context to answer a question better."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "What to search for — a natural-language description of the "
                            "information you need (e.g. 'Henning sauna preferences', "
                            "'EV charging decisions last week', 'Nicole business trips')."
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": ["conversation", "fact", "decision"],
                        "description": (
                            "Optional category filter: 'conversation' for past exchanges, "
                            "'fact' for stored knowledge, 'decision' for past orchestrator decisions."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (default: 5)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_fact",
            "description": (
                "Store an important fact, user preference, or piece of knowledge in long-term "
                "semantic memory. Use this when you learn something worth remembering across "
                "conversations — e.g. user habits, important decisions, household rules. "
                "This is different from set_user_preference (key-value pairs) — store_fact "
                "stores free-text knowledge that can be semantically searched later."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "The fact or knowledge to store. Be specific and include context. "
                            "Example: 'Henning prefers to charge the EV overnight when electricity "
                            "is cheaper, unless there is enough PV forecast for tomorrow.'"
                        ),
                    },
                    "category": {
                        "type": "string",
                        "enum": ["fact", "decision"],
                        "description": "Category: 'fact' for knowledge, 'decision' for orchestrator decisions",
                        "default": "fact",
                    },
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "store_learned_fact",
            "description": (
                "Store a structured, typed fact in the knowledge store. Use this when you "
                "learn something concrete and actionable from a conversation: a destination "
                "with distance, a person's behavioral pattern, a user preference, or a "
                "correction to previous knowledge. This is different from store_fact (free-text "
                "semantic memory) — store_learned_fact creates a structured, queryable entry "
                "that other services (ev-forecast, smart-ev-charging) can use to improve "
                "their behavior automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_type": {
                        "type": "string",
                        "enum": ["destination", "person_pattern", "preference", "correction", "general"],
                        "description": (
                            "Type of fact: 'destination' (place + distance), "
                            "'person_pattern' (behavioral pattern for a person), "
                            "'preference' (user preference), 'correction' (fix to previous knowledge), "
                            "'general' (other structured knowledge)"
                        ),
                    },
                    "key": {
                        "type": "string",
                        "description": (
                            "Normalised lookup key. For destinations: 'sarah_ibbenbüren' or 'münchen'. "
                            "For patterns: 'henning_berlin_train'. For preferences: 'henning_charge_overnight'."
                        ),
                    },
                    "data": {
                        "type": "object",
                        "description": (
                            "Type-specific data. Destination: {name, distance_km, person, disambiguation, notes}. "
                            "Pattern: {person, pattern, context}. Preference: {user, value, context}. "
                            "Correction: {original, corrected, context}."
                        ),
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Confidence: 1.0 = user explicitly confirmed, 0.7 = inferred from conversation",
                        "default": 1.0,
                    },
                },
                "required": ["fact_type", "key", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_learned_facts",
            "description": (
                "Search the knowledge store for previously learned structured facts. "
                "Use this to check what the system already knows before asking the user "
                "a question (e.g., check known destinations before asking about a trip, "
                "check person patterns before suggesting a charge mode)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fact_type": {
                        "type": "string",
                        "enum": ["destination", "person_pattern", "preference", "correction", "general"],
                        "description": "Filter by fact type (optional — omit to search all types)",
                    },
                    "query": {
                        "type": "string",
                        "description": "Search term — matches against key and data values (optional)",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_memory_notes",
            "description": (
                "Update the orchestrator's persistent memory notes (memory.md). "
                "This is your personal notebook — a living document where you maintain "
                "everything you've learned about the household, destinations, preferences, "
                "patterns, and rules. The current content is shown in your system prompt "
                "under '## Memory Notes'. When you learn something new, update the relevant "
                "section. Keep it concise and well-organized — it's injected into every "
                "conversation. Write the COMPLETE updated document (you'll see the current "
                "content in context)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "The full updated memory.md content. Markdown format. "
                            "Include all sections, not just the changed part."
                        ),
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_memory_notes",
            "description": (
                "Read the current content of the memory notes (memory.md). "
                "Use this if you need to check the full document before updating it, "
                "or if the system prompt excerpt was truncated."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class MemoryTools:
    """Handlers for memory, preferences, and knowledge tools."""

    def __init__(
        self,
        memory: Memory,
        semantic: SemanticMemory | None = None,
        knowledge: KnowledgeStore | None = None,
        memory_doc: MemoryDocument | None = None,
    ) -> None:
        self.memory = memory
        self.semantic = semantic
        self._knowledge = knowledge
        self._memory_doc = memory_doc

    async def get_user_preferences(self, user_id: str) -> dict[str, Any]:
        prefs = self.memory.get_all_preferences(user_id)
        name = self.memory.get_user_name(user_id)
        return {"user_id": user_id, "name": name, "preferences": prefs}

    async def set_user_preference(
        self, user_id: str, key: str, value: str
    ) -> dict[str, Any]:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = value
        self.memory.set_preference(user_id, key, parsed)
        return {"success": True, "user_id": user_id, "key": key, "value": parsed}

    async def recall_memory(
        self, query: str, category: str | None = None, top_k: int = 5,
    ) -> dict[str, Any]:
        if not self.semantic:
            return {"error": "Semantic memory not enabled"}
        results = await self.semantic.search(query, top_k=top_k, category=category)
        return {
            "query": query,
            "result_count": len(results),
            "memories": results,
            "total_stored": self.semantic.entry_count,
        }

    async def store_fact(
        self, text: str, category: str = "fact",
    ) -> dict[str, Any]:
        if not self.semantic:
            return {"error": "Semantic memory not enabled"}
        entry_id = await self.semantic.store(text, category=category)
        if not entry_id:
            return {"error": "Failed to store — embedding provider unavailable"}
        return {
            "success": True,
            "id": entry_id,
            "category": category,
            "total_stored": self.semantic.entry_count,
        }

    async def store_learned_fact(
        self,
        fact_type: str,
        key: str,
        data: dict[str, Any],
        confidence: float = 1.0,
    ) -> dict[str, Any]:
        if not self._knowledge:
            return {"error": "Knowledge store not enabled"}
        try:
            fact_id = self._knowledge.store(
                fact_type=fact_type,
                key=key,
                data=data,
                confidence=confidence,
                source="conversation",
            )
            return {
                "success": True,
                "id": fact_id,
                "fact_type": fact_type,
                "key": key,
                "total_facts": self._knowledge.count,
            }
        except ValueError as e:
            return {"error": str(e)}

    async def get_learned_facts(
        self,
        fact_type: str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        if not self._knowledge:
            return {"error": "Knowledge store not enabled"}
        results = self._knowledge.search(fact_type=fact_type, query=query)
        facts = [
            {
                "id": f["id"],
                "type": f["type"],
                "key": f["key"],
                "data": f["data"],
                "confidence": f["confidence"],
                "source": f["source"],
                "times_used": f["times_used"],
            }
            for f in results[:20]
        ]
        return {
            "query": query or "(all)",
            "fact_type": fact_type or "all",
            "result_count": len(facts),
            "facts": facts,
            "total_stored": self._knowledge.count,
        }

    async def update_memory_notes(self, content: str) -> dict[str, Any]:
        if not self._memory_doc:
            return {"error": "Memory document not enabled"}
        success = self._memory_doc.write(content)
        if success:
            return {
                "success": True,
                "size": len(content),
                "note": "Memory notes updated. Changes will be visible in the next conversation.",
            }
        return {"error": "Failed to write memory document"}

    async def read_memory_notes(self) -> dict[str, Any]:
        if not self._memory_doc:
            return {"error": "Memory document not enabled"}
        content = self._memory_doc.read()
        return {"content": content, "size": len(content)}
