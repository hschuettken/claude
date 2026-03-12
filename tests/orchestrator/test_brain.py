"""Unit tests for orchestrator/brain.py

Tests cover:
- Tool-call loop (_reasoning_loop): mock LLM, verify round trips
- Max tool rounds limit: exhausted rounds → summary request
- _auto_store_conversation is truly async (asyncio.create_task, not await)
- process_message wires up history and returns final text
- System prompt building (no exceptions)
"""

from __future__ import annotations

import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

# Patch the path before importing brain
SERVICE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "orchestrator")
)
SHARED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
for d in (SERVICE_DIR, SHARED_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)


# ---------------------------------------------------------------------------
# Minimal stubs for heavy dependencies
# ---------------------------------------------------------------------------

# Define minimal local equivalents of the llm.base dataclasses.
# We can't import from the real module cleanly because of sys.modules stubs.
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str
    content: str | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None
    name: str | None = None


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


# Stub shared.log before importing brain
log_stub = MagicMock()
log_stub.get_logger = MagicMock(return_value=MagicMock(
    info=MagicMock(), debug=MagicMock(), exception=MagicMock()
))
sys.modules.setdefault("shared", MagicMock())
sys.modules.setdefault("shared.log", log_stub)
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("knowledge", MagicMock())
sys.modules.setdefault("memory", MagicMock())
sys.modules.setdefault("semantic_memory", MagicMock())
sys.modules.setdefault("tools", MagicMock(TOOL_DEFINITIONS=[]))
sys.modules.setdefault("llm", MagicMock())
sys.modules.setdefault("llm.base", MagicMock())

# Import actual brain now that stubs are in place
from brain import Brain  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_settings(**kwargs):
    s = MagicMock()
    s.llm_max_tool_rounds = kwargs.get("llm_max_tool_rounds", 10)
    s.timezone = "Europe/Berlin"
    s.grid_price_ct = 30
    s.feed_in_tariff_ct = 8
    s.oil_price_per_kwh_ct = 12
    s.memory_context_results = 5
    s.memory_similarity_threshold = 0.7
    s.knowledge_auto_extract = False
    s.memory_consolidation_min_age_days = 7
    s.memory_consolidation_batch_limit = 50
    s.memory_consolidation_batch_size = 10
    s.memory_consolidation_min_batch_size = 5
    return s


def make_memory():
    m = MagicMock()
    m.get_history.return_value = []
    m.get_all_profiles_summary.return_value = "Henning"
    m.append_message = MagicMock()
    m.set_user_name = MagicMock()
    return m


def make_llm_text(text: str) -> MagicMock:
    """LLMResponse that is a plain text reply (no tool calls)."""
    r = MagicMock()
    r.content = text
    r.has_tool_calls = False
    r.tool_calls = []
    return r


def make_llm_tool_call(name: str, args: dict, call_id: str = "tc_1") -> MagicMock:
    """LLMResponse that requests a tool call."""
    tc = MagicMock()
    tc.id = call_id
    tc.name = name
    tc.arguments = args
    r = MagicMock()
    r.content = None
    r.has_tool_calls = True
    r.tool_calls = [tc]
    return r


def make_brain(llm=None, tool_executor=None, memory=None, settings=None, **kwargs) -> Brain:
    llm = llm or MagicMock()
    tool_executor = tool_executor or MagicMock()
    memory = memory or make_memory()
    settings = settings or make_settings()
    return Brain(
        llm=llm,
        tool_executor=tool_executor,
        memory=memory,
        settings=settings,
        **kwargs,
    )


# ===========================================================================
# _reasoning_loop — basic text response
# ===========================================================================

class TestReasoningLoopTextResponse:
    @pytest.mark.asyncio
    async def test_returns_text_on_first_round(self):
        """LLM returns text immediately (no tool calls) → loop exits after 1 round."""
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=make_llm_text("Hello from LLM"))

        brain = make_brain(llm=llm)
        messages = [Message(role="user", content="Hi")]
        result = await brain._reasoning_loop(messages)

        assert result == "Hello from LLM"
        llm.chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_fallback_on_empty_content(self):
        """LLM returns empty content → fallback string."""
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=make_llm_text(""))

        brain = make_brain(llm=llm)
        result = await brain._reasoning_loop([Message(role="user", content="Hi")])

        assert "don't have a response" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_llm_exception(self):
        """LLM raises exception → returns error message."""
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=Exception("API timeout"))

        brain = make_brain(llm=llm)
        result = await brain._reasoning_loop([Message(role="user", content="Hi")])

        assert "error" in result.lower()


