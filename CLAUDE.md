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
│   ├── retry.py                             #   Exponential backoff utility for external API calls
│   └── service.py                           #   BaseService class (heartbeat, debugger, shutdown)
├── services/                                # One directory per microservice
│   ├── orchestrator/                        #   AI-powered home brain & coordinator
│   │   ├── Dockerfile
│   │   ├── requirements.txt                 #   telegram-bot, google-generativeai, openai, anthropic
│   │   ├── main.py                          #   Entry point (OrchestratorService)
│   │   ├── config.py                        #   Orchestrator-specific settings
│   │   ├── brain.py                         #   Core reasoning engine (LLM + tool loop)
│   │   ├── tools.py                         #   LLM tool definitions & execution
│   │   ├── memory.py                        #   Persistent conversations, profiles, preferences
│   │   ├── semantic_memory.py               #   Vector-based long-term memory (embeddings + search)
│   │   ├── gcal.py                          #   Google Calendar integration (read family, write own)
│   │   ├── proactive.py                     #   Scheduled briefings, alerts, suggestions
│   │   ├── healthcheck.py                   #   Docker HEALTHCHECK script
│   │   ├── diagnose.py                      #   Step-by-step connectivity diagnostic
│   │   ├── llm/                             #   Pluggable LLM backends
│   │   │   ├── __init__.py                  #     Provider factory
│   │   │   ├── base.py                      #     Abstract LLM interface
│   │   │   ├── gemini.py                    #     Google Gemini (default)
│   │   │   ├── openai_compat.py             #     OpenAI / Ollama
│   │   │   └── anthropic_llm.py             #     Anthropic Claude
│   │   └── channels/                        #   Communication channels
│   │       ├── __init__.py
│   │       ├── base.py                      #     Abstract channel interface
│   │       └── telegram.py                  #     Telegram bot
│   ├── pv-forecast/                         #   AI solar production forecast
│   │   ├── Dockerfile
│   │   ├── requirements.txt                 #   scikit-learn, pandas, numpy
│   │   ├── main.py                          #   Entry point + scheduler
│   │   ├── config.py                        #   PV-specific settings
│   │   ├── weather.py                       #   Open-Meteo API client
│   │   ├── data.py                          #   InfluxDB data collector
│   │   ├── model.py                         #   Gradient Boosting ML model
│   │   ├── forecast.py                      #   Forecast orchestrator
│   │   ├── ha_sensors.py                    #   Push forecasts to HA sensors (REST API)
│   │   ├── healthcheck.py                   #   Docker HEALTHCHECK script
│   │   └── diagnose.py                      #   Step-by-step connectivity/data diagnostic
│   ├── smart-ev-charging/                   #   Smart EV charging controller
│   │   ├── Dockerfile
│   │   ├── requirements.txt                 #   No extra deps (base image sufficient)
│   │   ├── main.py                          #   Entry point + control loop
│   │   ├── config.py                        #   EV-specific settings
│   │   ├── charger.py                       #   Wallbox abstraction (read state, set power)
│   │   ├── strategy.py                      #   Charging strategy logic
│   │   ├── healthcheck.py                   #   Docker HEALTHCHECK script
│   │   └── diagnose.py                      #   Step-by-step connectivity/data diagnostic
│   ├── ev-forecast/                         #   EV driving forecast & charging planner
│   │   ├── Dockerfile
│   │   ├── requirements.txt                 #   google-api-python-client, google-auth
│   │   ├── main.py                          #   Entry point + scheduler
│   │   ├── config.py                        #   EV forecast settings
│   │   ├── vehicle.py                       #   Dual Audi Connect account handling
│   │   ├── trips.py                         #   Calendar-based trip prediction
│   │   ├── planner.py                       #   Smart charging plan generator
│   │   ├── healthcheck.py                   #   Docker HEALTHCHECK script
│   │   └── diagnose.py                      #   Step-by-step connectivity/data diagnostic
│   ├── health-monitor/                      #   Health monitoring & alerting
│   │   ├── Dockerfile
│   │   ├── requirements.txt                 #   No extra deps (uses httpx for Docker API)
│   │   ├── main.py                          #   Entry point (HealthMonitorService)
│   │   ├── config.py                        #   Health monitor settings
│   │   ├── checks.py                        #   Infrastructure + Docker + diagnostic checks
│   │   ├── alerts.py                        #   Telegram alerting with cooldown
│   │   ├── healthcheck.py                   #   Docker HEALTHCHECK script
│   │   └── diagnose.py                      #   Self-diagnostic
│   └── example-service/                     #   Template service
│       ├── Dockerfile
│       ├── requirements.txt                 #   Service-specific deps only
│       ├── main.py                          #   Entry point
│       └── healthcheck.py                   #   Docker HEALTHCHECK script
├── HomeAssistant_config/                    # Reference HA configuration (read-only docs)
│   ├── configuration.yaml                   #   Main HA config (entities, integrations, InfluxDB)
│   ├── ev_audi_connect.yaml                 #   Dual Audi Connect template sensors + automation
│   └── ...                                  #   KNX, sensor, climate, cover, light configs
├── infrastructure/                          # Config for infra containers
│   └── mosquitto/config/mosquitto.conf
└── scripts/
    ├── build-base.sh                        #   Build the shared base image
    ├── new-service.sh                       #   Scaffold a new service
    ├── ha-export.py                         #   Export all HA entities/services to Markdown
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
docker compose run --rm orchestrator python diagnose.py              # test everything
docker compose run --rm orchestrator python diagnose.py --step llm   # test just LLM provider

