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
├── .env.example                             # Template for secrets (copy to .env)
├── .gitignore
├── base/                                    # Shared Docker base image
│   ├── Dockerfile                           #   Python 3.12-slim + common deps
│   └── requirements.txt                     #   Pinned shared dependencies
├── shared/                                  # Shared Python library (mounted into every container)
│   ├── __init__.py
│   ├── config.py                            #   Pydantic settings from env vars
│   ├── logging.py                           #   Structured logging (structlog)
│   ├── ha_client.py                         #   Home Assistant async REST client
│   ├── influx_client.py                     #   InfluxDB v2 query wrapper
│   ├── mqtt_client.py                       #   MQTT pub/sub wrapper
│   └── service.py                           #   BaseService class (inherit this)
├── services/                                # One directory per microservice
│   └── example-service/                     #   Template service
│       ├── Dockerfile
│       ├── requirements.txt                 #   Service-specific deps only
│       └── main.py                          #   Entry point
├── infrastructure/                          # Config for infra containers
│   └── mosquitto/config/mosquitto.conf
└── scripts/
    ├── build-base.sh                        #   Build the shared base image
    └── new-service.sh                       #   Scaffold a new service
```

## Development Workflow

### First-time setup

```bash
cp .env.example .env           # Fill in your HA token, InfluxDB creds, etc.
./scripts/build-base.sh        # Build the shared base Docker image
docker compose up --build      # Start everything
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
- Graceful shutdown with resource cleanup

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
7. **Security** — Never commit `.env`. Be cautious with InfluxDB Flux queries (injection risk if building queries from user input).
8. **InfluxDB** — Currently configured for **v2** (Flux query language). If the user has v1, the client wrapper needs changing.
