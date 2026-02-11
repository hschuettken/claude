"""PV forecast service configuration.

Extends the base Settings with PV-specific configuration.
All values are read from environment variables / .env file.
"""

from shared.config import Settings as BaseSettings


class PVForecastSettings(BaseSettings):
    # --- PV Array: East ---
    # Energy entity must be a total_increasing cumulative kWh sensor (e.g.
    # a Riemann sum integration of the array's power sensor).
    pv_east_energy_entity_id: str = ""  # e.g. sensor.inverter_pv_east_energy
    pv_east_capacity_kwp: float = 0.0  # Peak capacity in kWp
    pv_east_azimuth: float = 90.0  # Degrees: 0=South, 90=East, -90=West, 180=North
    pv_east_tilt: float = 30.0  # Panel tilt in degrees from horizontal

    # --- PV Array: West ---
    pv_west_energy_entity_id: str = ""  # e.g. sensor.inverter_pv_west_energy
    pv_west_capacity_kwp: float = 0.0
    pv_west_azimuth: float = -90.0
    pv_west_tilt: float = 30.0

    # --- Forecast.Solar integration entities (optional, used as model feature) ---
    forecast_solar_east_entity_id: str = ""  # e.g. sensor.energy_production_today_east
    forecast_solar_west_entity_id: str = ""  # e.g. sensor.energy_production_today_west

    # --- Location (if empty, fetched from Home Assistant) ---
    pv_latitude: float = 0.0
    pv_longitude: float = 0.0

    # --- Model ---
    model_min_days: int = 14  # Minimum days of data before ML model is used
    model_retrain_hour: int = 1  # Hour of day (UTC) to retrain
    forecast_update_minutes: int = 60  # How often to update forecast (minutes)
    model_dir: str = "/app/data/models"  # Where to persist trained models

    # --- ML hyperparameters (Gradient Boosting) ---
    model_n_estimators: int = 200
    model_max_depth: int = 5
    model_learning_rate: float = 0.05
    model_subsample: float = 0.8
    model_min_samples_leaf: int = 10
    model_min_training_samples: int = 50  # min rows before training
    model_cv_folds: int = 3  # cross-validation folds

    # --- Fallback estimate parameters ---
    fallback_system_efficiency: float = 0.78  # inverter/wiring/soiling losses
    fallback_peak_irradiance: float = 1000.0  # W/m² STC irradiance

    # --- Data collection ---
    data_history_days: int = 3650  # days of historical data for training (matches InfluxDB retention)

    # --- HA output sensor prefix ---
    ha_sensor_prefix: str = "sensor.pv_ai_forecast"