docker compose run --rm pv-forecast python diagnose.py               # test everything
docker compose run --rm pv-forecast python diagnose.py --step ha     # test just HA

docker compose run --rm smart-ev-charging python diagnose.py         # test everything
docker compose run --rm smart-ev-charging python diagnose.py --step wallbox  # test just wallbox

docker compose run --rm ev-forecast python diagnose.py               # test everything
docker compose run --rm ev-forecast python diagnose.py --step audi   # test just Audi Connect

docker compose run --rm health-monitor python diagnose.py            # test everything
docker compose run --rm health-monitor python diagnose.py --step docker  # test just Docker
```

orchestrator steps: `config`, `ha`, `mqtt`, `llm`, `telegram`, `calendar`, `memory`, `services`, `all`
pv-forecast steps: `config`, `ha`, `influx`, `mqtt`, `weather`, `forecast`, `all`
smart-ev-charging steps: `config`, `ha`, `wallbox`, `energy`, `mqtt`, `cycle`, `all`
ev-forecast steps: `config`, `ha`, `audi`, `mqtt`, `calendar`, `geocoding`, `plan`, `all`
health-monitor steps: `config`, `ha`, `mqtt`, `docker`, `telegram`, `all`

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

### Exporting Home Assistant data

Export all entities, states, services, areas, and devices to a Markdown reference file:

```bash
python scripts/ha-export.py                          # Output: HomeAssistant_config/ha_export.md
python scripts/ha-export.py -o custom-path.md        # Custom output path
```

Requires `HA_URL` and `HA_TOKEN` in `.env`. Uses REST API for states/services and WebSocket API for area/device/entity registries. The generated file is useful as AI context — it gives a complete picture of what's available in the home.

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

### Inter-service commands via MQTT

The orchestrator can send commands to other services via MQTT:

```
homelab/orchestrator/command/{service-name}
```

Payload: `{"command": "refresh"}`, `{"command": "retrain"}`, `{"command": "refresh_vehicle"}`

Every service subscribes to its command topic on startup and handles commands asynchronously.
The orchestrator exposes this via the `request_service_refresh` LLM tool, so the AI can trigger
on-demand updates when a user asks for fresh data.

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

Services use a file-based healthcheck pattern for Docker:
1. The service writes a timestamp to `/app/data/healthcheck` after each successful operation
2. A `healthcheck.py` script checks if the file was updated within the last 5 minutes
3. The Dockerfile declares: `HEALTHCHECK --interval=60s --start-period=120s CMD ["python", "healthcheck.py"]`

Check health status with `docker ps` (shows `healthy`/`unhealthy` in the STATUS column).

### Configuration

All config flows through `shared.config.Settings` (Pydantic). To add service-specific settings:

```python
from shared.config import Settings as BaseSettings

class MySettings(BaseSettings):
    my_custom_var: str = "default"
```

Environment variables map to field names: `MY_CUSTOM_VAR` env var → `my_custom_var` field.

### MQTT dead-letter error topics

Services publish errors to `homelab/errors/{service-name}` when MQTT message processing fails. Payload includes the original topic, payload, error message, traceback, and timestamp. This provides centralized error visibility without losing the context of what failed.

### Global safe mode

A global safe mode switch (`input_boolean.homelab_safe_mode`) blocks all write actions across all services when enabled. Services check the safe mode entity before calling HA services, writing to the wallbox, or setting HA input helpers. Useful during maintenance or when debugging unexpected behavior. Configure the entity ID via `SAFE_MODE_ENTITY` env var.

### State persistence

Services persist critical state to disk (`/app/data/state.json`) for faster restart recovery. On startup, the service loads persisted state instead of starting from scratch. This avoids re-querying slow external APIs (e.g., Audi Connect, weather) and preserves session energy counters, pending clarifications, and charging plans across container restarts.

### Cross-service correlation IDs

Services propagate a `trace_id` through MQTT messages to correlate related events across services. For example, an ev-forecast plan includes a `trace_id` that appears in the smart-ev-charging status messages, making it easy to trace a charging decision back to the forecast that triggered it.

### Shared retry/backoff utility

`shared/retry.py` provides an exponential backoff decorator for HA API calls and other external requests. Retries with configurable max attempts, base delay, and jitter. Used by `ha_client.py` and service-specific API calls to handle transient network failures gracefully.

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

- **Grid connection meter**: `sensor.power_meter_active_power` (W) — positive = exporting to grid, negative = importing from grid
- **Household consumption**: Shelly 3EM (three-phase) — `sensor.shelly3em_main_channel_total_power` (W, always positive, house only)
- **PV DC input**: `sensor.inverter_input_power` (W) — raw solar panel output
- **Inverter AC output**: `sensor.inverter_active_power` (W) — combined PV + battery AC output
- **Home battery**: `sensor.batteries_charge_discharge_power` (W, positive = charging, negative = discharging), `sensor.batteries_state_of_capacity` (%, SoC) — 7 kWh / 3.5 kW max
- **Energy pricing**: Fixed rates — grid import 25 ct/kWh, feed-in 7 ct/kWh, EV reimbursement 25 ct/kWh. No EPEX spot market used.
- **EV charging**: Amtron wallbox via Modbus — `sensor.amtron_meter_total_power_w`, `sensor.amtron_meter_total_energy_kwh`
- **EV battery**: Audi Connect — SoC sensor (configurable via `EV_SOC_ENTITY`)
- **Forecast.Solar**: Configured per array — `sensor.energy_production_today_east` / `west`, `sensor.energy_production_tomorrow_east` / `west`
- **EV (Audi Connect)**: Dual-account setup with mileage-based active account detection — `sensor.ev_state_of_charge` (%, combined template), `sensor.ev_range` (km), `sensor.ev_charging_state`, `sensor.ev_plug_state`, `sensor.ev_mileage`, `sensor.ev_climatisation`, `binary_sensor.ev_plugged_in`, `binary_sensor.ev_is_charging`, `binary_sensor.ev_climatisation_active` (see `HomeAssistant_config/ev_audi_connect.yaml`)

## Services

### orchestrator — AI-Powered Home Brain & Coordinator

The central intelligence layer that coordinates all services, communicates with users via Telegram, and makes proactive suggestions. Uses an LLM (Gemini by default, swappable) with function-calling to reason about the home state and interact with Home Assistant.

**Architecture**: Brain (LLM + tools) ↔ Telegram (user I/O) ↔ Proactive Engine (scheduled), all backed by Memory (persistent profiles/conversations) and connected to HA/InfluxDB/MQTT.

**LLM Providers** (configured via `LLM_PROVIDER` env var):

| Provider | Model Default | Env Var for API Key |
|----------|--------------|---------------------|
| `gemini` (default) | `gemini-2.0-flash` | `GEMINI_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| `ollama` | `llama3` | — (uses `OLLAMA_URL`) |

