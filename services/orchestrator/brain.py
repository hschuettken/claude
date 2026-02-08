"""Brain — the core reasoning engine.

Orchestrates the multi-turn LLM conversation loop with tool calling.
Builds the system prompt with dynamic home context, manages conversation
history, and executes tool calls.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from shared.log import get_logger

from config import OrchestratorSettings
from llm.base import LLMProvider, LLMResponse, Message, ToolCall
from memory import Memory
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
- Read weather forecasts
- Store and recall user preferences (learn over time)
- Send notifications to household members

## Guidelines
- Be concise and practical. Include specific numbers (kWh, W, ct).
- When suggesting actions, explain the reasoning and potential savings.
- Prioritize: 1) User comfort 2) PV self-consumption 3) Cost optimization.
- If unsure about user plans, ASK rather than assume.
- ALWAYS confirm with the user before executing actions that change device states.
- Respond in the user's language (German if they write German, English if English).
- You can use emojis sparingly to make messages more readable on Telegram.
- For energy comparisons: relate to everyday costs (e.g. "that's about 1.50€").

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
    ) -> None:
        self._llm = llm
        self._tools = tool_executor
        self._memory = memory
        self._settings = settings
        self._tz = ZoneInfo(settings.timezone)

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

        messages = [system_msg] + history_msgs + [
            Message(role="user", content=user_message),
        ]

        logger.info(
            "processing_message",
            chat_id=chat_id,
            user=user_name,
            msg_len=len(user_message),
            history_len=len(history_msgs),
        )

        # Multi-turn tool-calling loop
        final_text = await self._reasoning_loop(messages)

        # Save conversation (only user + assistant text, not tool internals)
        self._memory.append_message(chat_id, "user", user_message)
        self._memory.append_message(chat_id, "assistant", final_text)

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

        return SYSTEM_PROMPT_TEMPLATE.format(
            user_profiles=self._memory.get_all_profiles_summary(),
            grid_price=self._settings.grid_price_ct,
            feed_in=self._settings.feed_in_tariff_ct,
            oil_price=self._settings.oil_price_per_kwh_ct,
            current_time=now.strftime("%Y-%m-%d %H:%M"),
            day_of_week=day_name,
        )

    # ------------------------------------------------------------------
    # History conversion
    # ------------------------------------------------------------------

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
