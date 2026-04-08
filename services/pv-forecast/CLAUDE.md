# pv-forecast — AI Solar Production Forecast

Predicts PV output (kWh) for east and west arrays using a Gradient Boosting model trained on historical production data (InfluxDB) correlated with weather features (Open-Meteo).

**Data flow**: InfluxDB (actual production) + Open-Meteo (radiation/clouds/temp/sunrise/sunset) + Forecast.Solar (optional) → ML model → HA sensors

## Key behaviors

**Cumulative energy sensors**: The input energy sensors (`sensor.inverter_pv_east_energy`, `sensor.inverter_pv_west_energy`) are `total_increasing` cumulative sensors. The data collector diffs consecutive hourly values to derive per-hour kWh — it does **not** assume midnight resets.

**Daylight filtering**: Uses actual sunrise/sunset times from Open-Meteo (daily API) to filter training data and forecast hours. A physics constraint also zeros out any prediction where GHI < 5 W/m² (no sun = no power). Replaces an earlier hardcoded 5–21 UTC range that included dark hours in winter at 52°N.

**Model versioning**: Models are saved as `{"model": ..., "features": [...]}` dicts. On load, the feature list is validated against current `FEATURE_COLS`. If features have changed (new features added), the old model is automatically discarded and retrained.

**Fallback**: Radiation-based estimation when <14 days of training data exist.

**Schedule**: Forecast every hour, model retrain at 1 AM UTC daily.

## HA output sensors

Registered via two mechanisms:

**Via REST API** (prefix configurable via `HA_SENSOR_PREFIX`):

- `sensor.pv_ai_forecast_today_kwh` — total both arrays
- `sensor.pv_ai_forecast_today_remaining_kwh` — remaining from current hour
- `sensor.pv_ai_forecast_tomorrow_kwh`
- `sensor.pv_ai_forecast_day_after_tomorrow_kwh`
- `sensor.pv_ai_forecast_east_today_kwh` / `west_today_kwh`
- `sensor.pv_ai_forecast_east_tomorrow_kwh` / `west_tomorrow_kwh`

Each sensor includes an `hourly` attribute with per-hour breakdown.

**Via MQTT auto-discovery** (grouped under "PV AI Forecast" device in HA, 23 entities):

- `binary_sensor` — Service status (online/offline, 3-min expiry)
- `sensor` — Uptime, Today/Tomorrow/Day-After kWh, Today Remaining kWh, East/West Today/Tomorrow kWh
- `sensor` (diagnostic) — East/West Model Type (ml/fallback), East/West R², East/West MAE, Training Data Days (East/West), Last Model Training timestamp
- `sensor` — Forecast.Solar Today (comparison), Forecast Reasoning (with full_reasoning attribute)

## MQTT events

`homelab/pv-forecast/updated`, `homelab/pv-forecast/model-trained`, `homelab/pv-forecast/heartbeat`

## ML features (19 total)

`hour`, `day_of_year`, `month`, `shortwave_radiation` (GHI), `direct_radiation`, `diffuse_radiation`, `direct_normal_irradiance` (DNI), `cloud_cover` (total/low/mid/high), `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `sunshine_duration`, `capacity_kwp`, `forecast_solar_kwh`, `sunrise_hour`, `sunset_hour`

## Config env vars

`PV_EAST_ENERGY_ENTITY_ID`, `PV_EAST_CAPACITY_KWP`, `PV_EAST_AZIMUTH`, `PV_EAST_TILT` (same for west). `FORECAST_SOLAR_EAST_ENTITY_ID` / `WEST` (optional — used as ML feature). Location auto-detected from HA if not set.