**LLM Tools** — functions the AI can call to interact with the home:
- `get_entity_state` — Read any HA entity
- `get_home_energy_summary` — Full energy snapshot (PV, grid, battery, EV, house)
- `get_pv_forecast` — Today/tomorrow solar forecast with hourly breakdown
- `get_ev_charging_status` — Current EV charge mode, power, session energy
- `set_ev_charge_mode` — Change EV charge mode (with user confirmation)
- `get_ev_forecast_plan` — EV driving forecast, predicted trips, and charging plan (from ev-forecast service via MQTT)
- `respond_to_ev_trip_clarification` — Forward user's answer to ev-forecast trip question
- `get_weather_forecast` — Current weather and short-term forecast
- `query_energy_history` — Historical data from InfluxDB (trends/analysis)
- `call_ha_service` — Control any HA device (with user confirmation)
- `get_user_preferences` / `set_user_preference` — Persistent user preferences
- `send_notification` — Send Telegram message to a specific user
- `get_energy_prices` — Grid, feed-in, EPEX spot, oil prices
- `get_calendar_events` — Read family or orchestrator Google Calendar events
- `check_household_availability` — Check who is home/away (absences, business trips)
- `create_calendar_event` — Create reminders/events on orchestrator's own calendar
- `recall_memory` — Semantic search over long-term memory (past conversations, facts, decisions)
- `store_fact` — Store knowledge/facts in long-term semantic memory for future recall
- `request_service_refresh` — Send a command to a service (refresh forecast, retrain model, etc.)

**Communication**: Telegram bot with commands `/start`, `/status`, `/forecast`, `/clear`, `/whoami`, `/help` plus free-text LLM conversation.

**Proactive Features**:
- **Morning briefing** (configurable time) — weather, PV forecast, energy plan for the day
- **Evening summary** — today's production, grid usage, savings
- **Optimization alerts** — excess PV, idle EV, battery strategy opportunities
- **EV charging calendar events** — auto-creates/updates all-day events on orchestrator calendar when ev-forecast reports charging needs. German summaries (e.g., "EV: 15 kWh laden bis 07:00 (Nicole → Lengerich)"). Events are deduplicated by tracking `{date: {event_id, summary}}` — only updated when the summary text changes. Stale events are deleted when a date no longer needs charging.
- **EV trip clarification** — forwards ambiguous trip questions from ev-forecast to Telegram users. When users respond in natural language, the Brain LLM recognizes the context (pending clarifications are injected into the system prompt) and calls the `respond_to_ev_trip_clarification` tool to route the answer back via MQTT.
- **Memory consolidation** — at 3 AM nightly, older conversation memories are grouped and merged by the LLM into denser entries

**Memory** (persistent in `/app/data/memory/`):
- Per-user conversation history (with configurable max length)
- User profiles with learned preferences (sauna days, wake times, departure times)
- Decision log (what the orchestrator decided and why)

