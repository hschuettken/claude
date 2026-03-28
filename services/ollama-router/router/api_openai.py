"""OpenAI-compatible API endpoints."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from .models import (
    OpenAIChatRequest, OpenAIEmbeddingRequest,
    OpenAIChatResponse, OpenAIChatChoice, OpenAIChatMessage,
    OpenAIEmbeddingResponse, OpenAIEmbeddingData, OpenAIModel,
)
from .task_classifier import classify_request
from .metrics import record_request

logger = logging.getLogger("ollama-router.api.openai")
router = APIRouter(prefix="/v1")


def _get_deps(request: Request):
    s = request.app.state
    return getattr(s, "node_manager"), getattr(s, "model_manager"), getattr(s, "balancer"), getattr(s, "settings")


@router.post("/chat/completions")
async def chat_completions(body: OpenAIChatRequest, request: Request):
    nm, mm, bal, settings = _get_deps(request)

    prompt = ""
    if body.messages:
        last = body.messages[-1]
        prompt = last.content if isinstance(last.content, str) else ""

    task_type, model = classify_request(
        body.model, prompt,
        request.headers.get("x-task-type"), settings,
    )
    task_str = task_type.value if task_type else "none"

    node = bal.select_node(model)
    if not node:
        raise HTTPException(503, detail=f"No available node for model {model}")

    # Translate to Ollama chat format
    ollama_body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": m.role, "content": m.content or ""} for m in body.messages],
        "stream": body.stream,
    }
    options: dict[str, Any] = {}
    if body.temperature is not None:
        options["temperature"] = body.temperature
    if body.top_p is not None:
        options["top_p"] = body.top_p
    if body.max_tokens is not None:
        options["num_predict"] = body.max_tokens
    if body.seed is not None:
        options["seed"] = body.seed
    if body.stop:
        options["stop"] = body.stop if isinstance(body.stop, list) else [body.stop]
    if options:
        ollama_body["options"] = options

    nm.increment_in_flight(node.name)
    mm.touch(model, node.name)
    start_time = time.monotonic()

    if body.stream:
        return await _stream_openai_chat(node, ollama_body, model, task_str, nm, start_time)

    # Non-streaming
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
            resp = await client.post(f"{node.url}/api/chat", json=ollama_body)
            resp.raise_for_status()
            data = resp.json()

        duration = time.monotonic() - start_time
        tps = 0.0
        if data.get("eval_count") and data.get("eval_duration"):
            tps = data["eval_count"] / (data["eval_duration"] / 1e9)
        record_request(model=model, task_type=task_str, node=node.name, duration_s=duration, tokens_per_sec=tps)

        msg = data.get("message", {})
        return OpenAIChatResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=model,
            choices=[OpenAIChatChoice(
                message=OpenAIChatMessage(role=msg.get("role", "assistant"), content=msg.get("content", "")),
                finish_reason="stop" if data.get("done") else None,
            )],
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
            },
        )
    except Exception as e:
        duration = time.monotonic() - start_time
        record_request(model=model, task_type=task_str, node=node.name, duration_s=duration, status="error")
        raise HTTPException(502, detail=str(e))
    finally:
        nm.decrement_in_flight(node.name)


async def _stream_openai_chat(node, ollama_body, model, task_str, nm, start_time):
    """Stream OpenAI SSE format from Ollama streaming response."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    async def generate() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
                async with client.stream("POST", f"{node.url}/api/chat", json=ollama_body) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        msg = data.get("message", {})
                        content = msg.get("content", "")
                        done = data.get("done", False)

                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {"content": content} if content else {},
                                "finish_reason": "stop" if done else None,
                            }],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n".encode()
                        if done:
                            yield b"data: [DONE]\n\n"
        except Exception as e:
            error = {"error": {"message": str(e), "type": "proxy_error"}}
            yield f"data: {json.dumps(error)}\n\n".encode()
        finally:
            nm.decrement_in_flight(node.name)
            duration = time.monotonic() - start_time
            record_request(model=model, task_type=task_str, node=node.name, duration_s=duration)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/embeddings")
async def embeddings(body: OpenAIEmbeddingRequest, request: Request):
    nm, mm, bal, settings = _get_deps(request)
    task_type, model = classify_request(
        body.model, "",
        request.headers.get("x-task-type") or "embedding", settings,
    )
    node = bal.select_node(model)
    if not node:
        raise HTTPException(503, detail=f"No available node for model {model}")

    inputs = body.input if isinstance(body.input, list) else [body.input]
    nm.increment_in_flight(node.name)
    mm.touch(model, node.name)

    try:
        data_list = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            for i, text in enumerate(inputs):
                resp = await client.post(
                    f"{node.url}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                resp.raise_for_status()
                emb = resp.json().get("embedding", [])
                data_list.append(OpenAIEmbeddingData(index=i, embedding=emb))

        return OpenAIEmbeddingResponse(
            data=data_list, model=model,
            usage={"prompt_tokens": sum(len(t.split()) for t in inputs), "total_tokens": sum(len(t.split()) for t in inputs)},
        )
    except Exception as e:
        raise HTTPException(502, detail=str(e))
    finally:
        nm.decrement_in_flight(node.name)


@router.get("/models")
async def list_models(request: Request):
    nm, *_ = _get_deps(request)
    models = set()
    for ns in nm.get_online_nodes():
        models.update(ns.available_models)
    return {
        "object": "list",
        "data": [OpenAIModel(id=m, created=0).model_dump() for m in sorted(models)],
    }
