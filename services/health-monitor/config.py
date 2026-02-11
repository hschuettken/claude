"""Health monitor service configuration."""

from shared.config import Settings as BaseSettings


class HealthMonitorSettings(BaseSettings):
    """All configuration for the health-monitor service."""

    # --- Telegram alerting ---
    telegram_bot_token: str = ""
    # Comma-separated Telegram chat IDs to receive alerts
    telegram_alert_chat_ids: str = ""

    # --- Services to monitor ---
    # Comma-separated service names (must match MQTT heartbeat service names)
    monitored_services: str = "orchestrator,pv-forecast,smart-ev-charging,ev-forecast"

    # --- Monitoring intervals ---
    # How long without a heartbeat before a service is considered offline
    heartbeat_timeout_seconds: int = 300  # 5 minutes

    # How often to run infrastructure checks (HA, MQTT, InfluxDB)
    infrastructure_check_minutes: int = 5

    # How often to run diagnose.py inside service containers
    diagnostic_run_minutes: int = 30

    # How often to check Docker container health status
    docker_check_minutes: int = 2

    # --- Alert behaviour ---
    # Don't re-alert for the same issue within this window
    alert_cooldown_minutes: int = 30

    # Send a daily summary at this hour (local time, 0-23; -1 to disable)
    daily_summary_hour: int = 8

    # --- HTTP ---
    http_check_timeout_seconds: float = 10.0  # timeout for HA/InfluxDB health checks

    # --- Docker ---
    docker_socket: str = "/var/run/docker.sock"
    # Compose project name (used to find containers)
    compose_project: str = ""  # Auto-detected if empty

    # --- HA entities to watch for staleness ---
    # Comma-separated entity IDs; alert if any become "unavailable" or "unknown"
    watched_entities: str = (
        "sensor.inverter_input_power,"
        "sensor.power_meter_active_power,"
        "sensor.batteries_state_of_capacity"
    )
    entity_check_minutes: int = 10
