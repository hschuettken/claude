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
| **smart-ev-charging** | PV surplus EV charging with battery assist and deadline logic | 22 |

All services expose comprehensive decision context in Home Assistant, so you can see exactly *why* each system made its decision — directly on the MQTT device page.

## Quick Start

```bash
# 1. Configure your environment
cp .env.example .env
# Edit .env with your Home Assistant token, InfluxDB credentials, etc.

# 2. Build the shared base image
./scripts/build-base.sh

# 3. Start services
docker compose up --build
```

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
│         └──────────────────┼────────────────────┘             │
│                            │                                  │
│                    ┌───────┴───────┐                          │
│                    │  MQTT Broker  │                          │
│                    │  (Mosquitto)  │                          │
│                    └───────────────┘                          │
└────────────────────────────┬─────────────────────────────────┘
                             │
                ┌────────────┼────────────┐
                │            │            │
         ┌──────┴──────┐ ┌──┴───┐ ┌─────┴─────┐
         │Home Assistant│ │Influx│ │  LLM API  │
         │  (REST+WS)  │ │ DB v2│ │(Gemini/..)│
         └─────────────┘ └──────┘ └───────────┘
```

Each service inherits from `BaseService` which provides pre-configured clients for Home Assistant, InfluxDB, and MQTT. Services communicate via MQTT events and HA entities — never by importing each other.

## Key Features

- **Decision transparency**: Every service publishes detailed reasoning to HA — see *why* the EV is charging from PV, *why* the forecast model chose ML vs fallback, *what* the orchestrator decided
- **MQTT auto-discovery**: All 59 MQTT entities register themselves in HA automatically — no manual configuration
- **Proactive AI**: The orchestrator sends morning briefings, evening summaries, and optimization alerts via Telegram
- **Battery-aware EV charging**: PV surplus tracking with home battery assist, deadline escalation, and ramp limiting

## Project Structure

See [CLAUDE.md](CLAUDE.md) for detailed documentation including all configuration options, entity IDs, and development workflows.
