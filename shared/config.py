"""Central configuration loaded from environment variables / .env file.

All services inherit these base settings. Individual services can extend
by subclassing Settings and adding their own fields.

Usage:
    from shared.config import Settings
    settings = Settings()
    print(settings.ha_url)

To extend in a service:
    from shared.config import Settings as BaseSettings

    class MyServiceSettings(BaseSettings):
        my_custom_var: str = "default"
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Home Assistant ---
    ha_url: str = "http://homeassistant.local:8123"
    ha_token: str = ""  # Long-lived access token

    # --- InfluxDB v2 ---
    influxdb_url: str = "http://influxdb:8086"
    influxdb_token: str = ""
    influxdb_org: str = "homelab"
    influxdb_bucket: str = "hass"

    # --- MQTT ---
    mqtt_host: str = "mqtt"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""

    # --- AI / LLM ---
    ollama_url: str = "http://ollama:11434"
    openai_api_key: str = ""
    anthropic_api_key: str = ""

    # --- General ---
    log_level: str = "INFO"
    timezone: str = "Europe/Berlin"
    heartbeat_interval_seconds: int = 60  # MQTT heartbeat interval (0 to disable)
