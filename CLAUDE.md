# CLAUDE.md

Guidance for AI assistants working on this repository.

## Project Overview

**Homelab automation platform** — a collection of Python microservices orchestrated with Docker Compose, integrating with Home Assistant and InfluxDB. Goals: comfort automation, energy optimization (electricity + oil), and AI-powered home control.

- **Repository**: `hschuettken/claude`
- **Language**: Python 3.12
- **Orchestration**: Docker Compose (one container per service)
- **Integrations**: Home Assistant (REST/WebSocket), InfluxDB v2 (Flux), **NATS JetStream** (primary event bus), MQTT only via nats-mqtt-bridge

## Services

Each service has its own `services/<name>/CLAUDE.md` with detailed documentation. **Read the per-service file before modifying a service.**

| Service | Purpose | Port |
|---------|---------|------|
| [`orchestrator`](services/orchestrator/CLAUDE.md) | AI-powered home brain & coordinator (LLM + tools + Telegram + MCP) | 8100 (API) |
| [`pv-forecast`](services/pv-forecast/CLAUDE.md) | AI solar production forecast (gradient boosting on Open-Meteo features) | — |
| [`smart-ev-charging`](services/smart-ev-charging/CLAUDE.md) | Smart EV charging controller (Amtron wallbox via HEMS) | — |
| [`ev-forecast`](services/ev-forecast/CLAUDE.md) | EV driving forecast & smart charging planner (Audi Connect + calendar) | — |
| [`dashboard`](services/dashboard/CLAUDE.md) | NiceGUI web dashboard (energy, services, controls, chat) | 8085 |
| [`ollama-router`](services/ollama-router/CLAUDE.md) | Multi-node Ollama load balancer + OpenAI-compat API | 11434 |
| `hems` | Heating energy management (separate deployment, see service README) | 8210 |
| `marketing-agent` | Content/Scout + Ghost + Neo4j agent (separate deployment) | 8211 |
| `example-service` | Template for scaffolding new services | — |

## Repository layout

```
/
├── docker-compose.yml                  # Orchestrates all services
├── docker-compose.override.example.yml # Dev mode template (live code + debugger)
├── .env.example / .env.enc / .sops.yaml # Secrets (see Secrets section)
├── base/                               # Shared Docker base image (Python 3.12-slim + deps)
├── shared/                             # Shared Python library mounted into every container
│   ├── config.py                       #   Pydantic settings from env vars
│   ├── log.py                          #   Structured logging (structlog)
│   ├── ha_client.py                    #   Home Assistant async REST client
│   ├── influx_client.py                #   InfluxDB v2 query wrapper
│   ├── mqtt_client.py                  #   MQTT pub/sub wrapper
│   ├── retry.py                        #   Exponential backoff utility
│   └── service.py                      #   BaseService class (heartbeat, debugger, shutdown)
├── services/<name>/                    # One directory per microservice, each with CLAUDE.md
└── scripts/                            # new-service.sh, build-base.sh, secrets-*.sh, ha-export.py
```

## Development Workflow

### First-time setup

```bash
./scripts/install-hooks.sh     # Install git pre-commit hooks
./scripts/secrets-decrypt.sh   # Decrypt .env.enc → .env (needs age key)
# OR for first-time: cp .env.example .env and fill in values
./scripts/build-base.sh        # Build the shared base Docker image
docker compose up --build      # Start everything
```

### Secrets management (SOPS + age)

