"""Brain — the core reasoning engine.

Orchestrates the multi-turn LLM conversation loop with tool calling.
Builds the system prompt with dynamic home context, manages conversation
history, and executes tool calls.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shared.log import get_logger

from config import OrchestratorSettings
from knowledge import KnowledgeStore, MemoryDocument
from llm.base import LLMProvider, LLMResponse, Message, ToolCall
from memory import Memory
from semantic_memory import SemanticMemory
from tools import TOOL_DEFINITIONS, ToolExecutor

logger = get_logger("brain")


SYSTEM_PROMPT_TEMPLATE = """\
You are the intelligent home orchestrator for a household in Germany.
You coordinate energy systems, comfort automation, and communicate proactively.

## Household
{user_profiles}

## Available Home Systems
- Solar PV (East + West arrays) with AI-powered production forecast
- Home battery (7 kWh / 3.5 kW)
- EV charger (Amtron wallbox, 4.2–11 kW, smart charging service)
- Oil central heating
- Wood-firing oven (manual, saves oil)
- Sauna with IR panels
- Various lights, covers, and climate devices via Home Assistant

## Energy Economics
- Grid electricity: ~{grid_price} ct/kWh
- Feed-in tariff: ~{feed_in} ct/kWh
- Oil heating: ~{oil_price} ct/kWh equivalent
- EV charging from PV surplus is +18 ct/kWh profit (employer reimburses 25 ct/kWh)

## Your Capabilities
Use the available tools to query real-time data. Do NOT guess sensor values.
- Read any Home Assistant sensor, switch, or input helper
- Query historical energy data from InfluxDB
- Get PV production forecasts (today, tomorrow, per-hour)
- Check and control EV charging (always confirm actions with user!)
- Read the EV forecast plan (predicted trips, energy needs, charging recommendations)
- Respond to EV trip clarification requests from the ev-forecast service
- Read weather forecasts
- Store and recall user preferences (learn over time)
- Search your long-term memory for past conversations, facts, and decisions (recall_memory)
- Store important facts and knowledge for future recall (store_fact)
- Store structured knowledge (destinations, patterns, preferences) that other services use (store_learned_fact)
- Query structured knowledge to check what you already know (get_learned_facts)
- Read and update your personal memory notes (read_memory_notes, update_memory_notes)
- Send notifications to household members
- Read the family Google Calendar (absences, business trips, appointments) — READ ONLY
- Write to the orchestrator's own Google Calendar (reminders, scheduled actions)
- Check who is home/away to optimize energy usage accordingly

## Guidelines
- Be concise and practical. Include specific numbers (kWh, W, ct).
- When suggesting actions, explain the reasoning and potential savings.
- Prioritize: 1) User comfort 2) PV self-consumption 3) Cost optimization.
- If unsure about user plans, ASK rather than assume.
- ALWAYS confirm with the user before executing actions that change device states.
- Respond in the user's language (German if they write German, English if English).
- You can use emojis sparingly to make messages more readable on Telegram.
- For energy comparisons: relate to everyday costs (e.g. "that's about 1.50€").

## Learning & Memory
- When you learn concrete facts (distances, preferences, corrections), store them:
  - Use `store_learned_fact` for structured knowledge other services can query
    (destinations with distances, person patterns, preferences)
  - Use `update_memory_notes` to update your personal notebook with anything
    worth remembering (nuanced context, rules, relationships, household quirks)
- ALWAYS store destination corrections immediately (e.g. user says "it's only 10 km")
- When a user corrects you, update both your memory notes AND the knowledge store
- Check `get_learned_facts` before asking clarification questions — you may already know
- Your memory notes (below) persist across conversations — keep them organized and concise

