# ev-forecast — EV Driving Forecast & Smart Charging Planner

Monitors the Audi A6 e-tron (83 kWh gross / 76 kWh net) via Audi Connect, predicts driving needs from the family calendar, and generates smart charging plans that maximize PV usage while ensuring the car is always ready.

**Vehicle**: Audi A6 e-tron. Consumption calculated dynamically from mileage + SoC changes (default 22 kWh/100 km until enough data is collected).

## Audi Connect account modes

Set via `AUDI_SINGLE_ACCOUNT`:

| Mode | Default | Description |
|------|---------|-------------|
| Single account (recommended) | `true` | Uses Henning's Audi Connect directly with standard sensor entities. No combined template sensors needed. |
| Dual account (legacy) | `false` | Uses combined `_comb` HA template sensors merging Henning + Nicole accounts via mileage comparison. Requires `ev_audi_connect.yaml` HA package. |

In single-account mode, the service reads direct Audi Connect entities (e.g. `sensor.audi_a6_avant_e_tron_state_of_charge`). The `active_account_entity` is left empty and only one VIN is used for cloud refresh.

In dual-account mode (legacy), the service reads combined `_comb` entities and refreshes both accounts.

## Dynamic consumption calculation

Tracks actual kWh/100km from mileage and SoC changes instead of using a fixed rate. When a driving segment is detected (mileage increased AND SoC decreased between readings):

```
consumption = (soc_delta / 100 × battery_capacity) / km_delta × 100
```

The rolling average of the last 10 measurements replaces the configured default. This adapts to seasonal changes (cold = higher consumption), driving style (highway vs city), and payload. Measurements are persisted across restarts. Only values in the 5–60 kWh/100km range pass the sanity check.

## Calendar-based trip prediction

Reads the shared family calendar. Events are parsed by prefix:

- `H: <destination>` — Henning drives (e.g., "H: Aachen", "H: STR")
- `N: <destination>` — Nicole drives (e.g., "N: Münster")
- Henning: trips >350 km → takes the train (no EV impact); 100–350 km → asks via Telegram
- Nicole: default commute Mon–Thu to Lengerich (22 km one way), departs 07:00, returns ~18:00
- Known destinations are mapped to distances via a configurable lookup table

## Geocoding for unknown destinations

Uses OpenStreetMap Nominatim (free, no API key). Flow: destination name → geocode to coordinates → haversine straight-line distance → multiply by road factor (default 1.3) → estimated road km. Results cached per session.

**Known destinations** (configurable via `KNOWN_DESTINATIONS` JSON env var): Pre-mapped city→distance lookup for common trips (e.g., Münster 60 km, Aachen 80 km, STR 500 km). Falls back to geocoding, then to a conservative 50 km default.

## Trip clarification

When the service can't determine if someone will use the EV (Henning for 100–350 km trips, unknown destinations), it publishes questions in German to `homelab/ev-forecast/clarification-needed`. Each clarification includes an `event_id` for tracking. The orchestrator forwards these to Telegram and routes user responses back via `homelab/ev-forecast/trip-response`.

## Smart charging plan (demand-focused)

The planner expresses **demand** ("need X kWh by time Y"), not supply. PV optimization is left to smart-ev-charging. For the next 3 days:

1. Calculates energy needed for each day's trips (distance × dynamic consumption rate)
2. Adds safety buffer (min SoC 20% + buffer 10% + min arrival SoC 15%)
3. Compares required SoC to current SoC, tracks running SoC across days
4. Assigns urgency: none → low → medium → high → critical (based on time-to-deadline)
5. Chooses the best charge mode:
   - **PV Surplus** — no trips or SoC already sufficient
   - **Smart** — PV surplus + grid fill by departure deadline
   - **Fast/Eco** — urgent, departure imminent (<2 hours)
6. Automatically sets the HA input helpers (`ev_charge_mode`, `ev_target_energy_kwh`, `ev_departure_time`, `ev_full_by_morning`) for smart-ev-charging

## Urgency parameters (configurable via env vars)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CRITICAL_URGENCY_HOURS` | 2.0 | Departure within 2h — switches to Fast or Eco |
| `HIGH_URGENCY_HOURS` | 6.0 | Departure within 6h — switches to Smart |
| `FAST_MODE_THRESHOLD_KWH` | 15.0 | In critical urgency, deficit >15 kWh → Fast instead of Eco |
| `EARLY_DEPARTURE_HOUR` | 10 | Tomorrow departure before 10 AM → charge overnight (Smart + Full by Morning) |

