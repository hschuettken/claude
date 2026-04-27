"""Agent Economy service configuration."""
from __future__ import annotations

import os


class Settings:
    # PostgreSQL
    db_url: str = os.getenv(
        "AGENT_ECONOMY_DB_URL",
        "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
    )
    # NATS
    nats_url: str = os.getenv("NATS_URL", "nats://192.168.0.50:4222")
    # Oracle
    oracle_url: str = os.getenv("ORACLE_URL", "http://192.168.0.50:8225")
    # Service
    port: int = int(os.getenv("AGENT_ECONOMY_PORT", "8240"))
    log_level: str = os.getenv("LOG_LEVEL", "info").upper()
    # JWT secret for Bifrost-style auth (agents authenticate to this API)
    jwt_secret: str = os.getenv("AGENT_ECONOMY_JWT_SECRET", "changeme-in-production")
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = int(os.getenv("AGENT_ECONOMY_JWT_EXPIRE_HOURS", "24"))
    # Rate limiting (requests per minute per agent)
    rate_limit_rpm: int = int(os.getenv("AGENT_ECONOMY_RATE_LIMIT_RPM", "120"))
    # Self-spawning: require approval for spawned agents beyond this count
    spawn_auto_approve_max: int = int(os.getenv("AGENT_ECONOMY_SPAWN_AUTO_APPROVE_MAX", "3"))
    # Default token budget for a new agent (0 = unlimited)
    default_token_budget: int = int(os.getenv("AGENT_ECONOMY_DEFAULT_TOKEN_BUDGET", "0"))


settings = Settings()
