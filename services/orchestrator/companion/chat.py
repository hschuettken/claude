"""ReAct loop engine for Kairos companion agent."""

import json
import logging
import time
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from companion.hot_state import HotStateSubscriber
from companion.memory import MemoryManager
from companion.persona import PersonaBuilder
from companion.tools import ToolRegistry

# Observability modules — imported lazily to avoid hard failures if not wired up
try:
    from companion.cost import CostTracker
except ImportError:
    CostTracker = None  # type: ignore[misc,assignment]

try:
    from companion.events import KairosEventPublisher
except ImportError:
    KairosEventPublisher = None  # type: ignore[misc,assignment]

try:
    from companion.metrics import KairosMetrics
except ImportError:
    KairosMetrics = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)

# RAGEngine imported lazily to avoid circular deps if rag.py not yet present
try:
    from companion.rag import RAGEngine
except ImportError:
    RAGEngine = None  # type: ignore[misc,assignment]


def _build_rag_addendum(rag_result: Any) -> str:
    """Build a system addendum from RAG retrieval results."""
    if not rag_result:
        return ""

    chunks = []
    # RAGEngine.retrieve returns a RetrievalResult with .chunks list
    if hasattr(rag_result, "chunks"):
        chunks = rag_result.chunks
    elif isinstance(rag_result, list):
        chunks = rag_result

    if not chunks:
        return ""

    lines = ["[Context from knowledge base]"]
    for chunk in chunks:
        if hasattr(chunk, "content"):
            content = chunk.content
        elif isinstance(chunk, dict):
            content = chunk.get("content", "")
        else:
            content = str(chunk)
        if content:
            lines.append(content)
            lines.append("---")

    return "\n".join(lines)


