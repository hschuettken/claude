"""Digital Twin service configuration."""
from __future__ import annotations

import os


class Settings:
    # Service
    port: int = int(os.getenv("DIGITAL_TWIN_PORT", "8238"))
    log_level: str = os.getenv("LOG_LEVEL", "info").upper()

    # PostgreSQL (room registry + state snapshots)
    db_url: str = os.getenv(
        "DIGITAL_TWIN_DB_URL",
        "postgresql://homelab:homelab@192.168.0.80:5432/homelab",
    )

    # Home Assistant
    ha_url: str = os.getenv("HA_URL", "http://192.168.0.40:8123")
    ha_token: str = os.getenv("HA_TOKEN", "")

    # InfluxDB
    influxdb_url: str = os.getenv("INFLUXDB_URL", "http://192.168.0.66:8086")
    influxdb_token: str = os.getenv("INFLUXDB_TOKEN", "")
    influxdb_org: str = os.getenv("INFLUXDB_ORG", "nb9")
    influxdb_bucket: str = os.getenv("INFLUXDB_BUCKET", "hass")

    # NATS
    nats_url: str = os.getenv("NATS_URL", "nats://192.168.0.50:4222")

    # Oracle
    oracle_url: str = os.getenv("ORACLE_URL", "http://192.168.0.50:8225")

    # Energy tariffs (ct/kWh, fixed rates)
    tariff_import_ct: float = float(os.getenv("TARIFF_IMPORT_CT", "25.0"))
    tariff_export_ct: float = float(os.getenv("TARIFF_EXPORT_CT", "7.0"))

    # Home battery
    battery_capacity_kwh: float = float(os.getenv("BATTERY_CAPACITY_KWH", "7.0"))
    battery_max_power_kw: float = float(os.getenv("BATTERY_MAX_POWER_KW", "3.5"))

    # EV (Audi A6 e-tron)
    ev_capacity_kwh: float = float(os.getenv("EV_CAPACITY_KWH", "83.0"))
    ev_min_charge_power_kw: float = float(os.getenv("EV_MIN_CHARGE_POWER_KW", "1.4"))
    ev_max_charge_power_kw: float = float(os.getenv("EV_MAX_CHARGE_POWER_KW", "11.0"))

    # Simulation defaults
    house_base_consumption_kwh_per_hour: float = float(
        os.getenv("HOUSE_BASE_CONSUMPTION_KWH_H", "0.45")
    )
    # Pre-heat scenario: extra heating power during night (kW)
    preheat_power_kw: float = float(os.getenv("PREHEAT_POWER_KW", "2.0"))
    # Hours 1-6 (0-indexed): cheap tariff / low-demand window for pre-heating
    preheat_hours: list[int] = [1, 2, 3, 4, 5]

    # HA entity IDs for state ingestion
    ha_entity_pv_east_power: str = os.getenv(
        "HA_ENTITY_PV_EAST_POWER", "sensor.inverter_pv_east_power"
    )
    ha_entity_pv_west_power: str = os.getenv(
        "HA_ENTITY_PV_WEST_POWER", "sensor.inverter_pv_west_power"
    )
    ha_entity_battery_soc: str = os.getenv(
        "HA_ENTITY_BATTERY_SOC", "sensor.batteries_state_of_capacity"
    )
    ha_entity_battery_power: str = os.getenv(
        "HA_ENTITY_BATTERY_POWER", "sensor.batteries_charge_discharge_power"
    )
    ha_entity_grid_power: str = os.getenv(
        "HA_ENTITY_GRID_POWER", "sensor.power_meter_active_power"
    )
    ha_entity_house_consumption: str = os.getenv(
        "HA_ENTITY_HOUSE_CONSUMPTION", "sensor.shelly3em_main_channel_total_power"
    )
    ha_entity_ev_power: str = os.getenv(
        "HA_ENTITY_EV_POWER", "sensor.amtron_meter_total_power_w"
    )
    ha_entity_ev_soc: str = os.getenv(
        "HA_ENTITY_EV_SOC", "sensor.audi_a6_avant_e_tron_state_of_charge"
    )


settings = Settings()