Secrets are stored encrypted in `.env.enc` using [SOPS](https://github.com/getsops/sops) with [age](https://github.com/FiloSottile/age) encryption. Plain `.env` is gitignored.

```bash
./scripts/secrets-encrypt.sh   # Encrypt .env → .env.enc (commit this)
./scripts/secrets-decrypt.sh   # Decrypt .env.enc → .env (after clone)
./scripts/secrets-edit.sh      # Edit encrypted secrets in-place via $EDITOR
```

**Age key**: stored at `.sops/age-key.txt` (gitignored). Back it up in a password manager — if lost, you cannot decrypt your secrets.

**Never hand-edit `.env.enc`** — it will destroy the ciphertext. Always use `secrets-edit.sh`. See the `homelab-secrets` skill for the full workflow.

### Dev mode

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

Every service has a `diagnose.py` that tests connectivity and config:

```bash
docker compose run --rm <service> python diagnose.py              # test everything
docker compose run --rm <service> python diagnose.py --step ha    # test just HA
```

Common steps: `config`, `ha`, `mqtt`, `influx`, `all`. Service-specific steps vary — run with no argument for the full list.

### Debugging with VS Code

1. Ensure `DEBUG_SERVICE=<name>` is set in `docker-compose.override.yml`
2. `docker compose up <name>` — service pauses, waiting for debugger
3. In VS Code: press F5 → "Attach to \<name\>"
4. Set breakpoints, inspect variables, step through code

For quick debugging without VS Code, add `breakpoint()` anywhere and run `docker compose run --rm <service> python main.py`.

### Creating a new service

```bash
./scripts/new-service.sh my-service-name
# Then add the service to docker-compose.yml (see template comment in the file)
```

### Building and running

```bash
./scripts/build-base.sh                       # Rebuild base image (after changing base/requirements.txt)
docker compose up --build <service-name>      # Build and run a single service
docker compose up --build                     # Build and run all services
docker compose logs -f <service-name>         # Tail logs for a service
docker compose down                           # Stop everything
```

### Exporting Home Assistant data

```bash
python scripts/ha-export.py                   # Output: HomeAssistant_config/ha_export.md
```

Requires `HA_URL` and `HA_TOKEN` in `.env`. Uses REST API for states/services and WebSocket API for area/device/entity registries. Useful as AI context — complete picture of available entities.

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

### NATS heartbeat (Session 28 — post-migration)

All services publish heartbeats to `heartbeat.{service-name}` on NATS every 60s:

```json
{"status": "online", "service": "pv-forecast", "uptime_seconds": 3661.2, "memory_mb": 42.3}
```

The `nats-mqtt-bridge` (:8235) translates `heartbeat.{service}` → MQTT `homelab/{service}/heartbeat` automatically so HA dashboards still work.

`NatsPublisher` in `shared/nats_client.py` provides `publish()` and `subscribe_json()`. `self.mqtt` is `None` (backward-compat sentinel only).

### NATS — the only event bus (Session 28)

**All services publish to NATS. No service imports paho or aiomqtt directly.**

| Use case | Subject pattern | Bridge? |
|----------|----------------|---------|
| Energy service events | `energy.pv.forecast.*`, `energy.ev.*` | Yes → MQTT for HA dashboards |
| HA auto-discovery | `ha.discovery.{component}.{node}.{id}.config` | Yes → MQTT `homeassistant/…/config` (retained) |
| Heartbeats | `heartbeat.{service}` | Yes → MQTT `homelab/{service}/heartbeat` |
| Governance/alerts | `governance.alert.*` | No (NATS-native) |
| HA state inbound | `ha.state.{domain}.{entity}` | From MQTT `homeassistant/+/+/state` |
| Bootstrap telemetry | `bootstrap.node.*.telemetry` | From MQTT `homelab/nodes/+/telemetry` |
| Frigate events | `frigate.events`, `frigate.detection.*` | From MQTT `frigate/…` |

### MQTT topic convention (HA integration only)

```
homelab/{service-name}/{event-type}
```

Used only for: heartbeat, HA sensor state topics, and MQTT discovery config payloads.

### Inter-service commands (NATS, post-Session 28 migration)

The orchestrator currently sends commands to services via MQTT:

```
homelab/orchestrator/command/{service-name}
```

Payload: `{"command": "refresh"}`, `{"command": "retrain"}`, `{"command": "refresh_vehicle"}`.

**Note**: This is a legacy pattern. New inter-service communication should use NATS subjects (e.g., `energy.pv.forecast_updated`). The orchestrator command topics will migrate to NATS once the orchestrator is updated.

| Service | Supported Commands |
|---------|-------------------|
| `pv-forecast` | `refresh` (re-run forecast), `retrain` (retrain ML model) |
| `smart-ev-charging` | `refresh` (trigger immediate control cycle) |
| `ev-forecast` | `refresh` (re-evaluate plan), `refresh_vehicle` (refresh Audi Connect data) |

### MQTT auto-discovery for Home Assistant

Services register their entities in HA automatically via [MQTT Discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery). On startup, each service publishes retained config messages to `homeassistant/{component}/{node_id}/{object_id}/config` — HA picks these up and creates entities without any manual configuration.

Helper method on `MQTTClient`:

```python
self.mqtt.publish_ha_discovery("sensor", "today_kwh", node_id="pv_forecast", config={
    "name": "PV Forecast Today",
    "device": {"identifiers": ["homelab_pv_forecast"], "name": "PV AI Forecast"},
    "state_topic": "homelab/pv-forecast/updated",
    "value_template": "{{ value_json.today_kwh }}",
    "unit_of_measurement": "kWh",
    "device_class": "energy",
})
```

**Important**: The MQTT broker used by the services must be the same one HA is connected to, otherwise HA won't see the discovery messages.

### Docker healthcheck

Services use a file-based healthcheck pattern:

1. The service writes a timestamp to `/app/data/healthcheck` after each successful operation
2. A `healthcheck.py` script checks if the file was updated within the last 5 minutes
3. The Dockerfile declares: `HEALTHCHECK --interval=60s --start-period=120s CMD ["python", "healthcheck.py"]`

Check with `docker ps` (shows `healthy`/`unhealthy` in the STATUS column).

### Configuration

All config flows through `shared.config.Settings` (Pydantic). To add service-specific settings:

```python
from shared.config import Settings as BaseSettings

class MySettings(BaseSettings):
    my_custom_var: str = "default"
```

Environment variables map to field names: `MY_CUSTOM_VAR` env var → `my_custom_var` field.

### MQTT dead-letter error topics

Services publish errors to `homelab/errors/{service-name}` when MQTT message processing fails. Payload includes the original topic, payload, error message, traceback, and timestamp.

### Global safe mode

A global safe mode switch (`input_boolean.homelab_safe_mode`) blocks all write actions across all services when enabled. Services check the safe mode entity before calling HA services, writing to the wallbox, or setting HA input helpers. Useful during maintenance or debugging. Configure the entity ID via `SAFE_MODE_ENTITY`.

### State persistence

Services persist critical state to disk (`/app/data/state.json`) for faster restart recovery. Avoids re-querying slow external APIs (Audi Connect, weather) and preserves session energy counters, pending clarifications, and charging plans across container restarts.

### Cross-service correlation IDs

Services propagate a `trace_id` through MQTT messages to correlate related events. E.g., an ev-forecast plan includes a `trace_id` that appears in smart-ev-charging status messages, making it easy to trace a charging decision back to the forecast that triggered it.

### Shared retry/backoff utility

`shared/retry.py` provides an exponential backoff decorator for HA API calls and other external requests. Configurable max attempts, base delay, and jitter. Used by `ha_client.py` and service-specific API calls.

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
- **`_measurement`**: the unit of measurement (e.g., `kWh`, `W`, `°C`) — NOT a fixed value
- **`entity_id` tag**: stored WITHOUT the `sensor.`/`binary_sensor.` domain prefix. The domain is in a separate `domain` tag. `shared/influx_client.py` handles stripping automatically.
- **`_field`**: `value` for the numeric state
- **Recorder**: 3650-day retention (10 years)

### Other Relevant Entities

- **Grid connection meter**: `sensor.power_meter_active_power` (W) — positive = exporting, negative = importing
- **Household consumption**: Shelly 3EM (three-phase) — `sensor.shelly3em_main_channel_total_power` (W, always positive, house only)
- **PV DC input**: `sensor.inverter_input_power` (W)
- **Inverter AC output**: `sensor.inverter_active_power` (W)
- **Home battery**: `sensor.batteries_charge_discharge_power` (W, positive = charging, negative = discharging), `sensor.batteries_state_of_capacity` (%, SoC) — 7 kWh / 3.5 kW max
- **Energy pricing**: Fixed rates — grid import 25 ct/kWh, feed-in 7 ct/kWh, EV reimbursement 25 ct/kWh. No EPEX spot market.
- **EV charging**: Amtron wallbox via Modbus — `sensor.amtron_meter_total_power_w`, `sensor.amtron_meter_total_energy_kwh`
- **EV battery**: Audi Connect — `sensor.audi_a6_avant_e_tron_state_of_charge` (single-account) or `..._comb` (dual-account legacy)
- **Forecast.Solar**: `sensor.energy_production_today_east` / `west`, `sensor.energy_production_tomorrow_east` / `west`

## Inter-Service Integration Patterns

### Demand Publisher / Intelligent Coordinator

Services follow a separation-of-concerns model: **data services publish demand**, the **orchestrator decides what to do**.

Example: ev-forecast publishes "need 15 kWh by 07:00" via MQTT. The orchestrator decides whether to create a calendar event, send a Telegram notification, or both. The ev-forecast service never writes to the calendar directly — it only sets HA input helpers for the smart-ev-charging controller.

### MQTT Thread → Asyncio Bridge

MQTT callbacks (paho) run on a background thread, but services use asyncio. Services bridge this with:

```python
asyncio.run_coroutine_threadsafe(coro, self._loop)
```

Safely schedules async work (e.g., calendar API calls, Telegram messages) from synchronous MQTT handlers.

### Shared State Dict

Cross-component state within a service is shared via reference to a mutable dict:

```python
self._ev_state = {"plan": None, "pending_clarifications": []}
```

Passed to Brain, ToolExecutor, and ProactiveEngine — all read/write the same object.

### Service Chain: ev-forecast → smart-ev-charging

ev-forecast writes HA input helpers (`ev_charge_mode`, `ev_target_energy_kwh`, `ev_departure_time`, `ev_full_by_morning`), which smart-ev-charging reads on its 30-second control loop. This decouples planning from execution — no direct MQTT dependency between the two.

### EV Trip Clarification Flow

Full lifecycle for ambiguous trip resolution:

1. **ev-forecast** parses calendar, finds ambiguous trip (e.g., Henning 100–350 km)
2. **ev-forecast** publishes to `homelab/ev-forecast/clarification-needed` with question in German
3. **orchestrator** receives via MQTT, stores in `ev_state["pending_clarifications"]`
4. **orchestrator** forwards question to Telegram via `ProactiveEngine.on_ev_clarification_needed()`
5. **Brain** injects pending clarifications into LLM system prompt (with `event_id`)
6. **User** responds naturally in Telegram chat
7. **Brain** (LLM) recognizes context, calls `respond_to_ev_trip_clarification` tool with `event_id`
8. **orchestrator** publishes answer to `homelab/ev-forecast/trip-response`
9. **ev-forecast** receives response, calls `TripPredictor.resolve_clarification()`, updates plan

## Code Conventions

- **Async by default** — Services use `asyncio`. HA client is async. InfluxDB client is sync (Flux queries are blocking).
- **Type hints** — Use type annotations on all function signatures.
- **Structured logging** — Use `self.logger.info("event_name", key=value)` not f-strings.
- **No secrets in code** — All credentials go in `.env`, accessed via `Settings`.
- **Service isolation** — Services communicate via MQTT, not by importing each other.

## Key Notes for AI Assistants

0. **Oracle first** — Before any new feature, endpoint, or integration, query the Integration Oracle (`POST http://192.168.0.50:8225/oracle/query` with `{"intent": "..."}`) and validate code before committing (`POST /oracle/validate` with `{"code_snippet": "..."}`). See workspace CLAUDE.md for details.
0b. **Oracle registration** — Every service MUST have `_register_with_oracle()` in its startup code. The manifest must list ALL NATS subjects (publish AND subscribe), all HTTP endpoints, and any MQTT translation routes. See `~/dev/CLAUDE.md` → "Oracle Registration" section for the full template and checklist. **If you add or remove a NATS subject, update the manifest in the same commit.**
0c. **Code KG (MCP SSE)** — The Oracle exposes 5 code knowledge graph tools via MCP SSE at `http://192.168.0.50:8225/mcp/sse`: `get_code_impact` (blast radius for changed files), `get_review_context` (focused code snippets within token budget), `query_code_graph` (function relationships by name or NL), `suggest_integrations` (NATS publisher gap finder), `rebuild_code_graph` (re-index trigger). Use `get_code_impact` before any multi-file refactor.
1. **Read before modifying** — Always read a file before proposing changes. For service-specific work, read the service's own `CLAUDE.md` first.
2. **Minimal changes** — Only make changes directly requested. Avoid over-engineering.
3. **Service template** — When creating new services, use `./scripts/new-service.sh` or copy `services/example-service/`.
4. **Base image** — If you add a dependency to `base/requirements.txt`, remind the user to rebuild with `./scripts/build-base.sh`.
5. **docker-compose.yml** — When adding a new service, add it to `docker-compose.yml` following the existing pattern.
6. **Security** — Never commit plain `.env`. Secrets go in `.env.enc` (encrypted via SOPS). Be cautious with InfluxDB Flux queries (injection risk if building queries from user input).
7. **InfluxDB** — Currently configured for **v2** (Flux query language). If the user has v1, the client wrapper needs changing.
8. **Server Python packages** — The server runs Debian/Ubuntu with PEP 668 (`externally-managed-environment`). Always use `python3 -m venv` for standalone scripts instead of `pip install` system-wide. A shared venv exists at `scripts/.venv/`.
9. **InfluxDB query gotchas** (learned from Shelly outlier fix):
    - Flux returns **separate tables per `_measurement`/series** — records from different tables are NOT sorted together. Always sort in Python after collecting from all tables.
    - The Shelly 3EM stores **triplicate records** per timestamp (one per phase series) with sub-millisecond timestamp differences. Deduplicate by truncating to the second before comparing.
    - The InfluxDB v2 **delete API only supports tag predicates** (e.g., `entity_id="..."`). Filtering by `_field` returns `501 Not Implemented`. Use a tight time window + tag filter instead.