**Semantic Memory** (vector-based long-term recall, persistent in `/app/data/memory/semantic_store.json`):
- Embeds conversation snippets, learned facts, and decisions as vectors for later semantic retrieval
- Uses the configured LLM provider's embedding API: Gemini `text-embedding-004` (default), OpenAI `text-embedding-3-small`, or Ollama `nomic-embed-text`
- Pure-Python cosine similarity — no heavy dependencies (ChromaDB, FAISS, PyTorch not needed)
- **LLM summarization** — conversations are distilled into concise memory entries before storage (not raw text dumps), producing better search results and less noise
- **Time-weighted scoring** — search results blend cosine similarity (85%) with recency (15%, 30-day half-life), so recent memories rank higher when equally relevant
- **Nightly consolidation** — at 3 AM, older conversation memories are grouped and merged by the LLM into denser entries (e.g. 50 EV charging conversations → 2-3 consolidated knowledge entries), reducing bloat while preserving important patterns
- LLM can explicitly store facts via `store_fact` tool and search via `recall_memory` tool
- Relevant memories are automatically injected into the LLM context before each response (similarity ≥ 0.5)
- Categories: `conversation` (auto-stored exchanges), `fact` (explicitly stored knowledge), `decision` (orchestrator decisions)
- Scale: up to 5000 entries (~20 MB JSON file), searches in milliseconds
- Enabled by default (`ENABLE_SEMANTIC_MEMORY=true`), disable if no embedding API key is available

**Google Calendar** (optional, via Service Account):
- Family calendar (read-only) — absences, business trips, appointments
- Orchestrator calendar (read/write) — reminders, scheduled actions
- Uses `google-api-python-client` with Service Account auth (no interactive OAuth)
- Setup: create Service Account in Google Cloud Console, share calendars with its email

**Google Calendar Setup** (step-by-step):

1. **Google Cloud Console** — go to https://console.cloud.google.com
   - Create a new project (or use an existing one)
   - Go to **APIs & Services → Library** → search "Google Calendar API" → **Enable**
   - Go to **APIs & Services → Credentials** → **Create Credentials → Service Account**
   - Give it a name (e.g. "homelab-orchestrator"), click through, done
   - Click the new service account → **Keys** tab → **Add Key → Create new key → JSON**
   - Download the JSON key file — this is your `GOOGLE_CALENDAR_CREDENTIALS_FILE`
   - Note the service account email (looks like `name@project.iam.gserviceaccount.com`)

2. **Share the family calendar** (read-only)
   - Open https://calendar.google.com → hover your family calendar on the left → three dots → **Settings and sharing**
   - Under **Share with specific people or groups** → **+ Add people and groups**
   - Paste the service account email → set permission to **See all event details** → Send
   - Scroll to **Integrate calendar** → copy the **Calendar ID** (e.g. `abc123@group.calendar.google.com` or your email for the primary calendar)

3. **Create the orchestrator calendar** (read/write)
   - In Google Calendar, click **+** next to "Other calendars" → **Create new calendar**
   - Name it "Home Orchestrator" → click **Create calendar**
   - Open its settings → under **Share with specific people or groups**, add the service account email with **Make changes to events** permission
   - Copy the **Calendar ID** from **Integrate calendar**

4. **Deploy the credentials**
   - Option A — file mount: copy the JSON key into the orchestrator data volume:
     ```bash
     docker compose up -d orchestrator
     docker cp /path/to/key.json orchestrator:/app/data/google-credentials.json
     ```
   - Option B — base64 env var (no file needed): `base64 -w0 /path/to/key.json` and set `GOOGLE_CALENDAR_CREDENTIALS_JSON` in `.env`

5. **Configure `.env`**:
   ```
   GOOGLE_CALENDAR_CREDENTIALS_FILE=/app/data/google-credentials.json
   GOOGLE_CALENDAR_FAMILY_ID=<family calendar ID from step 2>
   GOOGLE_CALENDAR_ORCHESTRATOR_ID=<orchestrator calendar ID from step 3>
   ```

6. **Verify**: `docker compose restart orchestrator && docker compose logs -f orchestrator` → look for `google_calendar_enabled  family_cal=True  orchestrator_cal=True`

**MQTT**: Subscribes to `homelab/+/heartbeat` and `homelab/+/updated` to track all service states. Also subscribes to `homelab/ev-forecast/plan` (creates calendar events for charging needs) and `homelab/ev-forecast/clarification-needed` (forwards trip questions to users via Telegram).

**HA entities** (via MQTT auto-discovery, "Home Orchestrator" device, 15 entities):
- `binary_sensor` — Service online/offline, Proactive Suggestions enabled, Morning/Evening Briefing enabled
- `sensor` — Uptime, LLM Provider, Messages Today, Tool Calls Today, Suggestions Sent Today, Last Tool Used, Last Decision, Last Suggestion, Services Online
- `sensor` (reasoning) — Orchestrator Reasoning (with `full_reasoning`, `services_tracked`, `last_decision_time` as JSON attributes)

**Config** (env vars): `LLM_PROVIDER`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `MORNING_BRIEFING_TIME`, `ENABLE_PROACTIVE_SUGGESTIONS`, `ENABLE_SEMANTIC_MEMORY`, `GRID_PRICE_CT`, `FEED_IN_TARIFF_CT`, `OIL_PRICE_PER_KWH_CT`, `HOUSEHOLD_USERS`, `GOOGLE_CALENDAR_CREDENTIALS_FILE`, `GOOGLE_CALENDAR_FAMILY_ID`, `GOOGLE_CALENDAR_ORCHESTRATOR_ID`. Most entity IDs have sensible defaults matching the existing HA setup.

