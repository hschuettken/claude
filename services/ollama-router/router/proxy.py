"""Request proxying with streaming support."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse, JSONResponse

from .models import NodeState
from .metrics import record_request
from .node_manager import NodeManager
from .model_manager import ModelManager

logger = logging.getLogger("ollama-router.proxy")


async def proxy_streaming(
    node: NodeState,
    path: str,
    body: dict[str, Any],
    node_manager: NodeManager,
    model_manager: ModelManager,
    model: str = "",
    task_type: str = "",
) -> StreamingResponse:
    """Proxy a streaming request to a node, forwarding tokens as they arrive."""
    url = f"{node.url}{path}"
    model = model or body.get("model", "unknown")
    node_manager.increment_in_flight(node.name)
    model_manager.touch(model, node.name)

    start_time = time.monotonic()
    first_token_time: float | None = None
    token_count = 0

    async def stream_generator() -> AsyncIterator[bytes]:
        nonlocal first_token_time, token_count
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                async with client.stream("POST", url, json=body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if first_token_time is None:
                            first_token_time = time.monotonic()
                        # Count tokens (approximate from response field)
                        try:
                            data = json.loads(line)
                            if data.get("response") or data.get("message", {}).get("content"):
                                token_count += 1
                        except (json.JSONDecodeError, AttributeError):
                            pass
                        yield line.encode() + b"\n"
        except httpx.HTTPStatusError as e:
            error_body = {"error": f"Upstream error: {e.response.status_code}"}
            yield json.dumps(error_body).encode() + b"\n"
        except Exception as e:
            error_body = {"error": f"Proxy error: {str(e)}"}
            yield json.dumps(error_body).encode() + b"\n"
        finally:
            node_manager.decrement_in_flight(node.name)
            duration = time.monotonic() - start_time
            ttft = (first_token_time - start_time) if first_token_time else 0
            tps = token_count / duration if duration > 0 else 0
            record_request(
                model=model, task_type=task_type, node=node.name,
                duration_s=duration, tokens_per_sec=tps, ttft_s=ttft,
            )

    return StreamingResponse(
        stream_generator(),
        media_type="application/x-ndjson",
    )


async def proxy_non_streaming(
    node: NodeState,
    path: str,
    body: dict[str, Any],
    node_manager: NodeManager,
    model_manager: ModelManager,
    model: str = "",
    task_type: str = "",
) -> JSONResponse:
    """Proxy a non-streaming request."""
    url = f"{node.url}{path}"
    model = model or body.get("model", "unknown")
    node_manager.increment_in_flight(node.name)
    model_manager.touch(model, node.name)
    start_time = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            duration = time.monotonic() - start_time
            data = resp.json()

            # Extract perf info if available
            tps = 0.0
            if "eval_count" in data and "eval_duration" in data and data["eval_duration"] > 0:
                tps = data["eval_count"] / (data["eval_duration"] / 1e9)

            record_request(
                model=model, task_type=task_type, node=node.name,
                duration_s=duration, tokens_per_sec=tps,
            )
            return JSONResponse(content=data)
    except httpx.HTTPStatusError as e:
        duration = time.monotonic() - start_time
        record_request(model=model, task_type=task_type, node=node.name, duration_s=duration, status="error")
        return JSONResponse(content={"error": f"Upstream error: {e.response.status_code}"}, status_code=e.response.status_code)
    except Exception as e:
        duration = time.monotonic() - start_time
        record_request(model=model, task_type=task_type, node=node.name, duration_s=duration, status="error")
        return JSONResponse(content={"error": str(e)}, status_code=502)
    finally:
        node_manager.decrement_in_flight(node.name)


async def proxy_get(node: NodeState, path: str) -> JSONResponse:
    """Proxy a GET request."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(f"{node.url}{path}")
            resp.raise_for_status()
            return JSONResponse(content=resp.json())
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=502)
