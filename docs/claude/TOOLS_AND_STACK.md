# Tools & Stack Documentation

> **Purpose**: Complete reference of the tools, dependencies, infrastructure, scripts, and operational patterns used in this project. Designed to be reusable — copy into new repos and adapt.

---

## Table of Contents

1. [Runtime & Language](#1-runtime--language)
2. [Python Dependencies](#2-python-dependencies)
3. [Infrastructure Stack](#3-infrastructure-stack)
4. [Docker & Orchestration](#4-docker--orchestration)
5. [Secrets Management (SOPS + age)](#5-secrets-management-sops--age)
6. [Environment Configuration (.env)](#6-environment-configuration-env)
7. [Deploy Scripts](#7-deploy-scripts)
8. [Utility Scripts](#8-utility-scripts)
9. [Git Hooks & Safety](#9-git-hooks--safety)
10. [Debugging & IDE Integration](#10-debugging--ide-integration)
11. [AI Memory & Knowledge System](#11-ai-memory--knowledge-system)
12. [Monitoring & Alerting](#12-monitoring--alerting)
13. [Documentation Sync](#13-documentation-sync)

---

## 1. Runtime & Language

| Component        | Version / Tool                  | Notes                                           |
|------------------|---------------------------------|-------------------------------------------------|
| Language         | Python 3.12                     | `python:3.12-slim` Docker base                  |
| Async framework  | `asyncio` (stdlib)              | All services async by default                   |
| Package manager  | `pip`                           | No Poetry/PDM — plain `requirements.txt`        |
| Type checking    | Type hints on all signatures    | No mypy/pyright enforced yet                    |
| Server Python    | PEP 668 restricted              | Use `python3 -m venv` for scripts, never `pip install` system-wide |

---

## 2. Python Dependencies

### Shared (base image — `base/requirements.txt`)

All services inherit these. Rebuild base image after changes: `./scripts/build-base.sh`.

| Package                      | Version Constraint   | Purpose                                      |
|------------------------------|----------------------|----------------------------------------------|
| `homeassistant-api`          | `>=4.2.1,<6`         | Home Assistant REST client                    |
| `websockets`                 | `>=12.0,<14.0`       | HA WebSocket API                              |
| `influxdb-client[async]`     | `>=1.40,<2`          | InfluxDB v2 queries (Flux)                    |
| `paho-mqtt`                  | `>=2.0,<3`           | MQTT pub/sub messaging                        |
| `pydantic`                   | `>=2.5,<3`           | Data validation & settings                    |
| `pydantic-settings`          | `>=2.1,<3`           | `.env` file loading into typed config         |
| `python-dotenv`              | `>=1.0,<2`           | Fallback `.env` loading                       |
| `structlog`                  | `>=24.1,<26`         | Structured logging (event + kwargs)           |
| `httpx`                      | `>=0.27,<1`          | Modern async HTTP client                      |
| `apscheduler`                | `>=3.10,<4`          | Cron-like task scheduling                     |
| `debugpy`                    | `>=1.8,<2`           | VS Code remote debugger attach                |

### Service-specific dependencies

Each service has its own `services/<name>/requirements.txt` layered on top of the base image.

| Service              | Key Dependencies                                            |
|----------------------|-------------------------------------------------------------|
| `orchestrator`       | `python-telegram-bot`, `google-generativeai`, `openai`, `anthropic`, `google-api-python-client`, `google-auth` |
| `pv-forecast`        | `scikit-learn`, `pandas`, `numpy`                           |
| `smart-ev-charging`  | (none — base image sufficient)                              |
| `ev-forecast`        | `google-api-python-client`, `google-auth`                   |
| `health-monitor`     | (none — uses `httpx` for Docker API)                        |
| `dashboard`          | `nicegui`                                                   |

### Adding dependencies

| Scope                        | Where                                | Then rebuild                         |
|------------------------------|--------------------------------------|--------------------------------------|
| Shared across all services   | `base/requirements.txt`              | `./scripts/build-base.sh` + all services |
| Specific to one service      | `services/<name>/requirements.txt`   | That service only                    |

---

## 3. Infrastructure Stack

### Core infrastructure (Docker Compose)

| Component    | Image / Tool             | Port  | Purpose                                    |
|--------------|--------------------------|-------|--------------------------------------------|
| MQTT Broker  | `eclipse-mosquitto:2`    | 1883  | Inter-service messaging, HA integration    |
| InfluxDB     | `influxdb:2` (optional)  | 8086  | Time-series data (Flux query language)     |
| Ollama       | `ollama/ollama` (optional)| 11434 | Local LLM inference (GPU passthrough)     |

### External integrations

| System             | Protocol            | Client wrapper                  |
|--------------------|----------------------|---------------------------------|
| Home Assistant     | REST + WebSocket     | `shared/ha_client.py`           |
| InfluxDB v2        | HTTP (Flux)          | `shared/influx_client.py`       |
| MQTT (Mosquitto)   | MQTT 3.1.1           | `shared/mqtt_client.py`         |
| Telegram           | Bot API (polling)    | `python-telegram-bot`           |
| Google Calendar    | REST (Service Acct)  | `google-api-python-client`      |
| OpenStreetMap      | Nominatim API        | Direct `httpx` (geocoding)      |
| Open-Meteo         | REST API             | Direct `httpx` (weather)        |
| Forecast.Solar     | HA integration       | Read via HA entities            |
| Audi Connect       | HA integration       | Read via HA entities            |

### LLM providers (pluggable)

| Provider     | Default model            | API key env var       | Embedding model              |
|--------------|--------------------------|----------------------|------------------------------|
| Gemini       | `gemini-2.0-flash`       | `GEMINI_API_KEY`     | `gemini-embedding-001`       |
| OpenAI       | `gpt-4o`                 | `OPENAI_API_KEY`     | `text-embedding-3-small`     |
| Anthropic    | `claude-sonnet-4-20250514`| `ANTHROPIC_API_KEY` | —                            |
| Ollama       | `llama3`                 | — (`OLLAMA_URL`)     | `nomic-embed-text`           |

Configured via `LLM_PROVIDER` env var. Hot-swappable without code changes.

---

## 4. Docker & Orchestration

### Image layering

```
python:3.12-slim
  └── homelab-base:latest       (shared deps, PYTHONPATH, WORKDIR)
        ├── pv-forecast          (+ scikit-learn, pandas, numpy)
        ├── orchestrator         (+ telegram-bot, google-ai, openai, anthropic)
        ├── smart-ev-charging    (no extra deps)
        ├── ev-forecast          (+ google-api-python-client)
        ├── health-monitor       (no extra deps)
        ├── dashboard            (+ nicegui)
        └── example-service      (template)
```

### Docker Compose service pattern

Every application service follows this template:

```yaml
my-service:
  build:
    context: .                              # Repo root (access to shared/)
    dockerfile: services/my-service/Dockerfile
  restart: unless-stopped
  env_file: .env                            # All config + secrets
  volumes:
    - ./shared:/app/shared:ro               # Shared Python library (read-only)
    - my_service_data:/app/data             # Persistent state (survives rebuilds)
  depends_on:
    - mqtt
  networks:
    - homelab
```

### Network topology

All services share a single `homelab` bridge network. No port exposure by default — only the dashboard (8085) and debugger (5678, dev only) are mapped.

### Volume strategy

| Volume type       | Use case                                          | Example                          |
|-------------------|---------------------------------------------------|----------------------------------|
| Named volume      | Persistent service data (state, models, memory)   | `pv_forecast_data:/app/data`     |
| Bind mount (ro)   | Shared library code                               | `./shared:/app/shared:ro`        |
| Bind mount (rw)   | Dev mode — live source editing                    | `./services/my-service:/app`     |
| Bind mount (ro)   | Infrastructure config                             | `./infrastructure/mosquitto/...` |
| Host socket       | Docker API access (health-monitor)                | `/var/run/docker.sock:ro`        |

### Key conventions

- **Build context is repo root** so Dockerfiles can copy from both `services/` and `shared/`.
- **Shared code is volume-mounted, not baked into images.** Update shared code without rebuilding.
- **`restart: unless-stopped`** — auto-restart on crash, stay down after manual stop.
- **`--start-period=120s` on HEALTHCHECK** — give services time before Docker marks them unhealthy.
- **One `.env` for all services** — Pydantic's `extra="ignore"` drops irrelevant vars.

---

## 5. Secrets Management (SOPS + age)

### Overview

Secrets are encrypted at rest using [SOPS](https://github.com/getsops/sops) with [age](https://github.com/FiloSottile/age) public-key encryption. No KMS or cloud dependency — pure local encryption.

### File flow

```
.env           ←→  .env.enc
 (plain text)       (encrypted, committed to git)
 (gitignored)       (safe to push)
```

### Tools required

| Tool   | Purpose                    | Install                            |
|--------|----------------------------|------------------------------------|
| `sops` | Encrypt/decrypt `.env`     | `brew install sops` or binary      |
| `age`  | Encryption backend         | `brew install age` or binary       |

### Key storage

- **Public key**: in `.sops.yaml` (committed)
- **Private key**: `.sops/age-key.txt` (gitignored, back up in password manager)
- If the private key is lost, secrets cannot be decrypted — there is no recovery.

### Scripts

| Script                        | Purpose                                    |
|-------------------------------|-------------------------------------------|
| `./scripts/secrets-encrypt.sh`| Encrypt `.env` → `.env.enc`               |
| `./scripts/secrets-decrypt.sh`| Decrypt `.env.enc` → `.env`               |
| `./scripts/secrets-edit.sh`   | Edit encrypted secrets in-place via `$EDITOR` |

### .sops.yaml config

```yaml
creation_rules:
  - path_regex: \.env(\.enc)?$
    age: age1...   # Your age public key
```

### Setup on a new machine

```bash
# 1. Install tools
brew install sops age   # or download binaries

# 2. Copy your age private key (from password manager)
mkdir -p .sops
cp /path/to/age-key.txt .sops/age-key.txt

# 3. Decrypt
./scripts/secrets-decrypt.sh

# 4. Install git hooks (prevents committing plain .env)
./scripts/install-hooks.sh
```

---

## 6. Environment Configuration (.env)

Everything is configurable via environment variables in `.env`. The file is shared across all services — each service ignores variables it doesn't use (`extra="ignore"` in Pydantic).

### Variable categories

#### Infrastructure connections

| Variable          | Default                             | Description                         |
|-------------------|-------------------------------------|-------------------------------------|
| `HA_URL`          | `http://homeassistant.local:8123`   | Home Assistant API URL              |
| `HA_TOKEN`        | (required)                          | HA long-lived access token          |
| `INFLUXDB_URL`    | (required)                          | InfluxDB v2 URL                     |
| `INFLUXDB_TOKEN`  | (required)                          | InfluxDB auth token                 |
| `INFLUXDB_ORG`    | (required)                          | InfluxDB organization ID            |
| `INFLUXDB_BUCKET` | `hass`                              | InfluxDB bucket name                |
| `MQTT_HOST`       | `mqtt`                              | MQTT broker hostname                |
| `MQTT_PORT`       | `1883`                              | MQTT broker port                    |

#### AI / LLM

| Variable            | Default          | Description                          |
|---------------------|------------------|--------------------------------------|
| `LLM_PROVIDER`      | `gemini`         | `gemini` / `openai` / `anthropic` / `ollama` |
| `GEMINI_API_KEY`    | (required for gemini) | Google AI API key               |
| `OPENAI_API_KEY`    | (required for openai) | OpenAI API key                  |
| `ANTHROPIC_API_KEY` | (required for anthropic) | Anthropic API key            |
| `OLLAMA_URL`        | `http://ollama:11434` | Ollama server URL              |

#### Global settings

| Variable              | Default                                | Description                    |
|-----------------------|----------------------------------------|--------------------------------|
| `LOG_LEVEL`           | `INFO`                                 | Python log level               |
| `TIMEZONE`            | `Europe/Berlin`                        | Default timezone               |
| `SAFE_MODE_ENTITY`    | `input_boolean.homelab_safe_mode`      | HA entity for global safe mode |
| `HEARTBEAT_INTERVAL_SECONDS` | `60`                            | MQTT heartbeat frequency (0 = disabled) |

#### Cross-repo documentation sync (see section 13)

| Variable          | Default | Description                                              |
|-------------------|---------|----------------------------------------------------------|
| `SYNC_REPOS`      | (empty) | Comma-separated `owner/repo` list for docs sync          |
| `SYNC_DOCS_BRANCH`| `main`  | Target branch in destination repos                       |

All service-specific variables (PV arrays, EV specs, charging economics, Telegram, Calendar, etc.) are documented in `.env.example`.

---

## 7. Deploy Scripts

### Push: `./scripts/deploy-push.sh`

Encrypt secrets, stage changes, and push to git — one command for dev-to-repo deployment.

```bash
# Interactive (shows diff, asks for confirmation)
./scripts/deploy-push.sh "Add PV forecast improvements"

# Non-interactive (CI/scripted use)
./scripts/deploy-push.sh -y "Automated config update"
```

**Steps:**
1. Encrypt `.env` → `.env.enc` via SOPS
2. Stage only already-tracked files (`git add -u`) plus `.env.enc`
3. Show untracked files for awareness (but don't auto-add them)
4. Show staged diff and ask for confirmation (skip with `-y`)
5. Commit with the provided message
6. Push to current branch with retry (up to 4 attempts, exponential backoff: 2s → 4s → 8s → 16s)

**Safety features:**
- Never picks up untracked files (prevents accidentally committing credentials directories)
- Shows exactly what will be committed before confirming
- Retries on network failure only
- `set -euo pipefail` — any step failure stops the entire script

### Pull/Deploy: `./scripts/deploy-pull.sh`

Pull latest code and restart all services on the server — one command for repo-to-server deployment.

```bash
./scripts/deploy-pull.sh
```

**Steps:**
1. `git pull --ff-only` from current branch (with retry, exponential backoff)
2. Abort cleanly on diverged branches — never force-pulls
3. Decrypt `.env.enc` → `.env` (if age key is present)
4. Rebuild the shared base image via `./scripts/build-base.sh`
5. `docker compose up --build -d` all services (excluding `example-service`)

**Safety features:**
- Fast-forward only — refuses to merge divergent histories
- Skips decryption gracefully if age key is missing but `.env` exists
- Fails immediately if no `.env` can be produced

### Typical deployment workflow

```
Workstation                          Server
───────────                          ──────
1. Edit code
2. Test locally
3. ./scripts/deploy-push.sh     →   (git push)
                                     4. SSH into server
                                     5. ./scripts/deploy-pull.sh
                                     6. docker compose logs -f
```

---

## 8. Utility Scripts

| Script                       | Purpose                                                   | Usage                                      |
|------------------------------|-----------------------------------------------------------|--------------------------------------------|
| `scripts/build-base.sh`     | Build the shared `homelab-base:latest` Docker image       | `./scripts/build-base.sh`                  |
| `scripts/new-service.sh`    | Scaffold a new microservice (Dockerfile, main.py, etc.)   | `./scripts/new-service.sh my-service`      |
| `scripts/ha-export.py`      | Export all HA entities/services to Markdown                | `python scripts/ha-export.py`              |
| `scripts/secrets-encrypt.sh`| Encrypt `.env` → `.env.enc`                              | `./scripts/secrets-encrypt.sh`             |
| `scripts/secrets-decrypt.sh`| Decrypt `.env.enc` → `.env`                              | `./scripts/secrets-decrypt.sh`             |
| `scripts/secrets-edit.sh`   | Edit encrypted secrets in-place                           | `./scripts/secrets-edit.sh`                |
| `scripts/install-hooks.sh`  | Install git pre-commit hooks                              | `./scripts/install-hooks.sh`               |

### Service scaffolding (`new-service.sh`)

Generates a complete service skeleton:

```bash
./scripts/new-service.sh my-new-service
```

Creates `services/my-new-service/` with:
- `Dockerfile` — extends `homelab-base:latest`, installs service-specific deps
- `requirements.txt` — empty placeholder
- `main.py` — `BaseService` subclass with `run()` stub
- `healthcheck.py` — file-based Docker health check

The class name is auto-derived from the service name (PascalCase: `my-new-service` → `MyNewServiceService`).

### HA export (`ha-export.py`)

Generates a comprehensive Markdown reference of the entire Home Assistant setup:

```bash
python scripts/ha-export.py                     # Output: HomeAssistant_config/ha_export.md
python scripts/ha-export.py -o custom-path.md    # Custom output path
```

Requires `HA_URL` and `HA_TOKEN` in `.env`. Exports:
- Configuration summary
- All areas and devices
- All entities grouped by domain (with state, attributes)
- All available services
- Useful as AI context for understanding the smart home

---

## 9. Git Hooks & Safety

### Pre-commit hook

Installed via `./scripts/install-hooks.sh`. Prevents two critical mistakes:

| Blocked pattern | Reason                                    |
|-----------------|-------------------------------------------|
| `.env`          | Plain-text secrets — must never be committed |
| `.sops/`        | Age private key — must never be committed |

The hook runs on every `git commit` and aborts with an error message if either pattern is staged.

### .gitignore protections

| Pattern                      | Protects against                          |
|------------------------------|-------------------------------------------|
| `.env`                       | Plain-text secrets                        |
| `.sops/`                     | Age private key                           |
| `credentials/`               | Any credential files                      |
| `docker-compose.override.yml`| Personal dev config leaking               |
| `__pycache__/`, `*.pyc`     | Build artifacts                           |
| `.idea/`, `.vscode/*`        | IDE-specific settings (except `launch.json`) |

The VS Code `launch.json` is explicitly whitelisted (`!.vscode/launch.json`) so debugger configs are shared across the team.

---

## 10. Debugging & IDE Integration

### VS Code remote debugging (debugpy)

Every service supports remote debugging via `debugpy`. The debugger is baked into the base image.

**Setup:**
1. Copy `docker-compose.override.example.yml` → `docker-compose.override.yml`
2. Set `DEBUG_SERVICE=my-service` for the target service
3. Ensure port `5678` is mapped
4. Start the service: `docker compose up my-service`
5. The service prints "Waiting for debugger..." and pauses
6. In VS Code: press F5 → select the attach configuration
7. Set breakpoints, step through code

**How it works:**

In `BaseService.__init__()`:
```python
if os.environ.get("DEBUG_SERVICE") == self.name:
    import debugpy
    debugpy.listen(("0.0.0.0", 5678))
    debugpy.wait_for_client()  # Pauses here until VS Code connects
```

### VS Code launch configurations (`.vscode/launch.json`)

| Configuration                      | Description                              |
|------------------------------------|------------------------------------------|
| "Attach to pv-forecast"           | Connects to port 5678, maps `services/pv-forecast/` → `/app` |
| "Attach to any service (port 5678)"| Generic attach, maps workspace root → `/app` |

### Quick debugging (no IDE)

Add `breakpoint()` anywhere in the code and run interactively:

```bash
docker compose run --rm my-service python main.py
```

This drops into `pdb` at the breakpoint — works without VS Code.

---

## 11. AI Memory & Knowledge System

The orchestrator service maintains a three-layer persistent memory system for learning and recalling information across conversations and restarts.

### Layer 1: Conversation Memory

| Storage file                                       | Content                                   |
|----------------------------------------------------|-------------------------------------------|
| `/app/data/memory/profiles.json`                   | Per-user profiles, preferences, patterns  |
| `/app/data/memory/conversations/<chat_id>.json`    | Per-chat conversation history             |
| `/app/data/memory/decisions.json`                  | Decision log (what the AI decided & why)  |

- Atomic writes (write to `.tmp`, then `rename()`) — crash-safe
- Conversation history trimmed to `MAX_CONVERSATION_HISTORY` (default 50)
- Decision log trimmed to `MAX_DECISIONS` (default 500)

### Layer 2: Semantic Memory (vector search)

**Storage**: `/app/data/memory/semantic_store.json`

- Each memory entry: text + embedding vector + category + metadata + timestamp
- Pure Python cosine similarity — no FAISS, ChromaDB, or PyTorch required
- Time-weighted scoring: `final = 0.85 × cosine_sim + 0.15 × recency`
- Recency decay: exponential with configurable half-life (default 30 days)
- LLM-powered summarization: conversations distilled to 1-2 sentences before storage
- Nightly consolidation (3 AM): older entries merged into denser knowledge entries
- Scale: up to 5000 entries, millisecond search times

**Categories:**
- `conversation` — auto-stored after each exchange
- `fact` — explicitly stored via `store_fact` tool
- `decision` — orchestrator decisions with reasoning

### Layer 3: Knowledge Store + Memory Document

#### Knowledge Store (`/app/data/memory/knowledge.json`)

Typed, structured facts that services can query programmatically.

| Fact type         | Example                                              |
|-------------------|------------------------------------------------------|
| `destination`     | "Münster" → 60 km, coordinates                       |
| `person_pattern`  | "Nicole commutes Mon-Thu"                            |
| `preference`      | "Henning prefers sauna on Fridays"                   |
| `correction`      | "Aachen is 80 km, not 60 km"                        |
| `general`         | Any other learned fact                               |

- Confidence levels: `0.7` (LLM-inferred), `1.0` (user-confirmed)
- Published via MQTT (`homelab/orchestrator/knowledge-update`) for cross-service consumption
- Downstream services (e.g., ev-forecast) subscribe and maintain local caches

#### Memory Document (`/app/data/memory/memory.md`)

A living Markdown notebook the AI reads and maintains — like CLAUDE.md but for the AI's own persistent notes.

- Injected into every LLM system prompt
- The AI updates it via the `update_memory_notes` tool when it learns something worth remembering
- Human-readable and editable
- Capped at `MEMORY_DOCUMENT_MAX_SIZE` chars (default 4000)
- Backup kept on each write (`.md.bak`)
- Auto-seeded with section structure if missing

**Default sections:**
```markdown
# Memory Notes
## Household
## Destinations & Distances
## Preferences & Habits
## Patterns & Rules
## Important Notes
```

### Auto-extraction pipeline

After each conversation turn:
1. LLM summarizes the exchange → stored in semantic memory
2. LLM extracts structured facts (destinations, patterns, preferences) as JSON
3. Facts stored in knowledge store with `confidence=0.7`
4. Published via MQTT to downstream services
5. When a user confirms a fact (e.g., via trip clarification), confidence upgrades to `1.0`

### Configuration

| Variable                                 | Default | Description                              |
|------------------------------------------|---------|------------------------------------------|
| `ENABLE_SEMANTIC_MEMORY`                 | `true`  | Enable vector-based memory               |
| `ENABLE_KNOWLEDGE_STORE`                 | `true`  | Enable structured knowledge store        |
| `KNOWLEDGE_AUTO_EXTRACT`                 | `true`  | Auto-extract facts from conversations    |
| `MEMORY_DOCUMENT_MAX_SIZE`               | `4000`  | Max chars for memory.md                  |
| `SEMANTIC_MEMORY_MAX_ENTRIES`            | `5000`  | Max memory entries                       |
| `SEMANTIC_MEMORY_RECENCY_WEIGHT`         | `0.15`  | Weight of recency vs similarity          |
| `SEMANTIC_MEMORY_RECENCY_HALF_LIFE_DAYS` | `30`    | Recency decay half-life                  |
| `MEMORY_CONSOLIDATION_HOUR`              | `3`     | Hour (UTC) for nightly memory merge      |
| `MEMORY_SIMILARITY_THRESHOLD`            | `0.5`   | Min similarity to inject into context    |

---

## 12. Monitoring & Alerting

### Health-monitor service

Continuously monitors all services and infrastructure. Sends Telegram alerts on issues and daily summaries.

**Monitoring layers:**

| Layer                | Method                                       | Interval     |
|----------------------|----------------------------------------------|--------------|
| Service heartbeats   | MQTT `homelab/+/heartbeat` subscription      | 60s          |
| Container health     | Docker socket (`/var/run/docker.sock`)       | 2 min        |
| Infrastructure       | HA API + InfluxDB health endpoint            | 5 min        |
| Entity staleness     | HA state check for `unavailable`/`unknown`   | 5 min        |
| Service diagnostics  | `docker exec` → `python diagnose.py`         | 30 min       |

**Alert behavior:**
- Per-issue cooldown (default 30 min) to prevent spam
- Recovery notifications when issues resolve
- Daily summary at configurable hour (default 8 AM)
- Severity: critical (service down), warning (unhealthy container), info (startup)

### Per-service diagnostics

Every service ships a `diagnose.py` script that can be run inside the container:

```bash
docker compose run --rm my-service python diagnose.py             # Test everything
docker compose run --rm my-service python diagnose.py --step api  # Test just API
```

Steps are independent — one failure doesn't block subsequent checks. Color-coded terminal output (PASS/FAIL/WARN).

### File-based Docker HEALTHCHECK

Services write a timestamp to `/app/data/healthcheck` after each successful operation. A separate `healthcheck.py` script checks if the file is recent (< 5 minutes). Docker manages the healthy/unhealthy lifecycle.

```dockerfile
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]
```

---

## 13. Documentation Sync

### Overview

Documentation files in `docs/<repo-name>/` are designed to be synced across multiple repositories. This ensures all repos share the same architecture guidelines, tool references, and coding conventions.

### Requirements for every repo

Every repository in the ecosystem **must**:

1. **Create its own `docs/<repo-name>/` folder** with at least:
   - `ARCHITECTURE_GUIDELINES.md` — repo-specific architecture, adapted from the `claude` repo's reference
   - `TOOLS_AND_STACK.md` — repo-specific tools, dependencies, scripts, deploy workflows

2. **Follow the patterns described in the shared docs.** These are not suggestions — they are the standard for the ecosystem. See the "Adoption Requirements" section in `ARCHITECTURE_GUIDELINES.md`.

3. **Keep docs up to date.** When you add a service, change infrastructure, add scripts, or modify deploy workflows, update the docs in the same commit.

### How the sync works

The `claude` repo is the **primary source** for shared guidelines. The sync script distributes docs bidirectionally:

```
claude repo                           other repos
───────────                           ───────────
docs/claude/ARCHITECTURE_*.md    →    docs/claude/ARCHITECTURE_*.md
docs/claude/TOOLS_AND_STACK.md   →    docs/claude/TOOLS_AND_STACK.md
docs/repo-a/... (if pulled)     →    docs/repo-a/...

docs/repo-a/...                  ←    docs/repo-a/...  (pulled back)
```

Each repo **owns** only its own `docs/<repo-name>/` folder. All other repo folders are read-only references synced in by the script.

### Sync script

The `scripts/sync-docs.sh` script copies documentation from this repo's `docs/` folder into other repos and pushes the changes. Repo names are configured via the `SYNC_REPOS` variable in `.env`.

### Configuration

Add to `.env`:
```bash
# Comma-separated list of GitHub repos (owner/repo format)
SYNC_REPOS=myuser/repo-a,myuser/repo-b,myuser/repo-c

# Branch to push docs to in destination repos (default: main)
SYNC_DOCS_BRANCH=main

# GitHub directory where repos are cloned (default: /tmp/docs-sync)
SYNC_CLONE_DIR=/tmp/docs-sync
```

### What gets synced

All files in `docs/` are synced to every destination repo:
```
docs/
├── claude/                        ← This repo's docs (synced by repo name)
│   ├── ARCHITECTURE_GUIDELINES.md
│   └── TOOLS_AND_STACK.md
├── repo-a/                        ← repo-a's docs (synced back from repo-a)
│   └── ARCHITECTURE_GUIDELINES.md
└── repo-b/                        ← repo-b's docs
    └── ...
```

Each repo only writes to its own `docs/<repo-name>/` subfolder. The sync script merges all docs from all repos.

### Usage

```bash
# Pull latest, then sync
git pull origin main
./scripts/sync-docs.sh             # Sync all repos configured in .env
./scripts/sync-docs.sh repo-a      # Sync only a specific repo
```

### Setting up a new repo for sync

1. Add the repo to `SYNC_REPOS` in `.env` (in the `claude` repo)
2. Run `./scripts/sync-docs.sh` — it will clone the new repo and push the shared docs
3. In the new repo, create `docs/<repo-name>/ARCHITECTURE_GUIDELINES.md` and `TOOLS_AND_STACK.md`
4. Run the sync again — the new repo's docs will be pulled back into `claude`
