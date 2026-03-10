# Homelab Automation Platform

Python microservices for home automation, integrating with **Home Assistant** and **InfluxDB**. Each service runs in its own Docker container, communicating via MQTT.

## Goals

- Comfort automation (climate, lighting, routines)
- Energy optimization (electricity and oil usage)
- AI-powered home control and insights

## Services

| Service | Purpose | HA Entities |
|---------|---------|-------------|
| **orchestrator** | AI-powered home brain — LLM reasoning, Telegram chat, proactive suggestions | 14 |
| **pv-forecast** | ML solar production forecast (Gradient Boosting + weather data) | 23 MQTT + 8 REST |
| **smart-ev-charging** | PV surplus EV charging with battery assist, deadline logic, and watchdog monitoring | 22 |
| **ev-forecast** | EV driving prediction from calendar + dual Audi Connect, smart charging plans | 13 |

All services expose comprehensive decision context in Home Assistant, so you can see exactly *why* each system made its decision — directly on the MQTT device page.

### Data Flow

```
Google Calendar ──► ev-forecast ──► HA Helpers ──► smart-ev-charging ──► Wallbox
                        │                               ▲
                        ▼ (MQTT)                        │
                   orchestrator ──► Telegram        PV surplus
                        │              ▲            calculation
                        ▼              │                ▲
                   Google Calendar   User            pv-forecast
                   (charging events) responses       (solar kWh)
```

**ev-forecast** expresses demand ("need 15 kWh by 07:00"), **smart-ev-charging** handles supply (PV surplus, grid fill, battery assist). The **orchestrator** coordinates user communication and creates calendar events for visibility.

## Quick Start

```bash
# 1. Set up secrets
./scripts/install-hooks.sh          # Install git pre-commit hooks
./scripts/secrets-decrypt.sh        # Decrypt .env.enc → .env (needs age key)
# OR for first-time: cp .env.example .env and fill in values

# 2. Build the shared base image
./scripts/build-base.sh

# 3. Start services
docker compose up --build
```

### Prerequisites

- Docker & Docker Compose
- [sops](https://github.com/getsops/sops/releases) and [age](https://github.com/FiloSottile/age) for secrets management

### Secrets Management

Secrets are stored encrypted in `.env.enc` (SOPS + age). The plain `.env` is gitignored.

```bash
./scripts/secrets-encrypt.sh   # Encrypt .env → .env.enc (commit this)
./scripts/secrets-decrypt.sh   # Decrypt .env.enc → .env (after clone)
./scripts/secrets-edit.sh      # Edit encrypted secrets in-place via $EDITOR
```

For semantic memory, set both `CHROMA_URL` and `CHROMA_AUTH_TOKEN` in `.env`.

**New machine setup:** Install `sops` + `age`, copy your age key to `.sops/age-key.txt`, then run `./scripts/secrets-decrypt.sh`. See [CLAUDE.md](CLAUDE.md) for details.

## Creating a New Service

```bash
./scripts/new-service.sh my-service-name
# Add it to docker-compose.yml, implement your logic, then:
docker compose up --build my-service-name
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Docker Compose                          │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  pv-forecast  │  │ smart-ev-    │  │   orchestrator   │  │
│  │  (ML model)   │  │ charging     │  │   (LLM brain)    │  │
│  │  23+8 sensors │  │ 22 sensors   │  │   14 sensors     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                  │                    │             │
│  ┌──────┴──────┐           │                    │             │
│  │ ev-forecast │           │                    │             │
│  │ 13 sensors  │           │                    │             │
│  └──────┬──────┘           │                    │             │
│         └──────────────────┼────────────────────┘             │
│                            │                                  │
│                    ┌───────┴───────┐                          │
│                    │  MQTT Broker  │                          │
│                    │  (Mosquitto)  │                          │
│                    └───────────────┘                          │
└────────────────────────────┬─────────────────────────────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
     ┌──────┴──────┐  ┌─────┴────┐  ┌───────┴───────┐
     │Home Assistant│  │ InfluxDB │  │ Google Calendar│
     │  (REST+WS)  │  │   v2     │  │ + LLM API     │
     └─────────────┘  └──────────┘  └───────────────┘
```

Each service inherits from `BaseService` which provides pre-configured clients for Home Assistant, InfluxDB, and MQTT. Services communicate via MQTT events and HA entities — never by importing each other.

## Key Features

- **Decision transparency**: Every service publishes detailed reasoning to HA — see *why* the EV is charging from PV, *why* the forecast model chose ML vs fallback, *what* the orchestrator decided
- **MQTT auto-discovery**: All 70+ MQTT entities register themselves in HA automatically — no manual configuration
- **Proactive AI**: The orchestrator sends morning briefings, evening summaries, and optimization alerts via Telegram
- **Battery-aware EV charging**: PV surplus tracking with home battery assist, deadline escalation, and ramp limiting
- **Calendar-driven EV planning**: Predicts driving needs from family calendar, auto-sets charging parameters, creates calendar events for visibility

## Project Structure

See [CLAUDE.md](CLAUDE.md) for detailed documentation including all configuration options, entity IDs, development workflows, and inter-service integration patterns.
