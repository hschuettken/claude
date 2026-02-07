# CLAUDE.md

This file provides guidance for AI assistants working with this repository.

## Project Overview

**Homelab automation platform** — a collection of Python microservices orchestrated with Docker Compose, integrating with Home Assistant and InfluxDB. Goals: comfort automation, energy optimization (electricity + oil), and AI-powered home control.

- **Repository**: `hschuettken/claude`
- **Language**: Python 3.12
- **Orchestration**: Docker Compose (one container per service)
- **Integrations**: Home Assistant (REST/WebSocket), InfluxDB v2 (Flux), MQTT (Mosquitto)

## Repository Structure

```
/
├── CLAUDE.md                                # This file
├── README.md                                # Project readme
├── docker-compose.yml                       # Orchestrates all services
├── docker-compose.override.example.yml      # Dev mode template (live code + debugger)
├── .env.example                             # Template for secrets (copy to .env)
├── .env.enc                                 # SOPS-encrypted secrets (safe to commit)
├── .sops.yaml                               # SOPS config (age public key + rules)
├── .gitignore
├── .vscode/launch.json                      # VS Code debugger attach configs
├── base/                                    # Shared Docker base image
│   ├── Dockerfile                           #   Python 3.12-slim + common deps
│   └── requirements.txt                     #   Pinned shared dependencies (incl. debugpy)
├── shared/                                  # Shared Python library (mounted into every container)
│   ├── __init__.py
│   ├── config.py                            #   Pydantic settings from env vars
│   ├── log.py                               #   Structured logging (structlog)
│   ├── ha_client.py                         #   Home Assistant async REST client
│   ├── influx_client.py                     #   InfluxDB v2 query wrapper
│   ├── mqtt_client.py                       #   MQTT pub/sub wrapper
│   └── service.py                           #   BaseService class (heartbeat, debugger, shutdown)
├── services/                                # One directory per microservice
│   ├── pv-forecast/                         #   AI solar production forecast
│   │   ├── Dockerfile
│   │   ├── requirements.txt                 #   scikit-learn, pandas, numpy
│   │   ├── main.py                          #   Entry point + scheduler
│   │   ├── config.py                        #   PV-specific settings
│   │   ├── weather.py                       #   Open-Meteo API client
│   │   ├── data.py                          #   InfluxDB data collector
│   │   ├── model.py                         #   Gradient Boosting ML model
│   │   ├── forecast.py                      #   Forecast orchestrator
│   │   ├── ha_sensors.py                    #   Push forecasts to HA sensors
│   │   └── diagnose.py                      #   Step-by-step connectivity/data diagnostic
│   └── example-service/                     #   Template service
│       ├── Dockerfile
│       ├── requirements.txt                 #   Service-specific deps only
│       └── main.py                          #   Entry point
├── HomeAssistant_config/                    # Reference HA configuration (read-only docs)
│   ├── configuration.yaml                   #   Main HA config (entities, integrations, InfluxDB)
│   └── ...                                  #   KNX, sensor, climate, cover, light configs
├── infrastructure/                          # Config for infra containers
│   └── mosquitto/config/mosquitto.conf
└── scripts/
    ├── build-base.sh                        #   Build the shared base image
    ├── new-service.sh                       #   Scaffold a new service
    ├── secrets-encrypt.sh                   #   Encrypt .env → .env.enc
    ├── secrets-decrypt.sh                   #   Decrypt .env.enc → .env
    ├── secrets-edit.sh                      #   Edit encrypted secrets in-place
    └── install-hooks.sh                     #   Install git pre-commit hooks
```

## Development Workflow

### First-time setup

```bash
# Secrets setup (SOPS + age)
./scripts/install-hooks.sh     # Install git pre-commit hooks
./scripts/secrets-decrypt.sh   # Decrypt .env.enc → .env (needs age key)
# OR for first-time: cp .env.example .env and fill in values

./scripts/build-base.sh        # Build the shared base Docker image
docker compose up --build      # Start everything
```

### Secrets management (SOPS + age)

