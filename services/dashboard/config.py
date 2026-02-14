"""Dashboard-specific configuration."""

from __future__ import annotations

from shared.config import Settings as BaseSettings


class DashboardSettings(BaseSettings):
    # --- Dashboard server ---
    dashboard_port: int = 8085
    dashboard_title: str = "Homelab Dashboard"

    # --- Energy entities ---
    pv_power_entity: str = "sensor.inverter_input_power"
    grid_power_entity: str = "sensor.power_meter_active_power"
    battery_power_entity: str = "sensor.batteries_charge_discharge_power"
    battery_soc_entity: str = "sensor.batteries_state_of_capacity"
    house_power_entity: str = "sensor.shelly3em_main_channel_total_power"
    inverter_power_entity: str = "sensor.inverter_active_power"

    # --- EV entities ---
    ev_charge_power_entity: str = "sensor.amtron_meter_total_power_w"
    ev_session_energy_entity: str = "sensor.amtron_meter_total_energy_kwh"
    ev_soc_entity: str = "sensor.audi_a6_avant_e_tron_state_of_charge_comb"
    ev_range_entity: str = "sensor.audi_a6_avant_e_tron_range_comb"
    ev_plug_entity: str = "binary_sensor.audi_a6_avant_e_tron_plugged_in_comb"

    # --- EV control entities ---
    ev_charge_mode_entity: str = "input_select.ev_charge_mode"
    ev_target_soc_entity: str = "input_number.ev_target_soc_pct"
    ev_departure_time_entity: str = "input_datetime.ev_departure_time"
    ev_full_by_morning_entity: str = "input_boolean.ev_full_by_morning"

    # --- PV forecast entities ---
    pv_forecast_today_entity: str = "sensor.pv_ai_forecast_today_kwh"
    pv_forecast_tomorrow_entity: str = "sensor.pv_ai_forecast_tomorrow_kwh"
    pv_forecast_remaining_entity: str = "sensor.pv_ai_forecast_today_remaining_kwh"

    # --- Safe mode ---
    safe_mode_entity_id: str = "input_boolean.homelab_safe_mode"

    # --- Chat ---
    dashboard_user_name: str = "Dashboard"

    # --- Update intervals (seconds) ---
    ha_poll_interval: int = 10
    ui_refresh_interval: int = 3
