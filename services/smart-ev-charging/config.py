"""Service-specific settings for smart-ev-charging."""

from shared.config import Settings as BaseSettings


class EVChargingSettings(BaseSettings):
    """All configuration for the smart EV charging service.

    Inherits shared settings (HA, InfluxDB, MQTT, etc.) and adds
    EV-charging-specific parameters.  Every field can be overridden
    via an environment variable with the same (upper-case) name.
    """

    # --- Wallbox entity IDs (Amtron via Modbus) ---
    wallbox_vehicle_state_entity: str = "sensor.amtron_vehicle_state_raw"
    wallbox_power_entity: str = "sensor.amtron_meter_total_power_w"
    wallbox_energy_session_entity: str = "sensor.amtron_charged_energy_session_kwh"
    wallbox_hems_power_number: str = "number.amtron_hems_power_limit_w"

    # --- Grid metering (Shelly 3EM) ---
    # Positive = importing from grid, negative = exporting to grid
    grid_power_entity: str = "sensor.shelly3em_main_channel_total_power"

    # --- PV production ---
    pv_east_power_entity: str = "sensor.inverter_pv_east_power"
    pv_west_power_entity: str = "sensor.inverter_pv_west_power"

    # --- HA helper entity IDs ---
    charge_mode_entity: str = "input_select.ev_charge_mode"
    full_by_morning_entity: str = "input_boolean.ev_full_by_morning"
    departure_time_entity: str = "input_datetime.ev_departure_time"
    target_energy_entity: str = "input_number.ev_target_energy_kwh"
    battery_capacity_entity: str = "input_number.ev_battery_capacity_kwh"

    # --- Wallbox power limits ---
    wallbox_max_power_w: int = 11000  # 16A x 3ph x 230V
    wallbox_min_power_w: int = 4200   # 6A x 3ph x 230V
    eco_charge_power_w: int = 5000    # ~7A x 3ph x 230V

    # --- PV surplus control ---
    grid_reserve_w: int = 200       # Buffer to keep slight export (avoid import)
    surplus_start_hysteresis_w: int = 300  # Extra surplus needed to START charging
    ramp_step_w: int = 500          # Max power change per control cycle

    # --- Economics (ct/kWh) ---
    grid_price_ct: float = 25.0       # Fixed grid buy price
    feed_in_tariff_ct: float = 7.0    # Feed-in revenue per kWh
    reimbursement_ct: float = 25.0    # Employer pays back per kWh charged

    # --- Timing ---
    control_interval_seconds: int = 30