# ===========================================================================
# _reasoning_loop — tool calling
# ===========================================================================

class TestReasoningLoopToolCalls:
    @pytest.mark.asyncio
    async def test_executes_tool_and_continues(self):
        """LLM requests one tool call → tool executed → LLM returns text."""
        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(return_value='{"temperature": 22}')

        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=[
            make_llm_tool_call("get_sensor", {"entity": "sensor.temp"}),
            make_llm_text("Temperature is 22°C"),
        ])

        brain = make_brain(llm=llm, tool_executor=tool_executor)
        result = await brain._reasoning_loop([Message(role="user", content="Temp?")])

        assert result == "Temperature is 22°C"
        tool_executor.execute.assert_awaited_once_with("get_sensor", {"entity": "sensor.temp"})
        assert llm.chat.await_count == 2

    @pytest.mark.asyncio
    async def test_multiple_tool_rounds(self):
        """LLM makes 3 rounds of tool calls before returning text."""
        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(return_value="result")

        rounds = [
            make_llm_tool_call("tool_a", {}, "tc_1"),
            make_llm_tool_call("tool_b", {}, "tc_2"),
            make_llm_tool_call("tool_c", {}, "tc_3"),
            make_llm_text("Final answer"),
        ]
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=rounds)

        brain = make_brain(llm=llm, tool_executor=tool_executor)
        result = await brain._reasoning_loop([Message(role="user", content="Complex query")])

        assert result == "Final answer"
        assert tool_executor.execute.await_count == 3

    @pytest.mark.asyncio
    async def test_tool_call_appends_messages(self):
        """Tool result is added to messages so LLM sees more messages in round 2."""
        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(return_value="42 kWh")

        call_msg_lengths = []

        async def capture_chat(messages, tools=None):
            call_msg_lengths.append(len(messages))
            if len(call_msg_lengths) == 1:
                return make_llm_tool_call("get_energy", {}, "tc_99")
            return make_llm_text("Energy is 42 kWh")

        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=capture_chat)

        brain = make_brain(llm=llm, tool_executor=tool_executor)
        await brain._reasoning_loop([Message(role="user", content="Energy?")])

        # Second call should have more messages than the first (assistant + tool result added)
        assert len(call_msg_lengths) == 2
        assert call_msg_lengths[1] > call_msg_lengths[0]


# ===========================================================================
# Max tool rounds limit
# ===========================================================================

class TestMaxToolRoundsLimit:
    @pytest.mark.asyncio
    async def test_exhausted_rounds_requests_summary(self):
        """After max_tool_rounds tool-call rounds, brain asks for a text summary."""
        max_rounds = 3
        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(return_value="data")

        # Always return a tool call (never text) → exhaust rounds
        always_tool = make_llm_tool_call("endless_tool", {})
        summary_text = make_llm_text("Here's my summary")

        call_count = 0

        async def side_effect(messages, tools=None):
            nonlocal call_count
            call_count += 1
            # Last call is the summary (tools=None)
            if tools is None:
                return summary_text
            return always_tool

        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=side_effect)

        brain = make_brain(llm=llm, tool_executor=tool_executor,
                           settings=make_settings(llm_max_tool_rounds=max_rounds))
        result = await brain._reasoning_loop([Message(role="user", content="Loop?")])

        assert result == "Here's my summary"
        # Should have called LLM max_rounds times + 1 summary call
        assert llm.chat.await_count == max_rounds + 1

    @pytest.mark.asyncio
    async def test_exhausted_rounds_summary_exception(self):
        """If summary call also fails → return fallback error string."""
        max_rounds = 2
        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(return_value="data")

        async def side_effect(messages, tools=None):
            if tools is None:
                raise Exception("API down")
            return make_llm_tool_call("tool", {})

        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=side_effect)

        brain = make_brain(llm=llm, tool_executor=tool_executor,
                           settings=make_settings(llm_max_tool_rounds=max_rounds))
        result = await brain._reasoning_loop([Message(role="user", content="Fail?")])

        assert "issue" in result.lower() or "error" in result.lower()