**Example use cases**:
- "Do you need to charge your car tomorrow?" → checks PV forecast, EV battery, schedule
- "Can you turn on the wood-firing oven tomorrow at 5 PM to save oil?" → weather check, heating demand analysis
- "Do you need your sauna tomorrow, or can we use more PV for the IR panels?" → preference check, PV forecast comparison
- "How much did PV save us this month?" → InfluxDB historical query + cost calculation

### pv-forecast — AI Solar Production Forecast

Predicts PV output (kWh) for east and west arrays using a Gradient Boosting model
trained on historical production data (InfluxDB) correlated with weather features (Open-Meteo).

**Data flow**: InfluxDB (actual production) + Open-Meteo (radiation/clouds/temp/sunrise/sunset) + Forecast.Solar (optional) → ML model → HA sensors

**Important**: The input energy sensors (`sensor.inverter_pv_east_energy`, `sensor.inverter_pv_west_energy`) are `total_increasing` cumulative sensors. The data collector diffs consecutive hourly values to derive per-hour kWh — it does **not** assume midnight resets.

**Daylight filtering**: Uses actual sunrise/sunset times from Open-Meteo (daily API) to filter training data and forecast hours. A physics constraint also zeros out any prediction where GHI < 5 W/m² (no sun = no power). This replaces an earlier hardcoded 5–21 UTC range that included many dark hours in winter at 52°N.

**Model versioning**: Models are saved as `{"model": ..., "features": [...]}` dicts. On load, the feature list is validated against current `FEATURE_COLS`. If features have changed (e.g., new features added), the old model is automatically discarded and retrained.

**Falls back** to radiation-based estimation when <14 days of training data exist.

**Schedule**: Forecast every hour, model retrain at 1 AM UTC daily.

**HA output sensors** — registered via two mechanisms:

*Via REST API* (prefix configurable via `HA_SENSOR_PREFIX`):
- `sensor.pv_ai_forecast_today_kwh` — total both arrays
- `sensor.pv_ai_forecast_today_remaining_kwh` — remaining from current hour
- `sensor.pv_ai_forecast_tomorrow_kwh`
- `sensor.pv_ai_forecast_day_after_tomorrow_kwh`
- `sensor.pv_ai_forecast_east_today_kwh` / `west_today_kwh`
- `sensor.pv_ai_forecast_east_tomorrow_kwh` / `west_tomorrow_kwh`

Each sensor includes an `hourly` attribute with per-hour breakdown.

*Via MQTT auto-discovery* (grouped under "PV AI Forecast" device in HA, 23 entities):
- `binary_sensor` — Service status (online/offline, 3-min expiry)
- `sensor` — Uptime, Today/Tomorrow/Day-After kWh, Today Remaining kWh, East/West Today/Tomorrow kWh
- `sensor` (diagnostic) — East/West Model Type (ml/fallback), East/West R², East/West MAE, Training Data Days (East/West), Last Model Training timestamp
- `sensor` — Forecast.Solar Today (comparison), Forecast Reasoning (with full_reasoning attribute)

**MQTT events**: `homelab/pv-forecast/updated`, `homelab/pv-forecast/model-trained`, `homelab/pv-forecast/heartbeat`

**ML features** (19 total): `hour`, `day_of_year`, `month`, `shortwave_radiation` (GHI), `direct_radiation`, `diffuse_radiation`, `direct_normal_irradiance` (DNI), `cloud_cover` (total/low/mid/high), `temperature_2m`, `relative_humidity_2m`, `wind_speed_10m`, `sunshine_duration`, `capacity_kwp`, `forecast_solar_kwh`, `sunrise_hour`, `sunset_hour`

**Config** (env vars): `PV_EAST_ENERGY_ENTITY_ID`, `PV_EAST_CAPACITY_KWP`, `PV_EAST_AZIMUTH`, `PV_EAST_TILT` (same for west). `FORECAST_SOLAR_EAST_ENTITY_ID` / `WEST` (optional — used as ML feature). Location auto-detected from HA if not set.

### smart-ev-charging — Smart EV Charging Controller

Controls the Amtron wallbox via HEMS power limit (Modbus register 1002) to optimize
EV charging based on PV surplus, user preferences, and departure deadlines.

**Charge modes** (selected via `input_select.ev_charge_mode`):

| Mode | Behavior |
|------|----------|
| Off | Wallbox paused (HEMS = 0 W) |
| PV Surplus | Dynamic tracking of solar surplus only |
| Smart | PV surplus + grid fill by departure (with "Full by Morning") |
| Eco | Fixed ~5 kW constant |
| Fast | Fixed 11 kW maximum |
| Manual | Service hands off — user controls wallbox directly via HA |

**"Full by Morning"** modifier (`input_boolean.ev_full_by_morning`): When enabled with PV Surplus or Smart mode, the service calculates if the target energy can be reached by departure time. If not, it escalates to grid charging as the deadline approaches.

**EV SoC integration** (Audi Connect): When `EV_SOC_ENTITY` is configured, the service reads the car's actual SoC and computes energy needed: `(target_soc% - current_soc%) × capacity`. Charging stops automatically when target SoC is reached (any mode). Falls back to manual `target_energy_kwh` vs session energy when SoC is unavailable.

