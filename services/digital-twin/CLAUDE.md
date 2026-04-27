# digital-twin — House + Energy + Life Digital Twin

Unified digital representation of the house, energy system, and occupant life.
Provides a real-time state model, a 4-scenario simulation engine (24h horizon),
and a room registry for Home Assistant entity mapping.

## Architecture

- **Framework**: FastAPI at port 8238
- **Storage**: PostgreSQL (192.168.0.80:5432) — room registry + simulation history
- **Event Bus**: NATS JetStream — publishes state/simulation events, subscribes to PV forecast updates
- **Ingest**: Home Assistant REST API, InfluxDB v2

## Key modules

| Module | Purpose |
|--------|---------|
| `models.py` | Pydantic models: HouseState, EnergyState, RoomState, ScenarioResult, etc. |
| `config.py` | Settings from env vars |
| `db.py` | asyncpg pool + schema migrations (3 tables) |
| `room_registry.py` | Room CRUD (PostgreSQL-backed, default rooms pre-seeded) |
| `state_ingestion.py` | HAStateIngester (HA REST) + PVForecastIngester |
| `simulation.py` | Pure 4-scenario simulation engine (no I/O) |
| `main.py` | FastAPI app + NATS subscriptions + Oracle registration |
| `healthcheck.py` | Docker HEALTHCHECK via /health endpoint |

## Scenarios

| ID | Name | Description |
|----|------|-------------|
| A | Baseline | Current settings — opportunistic battery charge from PV surplus |
| B | Aggressive battery | Charge battery to 100% whenever PV available; discharge evening peak (18–22h) |
| C | EV PV-only | EV only charges when PV surplus > minimum wallbox power (1.4 kW) |
| D | Pre-heat | Extra 2 kW heating during low-demand hours (1–6am) to reduce peak load |

## Simulation physics

The engine models an hourly energy balance:
```
net = pv_kwh - house_kwh - ev_kwh - heating_extra_kwh
surplus → charge battery → export to grid
deficit → discharge battery → import from grid
```

Output metrics per scenario:
- `energy_cost_eur`: import cost − export revenue (at fixed tariffs: 25/7 ct/kWh)
- `self_sufficiency_pct`: fraction of consumption met without grid import
- `battery_cycles`: equivalent full charge-discharge cycles
- `ev_charged_kwh`: total EV energy delivered
- `comfort_score`: 0–100 (penalises under-charged EV, overheating risk in D)
- `hourly[]`: 24-element trace for visualization

## Room registry

Default rooms pre-seeded: living_room, kitchen, bedroom_master, office, garage.
Each room maps HA entity IDs for temperature, humidity, occupancy, heating.

## HA entities ingested

| Entity | Meaning |
|--------|---------|
| `sensor.inverter_pv_east_power` | PV east array (W) |
| `sensor.inverter_pv_west_power` | PV west array (W) |
| `sensor.batteries_state_of_capacity` | Battery SoC (%) |
| `sensor.batteries_charge_discharge_power` | Battery power (W, +charging) |
| `sensor.power_meter_active_power` | Grid power (W, +exporting) |
| `sensor.shelly3em_main_channel_total_power` | House consumption (W) |
| `sensor.amtron_meter_total_power_w` | EV charging power (W) |
| `sensor.audi_a6_avant_e_tron_state_of_charge` | EV battery SoC (%) |

## Database tables

| Table | Purpose |
|-------|---------|
| `dt_rooms` | Room registry (room_id, name, HA entity IDs, metadata) |
| `dt_state_snapshots` | Hourly HouseState snapshots (energy + rooms) |
| `dt_simulation_results` | SimulationReport history |

## NATS subjects

| Subject | Direction | Purpose |
|---------|-----------|---------|
| `digital.twin.state.updated` | publish | New HouseState snapshot (every 60s + on demand) |
| `digital.twin.simulation.done` | publish | New SimulationReport after each run |
| `orchestrator.command.digital-twin` | subscribe | `refresh` / `simulate` commands |
| `energy.pv.forecast_updated` | subscribe | Trigger re-simulation on new PV forecast |

## API endpoints

- `GET /health` — service health
- `GET /api/v1/state` — full house state
- `GET /api/v1/state/energy` — energy snapshot only
- `POST /api/v1/state/refresh` — force HA re-fetch (async, 202)
- `GET /api/v1/rooms` — list rooms
- `POST /api/v1/rooms` — add room
- `GET /api/v1/rooms/{room_id}` — get room
- `PATCH /api/v1/rooms/{room_id}` — update room
- `DELETE /api/v1/rooms/{room_id}` — delete room
- `GET /api/v1/scenarios` — list scenario descriptions
- `POST /api/v1/simulate` — run simulation (returns SimulationReport)
- `GET /api/v1/simulate/latest` — latest cached report

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `DIGITAL_TWIN_PORT` | `8238` | Service port |
| `DIGITAL_TWIN_DB_URL` | `postgresql://homelab:homelab@192.168.0.80:5432/homelab` | PostgreSQL DSN |
| `HA_URL` | `http://192.168.0.40:8123` | Home Assistant URL |
| `HA_TOKEN` | — | Long-lived HA token |
| `NATS_URL` | `nats://192.168.0.50:4222` | NATS server |
| `INFLUXDB_URL` | `http://192.168.0.66:8086` | InfluxDB URL |
| `TARIFF_IMPORT_CT` | `25.0` | Grid import tariff (ct/kWh) |
| `TARIFF_EXPORT_CT` | `7.0` | Feed-in tariff (ct/kWh) |
| `BATTERY_CAPACITY_KWH` | `7.0` | Home battery capacity |
| `EV_CAPACITY_KWH` | `83.0` | EV battery capacity (Audi A6 e-tron) |

## Testing

```bash
cd /repos/claude/services/digital-twin
python -m pytest tests/ -v
```

Tests run without any external connections (DB, HA, NATS all gracefully absent).
