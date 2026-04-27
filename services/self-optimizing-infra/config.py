"""Self-Optimizing Infrastructure service configuration."""
from __future__ import annotations

import os


class Settings:
    # PostgreSQL
    db_url: str = os.getenv(
        "SOI_DB_URL",
        "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
    )
    # NATS
    nats_url: str = os.getenv("NATS_URL", "nats://192.168.0.50:4222")
    # Oracle
    oracle_url: str = os.getenv("ORACLE_URL", "http://192.168.0.50:8225")
    # Service
    port: int = int(os.getenv("SOI_PORT", "8242"))
    log_level: str = os.getenv("LOG_LEVEL", "info").upper()

    # Proxmox API (optional)
    proxmox_url: str = os.getenv("PROXMOX_URL", "https://192.168.0.10:8006")
    proxmox_token_id: str = os.getenv("PROXMOX_TOKEN_ID", "")
    proxmox_token_secret: str = os.getenv("PROXMOX_TOKEN_SECRET", "")
    proxmox_verify_ssl: bool = os.getenv("PROXMOX_VERIFY_SSL", "false").lower() == "true"

    # Bootstrap bridge (node manager REST API)
    bootstrap_url: str = os.getenv("BOOTSTRAP_URL", "http://192.168.0.50:8235")

    # Ops-bridge API (deploy / service control)
    ops_bridge_url: str = os.getenv("OPS_BRIDGE_URL", "http://192.168.0.50:8220")
    ops_bridge_token: str = os.getenv("OPS_BRIDGE_TOKEN", "")

    # K3s / Kubernetes API
    k3s_api_url: str = os.getenv("K3S_API_URL", "https://192.168.0.60:6443")
    k3s_token: str = os.getenv("K3S_TOKEN", "")

    # Decision engine
    heartbeat_timeout_seconds: int = int(os.getenv("SOI_HEARTBEAT_TIMEOUT_S", "300"))  # 5min
    decision_loop_interval_seconds: int = int(os.getenv("SOI_DECISION_LOOP_S", "60"))
    l1_poll_interval_seconds: int = int(os.getenv("SOI_L1_POLL_S", "120"))

    # Evolution
    evolution_day_of_month: int = int(os.getenv("SOI_EVOLUTION_DAY", "1"))  # run on 1st of month

    # Chaos testing
    chaos_enabled: bool = os.getenv("SOI_CHAOS_ENABLED", "false").lower() == "true"
    chaos_schedule_cron: str = os.getenv("SOI_CHAOS_CRON", "0 3 * * 0")  # Sunday 03:00
    chaos_max_kill_fraction: float = float(os.getenv("SOI_CHAOS_MAX_KILL_FRACTION", "0.3"))


settings = Settings()