**PV surplus formula** (grid meter: positive = exporting, negative = importing):
`pv_available = grid_power + ev_power + battery_power - reserve`. The grid meter sees the net of everything behind it. When the battery charges (battery_power > 0), the EV reclaims that power. When discharging (< 0), available is reduced to only count real PV surplus.

**Battery assist**: On top of PV-only surplus, the strategy allows limited battery discharge for EV charging. This is gated by: SoC > floor (20%), PV forecast quality (good day → more aggressive), and a max discharge rate cap (2 kW default) to protect battery longevity. Battery assist only kicks in when PV is producing but surplus alone isn't enough for the wallbox minimum.

**PV surplus continuation**: After the plan target (energy/SoC) is reached, the service continues PV surplus charging opportunistically. PV into the car is more valuable than feeding back to the grid (25 ct/kWh reimbursement vs 7 ct/kWh feed-in), so the car acts as a profitable energy sink.

**Economics**: Grid import 25 ct/kWh (fixed), feed-in 7 ct/kWh, employer reimburses 25 ct/kWh. No EPEX spot market. PV charging = +18 ct/kWh profit, grid charging = cost-neutral.

**Energy priority order**: Home consumption > Home battery charging > EV surplus charging > Grid feed-in. The PV surplus formula ensures the EV only gets power that would otherwise be exported to the grid, never stealing from household loads or the home battery.

**Control loop**: Every 30 s — read HA state → calculate target power → write HEMS limit → publish MQTT status.

**HA input helpers** (defined in `HomeAssistant_config/configuration.yaml`):
- `input_select.ev_charge_mode` — Charge mode selector
- `input_boolean.ev_full_by_morning` — Deadline mode
- `input_datetime.ev_departure_time` — When the car leaves
- `input_number.ev_target_soc_pct` — Target SoC % (default 80)
- `input_number.ev_target_energy_kwh` — Fallback manual energy target
- `input_number.ev_battery_capacity_kwh` — Total EV battery capacity

**HA output sensors** (via MQTT auto-discovery, "Smart EV Charging" device, 24 entities):
- `binary_sensor` — Service online/offline, Vehicle Connected, Full by Morning active
- `sensor` (core) — Charge Mode, Target Power (W), Actual Power (W), Session Energy (kWh), PV Available (W), Status text, Home Battery Power (W), Home Battery SoC (%), House Power (W)
- `sensor` (EV) — EV SoC (%), Energy Needed (kWh)
- `sensor` (decision context) — PV Surplus before assist (W), Battery Assist Power (W), Battery Assist Reason, PV DC Power (W), Grid Power (W), PV Forecast Remaining (kWh), Energy Remaining to Target (kWh), Target Energy (kWh)
- `sensor` (deadline) — Deadline Hours Left, Deadline Required Power (W)
- `sensor` (reasoning) — Decision Reasoning (with full_reasoning, battery_assist_reason, deadline details as JSON attributes)

**MQTT events**: `homelab/smart-ev-charging/status`, `homelab/smart-ev-charging/heartbeat`

**Config** (env vars): `EV_SOC_ENTITY`, `EV_GRID_PRICE_CT`, `EV_FEED_IN_TARIFF_CT`, `EV_REIMBURSEMENT_CT`, `WALLBOX_MAX_POWER_W`, `WALLBOX_MIN_POWER_W`, `ECO_CHARGE_POWER_W`, `GRID_RESERVE_W`, `CONTROL_INTERVAL_SECONDS`, `BATTERY_MIN_SOC_PCT`, `BATTERY_EV_ASSIST_MAX_W`, `PV_FORECAST_GOOD_KWH`, `SAFE_MODE_ENTITY`. Entity IDs have sensible defaults matching the Amtron + Sungrow + Shelly setup.

### ev-forecast — EV Driving Forecast & Smart Charging Planner

Monitors the Audi A6 e-tron (83 kWh gross / 76 kWh net) via dual Audi Connect accounts, predicts driving needs from the family calendar, and generates smart charging plans that maximize PV usage while ensuring the car is always ready.

**Vehicle**: Audi A6 e-tron, ~22 kWh/100 km average consumption.

**Dual Audi Connect accounts**: Henning and Nicole each have an Audi Connect account for the same car. Only the person who last drove sees valid sensor data — the other shows "unknown". HA template sensors (see `HomeAssistant_config/ev_audi_connect.yaml`) determine the active account via mileage-based comparison and expose combined entities. The service:
1. Reads from combined HA template sensors (`sensor.ev_state_of_charge`, `sensor.ev_range`, `sensor.ev_charging_state`, `sensor.ev_plug_state`, `sensor.ev_mileage`, `sensor.ev_climatisation`, etc.) — HA handles active account selection
2. Triggers `audiconnect.refresh_cloud_data` for both accounts to keep data fresh (account names + VINs still needed for cloud refresh)
3. Individual account sensor config has been replaced with combined sensor entity IDs in the service config

