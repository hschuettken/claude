# Architecture & Coding Guidelines — atlas_trad (AI Investment Platform)

> **Purpose**: Repo-specific architecture patterns, conventions, and decisions for the **atlas_trad** repository. This document extends the ecosystem-wide [ARCHITECTURE_GUIDELINES.md](../claude/ARCHITECTURE_GUIDELINES.md) with details specific to this repository: an AI-powered investment platform with two autonomous trading agents (flatex stocks/ETFs + Bitvavo crypto) delivered via Telegram through OpenClaw.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Service Architecture](#2-service-architecture)
3. [LLM Tier System](#3-llm-tier-system)
4. [Configuration](#4-configuration)
5. [Logging](#5-logging)
6. [State Persistence](#6-state-persistence)
7. [Inter-Service Communication](#7-inter-service-communication)
8. [Signal System](#8-signal-system)
9. [Docker & Containerization](#9-docker--containerization)
10. [Health Checks & Diagnostics](#10-health-checks--diagnostics)
11. [Code Style](#11-code-style)

---

## 1. Project Structure

```
/
├── CLAUDE.md                          # AI assistant instructions (project-specific)
├── README.md                          # Project overview and quick start
├── docs/
│   ├── claude/                        # Shared ecosystem docs (read-only, synced)
│   ├── atlas_helper_tools/            # WebSearch repo docs (read-only, synced)
│   └── atlas_trad/                    # This repo's docs
│       ├── ARCHITECTURE_GUIDELINES.md # This file
│       ├── TOOLS_AND_STACK.md
│       ├── INFLUXDB_SCHEMA.md
│       ├── API_REFERENCE.md
│       └── DEPLOYMENT.md
├── shared/                            # Shared Python library (mounted into every container)
│   ├── __init__.py
│   ├── config.py                      # Pydantic BaseSettings (shared base)
│   ├── log.py                         # structlog setup + get_logger()
│   ├── influx.py                      # InfluxDB v2 write/query client (InfluxWriter)
│   ├── mqtt.py                        # Paho MQTT wrapper with auto-reconnect (MQTTClient)
│   ├── state.py                       # JSON state persistence (save_state / load_state)
│   ├── models.py                      # Pydantic data models (signals, portfolio, etc.)
│   └── websearch.py                   # WebSearch HTTP client (Tavily-compatible)
├── services/
│   ├── python-backend/                # Flatex backend service (port 8100)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── healthcheck.py             # Docker HEALTHCHECK script
│   │   ├── diagnose.py                # 8-section diagnostic script (CLI + API)
│   │   └── app/
│   │       ├── main.py                # FastAPI app + lifespan (startup/shutdown)
│   │       ├── config.py              # BackendSettings (extends shared Settings)
│   │       ├── scheduler.py           # APScheduler job definitions (JobScheduler)
│   │       ├── api/                   # FastAPI route modules
│   │       │   ├── router.py          # Top-level router aggregation
│   │       │   ├── health.py          # GET /health, GET /diagnose
│   │       │   ├── portfolio.py       # GET/POST portfolio endpoints
│   │       │   ├── signals.py         # GET /signals, GET /signals/{symbol}
│   │       │   ├── prices.py          # GET /prices/{symbol}, /history
│   │       │   ├── fees.py            # GET /fees, /premium-etfs, /optimal
│   │       │   ├── sentiment.py       # GET/POST sentiment endpoints
│   │       │   ├── technical.py       # GET /technical/{symbol}
│   │       │   ├── watchlist.py       # GET/POST/DELETE watchlist endpoints
│   │       │   ├── performance.py     # GET /performance
│   │       │   ├── ml.py              # GET /model, POST /model/retrain
│   │       │   └── commands.py        # POST /command
│   │       └── core/                  # Business logic modules
│   │           ├── price_fetcher.py   # Yahoo Finance + exchange price scraping
│   │           ├── technical.py       # RSI, MACD, Bollinger, SMA, ATR, volume
│   │           ├── signal_combiner.py # Weighted 4-signal combination
│   │           ├── sentiment.py       # News collection + pending/result pattern
│   │           ├── portfolio.py       # PortfolioManager (state.json backed)
│   │           ├── ml_inference.py    # LightGBM model loading + prediction
│   │           ├── fee_scraper.py     # Flatex fee extraction via websearch
│   │           ├── fundamentals.py    # Yahoo Finance fundamental data
│   │           └── market_regime.py   # Rule-based bull/bear/sideways/crisis
│   │
│   ├── crypto-trader/                 # Bitvavo crypto backend service (port 8200)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── healthcheck.py             # Docker HEALTHCHECK script
│   │   ├── diagnose.py                # 7-section diagnostic script (CLI + API)
│   │   ├── config.yaml                # Trading parameters (reloaded each cycle)
│   │   └── app/
│   │       ├── main.py                # FastAPI app + lifespan
│   │       ├── config.py              # CryptoSettings + TradingConfig (YAML loader)
│   │       ├── models.py              # CryptoPosition, CryptoOrder, TradeLogEntry, etc.
│   │       ├── scheduler.py           # CryptoScheduler (5m exec, 30m ML, 2h news)
│   │       ├── api/                   # FastAPI route modules
│   │       │   ├── router.py          # Top-level router aggregation
│   │       │   ├── health.py          # GET /health, GET /diagnose
│   │       │   ├── portfolio.py       # GET /portfolio
│   │       │   ├── signals.py         # GET/POST /signals
│   │       │   ├── predictions.py     # GET /predictions
│   │       │   ├── trades.py          # GET /trades, /deposits, /fees
│   │       │   ├── config_api.py      # GET/POST /config
│   │       │   └── commands.py        # POST /command
│   │       └── core/                  # Trading engine and business logic
│   │           ├── bitvavo_client.py   # Bitvavo REST API (HMAC auth, dry_run, retry)
│   │           ├── execution.py        # ExecutionEngine.run_cycle() — the 5-min loop
│   │           ├── risk_manager.py     # Stop-loss, TP, trailing, position sizing
│   │           ├── portfolio_manager.py # Portfolio state, P&L, exports
│   │           ├── scanner.py          # Full universe scan + signal ranking
│   │           ├── signal_combiner.py  # 3-signal combination (tech/ML/sentiment)
│   │           ├── technical.py        # RSI, MACD, Bollinger, SMA, volume, ATR
│   │           ├── ml_predictor.py     # LightGBM inference + prediction export
│   │           ├── price_fetcher.py    # Bitvavo ticker prices + candles
│   │           ├── market_regime.py    # BTC-based regime classification
│   │           ├── news_collector.py   # Crypto news via WebSearch
│   │           ├── deposit_tracker.py  # EUR deposit detection + ledger
│   │           ├── account_sync.py     # Bitvavo account reconciliation
│   │           └── universe.py         # Dynamic EUR market discovery
│   │
│   ├── ml-trainer/                    # Flatex ML training (profile-gated)
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── config.py                  # TrainerSettings
│   │   ├── features.py                # Feature engineering from InfluxDB
│   │   └── trainer.py                 # LightGBM training + persistence
│   │
│   └── crypto-ml-trainer/             # Crypto ML training (profile-gated)
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── config.py                  # CryptoTrainerSettings
│       ├── features.py                # 18 crypto feature engineering
│       └── trainer.py                 # LightGBM binary classifier
│
├── skill/
│   ├── flatex/                        # OpenClaw skill — flatex investment advisor
│   │   ├── SKILL.md
│   │   └── prompts/
│   │       ├── sentiment_classify.md
│   │       ├── morning_summary.md
│   │       ├── weekly_report.md
│   │       └── strategy_advisor.md
│   └── bitvavo/                       # OpenClaw skill — crypto trading intelligence
│       ├── SKILL.md
│       └── prompts/
│           ├── sentiment_classify.md
│           ├── morning_summary.md
│           ├── weekly_report.md
│           ├── market_analysis.md
│           └── strategy_advisor.md
├── infrastructure/
│   └── influxdb/setup.py             # Bucket creation + verification
├── scripts/
│   ├── deploy.sh                      # Build + start Docker services
│   └── install-skill.sh              # Install both OpenClaw skills
├── tests/
│   ├── conftest.py                    # Root conftest (sys.path setup)
│   ├── flatex/                        # Flatex unit tests
│   │   ├── conftest.py
│   │   ├── test_technical.py
│   │   ├── test_signal_combiner.py
│   │   ├── test_portfolio.py
│   │   ├── test_sentiment.py
│   │   └── test_fee_scraper.py
│   ├── crypto/                        # Crypto unit tests
│   │   ├── conftest.py
│   │   ├── test_crypto_technical.py
│   │   ├── test_crypto_signal_combiner.py
│   │   ├── test_crypto_risk_manager.py
│   │   ├── test_crypto_portfolio.py
│   │   ├── test_crypto_execution.py
│   │   └── test_bitvavo_client.py
│   └── test_ml_trainer.py
├── docker-compose.yml                 # 4 services (2 default + 2 ml profile)
├── docker-compose.override.example.yml # Dev overrides
├── pyproject.toml                     # Ruff, mypy, pytest config
├── .env.example                       # All environment variables
└── .gitignore
```

### Principles

- **Shared library pattern.** The `shared/` directory contains all cross-service code (config, logging, InfluxDB client, MQTT client, data models, state persistence, websearch client). It is mounted into every container at `/app/shared/`.
- **Four-service architecture.** Two always-running data services (`python-backend` for flatex, `crypto-trader` for Bitvavo) plus two profile-gated ML trainers. Each agent pair shares its own Docker volume.
- **OpenClaw skill separation.** The `skill/flatex/` and `skill/bitvavo/` directories define OpenClaw skills that handle all user interaction and LLM routing. The backends are pure data services with no LLM calls.
- **Infrastructure as external.** InfluxDB, Grafana, MQTT, WebSearch, and Ollama are external services managed outside this repo.
- **Dual config pattern.** The crypto-trader uses `.env` for secrets (API keys) and `config.yaml` for trading parameters (reloaded each cycle). The flatex backend uses `.env` only.

---

## 2. Service Architecture

### Hybrid Pattern: FastAPI + APScheduler

Both `python-backend` and `crypto-trader` use the same **hybrid** architecture:

- **FastAPI** serves the REST API (query endpoints for portfolio, signals, prices, etc.)
- **APScheduler** (`BackgroundScheduler`) runs recurring jobs in background threads
- **MQTT** is used for event publishing and heartbeats (not as the primary processing loop)

```
                 ┌──────────────────────────────┐     ┌──────────────────────────────┐
                 │      python-backend (:8100)   │     │     crypto-trader (:8200)     │
                 │  ┌───────────┐ ┌──────────┐   │     │  ┌───────────┐ ┌──────────┐   │
   HTTP          │  │  FastAPI  │ │APScheduler│   │     │  │  FastAPI  │ │APScheduler│   │
   ────────────> │  │   (API)   │ │  (jobs)   │   │     │  │   (API)   │ │  (jobs)   │   │
                 │  └─────┬─────┘ └─────┬─────┘   │     │  └─────┬─────┘ └─────┬─────┘   │
                 │  ┌─────┴─────────────┴──────┐  │     │  ┌─────┴─────────────┴──────┐  │
                 │  │ price_fetcher, technical,  │  │     │  │ execution, risk_manager,  │  │
                 │  │ sentiment, signal_combiner,│  │     │  │ scanner, signal_combiner, │  │
                 │  │ portfolio, ml_inference,   │  │     │  │ portfolio_manager, bitvavo │  │
                 │  │ fee_scraper, fundamentals  │  │     │  │ ml_predictor, technical,  │  │
                 │  └──────────────────────────┘  │     │  │ news_collector, universe   │  │
                 │    │       │       │            │     │  └──────────────────────────┘  │
                 └────┼───────┼───────┼────────────┘     │    │       │       │    │      │
                      │       │       │                   └────┼───────┼───────┼────┼──────┘
                 InfluxDB   MQTT   state.json                  │       │       │    │
                                                          InfluxDB   MQTT  crypto   Bitvavo
                                                                           _state   REST API
                                                                           .json
```

### NO Direct LLM Calls

Both services are **pure data services**. They never call any LLM directly. The OpenClaw skills handle all LLM routing.

**Flatex: Async pending/result pattern** — Backend collects news, stores as pending. OpenClaw skill polls, classifies via Tier 1, POSTs results back.

```
python-backend                    OpenClaw flatex skill
     │  1. Collect news             │
     │  2. Store as pending         │
     │  <── GET /sentiment/pending  │
     │                    3. Classify via Tier 1 LLM
     │  <── POST /sentiment/result  │
     │  4. Update signals           │
```

**Crypto: Direct signal injection** — OpenClaw skill performs web search, analyzes news via Tier 2, and writes signals directly to the backend.

```
crypto-trader                     OpenClaw bitvavo skill
     │                              │
     │                    1. Web search for crypto news
     │                    2. Analyze via Tier 2 LLM
     │  <── POST /signals ──────    │
     │  3. Incorporate into         │
     │     signal combination       │
```

### Scheduled Jobs — Flatex (python-backend)

| Job | Schedule | Description |
|-----|----------|-------------|
| `fee_scrape` | Daily 06:00 CET | Scrape flatex fee schedules + premium ETF lists |
| `morning_analysis` | Daily 07:00 CET | Full pipeline: prices -> technical -> sentiment -> combine -> snapshot |
| `midday_update` | Weekdays 12:00 CET | Prices -> technical -> combine |
| `evening_update` | Weekdays 17:30 CET | Prices -> technical -> combine |
| `daily_snapshot` | Daily 00:00 CET | Persist portfolio snapshot to InfluxDB |
| `weekly_deep` | Sunday 08:00 CET | Full fundamental refresh for all symbols |
| `heartbeat` | Every 60 seconds | Publish MQTT heartbeat with scheduler metadata |

### Scheduled Jobs — Crypto (crypto-trader)

| Job | Schedule | Description |
|-----|----------|-------------|
| `execution_cycle` | Every 5 minutes | Full trading cycle: check stops/TP/trailing, scan, buy/sell |
| `prediction_cycle` | Every 30 minutes | ML predictions for entire universe |
| `news_collection` | Every 2 hours | Crypto news collection via WebSearch |
| `breaking_news_check` | Every 30 minutes | Scout diff detection for breaking news |
| `fee_change_check` | Daily 06:00 CET | Bitvavo fee page diff monitoring |
| `daily_snapshot` | Daily 00:00 UTC | Full account sync + portfolio snapshot |
| `heartbeat` | Every 60 seconds | MQTT heartbeat with rate limit info |

### Execution Engine (Crypto Only)

The crypto-trader has an `ExecutionEngine` that runs every 5 minutes with two modes:

- **Fast scan** (every cycle): Check stop-loss, take-profit, trailing stops, and stale orders for open positions only
- **Full scan** (every 6th cycle = 30 min): Also check deposits, run full universe scanner, evaluate new buys

The execution engine handles:
1. Stop-loss triggers (sell all)
2. Two-stage take-profit (sell 50% at stage 1, remaining at stage 2)
3. Trailing stop activation and trigger
4. Stale order cancellation (orders older than configured timeout)
5. New position entry based on combined signal scores
6. Cash reserve enforcement
7. Drawdown-based trading pause

---

## 3. LLM Tier System

All LLM work goes through **OpenClaw**. The python-backend never calls LLMs. The OpenClaw flatex skill routes each task to the appropriate tier.

### Tier 1 -- Ollama / Qwen2 0.5B (Free, CPU-only)

- **Context window**: 4096 tokens (configurable via `LLM_TIER1_CONTEXT_LENGTH`)
- **Characters per token**: ~3.5 (configurable via `LLM_TIER1_CHARS_PER_TOKEN`)
- **Maximum input content**: ~2500 characters (leaves room for system prompt + output tokens)
- **Prompt constraints**: Ultra-compact. System prompt under 12 words. No few-shot examples. Show expected JSON shape inline. Temperature 0.1 for classification tasks.
- **Use for**: Sentiment classification, fee extraction, simple formatting, yes/no decisions, portfolio status formatting

### Tier 2 -- Gemini (Cheap, generous context)

- **Use for**: Morning summaries, weekly report body, article analysis, market regime narratives, news aggregation, multi-paragraph composition
- **Context**: Generous -- suitable for multi-source synthesis

### Tier 3 -- Claude (Expensive, highest quality)

- **Use sparingly**: Only for decisions that could move money
- **Use for**: Buy/sell/hold decisions with full portfolio context, portfolio rebalancing advice, risk assessment, unusual market event analysis
- **Escalation pattern**: The weekly report body is composed with Tier 2, but the strategy advice section escalates to Tier 3

### Tier Routing in Practice

The skill instructs OpenClaw which tier to use per task. Examples from SKILL.md:

| Task | Tier | Reason |
|------|------|--------|
| `/flatex status` | 1 | Simple data formatting |
| `/flatex sentiment-update` | 1 | Bulk classification with compact prompts |
| `/flatex morning` | 2 | Multi-source summary composition |
| `/flatex explain` | 3 | Strategy reasoning with portfolio context |
| `/flatex weekly` | 2+3 | Report body (Tier 2), strategy section (Tier 3) |

---

## 4. Configuration

### Pydantic BaseSettings with `extra="ignore"`

All configuration uses Pydantic's `BaseSettings` with `extra="ignore"` so that every service can share a single `.env` file without failing on unknown keys.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )
```

### Inheritance chain

```
shared/config.py::Settings                 # Infrastructure, LLM tier config, general
    │
    ├── python-backend/app/config.py::BackendSettings   # Portfolio, signal weights, thresholds, fees, ML
    ├── ml-trainer/config.py::TrainerSettings            # ML hyperparameters, training split
    ├── crypto-trader/app/config.py::CryptoSettings      # Bitvavo API, crypto risk, crypto ML
    └── crypto-ml-trainer/config.py::CryptoTrainerSettings # Crypto ML training config
```

### Dual Config (Crypto Only)

The crypto-trader uses two configuration sources:

1. **`.env`** — Secrets and infrastructure (API keys, InfluxDB, MQTT). Loaded via `CryptoSettings(BaseSettings)`.
2. **`config.yaml`** — Trading parameters (risk limits, indicator periods, signal weights, thresholds). Loaded via `TradingConfig` Pydantic model and reloaded each execution cycle.

This separation allows trading parameter changes without restarts or env var modifications. The `config.yaml` can be updated via the `/crypto config` command.

### Key environment variables

| Variable | Default | Service | Description |
|----------|---------|---------|-------------|
| `MQTT_HOST` | `192.168.0.73` | all | MQTT broker address |
| `MQTT_PORT` | `1883` | all | MQTT broker port |
| `INFLUXDB_URL` | `http://192.168.0.66:8086` | all | InfluxDB connection URL |
| `INFLUXDB_TOKEN` | (required) | all | InfluxDB authentication token |
| `INFLUXDB_ORG` | `homelab` | all | InfluxDB organization |
| `INFLUXDB_BUCKET` | `atlas_trad` | all | InfluxDB bucket name |
| `WEBSEARCH_URL` | `https://scout.local.schuettken.net` | all | WebSearch API base URL |
| `LLM_TIER1_CONTEXT_LENGTH` | `4096` | all | Tier 1 LLM context window in tokens |
| `LLM_TIER1_CHARS_PER_TOKEN` | `3.5` | all | Tier 1 chars-per-token for budgeting |
| `PRICE_FETCH_SYMBOLS` | (empty) | backend | CSV of symbols to track (e.g. `VWCE.DE,EQQQ.DE`) |
| `PORTFOLIO_CURRENCY` | `EUR` | backend | Portfolio denomination currency |
| `SIGNAL_WEIGHT_TECHNICAL` | `0.40` | backend | Technical signal weight |
| `SIGNAL_WEIGHT_SENTIMENT` | `0.35` | backend | Sentiment signal weight |
| `SIGNAL_WEIGHT_FUNDAMENTAL` | `0.25` | backend | Fundamental signal weight |
| `SIGNAL_WEIGHT_ML` | `0.00` | backend | ML signal weight (0 = disabled) |
| `STRONG_BUY_THRESHOLD` | `0.70` | backend | Score threshold for strong buy |
| `BUY_THRESHOLD` | `0.55` | backend | Score threshold for buy |
| `SELL_THRESHOLD` | `0.40` | backend | Score threshold for sell |
| `STRONG_SELL_THRESHOLD` | `0.25` | backend | Score threshold for strong sell |
| `FLATEX_TRADE_FEE` | `5.90` | backend | Default flatex order fee (EUR) |
| `FLATEX_PREMIUM_ETF_MIN` | `1000.0` | backend | Minimum order for premium ETF pricing |
| `FLATEX_PREMIUM_ETF_FEE` | `2.00` | backend | Premium ETF flat fee (EUR) |
| `ML_MODEL_PATH` | `/app/data/models/latest.joblib` | backend/trainer | Path to persisted ML model |
| `ML_MIN_AUC` | `0.55` | backend/trainer | Minimum AUC to activate ML signal |
| `ML_MIN_TRAINING_DAYS` | `60` | backend/trainer | Minimum days of data for training |
| `LOG_LEVEL` | `INFO` | all | Logging level |
| `TIMEZONE` | `Europe/Berlin` | all | Scheduler timezone |

---

## 5. Logging

All logging uses **structlog** via the shared `shared/log.py` module.

### Rules

- **snake_case events**: `logger.info("price_fetch_ok", symbol=symbol, rows=len(df))`
- **Context as kwargs**: Never build log messages with f-strings or string concatenation
- **No f-strings in log calls**: Use `logger.info("event_name", key=value)`, never `logger.info(f"fetched {symbol}")`
- **Exception logging**: Use `logger.exception("event_failed")` to capture traceback automatically

### Configuration

```python
from shared.log import setup_logging, get_logger

setup_logging(level="INFO")
logger = get_logger(__name__)

# Correct
logger.info("price_fetch_ok", symbol="VWCE.DE", rows=60)
logger.exception("price_fetch_failed", symbol="VWCE.DE")

# WRONG -- never do this
logger.info(f"Fetched {symbol} with {rows} rows")
```

### Processors

The structlog pipeline: `merge_contextvars` -> `add_log_level` -> `StackInfoRenderer` -> `set_exc_info` -> `TimeStamper(iso)` -> `ConsoleRenderer`. Output goes to stderr.

---

## 6. State Persistence

### Flatex: state.json

The `shared/state.py` module provides `save_state()` and `load_state()` for persisting mutable application state to `/app/data/state.json`.

**Contents of state.json:**
- `cash`: Current cash balance (float)
- `positions`: Map of symbol -> `{quantity, avg_cost, name}` (dict)
- `watchlist`: List of watched symbols (list[str])
- `transactions_log`: Full transaction history (list[dict])
- `saved_at`: ISO timestamp of last save

### Crypto: crypto_state.json + Supporting Files

The crypto-trader persists multiple files to `/app/data/`:

| File | Purpose |
|------|---------|
| `crypto_state.json` | Portfolio state (cash_eur, positions, trailing stop state) |
| `portfolio.json` | Export for OpenClaw skill (current holdings + P&L) |
| `deposits.json` | Deposit ledger |
| `trade_log.csv` | Full trade history |
| `signals.json` | LLM intelligence signals (written by OpenClaw skill) |
| `predictions.json` | ML prediction results |
| `scan_state.json` | Scanner state (last scan time, cycle counter) |
| `config.yaml` | Trading parameters (copied from default on first run) |

### Shared Patterns

**Atomic writes**: All state is first written to a `.tmp` file, then renamed to prevent corruption on crash.

**Non-fatal failures**: Save and load operations catch all exceptions and log them. A missing or corrupt state file yields empty defaults.

### InfluxDB for Time Series

All time-series data is written to InfluxDB. See [INFLUXDB_SCHEMA.md](./INFLUXDB_SCHEMA.md) for the complete measurement reference.

### Separation of Concerns

| Data Type | Store | Agent |
|-----------|-------|-------|
| Portfolio state (positions, cash) | state.json / crypto_state.json | Both |
| Transaction/trade history | state.json + InfluxDB / trade_log.csv + InfluxDB | Both |
| Price data | InfluxDB | Both |
| Signal scores | InfluxDB + signals.json (crypto) | Both |
| Sentiment scores | InfluxDB | Both |
| Portfolio snapshots | InfluxDB | Both |
| Fee data | InfluxDB | Flatex |
| ML predictions | InfluxDB + predictions.json | Both |
| Deposit ledger | deposits.json + InfluxDB | Crypto |

---

## 7. Inter-Service Communication

### MQTT for Events

All MQTT topics use the `atlas-trad/` prefix. The `MQTTClient` wrapper in `shared/mqtt.py` provides:

- Auto-reconnect with resubscription
- JSON serialization/deserialization
- Heartbeat publishing
- Error reporting

**Flatex MQTT topics:**

| Topic | Direction | Description |
|-------|-----------|-------------|
| `atlas-trad/python-backend/heartbeat` | Backend -> Broker | Heartbeat with scheduler metadata |
| `atlas-trad/errors/python-backend` | Backend -> Broker | Error events |
| `atlas-trad/scheduler/{event}` | Backend -> Broker | Scheduler job lifecycle events |
| `atlas-trad/portfolio/transaction` | Backend -> Broker | Transaction recorded |
| `atlas-trad/sentiment/classified` | Backend -> Broker | Sentiment classification completed |
| `atlas-trad/ml/retrain` | API -> Trainer | ML model retrain request |

**Crypto MQTT topics:**

| Topic | Direction | Description |
|-------|-----------|-------------|
| `atlas-trad/crypto-trader/heartbeat` | Crypto -> Broker | Heartbeat with rate limit info |
| `atlas-trad/errors/crypto-trader` | Crypto -> Broker | Execution cycle errors |
| `atlas-trad/crypto-trader/news/breaking` | Crypto -> Broker | Breaking news alerts |
| `atlas-trad/crypto-trader/fees/change_detected` | Crypto -> Broker | Bitvavo fee changes |

### REST API for Queries

Both OpenClaw skills communicate with their backends exclusively via HTTP REST.

**Flatex skill -> python-backend (:8100):**
- `GET /portfolio`, `GET /signals`, `GET /sentiment/pending`, `POST /sentiment/result`, `POST /portfolio/transaction`

**Bitvavo skill -> crypto-trader (:8200):**
- `GET /portfolio`, `GET /signals`, `POST /signals`, `GET /predictions`, `GET /trades`, `GET /config`, `POST /config`, `POST /command`

See [API_REFERENCE.md](./API_REFERENCE.md) for the complete endpoint reference.

---

## 8. Signal System

### Flatex: Four Signal Types

| Type | Source | Score Range | Default Weight | Description |
|------|--------|-------------|---------------|-------------|
| `technical` | `app/core/technical.py` | [-1.0, +1.0] | 40% | RSI, MACD, Bollinger, SMA, volume ratio, ATR |
| `sentiment` | `app/core/sentiment.py` + OpenClaw Tier 1 | [-1.0, +1.0] | 35% | News sentiment classified by LLM |
| `fundamental` | `app/core/fundamentals.py` | [-1.0, +1.0] | 25% | PE ratio, analyst targets, dividend yield |
| `ml` | `app/core/ml_inference.py` | [0.0, 1.0] | 0% (off) | LightGBM binary classifier prediction |

### Crypto: Three Signal Types

| Type | Source | Score Range | Default Weight | Description |
|------|--------|-------------|---------------|-------------|
| `technical` | `app/core/technical.py` | [-1.0, +1.0] | 40% | RSI, MACD, Bollinger, SMA, volume ratios |
| `ml_prediction` | `app/core/ml_predictor.py` | [0.0, 1.0] | 35% | LightGBM 24h price prediction |
| `llm_sentiment` | OpenClaw bitvavo skill → POST /signals | [-1.0, +1.0] | 25% | LLM-classified crypto news sentiment |

### Weighted Combination (Both Agents)

Both `signal_combiner.py` modules follow the same algorithm:

1. **Normalize** each signal from [-1, +1] to [0, 1]: `normalized = (raw + 1) / 2`
2. **Redistribute weights** if some signal types are missing (proportional redistribution)
3. **Compute weighted average**: `overall_score = sum(normalized_i * weight_i)`
4. **Map to recommendation** via configurable thresholds

**Flatex thresholds:**

| Score Range | Recommendation |
|-------------|---------------|
| >= 0.70 | `strong_buy` |
| >= 0.55 | `buy` |
| >= 0.40 | `hold` |
| >= 0.25 | `sell` |
| < 0.25 | `strong_sell` |

**Crypto thresholds:**

| Score Range | Recommendation |
|-------------|---------------|
| >= 0.65 | `strong_buy` |
| >= 0.55 | `medium_buy` |
| >= 0.35 | `hold` |
| < 0.35 | `sell` |

### ML Signal Gating

Both agents: ML signal is only included if the model's AUC exceeds `ML_MIN_AUC` (default 0.55). Otherwise the ML weight is redistributed proportionally.

Crypto-specific: if ML model AUC drops below 0.55, the signal combiner automatically redistributes the 35% ML weight to technical (57%) and sentiment (43%).

### Crisis Override

When the market regime is classified as `crisis`, buy recommendations are automatically capped to `hold`. This applies to both agents.

### Market Regime Classification

**Flatex** (`market_regime.py`): Rule-based using index price data:
- **bull**: Indices above 20-day SMA, ATR ratio below 1.3x
- **bear**: Indices below 20-day SMA, ATR ratio above 1.3x
- **sideways**: Mixed signals
- **crisis**: ATR ratio above 2.0x, drawdown >3% in 5 days

**Crypto** (`market_regime.py`): BTC-based classification:
- **bull**: BTC in uptrend, positive sentiment
- **bear**: BTC in downtrend, negative sentiment
- **sideways**: Mixed BTC signals
- **crisis**: BTC drops >10% in 24h, major regulatory events

---

## 9. Docker & Containerization

### Managed Services

Four services are defined in `docker-compose.yml`:

| Service | Container Name | Port | Profile | Restart | Volume | Health Check |
|---------|---------------|------|---------|---------|--------|-------------|
| `python-backend` | `atlas-trad-backend` | 8100:8000 | (default) | `unless-stopped` | `backend_data` | 60s |
| `crypto-trader` | `atlas-trad-crypto` | 8200:8000 | (default) | `unless-stopped` | `crypto_data` | 60s |
| `ml-trainer` | `atlas-trad-ml-trainer` | (none) | `ml` | `no` | `backend_data` | 300s |
| `crypto-ml-trainer` | `atlas-trad-crypto-ml` | (none) | `ml` | `no` | `crypto_data` | (none) |

### Profile-Gated ML Trainers

Both ML trainers only run when explicitly requested:

```bash
# Run flatex ML trainer
docker compose --profile ml up ml-trainer

# Run crypto ML trainer
docker compose --profile ml up crypto-ml-trainer

# Normal operation (both backends only)
docker compose up -d
```

ML trainers depend on their respective backends being healthy before starting.

### Docker Volumes

| Volume | Mount Point | Used By | Contents |
|--------|------------|---------|----------|
| `backend_data` | `/app/data` | python-backend, ml-trainer | `state.json`, `models/latest.joblib` |
| `crypto_data` | `/app/data` | crypto-trader, crypto-ml-trainer | `crypto_state.json`, `config.yaml`, `models/`, `*.json`, `trade_log.csv` |

The volumes are fully isolated — the two agents share no state.

### Base Image

All services use `python:3.12-slim`. The `shared/` library is copied into each container at `/app/shared/` with `PYTHONPATH=/app`.

### External Services NOT Managed

The following are external and **not** defined in this repo's docker-compose:

- InfluxDB v2 (`192.168.0.66:8086`)
- Grafana (`192.168.0.67`)
- MQTT broker (`192.168.0.73:1883`)
- WebSearch API (`scout.local.schuettken.net`)
- Ollama (accessed via OpenClaw)
- OpenClaw (Telegram bot + LLM routing)

### Development Override

Copy `docker-compose.override.example.yml` to `docker-compose.override.yml` for development:

- Volume-mounts `shared/` and `app/` for live reload
- Sets `LOG_LEVEL=DEBUG`
- Exposes debug ports (5678 for flatex, 5679 for crypto)

---

## 10. Health Checks & Diagnostics

### healthcheck.py (Per Container)

Each container has a `healthcheck.py` script that:

1. Makes an HTTP GET to `http://localhost:8000/health`
2. Checks that the response status is 200 and `status` field is `"ok"`
3. Returns exit code 0 (healthy) or 1 (unhealthy)

Docker runs this check every 60 seconds with a 120-second start period.

### diagnose.py — Flatex (8 sections)

| Section | What It Checks |
|---------|---------------|
| `system` | Python version, uptime, RAM usage, disk usage |
| `data_pipeline` | state.json existence and freshness, last price fetch |
| `price_sources` | yfinance reachability (test symbol SAP.DE), websearch health |
| `influxdb` | Connection health, bucket access, test query |
| `mqtt` | Client connection status |
| `websearch` | WebSearch API `/health` endpoint |
| `sentiment` | Pending items count, last classification timestamp |
| `portfolio` | Position count, cash balance, last transaction |

### diagnose.py — Crypto (7 sections)

| Section | What It Checks |
|---------|---------------|
| `system` | Python version, uptime, RAM usage, disk space |
| `bitvavo` | API connectivity, remaining rate limit weight, account balance |
| `influxdb` | Connection health, crypto-specific measurement test |
| `mqtt` | Client connection status |
| `websearch` | WebSearch API health |
| `portfolio` | Positions, cash EUR, trailing stop state, drawdown status |
| `scanner` | Last scan time, cycle count, universe size |

**CLI usage (both services):**

```bash
docker compose exec python-backend python diagnose.py
docker compose exec crypto-trader python diagnose.py
docker compose exec crypto-trader python diagnose.py --step bitvavo influxdb
docker compose exec python-backend python diagnose.py --json
```

**API usage:** Both services expose `GET /diagnose` for programmatic diagnostics.

---

## 11. Code Style

### Language & Version

- **Python 3.12+** -- use modern syntax (union types with `|`, etc.)
- **`from __future__ import annotations`** at the top of every module for PEP 604 style in older contexts
- **Type hints on all function signatures** -- parameters and return types

### Linting & Formatting

Configured in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]

[tool.ruff.lint.isort]
known-first-party = ["shared", "app"]
```

### Import Ordering

1. Standard library (`import sys`, `from datetime import datetime`)
2. Third-party packages (`import pandas`, `from fastapi import APIRouter`)
3. Local -- shared library (`from shared.log import get_logger`)
4. Local -- application (`from app.config import get_settings`)

### Async by Default

Use `async def` for all FastAPI route handlers. Core business logic modules use synchronous functions (they run in APScheduler background threads).

### Naming Conventions

- **Modules**: `snake_case.py` (e.g., `price_fetcher.py`, `signal_combiner.py`)
- **Classes**: `PascalCase` (e.g., `PortfolioManager`, `MLInference`)
- **Functions**: `snake_case` (e.g., `fetch_daily_prices`, `combine_signals`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `PREMIUM_ETF_ISINS`, `_TOPIC_PREFIX`)
- **Private**: Leading underscore for internal helpers (e.g., `_parse_german_number`)

### Testing

- Framework: `pytest` with `asyncio_mode = "auto"`
- Test structure: `tests/flatex/` (6 test files), `tests/crypto/` (7 test files), `tests/test_ml_trainer.py`
- Total: 113 tests
- Run: `pytest tests/`

All tests use mocked external services (no real API calls, no InfluxDB, no MQTT). The crypto tests mock the Bitvavo REST API via `mock_bitvavo` fixture.