class ChatEngine:
    """
    Core ReAct loop engine for Kairos.

    Orchestrates: hot state + RAG + persona → LLM → tool execution → memory.
    Yields event dicts for streaming to callers.
    """

    def __init__(
        self,
        memory: MemoryManager,
        hot_state: HotStateSubscriber,
        tools: ToolRegistry,
        rag: Optional[Any],  # RAGEngine | None
        persona: PersonaBuilder,
        llm_router_url: str,
        max_iterations: int = 8,
        event_publisher: Optional[Any] = None,  # KairosEventPublisher | None
        metrics: Optional[Any] = None,  # KairosMetrics | None
        cost_tracker: Optional[Any] = None,  # CostTracker | None
    ) -> None:
        self.memory = memory
        self.hot_state = hot_state
        self.tools = tools
        self.rag = rag
        self.persona = persona
        self.llm_router_url = llm_router_url
        self.max_iterations = max_iterations
        self.event_publisher = event_publisher
        self.metrics = metrics
        self.cost_tracker = cost_tracker

    async def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Call LLM Router. Returns {content, tool_calls, usage}."""
        payload: dict[str, Any] = {
            "model": "quality",
            "messages": messages,
            "stream": False,
            "latency_mode": "low",
            "complexity_class": "medium",
            "cache": False,
        }
        if tool_schemas:
            payload["tools"] = tool_schemas

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{self.llm_router_url}/v1/chat/completions",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            # Normalise OpenAI-compat response → flat {content, tool_calls, usage}
            choices = data.get("choices") or []
            if choices:
                message = choices[0].get("message", {})
                return {
                    "content": message.get("content", "") or "",
                    "tool_calls": message.get("tool_calls") or [],
                    "usage": data.get("usage", {}),
                }
            # Fallback: router returned something unexpected — pass through as-is
            return data
        except httpx.HTTPError as exc:
            logger.error("llm_router_http_error", error=str(exc))
            raise
        except Exception as exc:
            logger.error("llm_router_call_failed", error=str(exc))
            raise

    async def chat(
        self,
        session_id: str,
        user_id: str,
        user_message: str,
        stream_cb: Optional[Any] = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Run the ReAct loop.

        Yields event dicts:
        - {"type": "thinking", "text": "..."}
        - {"type": "tool_call", "name": "...", "params": {...}}
        - {"type": "tool_result", "name": "...", "result": {...}}
        - {"type": "message", "role": "assistant", "content": "..."}
        - {"type": "done", "session_id": "...", "tokens_used": N}
        - {"type": "error", "message": "..."}
        """
        tokens_used = 0
        start_ts = time.monotonic()

        try:
            # 0. Cost gate — reject before doing any work if daily cap hit
            if self.cost_tracker is not None:
                try:
                    if await self.cost_tracker.is_cap_reached(user_id):
                        yield {"type": "error", "message": "Daily token cap reached"}
                        return
                except Exception as exc:
                    logger.warning(
                        "cost_tracker_cap_check_failed",
                        session_id=session_id,
                        error=str(exc),
                    )

            # 1. Save user message to memory
            await self.memory.save_message(session_id, "user", user_message)

            # Emit message_received event (token count unknown yet; use 0)
            if self.event_publisher is not None:
                try:
                    await self.event_publisher.message_received(user_id, session_id, 0)
                except Exception as exc:
                    logger.warning(
                        "event_publisher_message_received_failed", error=str(exc)
                    )

            # 2. Fetch hot state
            yield {"type": "thinking", "text": "Fetching home context..."}
            hot = await self.hot_state.get_hot_state(user_id)

            # 3. RAG retrieve on user message (top_k=5)
            rag_addendum = ""
            if self.rag is not None:
                try:
                    rag_result = await self.rag.retrieve(
                        query=user_message,
                        user_id=user_id,
                        session_id=session_id,
                        top_k=5,
                    )
                    rag_addendum = _build_rag_addendum(rag_result)
                except Exception as exc:
                    logger.warning("rag_retrieve_failed", error=str(exc))

            # 4. Get recent messages (last 20)
            recent = await self.memory.get_recent_messages(session_id, limit=20)

            # 5. Build system prompt
            tool_schemas = self.tools.get_tools_for_prompt()
            date_str = datetime.now(timezone.utc).isoformat(timespec="seconds")
            system_prompt = self.persona.build(
                hot, tools=tool_schemas, date_str=date_str
            )

            # 6. Build messages list
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
            ]

            # Inject RAG context as system addendum before history
            if rag_addendum:
                messages.append({"role": "system", "content": rag_addendum})

            # Add recent history (chronological order, skip if empty)
            for msg in recent:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                # Skip the message we're about to add (it was just saved)
                if role == "user" and content == user_message:
                    continue
                messages.append({"role": role, "content": content})

            # Add the new user message
            messages.append({"role": "user", "content": user_message})

            # 7. ReAct loop
            iteration = 0
            final_content = ""
            tool_calls_history: list[dict[str, Any]] = []

            while iteration < self.max_iterations:
                iteration += 1
                yield {"type": "thinking", "text": f"Reasoning... (step {iteration})"}

                try:
                    llm_response = await self._call_llm(messages, tool_schemas)
                except Exception as exc:
                    yield {"type": "error", "message": f"LLM call failed: {exc}"}
                    return

                usage = llm_response.get("usage", {})
                tokens_used += (
                    usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
                )

                response_tool_calls = llm_response.get("tool_calls") or []
                response_content = llm_response.get("content", "") or ""

                if not response_tool_calls:
                    # No more tool calls — final answer
                    final_content = response_content
                    break

                # Process tool calls
                tool_results_for_messages: list[dict[str, Any]] = []

                for tc in response_tool_calls:
                    # Normalise tool call structure (OpenAI format)
                    if isinstance(tc, dict):
                        tc_id = tc.get(
                            "id", f"tc_{iteration}_{len(tool_calls_history)}"
                        )
                        func = tc.get("function", tc)
                        tc_name = (
                            func.get("name", "")
                            if isinstance(func, dict)
                            else tc.get("name", "")
                        )
                        tc_args = (
                            func.get("arguments", {})
                            if isinstance(func, dict)
                            else tc.get("arguments", {})
                        )
                        if isinstance(tc_args, str):
                            try:
                                tc_args = json.loads(tc_args)
                            except json.JSONDecodeError:
                                tc_args = {}
                    else:
                        continue

                    # Derive service name from function name (format: service__endpoint)
                    tool_service = (
                        tc_name.split("__")[0] if "__" in tc_name else tc_name
                    )
                    endpoint = tc_args.get("endpoint", "/")
                    payload_params = tc_args.get("payload", {})

                    yield {
                        "type": "tool_call",
                        "name": tc_name,
                        "params": tc_args,
                        "tool_call_id": tc_id,
                    }
                    tool_calls_history.append(tc)

                    # Execute tool (auto-approve in headless mode)
                    tool_success = True
                    try:
                        result = await self.tools.execute(
                            tool_name=tool_service,
                            endpoint=endpoint,
                            payload=payload_params,
                            approval_cb=None,  # auto-approve; WS handler adds gates later
                        )
                    except Exception as exc:
                        result = {"result": None, "error": str(exc)}
                        tool_success = False

                    # Emit tool_called event
                    if self.event_publisher is not None:
                        try:
                            await self.event_publisher.tool_called(
                                user_id, session_id, tc_name, tool_success
                            )
                        except Exception as exc:
                            logger.warning(
                                "event_publisher_tool_called_failed", error=str(exc)
                            )

                    yield {
                        "type": "tool_result",
                        "name": tc_name,
                        "result": result,
                        "tool_call_id": tc_id,
                    }
                    tool_results_for_messages.append(
                        {
                            "tool_call_id": tc_id,
                            "name": tc_name,
                            "result": result,
                        }
                    )

                # Add assistant message with tool calls + tool results to conversation
                messages.append(
                    {
                        "role": "assistant",
                        "content": response_content,
                        "tool_calls": response_tool_calls,
                    }
                )
                for tr in tool_results_for_messages:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr["tool_call_id"],
                            "name": tr["name"],
                            "content": json.dumps(tr["result"]),
                        }
                    )
            else:
                # Hit max iterations without a final text response
                logger.warning("react_max_iterations_reached", session_id=session_id)
                final_content = "I've run through several reasoning steps. Here's what I found so far."

            # 8. Save assistant response to memory
            if final_content:
                await self.memory.save_message(
                    session_id,
                    "assistant",
                    final_content,
                    tool_calls=tool_calls_history,
                    token_count=tokens_used,
                )

            # 9. Observability: record cost, emit events, write metrics
            latency_ms = int((time.monotonic() - start_ts) * 1000)

            if self.cost_tracker is not None and tokens_used > 0:
                try:
                    cost_status = await self.cost_tracker.record(
                        user_id, session_id, tokens_used
                    )

                    # Emit cost events if needed
                    if self.event_publisher is not None:
                        if cost_status.capped:
                            try:
                                await self.event_publisher.cap_reached(
                                    user_id,
                                    cost_status.daily_tokens,
                                    cost_status.daily_cap,
                                )
                            except Exception as exc:
                                logger.warning(
                                    "event_publisher_cap_reached_failed", error=str(exc)
                                )
                        elif cost_status.warning:
                            try:
                                await self.event_publisher.cost_warning(
                                    user_id,
                                    cost_status.pct_used,
                                    cost_status.daily_tokens,
                                    cost_status.daily_cap,
                                )
                            except Exception as exc:
                                logger.warning(
                                    "event_publisher_cost_warning_failed",
                                    error=str(exc),
                                )

                    # Write cost snapshot to InfluxDB
                    if self.metrics is not None:
                        try:
                            await self.metrics.record_cost_snapshot(
                                user_id,
                                cost_status.daily_tokens,
                                cost_status.daily_cap,
                            )
                        except Exception as exc:
                            logger.warning(
                                "metrics_record_cost_snapshot_failed", error=str(exc)
                            )

                except Exception as exc:
                    logger.warning(
                        "cost_tracker_record_failed",
                        session_id=session_id,
                        error=str(exc),
                    )

            # Emit response_sent event
            if self.event_publisher is not None:
                try:
                    await self.event_publisher.response_sent(
                        user_id, session_id, tokens_used, latency_ms
                    )
                except Exception as exc:
                    logger.warning(
                        "event_publisher_response_sent_failed", error=str(exc)
                    )

            # Write response metrics to InfluxDB
            if self.metrics is not None:
                try:
                    await self.metrics.record_response(
                        user_id,
                        tokens_used,
                        latency_ms,
                        tool_calls_count=len(tool_calls_history),
                    )
                except Exception as exc:
                    logger.warning("metrics_record_response_failed", error=str(exc))

            # 10. Yield final message + done
            yield {
                "type": "message",
                "role": "assistant",
                "content": final_content,
            }
            yield {
                "type": "done",
                "session_id": session_id,
                "tokens_used": tokens_used,
            }

        except Exception as exc:
            logger.error("chat_engine_error", session_id=session_id, error=str(exc))
            yield {"type": "error", "message": str(exc)}
