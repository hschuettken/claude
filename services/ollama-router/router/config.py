"""Configuration loader — YAML + env overrides via Pydantic Settings."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class NodeCfg(BaseModel):
    name: str
    url: str
    tags: list[str] = []
    max_concurrent: int = 2
    default_models: list[str] = []


class RoutingCfg(BaseModel):
    default_strategy: str = "model_affinity"
    task_model_map: dict[str, list[str]] = {}


class LifecycleCfg(BaseModel):
    idle_unload_minutes: int = 15
    preload_on_startup: bool = True
    auto_pull: bool = False
    health_check_interval: int = 10


class MetricsCfg(BaseModel):
    enabled: bool = True
    prometheus_path: str = "/metrics"


class ServerCfg(BaseModel):
    host: str = "0.0.0.0"
    port: int = 11434


class Settings(BaseSettings):
    nodes: list[NodeCfg] = []
    routing: RoutingCfg = RoutingCfg()
    lifecycle: LifecycleCfg = LifecycleCfg()
    metrics: MetricsCfg = MetricsCfg()
    server: ServerCfg = ServerCfg()

    model_config = {"env_prefix": "OLLAMA_ROUTER_", "env_nested_delimiter": "__"}


def load_config(path: str | None = None) -> Settings:
    """Load config from YAML file, then overlay env vars."""
    config_path = path or os.getenv("OLLAMA_ROUTER_CONFIG", "config.yaml")
    data: dict[str, Any] = {}
    p = Path(config_path)
    if p.exists():
        with open(p) as f:
            data = yaml.safe_load(f) or {}
    return Settings(**data)


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings


def reload_settings(path: str | None = None) -> Settings:
    global _settings
    _settings = load_config(path)
    return _settings
