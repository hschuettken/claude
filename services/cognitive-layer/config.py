"""Cognitive Layer service configuration."""
from __future__ import annotations

import os


class Settings:
    # PostgreSQL
    db_url: str = os.getenv(
        "COGNITIVE_DB_URL",
        "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
    )
    # LLM Router (never call Anthropic/OpenAI directly)
    llm_router_url: str = os.getenv("LLM_ROUTER_URL", "http://192.168.0.50:8070")
    llm_model: str = os.getenv("COGNITIVE_LLM_MODEL", "qwen2.5:3b")

    # NATS
    nats_url: str = os.getenv("NATS_URL", "nats://192.168.0.50:4222")

    # Orbit (nb9os API)
    orbit_url: str = os.getenv("NB9OS_API_URL", "http://192.168.0.50:8060")

    # GitHub
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    github_owner: str = os.getenv("GITHUB_OWNER", "hschuettken")

    # Oracle
    oracle_url: str = os.getenv("ORACLE_URL", "http://192.168.0.50:8225")

    # Service
    port: int = int(os.getenv("COGNITIVE_PORT", "8230"))
    log_level: str = os.getenv("LOG_LEVEL", "info").upper()

    # Cognitive Load thresholds
    open_threads_weight: float = 0.4
    overdue_tasks_weight: float = 0.4
    unprocessed_events_weight: float = 0.2
    open_threads_max: int = 20
    overdue_tasks_max: int = 10
    unprocessed_events_max: int = 50


settings = Settings()