Secrets are stored encrypted in `.env.enc` using [SOPS](https://github.com/getsops/sops) with [age](https://github.com/FiloSottile/age) encryption. The plain `.env` is gitignored.

```bash
./scripts/secrets-encrypt.sh   # Encrypt .env → .env.enc (commit this)
./scripts/secrets-decrypt.sh   # Decrypt .env.enc → .env (after clone)
./scripts/secrets-edit.sh      # Edit encrypted secrets in-place via $EDITOR
```

**Setup on a new machine:**
1. Install `sops` and `age`
2. Copy your age key to `.sops/age-key.txt` (from your password manager)
3. Run `./scripts/secrets-decrypt.sh`
4. Run `./scripts/install-hooks.sh`

**Age key**: stored at `.sops/age-key.txt` (gitignored). Back it up in a password manager — if lost, you cannot decrypt your secrets.

### Dev mode (recommended for development)

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
```

This mounts source code directly into containers — edit code, restart, no rebuild:

```bash
docker compose up pv-forecast            # start service
# edit code...
docker compose restart pv-forecast       # picks up changes in ~2 seconds
docker compose logs -f pv-forecast       # watch output
```

### Diagnosing issues

```bash
docker compose run --rm pv-forecast python diagnose.py            # test everything
docker compose run --rm pv-forecast python diagnose.py --step ha  # test just HA
```

Steps: `config`, `ha`, `influx`, `mqtt`, `weather`, `forecast`, `all`

### Debugging with VS Code

1. Ensure `DEBUG_SERVICE=pv-forecast` is set in `docker-compose.override.yml`
2. `docker compose up pv-forecast` — service pauses, waiting for debugger
3. In VS Code: press F5 → "Attach to pv-forecast"
4. Set breakpoints, inspect variables, step through code

For quick debugging without VS Code, add `breakpoint()` anywhere in the code and run:
```bash
docker compose run --rm pv-forecast python main.py
```

### Creating a new service

```bash
./scripts/new-service.sh my-service-name
# Then add the service to docker-compose.yml (see template comment in the file)
```

### Building and running

```bash
./scripts/build-base.sh                          # Rebuild base image (after changing base/requirements.txt)
docker compose up --build <service-name>          # Build and run a single service
docker compose up --build                         # Build and run all services
docker compose logs -f <service-name>             # Tail logs for a service
docker compose down                               # Stop everything
```

### Adding a Python dependency

- **Shared across all services** → add to `base/requirements.txt`, then rebuild base image
- **Specific to one service** → add to `services/<name>/requirements.txt`, then rebuild that service

## Architecture & Patterns

### BaseService pattern

Every service inherits from `shared.service.BaseService`. This gives you:
- `self.settings` — Pydantic config from env vars
- `self.logger` — Structured logger
- `self.ha` — Home Assistant async client
- `self.influx` — InfluxDB query client
- `self.mqtt` — MQTT pub/sub client
- `self.publish(event, data)` — Publish to `homelab/{service-name}/{event}`
- `self.wait_for_shutdown()` — Block until SIGTERM/SIGINT
- Automatic MQTT heartbeat (every 60s, configurable)
- VS Code debugger support (via `DEBUG_SERVICE` env var)
- Graceful shutdown with resource cleanup

### MQTT heartbeat

All services automatically publish to `homelab/{service-name}/heartbeat` every 60s:
```json
{"status": "online", "service": "pv-forecast", "uptime_seconds": 3661.2, "memory_mb": 42.3}
```
Override `health_check()` to add custom status. Publishes `"offline"` on graceful shutdown. Configure interval via `HEARTBEAT_INTERVAL_SECONDS` (0 to disable).

### MQTT topic convention

```
homelab/{service-name}/{event-type}
```

Examples: `homelab/energy-monitor/price-changed`, `homelab/climate-control/setpoint-updated`

### Configuration

All config flows through `shared.config.Settings` (Pydantic). To add service-specific settings:

```python
from shared.config import Settings as BaseSettings

class MySettings(BaseSettings):
    my_custom_var: str = "default"
```

Environment variables map to field names: `MY_CUSTOM_VAR` env var → `my_custom_var` field.

## Home Assistant Setup

Reference configuration is stored in `HomeAssistant_config/` for documentation purposes.

### PV System

Two PV arrays connected to a single inverter:

| Array | Strings | Power Sensor | Energy Sensor |
|-------|---------|-------------|---------------|
| East  | PV1 + PV2 | `sensor.inverter_pv_east_power` (W) | `sensor.inverter_pv_east_energy` (kWh) |
| West  | PV3 + PV4 | `sensor.inverter_pv_west_power` (W) | `sensor.inverter_pv_west_energy` (kWh) |

- **Power sensors** are template sensors: `current × voltage` per string, summed per array
- **Energy sensors** are `platform: integration` (Riemann sum, trapezoidal) from the power sensors
- Energy sensors use `state_class: total_increasing` — they are **cumulative** (never reset at midnight)

### InfluxDB

- **Version**: v2 (Flux query language)
- **Bucket**: `hass`
- **Organization**: configured via org ID
- **`_measurement`**: the unit of measurement (e.g., `kWh`, `W`, `°C`) — NOT a fixed value
- **`entity_id` tag**: stored WITHOUT the `sensor.`/`binary_sensor.` domain prefix (e.g., `inverter_pv_east_energy`, not `sensor.inverter_pv_east_energy`). The domain is in a separate `domain` tag. The `shared/influx_client.py` handles this stripping automatically.
- **`_field`**: `value` for the numeric state
- **Recorder**: 3650-day retention (10 years)

### Other Relevant Entities

- **Grid metering**: Shelly 3EM (three-phase) — `sensor.shelly3em_main_channel_total_power` (W), `sensor.shelly3em_main_channel_total_energy` (kWh)
- **Energy pricing**: EPEX spot market (`sensor.epex_spot_data_price_2`), `input_number.price_per_kwh_electricity_grid`, `input_number.price_per_kwh_electricity_pv`
- **EV charging**: Amtron wallbox via Modbus — `sensor.amtron_meter_total_power_w`, `sensor.amtron_meter_total_energy_kwh`
- **Forecast.Solar**: Configured per array — `sensor.energy_production_today_east` / `west`, `sensor.energy_production_tomorrow_east` / `west`

## Services

### pv-forecast — AI Solar Production Forecast

Predicts PV output (kWh) for east and west arrays using a Gradient Boosting model
trained on historical production data (InfluxDB) correlated with weather features (Open-Meteo).

**Data flow**: InfluxDB (actual production) + Open-Meteo (radiation/clouds/temp) + Forecast.Solar (optional) → ML model → HA sensors

**Important**: The input energy sensors (`sensor.inverter_pv_east_energy`, `sensor.inverter_pv_west_energy`) are `total_increasing` cumulative sensors. The data collector diffs consecutive hourly values to derive per-hour kWh — it does **not** assume midnight resets.

**Falls back** to radiation-based estimation when <14 days of training data exist.

**Schedule**: Forecast every hour, model retrain at 1 AM UTC daily.

**HA output sensors** (prefix configurable via `HA_SENSOR_PREFIX`):
- `sensor.pv_ai_forecast_today_kwh` — total both arrays
- `sensor.pv_ai_forecast_today_remaining_kwh` — remaining from current hour
- `sensor.pv_ai_forecast_tomorrow_kwh`
- `sensor.pv_ai_forecast_day_after_tomorrow_kwh`
- `sensor.pv_ai_forecast_east_today_kwh` / `west_today_kwh`
- `sensor.pv_ai_forecast_east_tomorrow_kwh` / `west_tomorrow_kwh`

Each sensor includes an `hourly` attribute with per-hour breakdown.

**MQTT events**: `homelab/pv-forecast/updated`, `homelab/pv-forecast/model-trained`

**Config** (env vars): `PV_EAST_ENERGY_ENTITY_ID`, `PV_EAST_CAPACITY_KWP`, `PV_EAST_AZIMUTH`, `PV_EAST_TILT` (same for west). `FORECAST_SOLAR_EAST_ENTITY_ID` / `WEST` (optional — used as ML feature). Location auto-detected from HA if not set.

## Code Conventions

- **Async by default** — Services use `asyncio`. HA client is async. InfluxDB client is sync (Flux queries are blocking).
- **Type hints** — Use type annotations on all function signatures.
- **Structured logging** — Use `self.logger.info("event_name", key=value)` not f-strings.
- **No secrets in code** — All credentials go in `.env`, accessed via `Settings`.
- **Service isolation** — Services communicate via MQTT, not by importing each other.

## Key Notes for AI Assistants

1. **Read before modifying** — Always read a file before proposing changes to it.
2. **Minimal changes** — Only make changes that are directly requested. Avoid over-engineering.
3. **Service template** — When creating new services, use `./scripts/new-service.sh` or copy `services/example-service/`.
4. **Base image** — If you add a dependency to `base/requirements.txt`, remind the user to rebuild with `./scripts/build-base.sh`.
5. **docker-compose.yml** — When adding a new service, add it to `docker-compose.yml` following the existing pattern.
6. **Update this file** — When adding significant components, update this CLAUDE.md.
7. **Security** — Never commit plain `.env`. Secrets go in `.env.enc` (encrypted via SOPS). Be cautious with InfluxDB Flux queries (injection risk if building queries from user input).
8. **InfluxDB** — Currently configured for **v2** (Flux query language). If the user has v1, the client wrapper needs changing.
