"""HEMS service configuration."""

from __future__ import annotations

from enum import Enum

from pydantic_settings import BaseSettings


class HEMSMode(str, Enum):
    auto = "auto"
    manual = "manual"
    off = "off"


class HEMSSettings(BaseSettings):
    # Core
    hems_mode: HEMSMode = HEMSMode.auto
    hems_db_url: str = "postgresql://homelab:homelab@192.168.0.80:5432/homelab"
    hems_orchestrator_url: str = "http://orchestrator:8000"
    hems_ha_token: str = ""

    # Redis
    redis_url: str = "redis://192.168.0.81:6379"

    # InfluxDB v2
    influxdb_url: str = "http://192.168.0.50:8086"
    influxdb_token: str = ""
    influxdb_org: str = "homelab"
    influxdb_bucket: str = "hems"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8210

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}
