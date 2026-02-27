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

    # --- EV battery (Audi Connect / We Connect) ---
    # SoC sensor — use direct Audi Connect entity (single-account mode)
    # or combined _comb entity (dual-account mode)
    ev_soc_entity: str = "sensor.audi_a6_avant_e_tron_state_of_charge"
    ev_battery_capacity_entity: str = "input_number.ev_battery_capacity_kwh"

    # --- Grid connection meter ---
    # Positive = exporting to grid, negative = importing from grid
    grid_power_entity: str = "sensor.power_meter_active_power"

    # --- Household consumption (Shelly 3EM, always positive) ---
    house_power_entity: str = "sensor.shelly3em_main_channel_total_power"

    # --- PV production ---
    pv_power_entity: str = "sensor.inverter_input_power"

    # --- Home battery (7 kWh, 3.5 kW max charge/discharge) ---
    # positive = charging, negative = discharging
    battery_power_entity: str = "sensor.batteries_charge_discharge_power"
    battery_soc_entity: str = "sensor.batteries_state_of_capacity"
    battery_min_soc_pct: float = 20.0       # Floor — never drain below this for EV
    battery_ev_assist_max_w: float = 3500.0  # Max battery discharge rate for EV assist
    battery_capacity_kwh: float = 7.0        # Home battery usable capacity
    battery_target_eod_soc_pct: float = 90.0 # Acceptable end-of-day battery SoC

    # --- PV forecast (optional — for battery-aware decisions) ---
    pv_forecast_remaining_entity: str = "sensor.pv_ai_forecast_today_remaining_kwh"
    pv_forecast_tomorrow_entity: str = "sensor.pv_ai_forecast_tomorrow_kwh"
    pv_forecast_good_kwh: float = 15.0  # Above this = "good day", allow more battery use
    # Fraction of tomorrow's PV forecast usable before 13:00 (morning hours)
    # In Germany ~40-50% of daily production is before 13:00 in spring/summer
    pv_morning_fraction: float = 0.45
    # Charger efficiency loss (cable, conversion) — conservative 90%
    charger_efficiency: float = 0.90

    # --- HA helper entity IDs ---
    charge_mode_entity: str = "input_select.ev_charge_mode"
    full_by_morning_entity: str = "input_boolean.ev_full_by_morning"
    departure_time_entity: str = "input_datetime.ev_departure_time"
    target_soc_entity: str = "input_number.ev_target_soc_pct"
    target_energy_entity: str = "input_number.ev_target_energy_kwh"

    # --- Wallbox power limits ---
    wallbox_max_power_w: int = 11000  # 16A x 3ph x 230V
    wallbox_min_power_w: int = 3600   # ~5.2A x 3ph x 230V (lowered for battery-assist)
    eco_charge_power_w: int = 5000    # ~7A x 3ph x 230V

    # --- PV surplus control ---
    grid_reserve_w: int = 200       # Buffer to keep slight export (avoid import)
    surplus_start_hysteresis_w: int = 300  # Extra surplus needed to START charging
    ramp_step_w: int = 500          # Max power change per control cycle

    # --- Economics (ct/kWh) ---
    # Fixed prices — no EPEX spot market, just flat rates
    grid_price_ct: float = 25.0       # Fixed grid import price
    feed_in_tariff_ct: float = 7.0    # Grid export revenue per kWh
    reimbursement_ct: float = 25.0    # Employer reimburses per kWh charged

    # --- Timing ---
    control_interval_seconds: int = 30