**Calendar-based trip prediction**: Reads the shared family calendar. Events are parsed by prefix:
- `H: <destination>` — Henning drives (e.g., "H: Aachen", "H: STR")
- `N: <destination>` — Nicole drives (e.g., "N: Münster")
- Henning: trips >350 km → takes the train (no EV impact); 100–350 km → asks via Telegram
- Nicole: default commute Mon–Thu to Lengerich (22 km one way), departs 07:00, returns ~18:00
- Known destinations are mapped to distances via a configurable lookup table

**Geocoding** (for unknown destinations): Uses OpenStreetMap Nominatim (free, no API key) to estimate distances. Flow: destination name → geocode to coordinates → haversine straight-line distance → multiply by road factor (default 1.3) → estimated road km. Results are cached per session.

**Known destinations** (configurable via `KNOWN_DESTINATIONS` JSON env var): Pre-mapped city→distance lookup for common trips (e.g., Münster 60 km, Aachen 80 km, STR 500 km). Falls back to geocoding for unknown destinations, then to a conservative 50 km default.

**Trip clarification**: When the ev-forecast service can't determine if someone will use the EV (Henning for 100–350 km trips, unknown destinations), it publishes questions in German to `homelab/ev-forecast/clarification-needed`. Each clarification includes an `event_id` for tracking. The orchestrator forwards these to Telegram and routes user responses back via `homelab/ev-forecast/trip-response`.

**Smart charging plan** (demand-focused): The planner expresses **demand** ("need X kWh by time Y"), not supply. PV optimization is left to the smart-ev-charging service. For the next 3 days, the planner:
1. Calculates energy needed for each day's trips (distance × 22 kWh/100km)
2. Adds safety buffer (min SoC 20% + buffer 10% + min arrival SoC 15%)
3. Compares required SoC to current SoC, tracks running SoC across days
4. Assigns urgency: none → low → medium → high → critical (based on time-to-deadline)
5. Chooses the best charge mode:
   - **PV Surplus** — no trips or SoC already sufficient
   - **Smart** — PV surplus + grid fill by departure deadline
   - **Fast/Eco** — urgent, departure imminent (<2 hours)
6. Automatically sets the HA input helpers (`ev_charge_mode`, `ev_target_energy_kwh`, `ev_departure_time`, `ev_full_by_morning`) for the smart-ev-charging service

**Urgency parameters** (configurable via env vars):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CRITICAL_URGENCY_HOURS` | 2.0 | Departure within 2h — switches to Fast or Eco mode |
| `HIGH_URGENCY_HOURS` | 6.0 | Departure within 6h — switches to Smart mode |
| `FAST_MODE_THRESHOLD_KWH` | 15.0 | In critical urgency, deficit >15 kWh → Fast instead of Eco |
| `EARLY_DEPARTURE_HOUR` | 10 | Tomorrow departure before 10 AM → charge overnight (Smart + Full by Morning) |

**Data flow**: Audi Connect (SoC/range) + Google Calendar (trips) + PV Forecast (solar) → Charging Plan → HA Helpers → smart-ev-charging (wallbox control)

**Schedule**: Vehicle state check every 15 min, plan update every 30 min.

**HA output sensors** (via MQTT auto-discovery, "EV Forecast" device, 13 entities):
- `binary_sensor` — Service online/offline
- `sensor` — EV SoC (%), EV Range (km), Active Account, Charging State, Plug State, Energy Needed Today (kWh), Recommended Charge Mode, Next Trip, Next Departure, Plan Status, Uptime
- `sensor` (reasoning) — Plan Reasoning (with `full_reasoning`, `current_soc_pct`, `total_energy_needed_kwh`, `today_urgency` as JSON attributes)

**MQTT events**: `homelab/ev-forecast/vehicle`, `homelab/ev-forecast/plan`, `homelab/ev-forecast/clarification-needed`, `homelab/ev-forecast/heartbeat`

**MQTT integration with orchestrator**: When a trip needs clarification (unknown distance or Henning's ambiguous trips), publishes to `homelab/ev-forecast/clarification-needed`. The orchestrator can ask via Telegram and respond on `homelab/ev-forecast/trip-response`.

**HA YAML** (`HomeAssistant_config/ev_audi_connect.yaml`): Template sensors that combine both Audi Connect accounts into unified entities. Active account is determined by mileage comparison (higher mileage = last driver). Combined entities: `sensor.ev_state_of_charge`, `sensor.ev_range`, `sensor.ev_charging_state`, `sensor.ev_plug_state`, `sensor.ev_mileage`, `sensor.ev_active_account`, `sensor.ev_climatisation`, `binary_sensor.ev_plugged_in`, `binary_sensor.ev_is_charging`, `binary_sensor.ev_climatisation_active`.

**Config** (env vars): `EV_BATTERY_CAPACITY_GROSS_KWH`, `EV_BATTERY_CAPACITY_NET_KWH`, `EV_CONSUMPTION_KWH_PER_100KM`, `EV_SOC_ENTITY`, `EV_RANGE_ENTITY`, `EV_CHARGING_STATE_ENTITY`, `EV_PLUG_STATE_ENTITY`, `EV_MILEAGE_ENTITY`, `EV_CLIMATISATION_ENTITY` (combined sensor entity IDs — HA handles active account selection), `AUDI_ACCOUNT1_NAME` / `AUDI_ACCOUNT1_VIN`, `AUDI_ACCOUNT2_NAME` / `AUDI_ACCOUNT2_VIN` (needed for cloud refresh only), `NICOLE_COMMUTE_KM`, `NICOLE_COMMUTE_DAYS`, `HENNING_TRAIN_THRESHOLD_KM`, `KNOWN_DESTINATIONS` (JSON), `MIN_SOC_PCT`, `BUFFER_SOC_PCT`, `CRITICAL_URGENCY_HOURS`, `HIGH_URGENCY_HOURS`, `FAST_MODE_THRESHOLD_KWH`, `EARLY_DEPARTURE_HOUR`, `PLAN_UPDATE_MINUTES`, `VEHICLE_CHECK_MINUTES`, `SAFE_MODE_ENTITY`. Uses same `GOOGLE_CALENDAR_*` credentials as the orchestrator.

### health-monitor — Health Monitoring & Telegram Alerting

Continuously monitors all homelab services and infrastructure. Sends Telegram alerts when issues are detected and daily health summaries.

**Monitoring capabilities:**
- **MQTT heartbeats** — tracks all services via `homelab/+/heartbeat`, detects offline transitions (no heartbeat for 5 min)
- **Docker container health** — checks container status (healthy/unhealthy/restarting) and restart counts via Docker socket
- **Infrastructure connectivity** — periodically tests HA API and InfluxDB health endpoint
- **HA entity staleness** — monitors key entities for `unavailable`/`unknown` states
- **Diagnostic execution** — runs `diagnose.py --step all` inside each service's container via `docker exec`

**Alert behaviour:**
- Per-issue cooldown (default 30 min) to avoid spam
- Recovery notifications when issues resolve
- Daily health summary at configurable hour (default 08:00)
- Severity levels: critical (service down, HA unreachable), warning (unhealthy container, stale entity), info (startup)

**Docker socket**: Requires `/var/run/docker.sock` mounted read-only. Used to check container health status and exec diagnose.py inside running containers. Without the socket, heartbeat and infrastructure monitoring still work.

**HA entities** (via MQTT auto-discovery, "Health Monitor" device, 8 entities):
- `binary_sensor` — Service online/offline, HA Connectivity, InfluxDB Connectivity
- `sensor` — Services Online, Services Monitored, Active Issues, Uptime, Last Health Check

**MQTT events**: `homelab/health-monitor/status`, `homelab/health-monitor/heartbeat`

**Config** (env vars): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_IDS` (comma-separated chat IDs), `MONITORED_SERVICES` (comma-separated, default: all 4 services), `HEARTBEAT_TIMEOUT_SECONDS` (5 min), `INFRASTRUCTURE_CHECK_MINUTES` (5), `DIAGNOSTIC_RUN_MINUTES` (30), `DOCKER_CHECK_MINUTES` (2), `ALERT_COOLDOWN_MINUTES` (30), `DAILY_SUMMARY_HOUR` (8, -1 to disable), `WATCHED_ENTITIES` (comma-separated HA entity IDs to check for staleness).

