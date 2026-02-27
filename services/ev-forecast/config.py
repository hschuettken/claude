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
    # Default consumption — used as fallback until enough real data is collected.
    # The service calculates actual consumption dynamically from mileage + SoC changes.
    ev_consumption_kwh_per_100km: float = 22.0

    # --- Audi Connect account mode ---
    # true  = single account (Henning only, direct sensors — recommended)
    # false = dual account (Henning + Nicole, requires combined _comb template sensors in HA)
    audi_single_account: bool = True

    # --- EV sensors ---
    # Single-account defaults use direct Audi Connect entities (no _comb suffix).
    # Dual-account mode should override these with combined _comb template sensors.
    ev_soc_entity: str = "sensor.audi_a6_avant_e_tron_state_of_charge"
    ev_range_entity: str = "sensor.audi_a6_avant_e_tron_range"
    ev_charging_entity: str = "sensor.audi_a6_avant_e_tron_charging_state"
    ev_plug_entity: str = "sensor.audi_a6_avant_e_tron_plug_state"
    ev_mileage_entity: str = "sensor.audi_a6_avant_e_tron_mileage"
    ev_remaining_charge_entity: str = "sensor.audi_a6_avant_e_tron_remaining_charge_time"
    ev_active_account_entity: str = ""  # Only needed in dual-account mode
    ev_climatisation_entity: str = "sensor.audi_a6_avant_e_tron_climatisation_state"

    # --- Audi Connect accounts (needed for cloud data refresh via VIN) ---
    audi_account1_name: str = "Henning"
    audi_account1_vin: str = ""
    # Second account — only needed when audi_single_account=false
    audi_account2_name: str = "Nicole"
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
    calendar_prefix_henning: str = "H:"
    calendar_prefix_nicole: str = "N:"

    # Nicole's default commute (Mon-Thu) in km one way
    nicole_commute_km: float = 22.0
    nicole_commute_days: str = "mon,tue,wed,thu"  # comma-separated
    nicole_departure_time: str = "07:00"
    nicole_arrival_time: str = "18:00"

    # Henning thresholds for train vs car
    henning_train_threshold_km: float = 350.0

    # Known destinations with one-way distances (km) — JSON string
    # Format: {"Münster": 60, "Aachen": 80, "STR": 500, "Stuttgart": 500, ...}
    known_destinations: str = '{"Münster": 60, "Muenster": 60, "MS": 60, "Aachen": 80, "AC": 80, "Köln": 100, "Koeln": 100, "Düsseldorf": 80, "Duesseldorf": 80, "Dortmund": 80, "STR": 500, "Stuttgart": 500, "MUC": 500, "München": 500, "Muenchen": 500, "Berlin": 450, "BER": 450, "Hamburg": 300, "HAM": 300, "Frankfurt": 250, "FRA": 250, "Lengerich": 22, "Hopsten": 14, "Ibbenbüren": 10, "Ibbenbueren": 10, "Kathrin": 14, "Mareike": 10, "Vanne": 263}'

    # Activities where the person does NOT use the EV (e.g. takes bike) — JSON string
    # Format: {"Kegeln": "Henning"} means Henning bikes to Kegeln
    no_ev_activities: str = '{"Kegeln": "Henning"}'

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
    planning_horizon_days: int = 7

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
    
    # Audi Connect integration (optional, leave empty to disable)
    audi_vin: str = ""  # Vehicle VIN for audiconnect.set_target_soc (auto-detected if empty)
    audi_set_target_soc: bool = True  # Enable automatic Audi target SoC control
    
    # Wallbox/home charging detection (to prevent changing Audi settings when charging away)
    wallbox_vehicle_state_entity: str = "sensor.amtron_vehicle_state_raw"  # Amtron vehicle state

    # --- Scheduling ---
    plan_update_minutes: int = 30      # Re-evaluate plan every N minutes
    vehicle_check_minutes: int = 15    # Check vehicle state every N minutes

    # --- MQTT integration ---
    # Subscribe to orchestrator responses for trip clarifications
    orchestrator_response_topic: str = "homelab/ev-forecast/trip-response"
    # Subscribe to learned knowledge updates from orchestrator
    knowledge_update_topic: str = "homelab/orchestrator/knowledge-update"