## Data flow

Audi Connect (SoC/range) + Google Calendar (trips) + PV Forecast (solar) → Charging Plan → HA Helpers → smart-ev-charging (wallbox control)

## Schedule

Vehicle state check every 15 min, plan update every 30 min.

## HA output sensors

Via MQTT auto-discovery, "EV Forecast" device, 14 entities:

- `binary_sensor` — Service online/offline
- `sensor` — EV SoC (%), EV Range (km), Active Account, Charging State, Plug State, Energy Needed Today (kWh), Recommended Charge Mode, Next Trip, Next Departure, Plan Status, Uptime
- `sensor` — EV Consumption (kWh/100km, with `source` and `measurements` attributes — "measured" or "default")
- `sensor` (reasoning) — Plan Reasoning (with `full_reasoning`, `current_soc_pct`, `total_energy_needed_kwh`, `today_urgency` as JSON attributes)

## MQTT events

`homelab/ev-forecast/vehicle`, `homelab/ev-forecast/plan`, `homelab/ev-forecast/clarification-needed`, `homelab/ev-forecast/heartbeat`

## MQTT integration with orchestrator

When a trip needs clarification (unknown distance or Henning's ambiguous trips), publishes to `homelab/ev-forecast/clarification-needed`. The orchestrator asks via Telegram and responds on `homelab/ev-forecast/trip-response`.

## HA YAML package

`HomeAssistant_config/ev_audi_connect.yaml` — HA package for vehicle scripts and automation.

- **Single-account mode** (default): only the vehicle action scripts (`ev_refresh_cloud`, `ev_refresh_vehicle`, `ev_start_climate`, etc.) and periodic cloud refresh automation are needed — the combined `_comb` template sensors are not required.
- **Dual-account mode** (legacy): package additionally provides combined `_comb` entities via mileage-based active account detection.

Include as HA package: `homeassistant: packages: ev_audi: !include ev_audi_connect.yaml`.

Scripts provided: `script.ev_refresh_cloud`, `script.ev_refresh_vehicle`, `script.ev_start_climate`, `script.ev_stop_climate`, `script.ev_start_window_heating`, `script.ev_lock`, `script.ev_unlock`, `script.ev_start_charger`, `script.ev_stop_charger`, `script.ev_set_target_soc`.

## Config env vars

`AUDI_SINGLE_ACCOUNT` (true = single account, false = dual), `EV_BATTERY_CAPACITY_GROSS_KWH`, `EV_BATTERY_CAPACITY_NET_KWH`, `EV_CONSUMPTION_KWH_PER_100KM` (default fallback until dynamic data available), `EV_SOC_ENTITY`, `EV_RANGE_ENTITY`, `EV_CHARGING_ENTITY`, `EV_PLUG_ENTITY`, `EV_MILEAGE_ENTITY`, `EV_CLIMATISATION_ENTITY`, `EV_ACTIVE_ACCOUNT_ENTITY` (dual-account only), `AUDI_ACCOUNT1_NAME` / `AUDI_ACCOUNT1_VIN`, `AUDI_ACCOUNT2_NAME` / `AUDI_ACCOUNT2_VIN` (dual-account only), `AUDI_REFRESH_INTERVAL_MINUTES`, `AUDI_STALE_THRESHOLD_MINUTES`, `CALENDAR_PREFIX_HENNING`, `CALENDAR_PREFIX_NICOLE`, `NICOLE_COMMUTE_KM`, `NICOLE_COMMUTE_DAYS`, `HENNING_TRAIN_THRESHOLD_KM`, `KNOWN_DESTINATIONS` (JSON), `MIN_SOC_PCT`, `BUFFER_SOC_PCT`, `PLANNING_HORIZON_DAYS`, `CRITICAL_URGENCY_HOURS`, `HIGH_URGENCY_HOURS`, `FAST_MODE_THRESHOLD_KWH`, `EARLY_DEPARTURE_HOUR`, `PLAN_UPDATE_MINUTES`, `VEHICLE_CHECK_MINUTES`, `SAFE_MODE_ENTITY`. Uses the same `GOOGLE_CALENDAR_*` credentials as the orchestrator.