## Inter-Service Integration Patterns

### Demand Publisher / Intelligent Coordinator

Services follow a separation-of-concerns model: **data services publish demand**, the **orchestrator decides what to do**.

Example: ev-forecast publishes "need 15 kWh by 07:00" via MQTT. The orchestrator decides whether to create a calendar event, send a Telegram notification, or both. The ev-forecast service never writes to the calendar directly — it only sets HA input helpers for the smart-ev-charging controller.

### MQTT Thread → Asyncio Bridge

MQTT callbacks (paho) run on a background thread, but services use asyncio. The orchestrator bridges this with:
```python
asyncio.run_coroutine_threadsafe(coro, self._loop)
```
This safely schedules async work (e.g., calendar API calls, Telegram messages) from synchronous MQTT handlers.

### Shared State Dict

Cross-component state within a service is shared via reference to a mutable dict:
```python
self._ev_state = {"plan": None, "pending_clarifications": []}
```
This dict is passed to Brain, ToolExecutor, and ProactiveEngine — all read/write the same object. MQTT handlers update it, LLM tools read it, and the proactive engine reacts to changes.

### Service Chain: ev-forecast → smart-ev-charging

The ev-forecast service writes HA input helpers (`ev_charge_mode`, `ev_target_energy_kwh`, `ev_departure_time`, `ev_full_by_morning`), which the smart-ev-charging service reads on its 30-second control loop. This decouples planning from execution — no direct MQTT dependency between the two.

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

1. **Read before modifying** — Always read a file before proposing changes to it.
2. **Minimal changes** — Only make changes that are directly requested. Avoid over-engineering.
3. **Service template** — When creating new services, use `./scripts/new-service.sh` or copy `services/example-service/`.
4. **Base image** — If you add a dependency to `base/requirements.txt`, remind the user to rebuild with `./scripts/build-base.sh`.
5. **docker-compose.yml** — When adding a new service, add it to `docker-compose.yml` following the existing pattern.
6. **Update this file** — When adding significant components, update this CLAUDE.md.
7. **Security** — Never commit plain `.env`. Secrets go in `.env.enc` (encrypted via SOPS). Be cautious with InfluxDB Flux queries (injection risk if building queries from user input).
8. **InfluxDB** — Currently configured for **v2** (Flux query language). If the user has v1, the client wrapper needs changing.
