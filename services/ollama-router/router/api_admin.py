"""Admin API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .models import PreloadRequest, UnloadRequest, PullRequest

router = APIRouter(prefix="/admin")


def _get_deps(request: Request):
    s = request.app.state
    return getattr(s, "node_manager"), getattr(s, "model_manager"), getattr(s, "settings")


@router.get("/nodes")
async def list_nodes(request: Request):
    nm, *_ = _get_deps(request)
    return {
        "nodes": [ns.model_dump() for ns in nm.nodes.values()]
    }


@router.get("/models")
async def list_models(request: Request):
    nm, *_ = _get_deps(request)
    models: dict[str, dict] = {}
    for ns in nm.get_online_nodes():
        for m in ns.available_models:
            if m not in models:
                models[m] = {"name": m, "available_on": [], "loaded_on": []}
            models[m]["available_on"].append(ns.name)
            if m in ns.loaded_models:
                models[m]["loaded_on"].append(ns.name)
    return {"models": list(models.values())}


@router.post("/preload")
async def preload(body: PreloadRequest, request: Request):
    nm, mm, _ = _get_deps(request)
    if body.node:
        ok = await mm.preload(body.model, body.node)
        if not ok:
            raise HTTPException(500, detail="Preload failed")
        return {"status": "ok", "model": body.model, "node": body.node}
    # Preload on first available node
    for ns in nm.get_online_nodes():
        if body.model in ns.available_models:
            ok = await mm.preload(body.model, ns.name)
            if ok:
                return {"status": "ok", "model": body.model, "node": ns.name}
    raise HTTPException(404, detail="No node has this model available")


@router.post("/unload")
async def unload(body: UnloadRequest, request: Request):
    nm, mm, _ = _get_deps(request)
    if body.node:
        ok = await mm.unload(body.model, body.node)
        if not ok:
            raise HTTPException(500, detail="Unload failed")
        return {"status": "ok", "model": body.model, "node": body.node}
    # Unload from all nodes
    results = []
    for ns in nm.get_online_nodes():
        if body.model in ns.loaded_models:
            ok = await mm.unload(body.model, ns.name)
            results.append({"node": ns.name, "ok": ok})
    return {"status": "ok", "results": results}


@router.post("/pull")
async def pull(body: PullRequest, request: Request):
    nm, mm, _ = _get_deps(request)
    if body.node:
        ok = await mm.pull(body.model, body.node)
        if not ok:
            raise HTTPException(500, detail="Pull failed")
        return {"status": "ok", "model": body.model, "node": body.node}
    # Pull on first available node
    for ns in nm.get_online_nodes():
        ok = await mm.pull(body.model, ns.name)
        if ok:
            return {"status": "ok", "model": body.model, "node": ns.name}
    raise HTTPException(503, detail="No available node for pull")


@router.get("/config")
async def get_config(request: Request):
    _, _, settings = _get_deps(request)
    return settings.model_dump()


@router.put("/config")
async def update_config(request: Request):
    from .config import reload_settings
    new_settings = reload_settings()
    request.app.state.settings = new_settings
    return {"status": "reloaded", "config": new_settings.model_dump()}