## Current Context
- Time: {current_time}
- Day: {day_of_week}
"""


class Brain:
    """LLM-powered reasoning engine for the orchestrator."""

    def __init__(
        self,
        llm: LLMProvider,
        tool_executor: ToolExecutor,
        memory: Memory,
        settings: OrchestratorSettings,
        semantic: SemanticMemory | None = None,
        ev_state: dict[str, Any] | None = None,
        knowledge: KnowledgeStore | None = None,
        memory_doc: MemoryDocument | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tool_executor
        self._memory = memory
        self._settings = settings
        self._semantic = semantic
        self._ev_state = ev_state or {}
        self._knowledge = knowledge
        self._memory_doc = memory_doc
        self._tz = ZoneInfo(settings.timezone)
        # Injected by OrchestratorService after construction
        self._activity_tracker: Any = None

    async def process_message(
        self,
        user_message: str,
        chat_id: str,
        user_name: str = "",
    ) -> str:
        """Process a user message through the LLM with tool calling.

        Returns the final text response to send back to the user.
        """
        # Ensure user has a profile
        if user_name:
            self._memory.set_user_name(chat_id, user_name)

        # Build conversation
        system_msg = Message(role="system", content=self._build_system_prompt())

        # Load history and convert to Message objects
        raw_history = self._memory.get_history(chat_id)
        history_msgs = self._history_to_messages(raw_history)

        # Inject relevant semantic memories as context
        memory_context = await self._get_memory_context(user_message)

        messages = [system_msg] + history_msgs
        if memory_context:
            messages.append(Message(role="system", content=memory_context))
        messages.append(Message(role="user", content=user_message))

        logger.info(
            "processing_message",
            chat_id=chat_id,
            user=user_name,
            msg_len=len(user_message),
            history_len=len(history_msgs),
            has_memory_context=bool(memory_context),
        )

        # Track message activity
        if self._activity_tracker:
            self._activity_tracker.record_message()

        # Multi-turn tool-calling loop
        final_text = await self._reasoning_loop(messages)

        # Save conversation (only user + assistant text, not tool internals)
        self._memory.append_message(chat_id, "user", user_message)
        self._memory.append_message(chat_id, "assistant", final_text)

        # Auto-store conversation in semantic memory (fire-and-forget)
        await self._auto_store_conversation(user_message, final_text, user_name)

        return final_text

    async def generate_proactive_message(self, prompt: str) -> str:
        """Generate a proactive message (e.g. morning briefing) without user input.

        The prompt describes what the orchestrator should produce.
        """
        system_msg = Message(role="system", content=self._build_system_prompt())
        user_msg = Message(role="user", content=prompt)

        messages = [system_msg, user_msg]
        return await self._reasoning_loop(messages)

    # ------------------------------------------------------------------
    # Reasoning loop
    # ------------------------------------------------------------------

    async def _reasoning_loop(self, messages: list[Message]) -> str:
        """Run the LLM in a loop, executing tool calls until a text response."""
        max_rounds = self._settings.llm_max_tool_rounds

        for round_num in range(max_rounds):
            try:
                response = await self._llm.chat(messages, tools=TOOL_DEFINITIONS)
            except Exception:
                logger.exception("llm_chat_error", round=round_num)
                return "Sorry, I encountered an error communicating with the AI model. Please try again."

            if not response.has_tool_calls:
                return response.content or "I don't have a response for that."

            # Add assistant message with tool calls
            messages.append(Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))

            # Execute each tool call
            for tc in response.tool_calls:
                logger.info("tool_call", round=round_num, tool=tc.name, args=tc.arguments)
                if self._activity_tracker:
                    self._activity_tracker.record_tool_call(tc.name)
                result = await self._tools.execute(tc.name, tc.arguments)
                messages.append(Message(
                    role="tool",
                    content=result,
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

        # Exhausted rounds — ask LLM for a summary
        messages.append(Message(
            role="user",
            content="Please summarize what you've found so far and provide your answer.",
        ))
        try:
            final = await self._llm.chat(messages, tools=None)  # no tools — force text
            return final.content or "I've gathered the data but couldn't form a conclusion. Please ask again."
        except Exception:
            return "I ran into an issue after multiple data lookups. Please try a simpler question."

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        now = datetime.now(self._tz)
        days_de = {
            "Monday": "Montag",
            "Tuesday": "Dienstag",
            "Wednesday": "Mittwoch",
            "Thursday": "Donnerstag",
            "Friday": "Freitag",
            "Saturday": "Samstag",
            "Sunday": "Sonntag",
        }
        day_en = now.strftime("%A")
        day_name = f"{day_en} ({days_de.get(day_en, day_en)})"

        prompt = SYSTEM_PROMPT_TEMPLATE.format(
            user_profiles=self._memory.get_all_profiles_summary(),
            grid_price=self._settings.grid_price_ct,
            feed_in=self._settings.feed_in_tariff_ct,
            oil_price=self._settings.oil_price_per_kwh_ct,
            current_time=now.strftime("%Y-%m-%d %H:%M"),
            day_of_week=day_name,
        )

        ev_ctx = self._build_ev_context()
        if ev_ctx:
            prompt += "\n" + ev_ctx

        memory_notes = self._build_memory_notes_context()
        if memory_notes:
            prompt += "\n" + memory_notes

        return prompt

    # ------------------------------------------------------------------
    # History conversion
    # ------------------------------------------------------------------

    def _build_ev_context(self) -> str:
        """Build system prompt context for pending EV trip clarifications."""
        if not self._ev_state:
            return ""

        pending = self._ev_state.get("pending_clarifications", [])
        if not pending:
            return ""

        lines = [
            "## Pending EV Trip Clarifications",
            f"The ev-forecast service has {len(pending)} pending question(s):",
        ]
        for c in pending:
            lines.append(
                f"- {c.get('person', '?')} \u2192 {c.get('destination', '?')} "
                f"on {c.get('date', '?')} (est. {c.get('estimated_distance_km', '?')} km "
                f"one way, event_id: \"{c.get('event_id', '')}\")"
            )
        lines.append(
            "When a user responds to one of these, use the "
            "respond_to_ev_trip_clarification tool with the event_id."
        )
        return "\n".join(lines)

    def _build_memory_notes_context(self) -> str:
        """Inject the memory.md content into the system prompt."""
        if not self._memory_doc:
            return ""

        content = self._memory_doc.read()
        if not content or content.strip() == "":
            return ""

        return f"## Memory Notes\n{content}"

    @staticmethod
    def _history_to_messages(raw: list[dict[str, Any]]) -> list[Message]:
        """Convert stored history dicts to Message objects (text only)."""
        messages: list[Message] = []
        for entry in raw:
            role = entry.get("role", "user")
            content = entry.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append(Message(role=role, content=content))
        return messages

    # ------------------------------------------------------------------
    # Semantic memory helpers
    # ------------------------------------------------------------------

    async def _get_memory_context(self, user_message: str) -> str:
        """Search semantic memory for relevant context to inject."""
        if not self._semantic or self._semantic.entry_count == 0:
            return ""

        top_k = self._settings.memory_context_results
        sim_threshold = self._settings.memory_similarity_threshold
        try:
            results = await self._semantic.search(user_message, top_k=top_k)
        except Exception:
            logger.debug("semantic_search_failed")
            return ""

        # Only include results with reasonable similarity
        relevant = [r for r in results if r["similarity"] >= sim_threshold]
        if not relevant:
            return ""

        lines = ["## Relevant memories from past conversations"]
        for r in relevant:
            age = r["age_days"]
            age_str = f"{age:.0f}d ago" if age >= 1 else "today"
            lines.append(
                f"- [{r['category']}] ({age_str}, similarity={r['similarity']}): "
                f"{r['text'][:300]}"
            )
        lines.append(
            "\nUse these memories as context if relevant. "
            "You can also use the recall_memory tool for more specific searches."
        )
        return "\n".join(lines)

    async def _auto_store_conversation(
        self, user_message: str, assistant_response: str, user_name: str,
    ) -> None:
        """Summarize and store the conversation turn in semantic memory.

        Uses the LLM to distill the exchange into a concise memory entry
        instead of storing raw text — produces better search results and
        uses less storage.
        """
        if not self._semantic:
            return

        # Only store substantive exchanges (skip very short messages)
        if len(user_message) < 15 and len(assistant_response) < 50:
            return

        # Use LLM to extract the key takeaway
        summary = await self._summarize_for_memory(
            user_message, assistant_response, user_name,
        )
        if not summary:
            return

        try:
            await self._semantic.store(
                summary,
                category="conversation",
                metadata={"user": user_name},
            )
        except Exception:
            logger.debug("auto_store_failed")

        # Also extract structured knowledge if enabled (fire-and-forget)
        if self._knowledge and self._settings.knowledge_auto_extract:
            try:
                await self._auto_extract_knowledge(
                    user_message, assistant_response, user_name,
                )
            except Exception:
                logger.debug("auto_extract_knowledge_failed")

    async def _auto_extract_knowledge(
        self, user_message: str, assistant_response: str, user_name: str,
    ) -> None:
        """Ask the LLM to extract structured facts from a conversation turn.

        Runs asynchronously after each conversation — does not slow down
        the user-facing response.
        """
        if not self._knowledge:
            return

        prompt = (
            "Extract any structured facts from this conversation exchange. "
            "Return ONLY a JSON array (no markdown, no explanation). "
            "Each element should have: type, key, data.\n"
            "Types:\n"
            '- "destination": {key: place name, data: {name, distance_km, person, notes}}\n'
            '- "person_pattern": {key: descriptive_key, data: {person, pattern, context}}\n'
            '- "preference": {key: descriptive_key, data: {user, value, context}}\n'
            '- "correction": {key: descriptive_key, data: {original, corrected, context}}\n\n'
            "Return [] if no structured facts were revealed.\n\n"
            f"User ({user_name}): {user_message[:500]}\n"
            f"Assistant: {assistant_response[:500]}"
        )
        try:
            response = await self._llm.chat(
                [Message(role="user", content=prompt)],
                tools=None,
            )
            text = (response.content or "").strip()
            # Strip markdown code fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            if not text or text == "[]":
                return

            facts = json.loads(text)
            if not isinstance(facts, list):
                return

            for fact in facts:
                fact_type = fact.get("type", "")
                key = fact.get("key", "")
                data = fact.get("data", {})
                if fact_type and key and data:
                    self._knowledge.store(
                        fact_type=fact_type,
                        key=key,
                        data=data,
                        confidence=0.7,  # LLM-inferred, not user-confirmed
                        source="auto_extract",
                    )
                    logger.info(
                        "knowledge_auto_extracted",
                        type=fact_type,
                        key=key,
                    )
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.debug("knowledge_extraction_parse_failed")
        except Exception:
            logger.debug("knowledge_extraction_failed")

    async def _summarize_for_memory(
        self, user_message: str, assistant_response: str, user_name: str,
    ) -> str:
        """Use the LLM to distill a conversation into a concise memory entry."""
        prompt = (
            "Summarize this conversation exchange in 1-2 sentences for long-term memory storage. "
            "Focus on: key facts learned, decisions made, user preferences revealed, or actions taken. "
            "Be specific — include names, numbers, entity names, and concrete details. "
            "Write in third person. If nothing noteworthy happened, write 'trivial exchange'.\n\n"
            f"User ({user_name}): {user_message[:600]}\n"
            f"Assistant: {assistant_response[:600]}"
        )
        try:
            response = await self._llm.chat(
                [Message(role="user", content=prompt)],
                tools=None,
            )
            summary = (response.content or "").strip()
            # Fall back to raw text if LLM returns empty or very short
            if len(summary) < 10 or summary.lower() == "trivial exchange":
                return ""
            return summary
        except Exception:
            logger.debug("summarization_failed_using_raw")
            # Fall back to truncated raw text
            return f"User ({user_name}): {user_message[:300]}\nAssistant: {assistant_response[:300]}"

    async def consolidate_memories(self) -> int:
        """Consolidate older conversation memories into denser entries.

        Groups related memories and asks the LLM to merge them.
        Returns the number of entries that were consolidated.
        """
        if not self._semantic:
            return 0

        min_age = self._settings.memory_consolidation_min_age_days
        limit = self._settings.memory_consolidation_batch_limit
        batch_size = self._settings.memory_consolidation_batch_size
        min_batch = self._settings.memory_consolidation_min_batch_size

        entries = self._semantic.get_entries_for_consolidation(
            category="conversation", min_age_days=min_age, limit=limit,
        )
        if len(entries) < min_batch:
            return 0  # not enough to consolidate

        total_consolidated = 0

        for i in range(0, len(entries), batch_size):
            batch = entries[i : i + batch_size]
            if len(batch) < 3:
                break

            texts = "\n---\n".join(
                f"[{e.get('category', 'conversation')}] {e['text']}" for e in batch
            )
            prompt = (
                "You are consolidating long-term memory entries for a smart home orchestrator. "
                "Below are several related memory entries from past conversations. "
                "Merge them into 1-3 concise, information-dense summaries that preserve "
                "all important facts, preferences, patterns, and decisions. "
                "Drop redundant or trivial information. "
                "Write each summary as a separate paragraph.\n\n"
                f"Entries to consolidate:\n{texts}"
            )

            try:
                response = await self._llm.chat(
                    [Message(role="user", content=prompt)],
                    tools=None,
                )
                consolidated_text = (response.content or "").strip()
                if len(consolidated_text) < 20:
                    continue

                old_ids = [e["id"] for e in batch]
                await self._semantic.replace_with_consolidated(
                    old_ids, consolidated_text, category="conversation",
                )
                total_consolidated += len(old_ids)
                logger.info(
                    "batch_consolidated",
                    merged=len(old_ids),
                    summary_len=len(consolidated_text),
                )
            except Exception:
                logger.exception("consolidation_batch_failed")

        return total_consolidated
