# Homelab Automation Platform

Python microservices for home automation, integrating with **Home Assistant** and **InfluxDB**. Each service runs in its own Docker container, communicating via MQTT.

## Goals

- Comfort automation (climate, lighting, routines)
- Energy optimization (electricity and oil usage)
- AI-powered home control and insights

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
┌──────────────────────────────────────────────────┐
│                Docker Compose                     │
│                                                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │ Service A │  │ Service B │  │ Service C │ ...  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │              │              │              │
│       └──────────────┼──────────────┘              │
│                      │                             │
│              ┌───────┴───────┐                     │
│              │  MQTT Broker  │                     │
│              │  (Mosquitto)  │                     │
│              └───────────────┘                     │
└──────────────────────┬─────────────────────────────┘
                       │
          ┌────────────┼────────────┐
          │            │            │
   ┌──────┴──────┐ ┌──┴───┐ ┌─────┴─────┐
   │Home Assistant│ │Influx│ │  Ollama   │
   │              │ │ DB   │ │  (AI/LLM) │
   └──────────────┘ └──────┘ └───────────┘
```

Each service inherits from `BaseService` which provides pre-configured clients for Home Assistant, InfluxDB, and MQTT. See `services/example-service/` for a template.

## Project Structure

See [CLAUDE.md](CLAUDE.md) for detailed documentation.
