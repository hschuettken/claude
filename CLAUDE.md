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
│   ├── orchestrator/                        #   AI-powered home brain & coordinator
│   │   ├── Dockerfile
│   │   ├── requirements.txt                 #   telegram-bot, google-generativeai, openai, anthropic
│   │   ├── main.py                          #   Entry point (OrchestratorService)
│   │   ├── config.py                        #   Orchestrator-specific settings
│   │   ├── brain.py                         #   Core reasoning engine (LLM + tool loop)
│   │   ├── tools.py                         #   LLM tool definitions & execution
│   │   ├── memory.py                        #   Persistent conversations, profiles, preferences
│   │   ├── semantic_memory.py               #   Vector-based long-term memory (embeddings + search)
│   │   ├── calendar.py                      #   Google Calendar integration (read family, write own)
│   │   ├── proactive.py                     #   Scheduled briefings, alerts, suggestions
│   │   ├── healthcheck.py                   #   Docker HEALTHCHECK script
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
│   │   └── healthcheck.py                   #   Docker HEALTHCHECK script
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
- **Energy pricing**: EPEX spot market (`sensor.epex_spot_data_price_2`), `input_number.price_per_kwh_electricity_grid`, `input_number.price_per_kwh_electricity_pv`
- **EV charging**: Amtron wallbox via Modbus — `sensor.amtron_meter_total_power_w`, `sensor.amtron_meter_total_energy_kwh`
- **Forecast.Solar**: Configured per array — `sensor.energy_production_today_east` / `west`, `sensor.energy_production_tomorrow_east` / `west`

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

**Communication**: Telegram bot with commands `/start`, `/status`, `/forecast`, `/clear`, `/whoami`, `/help` plus free-text LLM conversation.

**Proactive Features**:
- **Morning briefing** (configurable time) — weather, PV forecast, energy plan for the day
- **Evening summary** — today's production, grid usage, savings
- **Optimization alerts** — excess PV, idle EV, battery strategy opportunities

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

**MQTT**: Subscribes to `homelab/+/heartbeat` and `homelab/+/updated` to track all service states.

**HA entities** (via MQTT auto-discovery, "Home Orchestrator" device):
- `binary_sensor` — Service online/offline
- `sensor` — Uptime, LLM Provider

**Config** (env vars): `LLM_PROVIDER`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `MORNING_BRIEFING_TIME`, `ENABLE_PROACTIVE_SUGGESTIONS`, `ENABLE_SEMANTIC_MEMORY`, `GRID_PRICE_CT`, `FEED_IN_TARIFF_CT`, `OIL_PRICE_PER_KWH_CT`, `HOUSEHOLD_USERS`, `GOOGLE_CALENDAR_CREDENTIALS_FILE`, `GOOGLE_CALENDAR_FAMILY_ID`, `GOOGLE_CALENDAR_ORCHESTRATOR_ID`. Most entity IDs have sensible defaults matching the existing HA setup.

**Example use cases**:
- "Do you need to charge your car tomorrow?" → checks PV forecast, EV battery, schedule
- "Can you turn on the wood-firing oven tomorrow at 5 PM to save oil?" → weather check, heating demand analysis
- "Do you need your sauna tomorrow, or can we use more PV for the IR panels?" → preference check, PV forecast comparison
- "How much did PV save us this month?" → InfluxDB historical query + cost calculation

### pv-forecast — AI Solar Production Forecast

Predicts PV output (kWh) for east and west arrays using a Gradient Boosting model
trained on historical production data (InfluxDB) correlated with weather features (Open-Meteo).

**Data flow**: InfluxDB (actual production) + Open-Meteo (radiation/clouds/temp) + Forecast.Solar (optional) → ML model → HA sensors

**Important**: The input energy sensors (`sensor.inverter_pv_east_energy`, `sensor.inverter_pv_west_energy`) are `total_increasing` cumulative sensors. The data collector diffs consecutive hourly values to derive per-hour kWh — it does **not** assume midnight resets.

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

*Via MQTT auto-discovery* (grouped under "PV AI Forecast" device in HA):
- `binary_sensor` — Service status (online/offline, 3-min expiry)
- `sensor` — Uptime (seconds), Today kWh, Today Remaining kWh, Tomorrow kWh, Day After kWh

**MQTT events**: `homelab/pv-forecast/updated`, `homelab/pv-forecast/model-trained`, `homelab/pv-forecast/heartbeat`

**Config** (env vars): `PV_EAST_ENERGY_ENTITY_ID`, `PV_EAST_CAPACITY_KWP`, `PV_EAST_AZIMUTH`, `PV_EAST_TILT` (same for west). `FORECAST_SOLAR_EAST_ENTITY_ID` / `WEST` (optional — used as ML feature). Location auto-detected from HA if not set.

### smart-ev-charging — Smart EV Charging Controller

Controls the Amtron wallbox via HEMS power limit (Modbus register 1002) to optimize
EV charging based on PV surplus, user preferences, and departure deadlines.

**Economics**: Grid buy 25 ct/kWh (fixed), feed-in 7 ct/kWh, employer reimburses 25 ct/kWh.
Charging from PV surplus = +18 ct/kWh profit. Grid charging = cost-neutral.

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

**PV surplus formula** (grid meter: positive = exporting, negative = importing):
`pv_available = grid_power + ev_power + battery_power - reserve`. The grid meter sees the net of everything behind it. When the battery charges (battery_power > 0), the EV reclaims that power. When discharging (< 0), available is reduced to only count real PV surplus.

**Battery assist**: On top of PV-only surplus, the strategy allows limited battery discharge for EV charging. This is gated by: SoC > floor (20%), PV forecast quality (good day → more aggressive), and a max discharge rate cap (2 kW default) to protect battery longevity. Battery assist only kicks in when PV is producing but surplus alone isn't enough for the wallbox minimum.

**Control loop**: Every 30 s — read HA state → calculate target power → write HEMS limit → publish MQTT status.

**HA input helpers** (defined in `HomeAssistant_config/configuration.yaml`):
- `input_select.ev_charge_mode` — Charge mode selector
- `input_boolean.ev_full_by_morning` — Deadline mode
- `input_datetime.ev_departure_time` — When the car leaves
- `input_number.ev_target_energy_kwh` — Energy to add this session
- `input_number.ev_battery_capacity_kwh` — Total EV battery capacity

**HA output sensors** (via MQTT auto-discovery, "Smart EV Charging" device, 10 entities):
- `binary_sensor` — Service online/offline
- `sensor` — Charge Mode, Target Power (W), Actual Power (W), Session Energy (kWh), PV Available (W), Status text, Home Battery Power (W), Home Battery SoC (%), House Power (W)

**MQTT events**: `homelab/smart-ev-charging/status`, `homelab/smart-ev-charging/heartbeat`

**Config** (env vars): `EV_GRID_PRICE_CT`, `EV_FEED_IN_TARIFF_CT`, `EV_REIMBURSEMENT_CT`, `WALLBOX_MAX_POWER_W`, `WALLBOX_MIN_POWER_W`, `ECO_CHARGE_POWER_W`, `GRID_RESERVE_W`, `CONTROL_INTERVAL_SECONDS`, `BATTERY_MIN_SOC_PCT`, `BATTERY_EV_ASSIST_MAX_W`, `PV_FORECAST_GOOD_KWH`. Entity IDs have sensible defaults matching the Amtron + Sungrow + Shelly setup.

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
