# Tools & Stack Documentation — atlas_trad

> **Purpose**: Complete reference of the tools, dependencies, infrastructure, scripts, and operational patterns used in the `atlas_trad` repository. This repo hosts an AI-powered investment platform with two trading agents (flatex stocks/ETFs + Bitvavo crypto) delivered via Telegram through OpenClaw.

---

## Table of Contents

1. [Runtime & Language](#1-runtime--language)
2. [Python Dependencies](#2-python-dependencies)
3. [Infrastructure Stack](#3-infrastructure-stack)
4. [LLM Configuration](#4-llm-configuration)
5. [API Endpoints](#5-api-endpoints)
6. [MQTT Topics](#6-mqtt-topics)
7. [Docker & Orchestration](#7-docker--orchestration)
8. [Development Workflow](#8-development-workflow)

---

## 1. Runtime & Language

| Component | Version / Tool | Notes |
|-----------|---------------|-------|
| Language | Python 3.12 | `python:3.12-slim` Docker base image |
| Package manager | `pip` + `requirements.txt` | Separate requirements per service |
| Type checking | Type hints on all signatures | `mypy` strict mode configured in `pyproject.toml` |
| Linting | `ruff` | `line-length=100`, `target-version="py312"` |
| Testing | `pytest` | `asyncio_mode = "auto"`, tests in `tests/` |

---

## 2. Python Dependencies

### python-backend (`services/python-backend/requirements.txt`)

| Package | Purpose |
|---------|---------|
| `fastapi` | REST API framework for all query and mutation endpoints |
| `uvicorn[standard]` | ASGI server for FastAPI (production + development) |
| `httpx` | HTTP client for WebSearch API calls, health checks, and exchange price scraping |
| `yfinance` | Yahoo Finance data source for OHLCV prices and fundamental data |
| `numpy` | Numerical computation for technical indicators (RSI, MACD, Bollinger, ATR) |
| `pandas` | DataFrame operations for price history, feature engineering, and data manipulation |
| `pydantic` | Data validation and serialization for all API models and domain objects |
| `pydantic-settings` | Configuration management via `BaseSettings` with `.env` file loading |
| `python-dotenv` | Environment variable loading from `.env` files |
| `structlog` | Structured logging with snake_case events and kwargs |
| `influxdb-client` | InfluxDB v2 client for time-series writes and Flux queries |
| `paho-mqtt` | MQTT client for event publishing, heartbeats, and error reporting |
| `apscheduler` | Background job scheduler (cron and interval triggers) for recurring tasks |
| `lightgbm` | LightGBM model loading for ML inference (prediction only in backend) |
| `scikit-learn` | ML utilities (ROC AUC score, data splitting) used in inference evaluation |
| `joblib` | Model serialization/deserialization for persisted LightGBM models |

### ml-trainer (`services/ml-trainer/requirements.txt`)

| Package | Purpose |
|---------|---------|
| `influxdb-client` | Query historical data from InfluxDB for feature engineering |
| `pydantic` | Data validation for configuration models |
| `pydantic-settings` | Configuration management via `BaseSettings` |
| `structlog` | Structured logging |
| `pandas` | Feature matrix construction and manipulation |
| `numpy` | Numerical operations for feature computation |
| `lightgbm` | LightGBM binary classifier training |
| `scikit-learn` | ROC AUC scoring, train/validation splitting |
| `joblib` | Model serialization to `/app/data/models/latest.joblib` |

### crypto-trader (`services/crypto-trader/requirements.txt`)

| Package | Purpose |
|---------|---------|
| `fastapi` | REST API framework |
| `uvicorn[standard]` | ASGI server |
| `httpx` | HTTP client for Bitvavo REST API (HMAC-SHA256 auth) |
| `numpy` | Technical indicator computation |
| `pandas` | Candle data manipulation and feature engineering |
| `pydantic` | Data validation and serialization |
| `pydantic-settings` | Configuration via `BaseSettings` |
| `structlog` | Structured logging |
| `influxdb-client` | Time-series writes for prices, signals, snapshots |
| `paho-mqtt` | Event publishing, heartbeats, breaking news alerts |
| `apscheduler` | Recurring jobs (5m execution, 30m ML, 2h news) |
| `lightgbm` | ML model loading for crypto price prediction |
| `scikit-learn` | ML utilities (AUC scoring) |
| `joblib` | Model deserialization |
| `pyyaml` | Trading config.yaml loading |

### crypto-ml-trainer (`services/crypto-ml-trainer/requirements.txt`)

| Package | Purpose |
|---------|---------|
| `httpx` | Fetch historical candles from Bitvavo API |
| `pandas` | Feature matrix construction |
| `numpy` | Numerical feature computation |
| `lightgbm` | LightGBM binary classifier training |
| `scikit-learn` | AUC scoring, time-based train/validation split |
| `joblib` | Model serialization to `/app/data/models/crypto_latest.joblib` |
| `pydantic-settings` | Configuration via `BaseSettings` |
| `structlog` | Structured logging |
| `pyyaml` | Config loading |

---

## 3. Infrastructure Stack

### Docker Compose Services (managed by this repo)

| Service | Image | Port | Profile | Volume | Purpose |
|---------|-------|------|---------|--------|---------|
| `python-backend` | `python:3.12-slim` | 8100:8000 | default | `backend_data` | Flatex backend |
| `crypto-trader` | `python:3.12-slim` | 8200:8000 | default | `crypto_data` | Crypto backend |
| `ml-trainer` | `python:3.12-slim` | (none) | `ml` | `backend_data` | Flatex ML training |
| `crypto-ml-trainer` | `python:3.12-slim` | (none) | `ml` | `crypto_data` | Crypto ML training |

### External Services (NOT managed by this repo)

| Service | Address | Purpose |
|---------|---------|---------|
| InfluxDB v2 | `192.168.0.66:8086` | Time-series storage (bucket: `atlas_trad`, org: `homelab`) |
| Grafana | `192.168.0.67` | Dashboards and visualization for InfluxDB data |
| MQTT Broker | `192.168.0.73:1883` | Event bus for inter-service communication and heartbeats |
| WebSearch API | `scout.local.schuettken.net` | Self-hosted Tavily-compatible search (atlas_helper_tools) |
| Ollama | via OpenClaw | Tier 1 LLM (Qwen2 0.5B) for sentiment classification |
| OpenClaw | Telegram bot | User interaction layer + LLM routing (Tier 1/2/3) |

### Network Architecture

```
User (Telegram)
    │
    v
OpenClaw ─── LLM routing ─── Tier 1: Ollama (Qwen2 0.5B)
    │                         Tier 2: Gemini
    │                         Tier 3: Claude
    │
    ├── /flatex skill ──── HTTP ──── python-backend (:8100)
    │                                     │
    │                                     ├── InfluxDB (:8086)
    │                                     ├── MQTT (:1883)
    │                                     └── WebSearch (scout.local)
    │
    └── /crypto skill ──── HTTP ──── crypto-trader (:8200)
                                          │
                                          ├── Bitvavo REST API
                                          ├── InfluxDB (:8086)
                                          ├── MQTT (:1883)
                                          └── WebSearch (scout.local)
```

---

## 4. LLM Configuration

### Tier 1 -- Ollama / Qwen2 0.5B

| Parameter | Value | Env Var |
|-----------|-------|---------|
| Model | Qwen2 0.5B | (configured in OpenClaw) |
| Context window | 4096 tokens | `LLM_TIER1_CONTEXT_LENGTH` |
| Chars per token | 3.5 | `LLM_TIER1_CHARS_PER_TOKEN` |
| Max input content | ~2500 characters | Derived: leaves room for system + output |
| Cost | Free | Local CPU inference |
| Temperature | 0.1 (for classification) | Set per-request by skill |

**Tier 1 prompt constraints:**
- System prompt under 12 words
- No few-shot examples
- Show expected JSON shape inline
- Truncate input to fit within context budget

### Tier 2 -- Gemini

| Parameter | Value |
|-----------|-------|
| Cost | Cheap |
| Context | Generous |
| Use cases | Morning summaries, weekly reports, analysis, multi-paragraph composition |

### Tier 3 -- Claude

| Parameter | Value |
|-----------|-------|
| Cost | Expensive |
| Quality | Highest |
| Use cases | Buy/sell/hold decisions, portfolio rebalancing, risk assessment |
| Policy | Use sparingly -- only for decisions that could move money |

---

## 5. API Endpoints

### Flatex Backend (python-backend, port 8100)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/diagnose` | Full system diagnostic |
| `GET` | `/portfolio` | Portfolio state (positions, cash, P&L, watchlist) |
| `POST` | `/portfolio/transaction` | Record a buy/sell transaction |
| `POST` | `/portfolio/deposit` | Deposit cash |
| `POST` | `/portfolio/withdraw` | Withdraw cash |
| `GET` | `/signals` | Latest combined signals for all assets |
| `GET` | `/signals/{symbol}` | Signal breakdown for a single asset |
| `GET` | `/prices/{symbol}` | Latest OHLCV price data |
| `GET` | `/prices/{symbol}/history` | 60-day OHLCV history |
| `GET` | `/fees` | Current flatex fee schedule |
| `GET` | `/fees/premium-etfs` | Premium ETF ISIN list |
| `GET` | `/fees/optimal/{symbol}` | Fee-optimal execution path |
| `GET` | `/sentiment` | Latest sentiment scores |
| `GET` | `/sentiment/pending` | Headlines awaiting LLM classification |
| `POST` | `/sentiment/result` | Accept classification result from OpenClaw |
| `GET` | `/technical/{symbol}` | Technical indicator values |
| `GET` | `/watchlist` | Current watchlist |
| `POST` | `/watchlist` | Add symbol to watchlist |
| `DELETE` | `/watchlist/{symbol}` | Remove from watchlist |
| `GET` | `/performance` | Portfolio performance metrics |
| `GET` | `/model` | ML model status |
| `POST` | `/model/retrain` | Trigger ML retraining |
| `POST` | `/command` | Dispatch slash commands |

### Crypto Trader (crypto-trader, port 8200)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (includes dry_run status) |
| `GET` | `/diagnose` | Full system diagnostic (includes Bitvavo API status) |
| `GET` | `/portfolio` | Portfolio state (positions, cash, P&L, deposits) |
| `GET` | `/signals` | Current intelligence signals |
| `POST` | `/signals` | Write intelligence signals (from OpenClaw) |
| `GET` | `/predictions` | ML model predictions |
| `GET` | `/trades` | Recent trade log |
| `GET` | `/trades/deposits` | Deposit history |
| `GET` | `/trades/fees` | Fee summary |
| `GET` | `/config` | Current config.yaml |
| `POST` | `/config` | Update config parameters |
| `POST` | `/command` | Dispatch commands (pause/resume/retrain/dryrun/health/status) |

See [API_REFERENCE.md](./API_REFERENCE.md) for complete endpoint documentation.

---

## 6. MQTT Topics

All topics use the `atlas-trad/` prefix. Client ID format: `atlas-trad-{service_name}`.

### Flatex Topics

| Topic | Publisher | Payload |
|-------|-----------|---------|
| `atlas-trad/python-backend/heartbeat` | Backend | `{status, service, timestamp, scheduler_running, job_count}` |
| `atlas-trad/errors/python-backend` | Backend | `{error, service, timestamp}` |
| `atlas-trad/scheduler/morning_analysis_done` | Scheduler | `{event, timestamp, elapsed_s}` |
| `atlas-trad/scheduler/daily_snapshot_done` | Scheduler | `{event, timestamp, total_value}` |
| `atlas-trad/portfolio/transaction` | API | `{symbol, action, quantity, price, fee}` |
| `atlas-trad/sentiment/classified` | API | `{symbol, sentiment, score, confidence}` |
| `atlas-trad/ml/retrain` | API | `{action, requested_by}` |

### Crypto Topics

| Topic | Publisher | Payload |
|-------|-----------|---------|
| `atlas-trad/crypto-trader/heartbeat` | Crypto | `{timestamp, uptime_s, remaining_weight}` |
| `atlas-trad/errors/crypto-trader` | Crypto | `{error, timestamp}` |
| `atlas-trad/crypto-trader/news/breaking` | Crypto | `{title, source_job, url, timestamp}` |
| `atlas-trad/crypto-trader/fees/change_detected` | Crypto | `{new_pages, changed_pages, timestamp}` |

---

## 7. Docker & Orchestration

### Images

All services use `python:3.12-slim` as the base image. Each service has its own Dockerfile.

### Volumes

| Volume | Mount Point | Contents |
|--------|------------|----------|
| `backend_data` | `/app/data` | `state.json`, `models/latest.joblib` |
| `crypto_data` | `/app/data` | `crypto_state.json`, `config.yaml`, `models/`, trade data |

### Networks

| Network | Driver | Purpose |
|---------|--------|---------|
| `atlas-trad` | bridge | Internal communication between all services |

### Health Checks

| Service | Script | Interval | Timeout | Start Period | Retries |
|---------|--------|----------|---------|-------------|---------|
| `python-backend` | `healthcheck.py` | 60s | 5s | 120s | 3 |
| `crypto-trader` | `healthcheck.py` | 60s | 5s | 120s | 3 |
| `ml-trainer` | `healthcheck.py` | 300s | 5s | 30s | 1 |

---

## 8. Development Workflow

### Initial Setup

```bash
# 1. Clone the repository
git clone <repo-url> atlas_trad
cd atlas_trad

# 2. Create environment file
cp .env.example .env
# Edit .env: fill in INFLUXDB_TOKEN, BITVAVO_API_KEY, BITVAVO_API_SECRET

# 3. Build Docker images
docker compose build

# 4. Start both backends
docker compose up -d

# 5. Verify health
curl http://localhost:8100/health   # flatex
curl http://localhost:8200/health   # crypto
```

### Development Mode

```bash
# 1. Create development override
cp docker-compose.override.example.yml docker-compose.override.yml

# 2. Start with live-reload volumes
docker compose up -d
# Mounts shared/ and app/ for live reload
# Sets LOG_LEVEL=DEBUG
# Exposes debugpy on ports 5678 (flatex) and 5679 (crypto)

# 3. Tail logs
docker compose logs -f
```

### Running Tests

```bash
# Install dependencies
pip install -r services/python-backend/requirements.txt
pip install -r services/crypto-trader/requirements.txt

# Run all 113 tests
pytest tests/

# Flatex tests only
pytest tests/flatex/

# Crypto tests only
pytest tests/crypto/
```

### Installing OpenClaw Skills

```bash
# Manual installation (recommended)
mkdir -p ~/.openclaw/skills/flatex ~/.openclaw/skills/bitvavo
cp -r skill/flatex/* ~/.openclaw/skills/flatex/
cp -r skill/bitvavo/* ~/.openclaw/skills/bitvavo/

# Or via script
bash scripts/install-skill.sh
```

### Running ML Trainers

```bash
# Flatex ML trainer
docker compose --profile ml up ml-trainer

# Crypto ML trainer
docker compose --profile ml up crypto-ml-trainer
```

### Diagnostic Scripts

```bash
# Flatex diagnostics
docker compose exec python-backend python diagnose.py
docker compose exec python-backend python diagnose.py --step influxdb mqtt --json

# Crypto diagnostics
docker compose exec crypto-trader python diagnose.py
docker compose exec crypto-trader python diagnose.py --step bitvavo portfolio --json

# Via API
curl http://localhost:8100/diagnose
curl http://localhost:8200/diagnose
```

For the complete deployment guide, see [DEPLOYMENT.md](./DEPLOYMENT.md).
