"""FastAPI app — startup, shutdown, router registration."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .node_manager import NodeManager
from .model_manager import ModelManager
from .balancer import LoadBalancer
from .models import BalancerStrategy
from . import api_ollama, api_openai, api_admin, metrics

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger("ollama-router")

# Global state dict accessible via request.app.state
app_state: dict = {}


async def _register_with_oracle() -> None:
    """Best-effort Oracle registration."""
    import asyncio
    import httpx

    await asyncio.sleep(3)
    try:
        manifest = {
            "service_name": "ollama-router",
            "port": 11434,
            "description": "Multi-node Ollama load balancer — model affinity routing, OpenAI-compat API",
            "endpoints": [
                {"method": "GET", "path": "/health", "purpose": "Health check"},
                {
                    "method": "POST",
                    "path": "/api/generate",
                    "purpose": "Ollama generate",
                },
                {"method": "POST", "path": "/api/chat", "purpose": "Ollama chat"},
                {"method": "GET", "path": "/api/tags", "purpose": "List models"},
                {"method": "POST", "path": "/api/embeddings", "purpose": "Embeddings"},
                {
                    "method": "POST",
                    "path": "/v1/chat/completions",
                    "purpose": "OpenAI-compat chat",
                },
                {
                    "method": "GET",
                    "path": "/v1/models",
                    "purpose": "OpenAI-compat models",
                },
                {
                    "method": "POST",
                    "path": "/v1/embeddings",
                    "purpose": "OpenAI-compat embeddings",
                },
                {
                    "method": "GET",
                    "path": "/admin/nodes",
                    "purpose": "Admin: node status",
                },
                {
                    "method": "GET",
                    "path": "/admin/models",
                    "purpose": "Admin: loaded models",
                },
                {"method": "GET", "path": "/metrics", "purpose": "Prometheus metrics"},
            ],
            "nats_subjects": [],
            "source_paths": [
                {"repo": "claude", "paths": ["services/ollama-router/"]},
            ],
        }
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post("http://192.168.0.50:8225/oracle/register", json=manifest)
    except Exception:
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    settings = get_settings()
    nm = NodeManager(settings)
    mm = ModelManager(settings, nm)
    strategy = BalancerStrategy(settings.routing.default_strategy)
    bal = LoadBalancer(nm, strategy)

    app_state.update(
        {
            "settings": settings,
            "node_manager": nm,
            "model_manager": mm,
            "balancer": bal,
        }
    )
    # Set state attributes individually (Starlette 0.52+ treats _state as internal)
    for k, v in app_state.items():
        setattr(app.state, k, v)

    await nm.start()
    await mm.start()
    asyncio.create_task(_register_with_oracle())
    logger.info("Ollama Router started — %d nodes configured", len(settings.nodes))

    yield

    await mm.stop()
    await nm.stop()
    logger.info("Ollama Router stopped")


app = FastAPI(title="Ollama Router", version="0.1.0", lifespan=lifespan)

app.include_router(api_ollama.router)
app.include_router(api_openai.router)
app.include_router(api_admin.router)
app.include_router(metrics.router)


@app.get("/")
async def root():
    return {"name": "ollama-router", "version": "0.1.0"}