# ===========================================================================
# _auto_store_conversation is truly async (fire-and-forget)
# ===========================================================================

class TestAutoStoreIsAsync:
    @pytest.mark.asyncio
    async def test_auto_store_is_create_task_not_await(self):
        """process_message must use asyncio.create_task for auto_store_conversation.

        If it used 'await', it would block the response. The fix uses
        asyncio.create_task (fire-and-forget). We verify create_task is called.
        """
        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(return_value="ok")

        llm = MagicMock()
        llm.chat = AsyncMock(return_value=make_llm_text("Response text"))

        memory = make_memory()
        semantic = MagicMock()
        semantic.entry_count = 0

        brain = make_brain(llm=llm, tool_executor=tool_executor,
                           memory=memory, semantic=semantic)

        with patch("asyncio.create_task") as mock_create_task:
            # create_task needs a real coroutine — stub it
            mock_create_task.return_value = MagicMock()
            result = await brain.process_message("Hello", "chat_1", "Henning")

        assert result == "Response text"
        # create_task must have been called (for auto-store)
        mock_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_store_skips_trivial_messages(self):
        """Very short exchanges are not stored."""
        semantic = MagicMock()
        semantic.entry_count = 0
        semantic.store = AsyncMock()

        brain = make_brain(semantic=semantic)
        # Call with very short message + response
        await brain._auto_store_conversation("Hi", "OK", "Henning")

        # store should NOT have been called (too short)
        semantic.store.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_store_skips_when_no_semantic(self):
        """If no semantic memory configured, auto_store is a no-op."""
        brain = make_brain(semantic=None)
        # Should not raise
        await brain._auto_store_conversation(
            "This is a longer user message with real content",
            "This is a longer assistant response with real content",
            "Henning",
        )


# ===========================================================================
# process_message
# ===========================================================================

class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_process_message_returns_llm_text(self):
        """End-to-end: process_message returns the LLM text."""
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=make_llm_text("All good"))

        memory = make_memory()
        semantic = MagicMock()
        semantic.entry_count = 0

        brain = make_brain(llm=llm, memory=memory, semantic=semantic)
        with patch("asyncio.create_task"):
            result = await brain.process_message("Status?", "chat_42", "Henning")

        assert result == "All good"

    @pytest.mark.asyncio
    async def test_process_message_saves_history(self):
        """User message and assistant response are saved to memory."""
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=make_llm_text("Saved"))

        memory = make_memory()
        semantic = MagicMock()
        semantic.entry_count = 0

        brain = make_brain(llm=llm, memory=memory, semantic=semantic)
        with patch("asyncio.create_task"):
            await brain.process_message("Save me", "chat_99", "Henning")

        calls = memory.append_message.call_args_list
        roles = [c[0][1] for c in calls]
        assert "user" in roles
        assert "assistant" in roles

    @pytest.mark.asyncio
    async def test_process_message_sets_username(self):
        """User name is registered in memory on each message."""
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=make_llm_text("Done"))

        memory = make_memory()
        semantic = MagicMock()
        semantic.entry_count = 0

        brain = make_brain(llm=llm, memory=memory, semantic=semantic)
        with patch("asyncio.create_task"):
            await brain.process_message("Hello", "chat_5", "Henning")

        memory.set_user_name.assert_called_once_with("chat_5", "Henning")


# ===========================================================================
# System prompt
# ===========================================================================

class TestSystemPrompt:
    def test_build_system_prompt_does_not_raise(self):
        """_build_system_prompt should complete without exceptions."""
        memory = make_memory()
        brain = make_brain(memory=memory)
        prompt = brain._build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_system_prompt_includes_grid_price(self):
        settings = make_settings()
        settings.grid_price_ct = 32
        memory = make_memory()
        brain = make_brain(memory=memory, settings=settings)
        prompt = brain._build_system_prompt()
        assert "32" in prompt
