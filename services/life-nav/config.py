"""Life Navigation System service configuration."""
from __future__ import annotations

import os


class Settings:
    # PostgreSQL
    db_url: str = os.getenv(
        "LIFE_NAV_DB_URL",
        "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
    )
    # NATS
    nats_url: str = os.getenv("NATS_URL", "nats://192.168.0.50:4222")
    # Oracle
    oracle_url: str = os.getenv("ORACLE_URL", "http://192.168.0.50:8225")
    # Service
    port: int = int(os.getenv("LIFE_NAV_PORT", "8243"))
    log_level: str = os.getenv("LOG_LEVEL", "info").upper()

    # Monte Carlo defaults
    mc_simulations: int = int(os.getenv("LIFE_NAV_MC_SIMULATIONS", "1000"))
    mc_return_mean: float = float(os.getenv("LIFE_NAV_MC_RETURN_MEAN", "0.07"))
    mc_return_std: float = float(os.getenv("LIFE_NAV_MC_RETURN_STD", "0.15"))
    mc_inflation_mean: float = float(os.getenv("LIFE_NAV_MC_INFLATION_MEAN", "0.03"))
    mc_inflation_std: float = float(os.getenv("LIFE_NAV_MC_INFLATION_STD", "0.01"))

    # Default user (single-user homelab)
    default_user: str = os.getenv("LIFE_NAV_USER", "henning")


settings = Settings()
