# REST API Reference — atlas_trad

> **Purpose**: Complete reference for all REST API endpoints exposed by the python-backend service. The API is served by FastAPI on port 8100 (host) / 8000 (container).

---

## Table of Contents

1. [General Information](#general-information)
2. [Health & Diagnostics](#health--diagnostics)
   - [GET /health](#get-health)
   - [GET /diagnose](#get-diagnose)
3. [Portfolio](#portfolio)
   - [GET /portfolio](#get-portfolio)
   - [POST /portfolio/transaction](#post-portfoliotransaction)
   - [POST /portfolio/deposit](#post-portfoliodeposit)
   - [POST /portfolio/withdraw](#post-portfoliowithdraw)
4. [Signals](#signals)
   - [GET /signals](#get-signals)
   - [GET /signals/{symbol}](#get-signalssymbol)
5. [Prices](#prices)
   - [GET /prices/{symbol}](#get-pricessymbol)
   - [GET /prices/{symbol}/history](#get-pricessymbolhistory)
6. [Fees](#fees)
   - [GET /fees](#get-fees)
   - [GET /fees/premium-etfs](#get-feespremium-etfs)
   - [GET /fees/optimal/{symbol}](#get-feesoptimalsymbol)
7. [Sentiment](#sentiment)
   - [GET /sentiment](#get-sentiment)
   - [GET /sentiment/pending](#get-sentimentpending)
   - [POST /sentiment/result](#post-sentimentresult)
   - [GET /sentiment/{symbol}](#get-sentimentsymbol)
8. [Technical](#technical)
   - [GET /technical/{symbol}](#get-technicalsymbol)
9. [Watchlist](#watchlist)
   - [GET /watchlist](#get-watchlist)
   - [POST /watchlist](#post-watchlist)
   - [DELETE /watchlist/{symbol}](#delete-watchlistsymbol)
10. [Performance](#performance)
    - [GET /performance](#get-performance)
11. [ML Model](#ml-model)
    - [GET /model](#get-model)
    - [POST /model/retrain](#post-modelretrain)
12. [Commands](#commands)
    - [POST /command](#post-command)

---

## General Information

| Property | Value |
|----------|-------|
| Base URL | `http://localhost:8100` (host) / `http://localhost:8000` (container) |
| Content Type | `application/json` |
| Authentication | None (internal network only) |
| Framework | FastAPI 0.x |

All responses follow a consistent pattern with a `status` field:
- `"ok"` -- request succeeded
- `"error"` -- request failed, see `error` field for details

---

## Health & Diagnostics

### GET /health

Basic health check with dependency status. Used by the Docker HEALTHCHECK script.

**Response:**

```json
{
  "status": "healthy",
  "influxdb": true,
  "mqtt": true,
  "uptime_seconds": 3621.45
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Always `"healthy"` if the endpoint responds |
| `influxdb` | boolean | Whether InfluxDB health check passes |
| `mqtt` | boolean | Whether the MQTT client is connected |
| `uptime_seconds` | float | Seconds since application startup |

**Notes:** This endpoint is called every 60 seconds by the Docker health check. It should respond within 5 seconds.

---

### GET /diagnose

Detailed diagnostics for debugging. Returns comprehensive system, infrastructure, and data pipeline information.

**Response:**

```json
{
  "system": {
    "python_version": "3.12.3 (main, Apr  9 2024, 08:09:14)",
    "platform": "Linux-4.4.0-x86_64-with-glib2.36",
    "uptime_seconds": 3621.45
  },
  "influxdb": {
    "connected": true,
    "url": "http://192.168.0.66:8086",
    "bucket": "atlas_trad"
  },
  "mqtt": {
    "connected": true,
    "host": "192.168.0.73",
    "port": 1883
  },
  "websearch": {
    "url": "https://scout.local.schuettken.net",
    "healthy": true
  },
  "data_pipeline": {
    "configured_symbols": ["VWCE.DE", "EQQQ.DE"],
    "symbol_count": 2
  },
  "portfolio": {
    "position_count": 2,
    "currency": "EUR"
  }
}
```

**Notes:** Unlike `/health`, this endpoint actively probes all dependencies and may take several seconds to respond.

---

## Portfolio

### GET /portfolio

Return the current portfolio state with all positions, P&L calculations, and watchlist.

**Response:**

```json
{
  "status": "ok",
  "portfolio": {
    "cash": 1500.00,
    "total_value": 12345.67,
    "positions": [
      {
        "symbol": "VWCE.DE",
        "name": "VWCE.DE",
        "quantity": 10.0,
        "avg_cost": 105.50,
        "current_price": 108.37,
        "pnl": 28.70,
        "pnl_pct": 2.72,
        "weight_pct": 87.8
      }
    ],
    "watchlist": ["EQQQ.DE", "SAP.DE"]
  }
}
```

**Notes:** Current prices are fetched from InfluxDB (latest `price_data` close within the last 7 days). If no price data is available for a position, the average cost is used as fallback.

---

### POST /portfolio/transaction

Record a buy or sell transaction. Updates portfolio state, persists to state.json and InfluxDB, and publishes an MQTT event.

**Request body:**

```json
{
  "symbol": "VWCE.DE",
  "action": "buy",
  "quantity": 5.0,
  "price": 108.50,
  "fee": 5.90,
  "reason": "Morning signal: strong buy",
  "trigger": "signal"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbol` | string | yes | Ticker symbol |
| `action` | string | yes | `"buy"` or `"sell"` |
| `quantity` | float | yes | Number of shares/units |
| `price` | float | yes | Price per share/unit |
| `fee` | float | no | Transaction fee (default: `0.0`) |
| `reason` | string | no | Human-readable reason |
| `trigger` | string | no | What initiated the trade: `manual`, `signal`, `sparplan`, `rebalance` (default: `"manual"`) |

**Response:**

```json
{
  "status": "ok",
  "transaction": {
    "symbol": "VWCE.DE",
    "action": "buy",
    "quantity": 5.0,
    "price": 108.50,
    "fee": 5.90,
    "timestamp": "2026-02-17T08:30:00+00:00",
    "reason": "Morning signal: strong buy",
    "trigger": "signal"
  }
}
```

**Side effects:**
- Updates portfolio positions and cash balance in state.json
- Writes a `transactions` measurement to InfluxDB
- Publishes to MQTT topic `atlas-trad/portfolio/transaction`

**Notes:** For buy transactions, cash is debited by `(quantity * price) + fee`. For sell transactions, cash is credited by `(quantity * price) - fee`. The average cost is recalculated using a weighted average on buy. Positions with zero quantity are automatically removed.

---

### POST /portfolio/deposit

Deposit cash into the portfolio.

**Request body:**

```json
{
  "amount": 1000.00
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `amount` | float | yes | Amount to deposit (EUR) |

**Response:**

```json
{
  "status": "ok",
  "cash_balance": 2500.00
}
```

---

### POST /portfolio/withdraw

Withdraw cash from the portfolio.

**Request body:**

```json
{
  "amount": 500.00
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `amount` | float | yes | Amount to withdraw (EUR) |

**Response:**

```json
{
  "status": "ok",
  "cash_balance": 2000.00
}
```

**Notes:** No validation is performed to prevent negative cash balances. The caller is responsible for ensuring sufficient funds.

---

## Signals

### GET /signals

Return the latest combined signals for all tracked assets. Queries the `signal_scores` measurement in InfluxDB filtered to `signal_type == "combined"`.

**Response:**

```json
{
  "status": "ok",
  "signals": [
    {
      "symbol": "VWCE.DE",
      "score": 0.6234,
      "confidence": 0.85,
      "recommendation": "buy",
      "timestamp": "2026-02-17T07:00:00+00:00"
    },
    {
      "symbol": "EQQQ.DE",
      "score": 0.4512,
      "confidence": 0.72,
      "recommendation": "hold",
      "timestamp": "2026-02-17T07:00:00+00:00"
    }
  ]
}
```

**Notes:** The score is a normalized [0.0, 1.0] value. The recommendation is derived from configurable thresholds (see ARCHITECTURE_GUIDELINES.md, Signal System).

---

### GET /signals/{symbol}

Return the signal breakdown for a single asset, including all individual signal types (technical, sentiment, fundamental, ML) and the combined signal.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol (e.g., `VWCE.DE`) |

**Response:**

```json
{
  "status": "ok",
  "symbol": "VWCE.DE",
  "signals": [
    {
      "signal_type": "technical",
      "score": 0.35,
      "confidence": 0.90,
      "recommendation": "hold",
      "timestamp": "2026-02-17T07:00:00+00:00"
    },
    {
      "signal_type": "sentiment",
      "score": 0.65,
      "confidence": 0.75,
      "recommendation": "buy",
      "timestamp": "2026-02-17T07:00:00+00:00"
    },
    {
      "signal_type": "combined",
      "score": 0.6234,
      "confidence": 0.85,
      "recommendation": "buy",
      "timestamp": "2026-02-17T07:00:00+00:00"
    }
  ]
}
```

---

## Prices

### GET /prices/{symbol}

Return the latest OHLCV price data for a symbol from InfluxDB.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol (e.g., `VWCE.DE`) |

**Response:**

```json
{
  "status": "ok",
  "symbol": "VWCE.DE",
  "price": {
    "open": 107.20,
    "high": 109.10,
    "low": 106.85,
    "close": 108.37,
    "volume": 234567.0,
    "change_pct": 1.09,
    "timestamp": "2026-02-17T00:00:00+00:00"
  }
}
```

**Notes:** Returns `"price": null` if no price data is found for the symbol within the last 7 days.

---

### GET /prices/{symbol}/history

Return the last 60 days of OHLCV data for a symbol, sorted chronologically.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol |

**Response:**

```json
{
  "status": "ok",
  "symbol": "VWCE.DE",
  "count": 42,
  "history": [
    {
      "open": 103.50,
      "high": 104.20,
      "low": 103.10,
      "close": 103.80,
      "volume": 198000.0,
      "change_pct": 0.48,
      "timestamp": "2025-12-20T00:00:00+00:00"
    }
  ]
}
```

**Notes:** The `count` field indicates the actual number of data points returned (may be less than 60 for recently added symbols or due to market holidays).

---

## Fees

### GET /fees

Return the current flatex fee schedule from configuration.

**Response:**

```json
{
  "status": "ok",
  "fees": {
    "trade_fee": 5.90,
    "premium_etf_min_order": 1000.0,
    "premium_etf_fee": 2.00,
    "etf_sparplan_fee": 0.00,
    "currency": "EUR"
  }
}
```

---

### GET /fees/premium-etfs

Return the list of premium ETF ISINs eligible for reduced-fee trading at flatex.

**Response:**

```json
{
  "status": "ok",
  "premium_etfs": [
    "IE00B4L5Y983",
    "IE00B4L5YC18",
    "IE00BKM4GZ66",
    "IE00B1XNHC34",
    "LU0290358497",
    "LU0274208692"
  ],
  "count": 6
}
```

**Notes:** This is a hardcoded list in `app/api/fees.py`. The `fee_scraper` module also scrapes ISINs from the web but the two lists may differ.

---

### GET /fees/optimal/{symbol}

Calculate the fee-optimal execution path for a trade based on the symbol, quantity, and price.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | ISIN or ticker symbol |

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `quantity` | float | yes | Number of shares (must be > 0) |
| `price` | float | yes | Price per share (must be > 0) |

**Example:** `GET /fees/optimal/IE00B4L5Y983?quantity=10&price=120.50`

**Response (premium ETF, qualifying order):**

```json
{
  "status": "ok",
  "symbol": "IE00B4L5Y983",
  "method": "premium_etf",
  "fee": 2.00,
  "order_value": 1205.00,
  "total_cost": 1207.00,
  "explanation": "Premium ETF order: 2.00 EUR flat fee (order >= 1000 EUR)."
}
```

**Response (premium ETF, below minimum):**

```json
{
  "status": "ok",
  "symbol": "IE00B4L5Y983",
  "method": "sparplan",
  "fee": 0.00,
  "order_value": 500.00,
  "total_cost": 500.00,
  "explanation": "Order below premium ETF minimum. Consider using a Sparplan (savings plan) for zero-fee execution."
}
```

**Response (regular trade):**

```json
{
  "status": "ok",
  "symbol": "SAP.DE",
  "method": "regular",
  "fee": 5.90,
  "order_value": 1205.00,
  "total_cost": 1210.90,
  "explanation": "Standard flatex trade fee: 5.90 EUR."
}
```

**Notes:** The `method` field indicates the fee path: `premium_etf` (flat EUR 2.00 for qualifying orders >= EUR 1000), `sparplan` (EUR 0.00 savings plan), or `regular` (standard EUR 5.90 order fee).

---

## Sentiment

### GET /sentiment

Return the latest sentiment scores for all tracked assets from InfluxDB.

**Response:**

```json
{
  "status": "ok",
  "sentiments": [
    {
      "symbol": "VWCE.DE",
      "score": 0.45,
      "confidence": 0.80,
      "summary": "bullish",
      "timestamp": "2026-02-17T07:15:00+00:00"
    }
  ]
}
```

---

### GET /sentiment/pending

Return headlines and news text that are pending LLM sentiment classification. This endpoint is consumed by the OpenClaw flatex skill to process sentiment analysis asynchronously.

**Response:**

```json
{
  "status": "ok",
  "pending": [
    {
      "symbol": "VWCE.DE",
      "raw_text": "VWCE reaches all-time high as global markets rally...\nMSCI World ETF inflows surge in February...",
      "fetched_at": "2026-02-17T07:00:00+00:00"
    }
  ],
  "count": 1
}
```

**Notes:** The `raw_text` field contains concatenated news headlines and snippets, truncated to 2500 characters. Pending items are from the last 24 hours that have not yet been classified (`classified == "false"` tag).

---

### POST /sentiment/result

Accept a sentiment classification result from the OpenClaw skill. Writes the result to InfluxDB and publishes an MQTT notification.

**Request body:**

```json
{
  "symbol": "VWCE.DE",
  "sentiment": "bullish",
  "score": 0.65,
  "confidence": 0.80
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbol` | string | yes | Ticker symbol |
| `sentiment` | string | yes | Classification: `bullish`, `bearish`, `neutral` |
| `score` | float | yes | Sentiment score [-1.0, +1.0] |
| `confidence` | float | yes | Classification confidence [0.0, 1.0] |

**Response:**

```json
{
  "status": "ok",
  "symbol": "VWCE.DE",
  "accepted": true
}
```

**Side effects:**
- Writes a `signal_scores` measurement to InfluxDB with `signal_type: "sentiment"` and `source: "openclaw"`
- Publishes to MQTT topic `atlas-trad/sentiment/classified`

---

### GET /sentiment/{symbol}

Return detailed sentiment data for a single asset, including the latest classification and up to 30 days of history.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol |

**Response:**

```json
{
  "status": "ok",
  "symbol": "VWCE.DE",
  "latest": {
    "score": 0.65,
    "confidence": 0.80,
    "sentiment": "bullish",
    "source": "openclaw",
    "timestamp": "2026-02-17T07:15:00+00:00"
  },
  "history": [
    {
      "score": 0.65,
      "confidence": 0.80,
      "sentiment": "bullish",
      "source": "openclaw",
      "timestamp": "2026-02-17T07:15:00+00:00"
    },
    {
      "score": 0.20,
      "confidence": 0.70,
      "sentiment": "neutral",
      "source": "openclaw",
      "timestamp": "2026-02-16T07:15:00+00:00"
    }
  ],
  "count": 2
}
```

**Notes:** History is sorted by timestamp descending (most recent first), limited to 30 entries.

---

## Technical

### GET /technical/{symbol}

Return all technical indicator values for a symbol, computed from the most recent price data in InfluxDB.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol |

**Response:**

```json
{
  "status": "ok",
  "symbol": "VWCE.DE",
  "indicators": {
    "rsi": 58.3,
    "macd": 0.42,
    "macd_signal": 0.35,
    "macd_histogram": 0.07,
    "bollinger_upper": 112.50,
    "bollinger_middle": 108.00,
    "bollinger_lower": 103.50,
    "sma_20": 107.80,
    "sma_50": 105.30,
    "sma_200": 100.15,
    "volume_ratio": 1.23,
    "atr": 2.15,
    "price_change_1d": 1.09,
    "price_change_5d": 2.34,
    "price_change_20d": 5.67,
    "timestamp": "2026-02-17T07:00:00+00:00"
  }
}
```

**Response (no data available):**

```json
{
  "status": "ok",
  "symbol": "UNKNOWN.DE",
  "indicators": null,
  "message": "No technical indicator data available"
}
```

**Indicator descriptions:**

| Indicator | Description |
|-----------|-------------|
| `rsi` | Relative Strength Index (14-period), 0-100 |
| `macd` | MACD line (12/26 EMA difference) |
| `macd_signal` | MACD signal line (9-period EMA of MACD) |
| `macd_histogram` | MACD histogram (MACD - signal) |
| `bollinger_upper` | Upper Bollinger Band (20-period, 2 std dev) |
| `bollinger_middle` | Middle Bollinger Band (20-period SMA) |
| `bollinger_lower` | Lower Bollinger Band |
| `sma_20` | 20-day Simple Moving Average |
| `sma_50` | 50-day Simple Moving Average |
| `sma_200` | 200-day Simple Moving Average |
| `volume_ratio` | Current volume / 20-day average volume |
| `atr` | Average True Range (14-period, Wilder's smoothing) |
| `price_change_1d` | 1-day price change (%) |
| `price_change_5d` | 5-day price change (%) |
| `price_change_20d` | 20-day price change (%) |

---

## Watchlist

### GET /watchlist

Return the current watchlist of tracked symbols.

**Response:**

```json
{
  "status": "ok",
  "watchlist": ["EQQQ.DE", "SAP.DE", "ASML.AS"],
  "count": 3
}
```

---

### POST /watchlist

Add a symbol to the watchlist. Duplicates are silently ignored.

**Request body:**

```json
{
  "symbol": "SAP.DE"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `symbol` | string | yes | Ticker symbol to add |

**Response:**

```json
{
  "status": "ok",
  "symbol": "SAP.DE",
  "added": true,
  "watchlist": ["EQQQ.DE", "SAP.DE", "ASML.AS"]
}
```

---

### DELETE /watchlist/{symbol}

Remove a symbol from the watchlist.

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | string | Ticker symbol to remove |

**Response:**

```json
{
  "status": "ok",
  "symbol": "SAP.DE",
  "removed": true,
  "watchlist": ["EQQQ.DE", "ASML.AS"]
}
```

**Notes:** Removing a symbol that is not in the watchlist is a no-op (no error).

---

## Performance

### GET /performance

Return portfolio performance metrics including P&L, total fees paid, and trade count over a configurable period.

**Query parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `days` | integer | no | 30 | Period in days for fee/trade statistics (must be >= 1) |

**Example:** `GET /performance?days=90`

**Response:**

```json
{
  "status": "ok",
  "performance": {
    "total_pnl": 234.56,
    "total_value": 12345.67,
    "cash": 1500.00,
    "position_count": 2,
    "total_fees": 23.60,
    "trade_count": 4,
    "period_days": 30,
    "currency": "EUR"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `total_pnl` | float | Total unrealized P&L across all positions (EUR) |
| `total_value` | float | Total portfolio value (cash + positions, EUR) |
| `cash` | float | Current cash balance (EUR) |
| `position_count` | integer | Number of open positions |
| `total_fees` | float | Sum of fees paid in the specified period (EUR) |
| `trade_count` | integer | Number of trades executed in the specified period |
| `period_days` | integer | The lookback period used for fee/trade stats |
| `currency` | string | Portfolio currency |

---

## ML Model

### GET /model

Return the current ML model status: version, AUC, whether it is active, and when it was last trained.

**Response (model loaded and active):**

```json
{
  "status": "ok",
  "model": {
    "model_path": "/app/data/models/latest.joblib",
    "model_exists": true,
    "min_auc_threshold": 0.55,
    "min_training_days": 60,
    "version": "v1.2",
    "auc": 0.63,
    "is_active": true,
    "last_trained": "2026-02-10T08:00:00+00:00",
    "feature_count": 14
  }
}
```

**Response (no model available):**

```json
{
  "status": "ok",
  "model": {
    "model_path": "/app/data/models/latest.joblib",
    "model_exists": false,
    "min_auc_threshold": 0.55,
    "min_training_days": 60,
    "version": null,
    "auc": null,
    "is_active": false,
    "last_trained": null
  }
}
```

**Notes:** The `is_active` field is `true` only when a model exists AND its AUC exceeds the `min_auc_threshold`. An inactive model means the ML signal weight is redistributed to other signal types.

---

### POST /model/retrain

Trigger ML model retraining. Returns an acknowledgment immediately -- the actual retraining runs asynchronously via the ml-trainer service.

**Request body:** None required.

**Response:**

```json
{
  "status": "ok",
  "message": "Model retraining has been triggered.",
  "async": true
}
```

**Side effects:**
- Publishes to MQTT topic `atlas-trad/ml/retrain` with payload `{"action": "retrain", "requested_by": "api"}`

**Notes:** The ml-trainer service must be running (started with `docker compose --profile ml up ml-trainer`) to pick up the retrain request. If the trainer is not running, the MQTT message will be published but not consumed.

---

## Commands

### POST /command

Dispatch a slash command to the appropriate handler. This endpoint is used by the OpenClaw skill to execute quick commands.

**Request body:**

```json
{
  "command": "status",
  "args": ""
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `command` | string | yes | Command name (leading `/` is stripped automatically) |
| `args` | string | no | Command arguments (default: `""`) |

### Available Commands

#### status

Return a concise portfolio status summary.

**Request:** `{"command": "status", "args": ""}`

**Response:**

```json
{
  "status": "ok",
  "command": "status",
  "position_count": 2,
  "cash_balance": 1500.00,
  "watchlist_count": 3,
  "currency": "EUR"
}
```

#### price

Fetch the latest price for a given symbol.

**Request:** `{"command": "price", "args": "VWCE.DE"}`

**Response:**

```json
{
  "status": "ok",
  "command": "price",
  "symbol": "VWCE.DE",
  "close": 108.37,
  "change_pct": 1.09,
  "timestamp": "2026-02-17T00:00:00+00:00"
}
```

**Error (no symbol):**

```json
{
  "status": "ok",
  "command": "price",
  "error": "No symbol provided. Usage: /price AAPL"
}
```

#### signal

Fetch the latest combined signal for a given symbol.

**Request:** `{"command": "signal", "args": "VWCE.DE"}`

**Response:**

```json
{
  "status": "ok",
  "command": "signal",
  "symbol": "VWCE.DE",
  "score": 0.6234,
  "recommendation": "buy",
  "confidence": 0.85,
  "timestamp": "2026-02-17T07:00:00+00:00"
}
```

#### watchlist

Manage the watchlist via subcommands.

**List:** `{"command": "watchlist", "args": ""}`

```json
{
  "status": "ok",
  "command": "watchlist",
  "action": "list",
  "watchlist": ["EQQQ.DE", "SAP.DE"]
}
```

**Add:** `{"command": "watchlist", "args": "add SAP.DE"}`

```json
{
  "status": "ok",
  "command": "watchlist",
  "action": "add",
  "symbol": "SAP.DE"
}
```

**Remove:** `{"command": "watchlist", "args": "remove SAP.DE"}`

```json
{
  "status": "ok",
  "command": "watchlist",
  "action": "remove",
  "symbol": "SAP.DE"
}
```

#### help

Return available commands.

**Request:** `{"command": "help", "args": ""}`

**Response:**

```json
{
  "status": "ok",
  "command": "help",
  "commands": {
    "status": "Portfolio status summary",
    "price <symbol>": "Latest price for symbol",
    "signal <symbol>": "Latest combined signal for symbol",
    "watchlist [add|remove] [symbol]": "Manage watchlist",
    "help": "Show this help message"
  }
}
```

#### Unknown Command

**Request:** `{"command": "unknown", "args": ""}`

**Response:**

```json
{
  "status": "error",
  "error": "Unknown command: unknown",
  "available": ["status", "price", "signal", "watchlist", "help"]
}
```
