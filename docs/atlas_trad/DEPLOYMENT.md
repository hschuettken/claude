# Deployment Guide — Atlas Trad

Complete step-by-step guide for deploying both the Flatex investment advisor and Bitvavo crypto trading agents, including all infrastructure dependencies and OpenClaw skill setup.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Infrastructure Setup](#2-infrastructure-setup)
3. [Repository Setup](#3-repository-setup)
4. [Environment Configuration](#4-environment-configuration)
5. [Docker Services](#5-docker-services)
6. [Verify Services](#6-verify-services)
7. [OpenClaw Skill Installation](#7-openclaw-skill-installation)
8. [OpenClaw Configuration](#8-openclaw-configuration)
9. [Enable Live Trading (Crypto)](#9-enable-live-trading-crypto)
10. [ML Model Training](#10-ml-model-training)
11. [Development Mode](#11-development-mode)
12. [Monitoring & Diagnostics](#12-monitoring--diagnostics)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. Prerequisites

### Required Software

| Software | Version | Purpose |
|----------|---------|---------|
| Docker | 24.0+ | Container runtime |
| Docker Compose | v2.20+ | Service orchestration |
| Git | 2.30+ | Version control |
| Python | 3.12+ | Local testing (optional) |

### Required External Services

These must be running and accessible before deploying Atlas Trad:

| Service | Default Address | Purpose | Setup Guide |
|---------|----------------|---------|-------------|
| **InfluxDB v2** | `192.168.0.66:8086` | Time-series storage | See [InfluxDB Setup](#influxdb) below |
| **MQTT Broker** | `192.168.0.73:1883` | Event bus (Mosquitto recommended) | Standard Mosquitto install |
| **WebSearch API** | `scout.local.schuettken.net` | News, fees, diff detection | atlas_helper_tools repo |
| **Grafana** | `192.168.0.67` | Dashboards (optional) | Standard Grafana install |
| **OpenClaw** | (Telegram bot) | User interface + LLM routing | OpenClaw documentation |

### Required Accounts

| Account | Purpose | How to Get |
|---------|---------|-----------|
| **Bitvavo** | Crypto trading API access | Sign up at bitvavo.com, generate API key in settings |
| **InfluxDB** | Token for time-series access | Generated during InfluxDB setup |

---

## 2. Infrastructure Setup

### InfluxDB

If InfluxDB is not yet configured for Atlas Trad:

```bash
# Set your InfluxDB token
export INFLUXDB_TOKEN=your-token-here

# Run the setup script (creates bucket + verifies access)
python infrastructure/influxdb/setup.py
```

This creates the `atlas_trad` bucket in the `homelab` organization with 365-day retention.

### MQTT Broker

No special configuration needed. Atlas Trad uses topics with the `atlas-trad/` prefix. Ensure the broker is accessible from your Docker host.

### WebSearch API

The WebSearch API (scout) must be running and accessible. Verify:

```bash
curl -s https://scout.local.schuettken.net/health
```

---

## 3. Repository Setup

```bash
# Clone the repository
git clone <repo-url> atlas_trad
cd atlas_trad
```

### Directory Structure Verification

After cloning, verify the key directories exist:

```bash
ls services/python-backend/Dockerfile
ls services/crypto-trader/Dockerfile
ls shared/config.py
ls skill/flatex/SKILL.md
ls skill/bitvavo/SKILL.md
```

---

## 4. Environment Configuration

### Create the .env file

```bash
cp .env.example .env
```

### Edit .env — Required Values

Open `.env` in your editor and fill in these **required** values:

```bash
# === REQUIRED: InfluxDB ===
INFLUXDB_TOKEN=your-actual-influxdb-token

# === REQUIRED: Bitvavo (for crypto trading) ===
BITVAVO_API_KEY=your-bitvavo-api-key
BITVAVO_API_SECRET=your-bitvavo-api-secret
```

### Edit .env — Review Defaults

The following have sensible defaults but should be reviewed:

```bash
# Infrastructure addresses (change if your setup differs)
MQTT_HOST=192.168.0.73
MQTT_PORT=1883
INFLUXDB_URL=http://192.168.0.66:8086
INFLUXDB_ORG=homelab
INFLUXDB_BUCKET=atlas_trad
WEBSEARCH_URL=https://scout.local.schuettken.net

# Safety: crypto dry run (KEEP true until verified!)
BITVAVO_DRY_RUN=true

# Logging
LOG_LEVEL=INFO
TIMEZONE=Europe/Berlin
```

### Full .env Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INFLUXDB_TOKEN` | Yes | — | InfluxDB authentication token |
| `BITVAVO_API_KEY` | Yes (crypto) | — | Bitvavo API key |
| `BITVAVO_API_SECRET` | Yes (crypto) | — | Bitvavo API secret |
| `MQTT_HOST` | No | `192.168.0.73` | MQTT broker address |
| `MQTT_PORT` | No | `1883` | MQTT broker port |
| `INFLUXDB_URL` | No | `http://192.168.0.66:8086` | InfluxDB URL |
| `INFLUXDB_ORG` | No | `homelab` | InfluxDB organization |
| `INFLUXDB_BUCKET` | No | `atlas_trad` | InfluxDB bucket |
| `WEBSEARCH_URL` | No | `https://scout.local.schuettken.net` | WebSearch API URL |
| `BITVAVO_DRY_RUN` | No | `true` | Dry run mode for crypto |
| `LOG_LEVEL` | No | `INFO` | Logging level |
| `TIMEZONE` | No | `Europe/Berlin` | Scheduler timezone |
| `PORTFOLIO_CURRENCY` | No | `EUR` | Flatex portfolio currency |
| `PRICE_FETCH_SYMBOLS` | No | (empty) | Seed symbols for flatex (auto-discovered) |
| `SIGNAL_WEIGHT_TECHNICAL` | No | `0.40` | Flatex technical signal weight |
| `SIGNAL_WEIGHT_SENTIMENT` | No | `0.35` | Flatex sentiment signal weight |
| `SIGNAL_WEIGHT_FUNDAMENTAL` | No | `0.25` | Flatex fundamental signal weight |
| `SIGNAL_WEIGHT_ML` | No | `0.00` | Flatex ML signal weight (0 = disabled) |
| `CRYPTO_SIGNAL_WEIGHT_TECHNICAL` | No | `0.40` | Crypto technical signal weight |
| `CRYPTO_SIGNAL_WEIGHT_ML` | No | `0.35` | Crypto ML signal weight |
| `CRYPTO_SIGNAL_WEIGHT_SENTIMENT` | No | `0.25` | Crypto sentiment signal weight |
| `CRYPTO_MAX_POSITIONS` | No | `8` | Max crypto positions |
| `CRYPTO_STOP_LOSS_PCT` | No | `0.10` | Crypto stop-loss percentage |

---

## 5. Docker Services

### Build All Services

```bash
docker compose build
```

This builds four images:
- `atlas-trad-backend` (python-backend)
- `atlas-trad-crypto` (crypto-trader)
- `atlas-trad-ml-trainer` (ml-trainer, profile-gated)
- `atlas-trad-crypto-ml` (crypto-ml-trainer, profile-gated)

### Start the Main Services

```bash
# Start both trading agents
docker compose up -d
```

This starts:
- **python-backend** on port 8100 (flatex)
- **crypto-trader** on port 8200 (bitvavo, in dry_run mode)

The ML trainers are NOT started (they use the `ml` profile).

### Start Individual Services

```bash
# Flatex only
docker compose up -d python-backend

# Crypto only
docker compose up -d crypto-trader

# Both (default)
docker compose up -d
```

### Check Status

```bash
docker compose ps
```

Expected output shows both services as `running (healthy)`.

---

## 6. Verify Services

### Flatex Backend (port 8100)

```bash
# Health check
curl -s http://localhost:8100/health | python -m json.tool

# Expected:
# {
#   "status": "ok",
#   "service": "python-backend",
#   "uptime_s": ...,
#   "timestamp": "..."
# }

# Full diagnostics
curl -s http://localhost:8100/diagnose | python -m json.tool

# CLI diagnostics
docker compose exec python-backend python diagnose.py
```

### Crypto Trader (port 8200)

```bash
# Health check
curl -s http://localhost:8200/health | python -m json.tool

# Expected:
# {
#   "status": "ok",
#   "service": "crypto-trader",
#   "dry_run": true,
#   "uptime_s": ...,
#   "timestamp": "..."
# }

# Full diagnostics
curl -s http://localhost:8200/diagnose | python -m json.tool

# CLI diagnostics
docker compose exec crypto-trader python diagnose.py
```

### Verify InfluxDB Connectivity

```bash
# Check via diagnostics
docker compose exec python-backend python diagnose.py --step influxdb
docker compose exec crypto-trader python diagnose.py --step influxdb
```

### Verify MQTT Connectivity

```bash
docker compose exec python-backend python diagnose.py --step mqtt
docker compose exec crypto-trader python diagnose.py --step mqtt
```

### Check Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f python-backend
docker compose logs -f crypto-trader
```

---

## 7. OpenClaw Skill Installation

Install both skills **manually** (without the install script).

### Step 7.1: Create Skill Directories

```bash
mkdir -p ~/.openclaw/skills/flatex
mkdir -p ~/.openclaw/skills/bitvavo
```

### Step 7.2: Copy Flatex Skill Files

```bash
cp skill/flatex/SKILL.md ~/.openclaw/skills/flatex/SKILL.md
cp -r skill/flatex/prompts/ ~/.openclaw/skills/flatex/prompts/
```

Verify the flatex skill:

```bash
ls -la ~/.openclaw/skills/flatex/
# Expected:
# SKILL.md
# prompts/
#   sentiment_classify.md
#   morning_summary.md
#   weekly_report.md
#   strategy_advisor.md
```

### Step 7.3: Copy Bitvavo Skill Files

```bash
cp skill/bitvavo/SKILL.md ~/.openclaw/skills/bitvavo/SKILL.md
cp -r skill/bitvavo/prompts/ ~/.openclaw/skills/bitvavo/prompts/
```

Verify the bitvavo skill:

```bash
ls -la ~/.openclaw/skills/bitvavo/
# Expected:
# SKILL.md
# prompts/
#   sentiment_classify.md
#   morning_summary.md
#   weekly_report.md
#   market_analysis.md
#   strategy_advisor.md
```

---

## 8. OpenClaw Configuration

### Step 8.1: Edit openclaw.json

Add both skills to your OpenClaw configuration file (`~/.openclaw/openclaw.json`).

Add the following to the `skills` section:

```json
{
  "skills": {
    "entries": {
      "flatex": {
        "enabled": true,
        "env": {
          "FLATEX_BACKEND_URL": "http://192.168.0.50:8100"
        }
      },
      "bitvavo": {
        "enabled": true,
        "env": {
          "BITVAVO_BACKEND_URL": "http://192.168.0.50:8200"
        }
      }
    }
  }
}
```

**Important:** Replace `192.168.0.50` with the IP address of the machine running the Docker services. If OpenClaw runs on the same machine, you can use `http://localhost:8100` and `http://localhost:8200`.

### Step 8.2: Restart OpenClaw

Restart OpenClaw to load the new skills. The exact method depends on your OpenClaw setup.

### Step 8.3: Verify Skills

Send these commands via Telegram to verify:

```
/flatex status
/crypto health
```

- `/flatex status` should return a portfolio overview (may be empty initially)
- `/crypto health` should return a system diagnostic with `dry_run: true`

---

## 9. Enable Live Trading (Crypto)

**WARNING: This section enables real money trading. Only proceed when you have verified the system works correctly in dry_run mode.**

### Step 9.1: Verify Dry Run Behavior

Before enabling live trading, verify that the crypto trader is making sensible decisions:

```bash
# Check recent execution cycles
docker compose logs crypto-trader | grep execution

# Check portfolio state
curl -s http://localhost:8200/portfolio | python -m json.tool

# Check what the scanner found
curl -s http://localhost:8200/signals | python -m json.tool
```

### Step 9.2: Bitvavo API Permissions

Verify your Bitvavo API key has the required permissions:
- **View** balance and trading history
- **Trade** (buy/sell orders)
- **Withdraw** is NOT needed and should be DISABLED for security

### Step 9.3: Enable Live Trading

Option A — Via Telegram command:
```
/crypto dryrun off
```

Option B — Via API:
```bash
curl -s -X POST http://localhost:8200/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"dryrun","args":"off"}'
```

Option C — Via .env (persistent across restarts):
```bash
# Edit .env
BITVAVO_DRY_RUN=false

# Restart
docker compose restart crypto-trader
```

### Step 9.4: Monitor First Live Trades

```bash
# Watch execution logs
docker compose logs -f crypto-trader | grep -E "order_placed|execution"

# Check trade log
curl -s http://localhost:8200/trades | python -m json.tool

# Pause trading at any time
curl -s -X POST http://localhost:8200/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"pause"}'
```

---

## 10. ML Model Training

### Flatex ML Trainer

```bash
# Run the flatex ML trainer (requires InfluxDB historical data)
docker compose --profile ml up ml-trainer

# The trainer:
# 1. Queries historical price/signal data from InfluxDB
# 2. Engineers features (technical, sentiment, fundamental, regime)
# 3. Trains a LightGBM binary classifier
# 4. Saves to /app/data/models/latest.joblib if AUC improves
# 5. Exits when done
```

The ML signal is only activated when:
- A model exists at the configured path
- The model's AUC exceeds `ML_MIN_AUC` (default 0.55)
- `SIGNAL_WEIGHT_ML` is set > 0 in .env

### Crypto ML Trainer

```bash
# Run the crypto ML trainer (requires Bitvavo historical candle data)
docker compose --profile ml up crypto-ml-trainer

# The trainer:
# 1. Fetches historical candles from Bitvavo API
# 2. Engineers 18 crypto features (RSI, MACD, Bollinger, volume, etc.)
# 3. Trains a LightGBM binary classifier (price up >= 3% in 24h?)
# 4. Saves to /app/data/models/crypto_latest.joblib if AUC improves
# 5. Exits when done
```

### Scheduling ML Training

ML trainers are designed to run periodically (e.g., weekly). Set up a cron job:

```bash
# Example: retrain crypto model every Sunday at 03:00
0 3 * * 0 cd /path/to/atlas_trad && docker compose --profile ml up crypto-ml-trainer

# Example: retrain flatex model every Sunday at 04:00
0 4 * * 0 cd /path/to/atlas_trad && docker compose --profile ml up ml-trainer
```

Or trigger retraining via Telegram:
```
/flatex retrain
/crypto retrain
```

---

## 11. Development Mode

### Setup

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
docker compose up -d
```

Development mode adds:
- **Volume mounts** for `shared/` and `app/` directories (live reload)
- **LOG_LEVEL=DEBUG** for verbose logging
- **Debug ports**: 5678 (flatex) and 5679 (crypto) for debugpy

### Running Tests Locally

```bash
# Install dependencies
pip install -r services/python-backend/requirements.txt
pip install -r services/crypto-trader/requirements.txt

# Run all 113 tests
pytest tests/

# Run flatex tests only
pytest tests/flatex/

# Run crypto tests only
pytest tests/crypto/

# Run with verbose output
pytest tests/ -v

# Run a specific test file
pytest tests/crypto/test_crypto_execution.py -v
```

### Debugging

Attach a debugger to the exposed debug ports:

```python
# In VS Code launch.json
{
    "name": "Attach to Flatex",
    "type": "python",
    "request": "attach",
    "port": 5678,
    "host": "localhost"
}

{
    "name": "Attach to Crypto",
    "type": "python",
    "request": "attach",
    "port": 5679,
    "host": "localhost"
}
```

---

## 12. Monitoring & Diagnostics

### Health Endpoints

| Service | URL | Description |
|---------|-----|-------------|
| Flatex health | `http://localhost:8100/health` | Basic health |
| Flatex diagnose | `http://localhost:8100/diagnose` | Full diagnostic |
| Crypto health | `http://localhost:8200/health` | Basic health + dry_run status |
| Crypto diagnose | `http://localhost:8200/diagnose` | Full diagnostic with Bitvavo API status |

### CLI Diagnostics

```bash
# Flatex — all sections
docker compose exec python-backend python diagnose.py

# Flatex — specific sections
docker compose exec python-backend python diagnose.py --step influxdb mqtt websearch

# Crypto — all sections
docker compose exec crypto-trader python diagnose.py

# Crypto — specific sections
docker compose exec crypto-trader python diagnose.py --step bitvavo influxdb portfolio

# JSON output (for scripting)
docker compose exec python-backend python diagnose.py --json
docker compose exec crypto-trader python diagnose.py --json
```

### MQTT Monitoring

Subscribe to all Atlas Trad events:

```bash
mosquitto_sub -h 192.168.0.73 -t 'atlas-trad/#' -v
```

Key topics to monitor:

| Topic | What It Shows |
|-------|--------------|
| `atlas-trad/python-backend/heartbeat` | Flatex service alive |
| `atlas-trad/crypto-trader/heartbeat` | Crypto service alive (includes rate limit) |
| `atlas-trad/errors/crypto-trader` | Crypto execution errors |
| `atlas-trad/crypto-trader/news/breaking` | Breaking crypto news alerts |

### Grafana Dashboards

With InfluxDB as data source, create dashboards for:

- **Crypto prices**: `crypto_price_data` measurement, filter by pair
- **Portfolio value**: `portfolio_snapshot` measurement, track total_value over time
- **Signal scores**: `signal_scores` measurement, combined vs individual
- **Trade activity**: `transactions` measurement

### Log Monitoring

```bash
# Follow all service logs
docker compose logs -f

# Filter for specific events
docker compose logs -f crypto-trader | grep "order_placed"
docker compose logs -f crypto-trader | grep "stop_loss"
docker compose logs -f python-backend | grep "morning_analysis"
```

---

## 13. Troubleshooting

### Service Won't Start

```bash
# Check Docker build output
docker compose build --no-cache crypto-trader

# Check container logs for startup errors
docker compose logs crypto-trader

# Verify .env file is present and valid
cat .env | grep BITVAVO
```

### InfluxDB Connection Failed

```bash
# Verify InfluxDB is reachable
curl -s http://192.168.0.66:8086/health

# Check token is valid
docker compose exec python-backend python diagnose.py --step influxdb

# Common fix: incorrect INFLUXDB_TOKEN in .env
```

### MQTT Connection Failed

```bash
# Verify broker is reachable
mosquitto_pub -h 192.168.0.73 -t test -m "hello"

# Check from inside container
docker compose exec crypto-trader python diagnose.py --step mqtt

# Common fix: firewall blocking port 1883
```

### Bitvavo API Errors

```bash
# Check remaining rate limit
curl -s http://localhost:8200/diagnose | python -m json.tool | grep remaining_weight

# Verify API key permissions
docker compose exec crypto-trader python diagnose.py --step bitvavo

# Common issues:
# - API key expired → regenerate in Bitvavo settings
# - Rate limit exhausted → wait (resets automatically)
# - IP restriction → add server IP to Bitvavo API whitelist
```

### Crypto Trader Not Trading

```bash
# Check if paused
curl -s http://localhost:8200/portfolio | python -m json.tool | grep paused

# Check if in dry_run mode
curl -s http://localhost:8200/health | python -m json.tool | grep dry_run

# Check if drawdown paused
curl -s http://localhost:8200/portfolio | python -m json.tool | grep drawdown

# Resume trading
curl -s -X POST http://localhost:8200/command \
  -H 'Content-Type: application/json' \
  -d '{"command":"resume"}'
```

### OpenClaw Skills Not Working

```bash
# Verify skill files are in place
ls -la ~/.openclaw/skills/flatex/SKILL.md
ls -la ~/.openclaw/skills/bitvavo/SKILL.md

# Verify backend URLs are reachable from OpenClaw host
curl -s http://192.168.0.50:8100/health
curl -s http://192.168.0.50:8200/health

# Check openclaw.json configuration
cat ~/.openclaw/openclaw.json | python -m json.tool

# Common fix: wrong IP address in FLATEX_BACKEND_URL / BITVAVO_BACKEND_URL
```

### Tests Failing

```bash
# Ensure all dependencies are installed
pip install -r services/python-backend/requirements.txt
pip install -r services/crypto-trader/requirements.txt

# Run with verbose output
pytest tests/ -v --tb=short

# Run specific failing test
pytest tests/crypto/test_crypto_execution.py::test_name -v
```

---

## Quick Reference

### Common Commands

```bash
# Start everything
docker compose up -d

# Stop everything
docker compose down

# Rebuild after code changes
docker compose build && docker compose up -d

# View logs
docker compose logs -f

# Run diagnostics
docker compose exec python-backend python diagnose.py
docker compose exec crypto-trader python diagnose.py

# Run ML trainers
docker compose --profile ml up ml-trainer
docker compose --profile ml up crypto-ml-trainer

# Run tests
pytest tests/
```

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/flatex status` | Flatex portfolio overview |
| `/flatex morning` | Generate morning report |
| `/flatex weekly` | Generate weekly report |
| `/flatex explain` | Strategy reasoning (Tier 3) |
| `/flatex diagnose` | System health check |
| `/crypto status` | Crypto portfolio overview |
| `/crypto report` | Generate daily report |
| `/crypto trades` | Recent trade log |
| `/crypto signals` | Current intelligence signals |
| `/crypto health` | System health check |
| `/crypto pause` | Pause trading |
| `/crypto resume` | Resume trading |
| `/crypto dryrun on/off` | Toggle dry run mode |
| `/crypto config` | View/update trading parameters |
