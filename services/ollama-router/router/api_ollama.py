"""Ollama-compatible API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from .models import (
    OllamaGenerateRequest, OllamaChatRequest, OllamaEmbeddingsRequest,
    OllamaPullRequest, OllamaDeleteRequest,
)
from .task_classifier import classify_request
from .proxy import proxy_streaming, proxy_non_streaming

logger = logging.getLogger("ollama-router.api.ollama")
router = APIRouter(prefix="/api")


def _get_deps(request: Request):
    s = request.app.state
    return getattr(s, "node_manager"), getattr(s, "model_manager"), getattr(s, "balancer"), getattr(s, "settings")


@router.post("/generate")
async def generate(body: OllamaGenerateRequest, request: Request):
    nm, mm, bal, settings = _get_deps(request)
    task_type, model = classify_request(
        body.model, body.prompt,
        request.headers.get("x-task-type"), settings,
    )
    task_str = task_type.value if task_type else "none"
    node = bal.select_node(model)
    if not node:
        raise HTTPException(503, detail=f"No available node for model {model}")

    payload = body.model_dump(exclude_none=True)
    payload["model"] = model

    if body.stream:
        return await proxy_streaming(node, "/api/generate", payload, nm, mm, model, task_str)
    return await proxy_non_streaming(node, "/api/generate", payload, nm, mm, model, task_str)


@router.post("/chat")
async def chat(body: OllamaChatRequest, request: Request):
    nm, mm, bal, settings = _get_deps(request)
    prompt = ""
    if body.messages:
        last = body.messages[-1]
        prompt = last.get("content", "") if isinstance(last, dict) else ""
    task_type, model = classify_request(
        body.model, prompt,
        request.headers.get("x-task-type"), settings,
    )
    task_str = task_type.value if task_type else "none"
    node = bal.select_node(model)
    if not node:
        raise HTTPException(503, detail=f"No available node for model {model}")

    payload = body.model_dump(exclude_none=True)
    payload["model"] = model

    if body.stream:
        return await proxy_streaming(node, "/api/chat", payload, nm, mm, model, task_str)
    return await proxy_non_streaming(node, "/api/chat", payload, nm, mm, model, task_str)


@router.post("/embeddings")
@router.post("/embed")
async def embeddings(body: OllamaEmbeddingsRequest, request: Request):
    nm, mm, bal, settings = _get_deps(request)
    task_type, model = classify_request(
        body.model, "",
        request.headers.get("x-task-type") or "embedding", settings,
    )
    task_str = task_type.value if task_type else "embedding"
    node = bal.select_node(model)
    if not node:
        raise HTTPException(503, detail=f"No available node for model {model}")

    payload = body.model_dump(exclude_none=True)
    payload["model"] = model
    return await proxy_non_streaming(node, "/api/embeddings", payload, nm, mm, model, task_str)


@router.get("/tags")
async def tags(request: Request):
    """Aggregate models from all nodes."""
    nm, *_ = _get_deps(request)
    all_models: dict[str, dict[str, Any]] = {}
    for ns in nm.get_online_nodes():
        for m in ns.available_models:
            if m not in all_models:
                all_models[m] = {"name": m, "nodes": []}
            all_models[m]["nodes"].append(ns.name)
    return {"models": list(all_models.values())}


@router.get("/ps")
async def ps(request: Request):
    """Aggregate loaded models from all nodes."""
    nm, *_ = _get_deps(request)
    loaded = []
    for ns in nm.get_online_nodes():
        for m in ns.loaded_models:
            loaded.append({"name": m, "node": ns.name})
    return {"models": loaded}


@router.post("/pull")
async def pull(body: OllamaPullRequest, request: Request):
    nm, mm, bal, _ = _get_deps(request)
    node_name = request.headers.get("x-node")
    if node_name and node_name in nm.nodes:
        node = nm.nodes[node_name]
    else:
        node = bal.select_node(body.name)
    if not node:
        raise HTTPException(503, detail="No available node for pull")
    ok = await mm.pull(body.name, node.name)
    if not ok:
        raise HTTPException(500, detail=f"Failed to pull {body.name}")
    return {"status": "success"}


@router.delete("/delete")
async def delete(body: OllamaDeleteRequest, request: Request):
    nm, *_ = _get_deps(request)
    node_name = request.headers.get("x-node")
    if not node_name:
        raise HTTPException(400, detail="X-Node header required for delete")
    ns = nm.nodes.get(node_name)
    if not ns:
        raise HTTPException(404, detail=f"Unknown node: {node_name}")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request("DELETE", f"{ns.url}/api/delete", json={"name": body.name})
            resp.raise_for_status()
            return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, detail=str(e))
