# Homelab Automation Platform

Python microservices for home automation, integrating with **Home Assistant** and **InfluxDB**. Each service runs in its own Docker container, communicating via MQTT.

## Goals

- Comfort automation (climate, lighting, routines)
- Energy optimization (electricity and oil usage)
- AI-powered home control and insights

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

**New machine setup:** Install `sops` + `age`, copy your age key to `.sops/age-key.txt`, then run `./scripts/secrets-decrypt.sh`. See [CLAUDE.md](CLAUDE.md) for details.

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
