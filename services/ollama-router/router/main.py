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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("ollama-router")

# Global state dict accessible via request.app.state
app_state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    nm = NodeManager(settings)
    mm = ModelManager(settings, nm)
    strategy = BalancerStrategy(settings.routing.default_strategy)
    bal = LoadBalancer(nm, strategy)

    app_state.update({
        "settings": settings,
        "node_manager": nm,
        "model_manager": mm,
        "balancer": bal,
    })
    app.state._state = app_state

    await nm.start()
    await mm.start()
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
