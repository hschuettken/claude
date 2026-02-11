"""Service-specific settings for ev-forecast."""

from shared.config import Settings as BaseSettings


class EVForecastSettings(BaseSettings):
    """Configuration for the EV forecast and charging planner.

    Inherits shared settings (HA, InfluxDB, MQTT, etc.) and adds
    EV-specific parameters for vehicle monitoring, trip prediction,
    and charging plan generation.
    """

    # --- EV Battery specs ---
    ev_battery_capacity_gross_kwh: float = 83.0   # Audi A6 e-tron gross
    ev_battery_capacity_net_kwh: float = 76.0     # Usable capacity
    ev_consumption_kwh_per_100km: float = 22.0    # Average mileage

    # --- Audi Connect — Account 1 (Hans) ---
    audi_account1_name: str = "Hans"
    audi_account1_soc_entity: str = "sensor.audi_a6_e_tron_state_of_charge"
    audi_account1_range_entity: str = "sensor.audi_a6_e_tron_range"
    audi_account1_charging_entity: str = "sensor.audi_a6_e_tron_charging_state"
    audi_account1_plug_entity: str = "sensor.audi_a6_e_tron_plug_state"
    audi_account1_mileage_entity: str = "sensor.audi_a6_e_tron_mileage"
    audi_account1_remaining_charge_entity: str = "sensor.audi_a6_e_tron_remaining_charge_time"
    audi_account1_vin: str = ""  # VIN for service calls

    # --- Audi Connect — Account 2 (Nicole) ---
    audi_account2_name: str = "Nicole"
    audi_account2_soc_entity: str = "sensor.audi_a6_e_tron_state_of_charge_2"
    audi_account2_range_entity: str = "sensor.audi_a6_e_tron_range_2"
    audi_account2_charging_entity: str = "sensor.audi_a6_e_tron_charging_state_2"
    audi_account2_plug_entity: str = "sensor.audi_a6_e_tron_plug_state_2"
    audi_account2_mileage_entity: str = "sensor.audi_a6_e_tron_mileage_2"
    audi_account2_remaining_charge_entity: str = "sensor.audi_a6_e_tron_remaining_charge_time_2"
    audi_account2_vin: str = ""

    # --- Refresh intervals ---
    audi_refresh_interval_minutes: int = 30  # How often to try refreshing data
    audi_stale_threshold_minutes: int = 60   # Data older than this triggers refresh

    # --- Google Calendar ---
    google_calendar_credentials_file: str = ""
    google_calendar_credentials_json: str = ""
    google_calendar_family_id: str = ""

    # --- Trip prediction ---
    # Calendar event prefixes for identifying who drives
    calendar_prefix_hans: str = "H:"
    calendar_prefix_nicole: str = "N:"

    # Nicole's default commute (Mon-Thu) in km one way
    nicole_commute_km: float = 22.0
    nicole_commute_days: str = "mon,tue,wed,thu"  # comma-separated
    nicole_departure_time: str = "07:00"
    nicole_arrival_time: str = "18:00"

    # Hans thresholds for train vs car
    hans_train_threshold_km: float = 350.0

    # Known destinations with one-way distances (km) — JSON string
    # Format: {"Münster": 60, "Aachen": 80, "STR": 500, "Stuttgart": 500, ...}
    known_destinations: str = '{"Münster": 60, "Muenster": 60, "MS": 60, "Aachen": 80, "AC": 80, "Köln": 100, "Koeln": 100, "Düsseldorf": 80, "Duesseldorf": 80, "Dortmund": 80, "STR": 500, "Stuttgart": 500, "MUC": 500, "München": 500, "Muenchen": 500, "Berlin": 450, "BER": 450, "Hamburg": 300, "HAM": 300, "Frankfurt": 250, "FRA": 250, "Lengerich": 22}'

    # --- Geocoding for unknown destinations ---
    # Home coordinates (auto-detected from HA if 0)
    home_latitude: float = 0.0
    home_longitude: float = 0.0
    # Road factor: multiplier from straight-line to road distance (1.3 = 30% longer)
    geocoding_road_factor: float = 1.3

    # --- Charging plan ---
    min_soc_pct: float = 20.0         # Never plan below this SoC
    buffer_soc_pct: float = 10.0      # Extra buffer above minimum needed
    min_arrival_soc_pct: float = 15.0  # Min SoC when arriving at destination
    default_assumed_soc_pct: float = 50.0  # Assumed SoC when actual is unknown

    # How far ahead to plan (days)
    planning_horizon_days: int = 3

    # --- Urgency thresholds ---
    critical_urgency_hours: float = 2.0  # departure within this → critical
    high_urgency_hours: float = 6.0      # departure within this → high urgency
    fast_mode_threshold_kwh: float = 15.0  # deficit above this → Fast instead of Eco
    early_departure_hour: int = 10  # tomorrow departure before this hour → charge overnight

    # --- HA helper entities (written by this service) ---
    charge_mode_entity: str = "input_select.ev_charge_mode"
    full_by_morning_entity: str = "input_boolean.ev_full_by_morning"
    departure_time_entity: str = "input_datetime.ev_departure_time"
    target_energy_entity: str = "input_number.ev_target_energy_kwh"

    # --- Scheduling ---
    plan_update_minutes: int = 30      # Re-evaluate plan every N minutes
    vehicle_check_minutes: int = 15    # Check vehicle state every N minutes

    # --- MQTT integration ---
    # Subscribe to orchestrator responses for trip clarifications
    orchestrator_response_topic: str = "homelab/ev-forecast/trip-response"
