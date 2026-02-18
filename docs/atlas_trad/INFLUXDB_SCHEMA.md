# InfluxDB Measurement Reference — atlas_trad

> **Purpose**: Complete reference for all InfluxDB measurements used by the atlas_trad system. Each measurement documents its tags, fields, write sources, and includes example Flux queries.

---

## Table of Contents

1. [Bucket Configuration](#bucket-configuration)
2. [Measurements](#measurements)
   - [price_data](#1-price_data)
   - [signal_scores](#2-signal_scores)
   - [sentiment_scores](#3-sentiment_scores)
   - [portfolio_snapshot](#4-portfolio_snapshot)
   - [transactions](#5-transactions)
   - [fee_data](#6-fee_data)
   - [ml_predictions](#7-ml_predictions)
   - [llm_calls](#8-llm_calls)
3. [Downsampling Notes](#downsampling-notes)
4. [Common Query Patterns](#common-query-patterns)

---

## Bucket Configuration

| Parameter | Value |
|-----------|-------|
| **Bucket name** | `atlas_trad` |
| **Organization** | `homelab` |
| **Retention** | 365 days |
| **InfluxDB version** | v2 |
| **URL** | `http://192.168.0.66:8086` |

### Setup

Run the setup script to create the bucket and verify access:

```bash
export INFLUXDB_TOKEN=your-token-here
python infrastructure/influxdb/setup.py
```

---

## Measurements

### 1. price_data

Daily OHLCV price data fetched from Yahoo Finance for all tracked symbols. Written by the scheduler during morning, midday, and evening analysis runs.

**Write source**: `app/core/price_fetcher.py::fetch_daily_prices()`

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `symbol` | string | Ticker symbol (e.g., `VWCE.DE`, `EQQQ.DE`) |
| `asset_type` | string | Asset classification: `etf` or `stock` |
| `source` | string | Data source identifier (currently always `yahoo`) |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `open` | float | Opening price |
| `high` | float | Highest price of the day |
| `low` | float | Lowest price of the day |
| `close` | float | Closing price |
| `volume` | float | Trading volume (number of shares) |
| `change_pct` | float | Daily price change as a percentage |

#### Example Flux Query

```flux
// Get the latest price for a specific symbol
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "price_data")
  |> filter(fn: (r) => r.symbol == "VWCE.DE")
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
```

```flux
// Get 60-day price history for a symbol
from(bucket: "atlas_trad")
  |> range(start: -60d)
  |> filter(fn: (r) => r._measurement == "price_data")
  |> filter(fn: (r) => r.symbol == "VWCE.DE")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
```

---

### 2. signal_scores

Combined and individual signal scores for each tracked asset. Written by the signal combiner after each analysis run, and by the sentiment classification callback.

**Write sources**:
- `app/core/signal_combiner.py::write_combined_signals()` -- combined signals
- `app/api/sentiment.py::submit_sentiment_result()` -- sentiment signals from OpenClaw

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `symbol` | string | Ticker symbol |
| `signal_type` | string | Signal category: `technical`, `sentiment`, `fundamental`, `ml`, or `combined` |
| `source` | string | (optional) Origin of the signal, e.g., `openclaw` for sentiment results |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `score` | float | Signal score. Individual signals: [-1.0, +1.0]. Combined signals: [0.0, 1.0] |
| `confidence` | float | Confidence level [0.0, 1.0] |
| `recommendation` | string | Recommendation label: `strong_buy`, `buy`, `hold`, `sell`, `strong_sell` |
| `signal_count` | integer | (combined only) Number of individual signals that were combined |
| `sentiment` | string | (sentiment only) Classification: `bullish`, `bearish`, `neutral` |
| `details_json` | string | (optional) JSON-serialized details for the signal |

#### Example Flux Query

```flux
// Get the latest combined signals for all assets
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "signal_scores")
  |> filter(fn: (r) => r.signal_type == "combined")
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
```

```flux
// Get all signal types for a specific asset
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "signal_scores")
  |> filter(fn: (r) => r.symbol == "VWCE.DE")
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
```

---

### 3. sentiment_scores

Sentiment classification results from the OpenClaw Tier 1 LLM. Written when the OpenClaw skill processes pending news text and posts results back to the backend.

**Write source**: `app/core/sentiment.py::submit_result()`

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `symbol` | string | Ticker symbol |
| `llm_tier` | string | LLM tier used for classification (currently `tier_1`) |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `score` | float | Sentiment score [-1.0, +1.0] (negative = bearish, positive = bullish) |
| `confidence` | float | Classification confidence [0.0, 1.0] |
| `headline_count` | integer | Number of news headlines that were analyzed |
| `summary` | string | Sentiment label: `bullish`, `bearish`, `neutral` |

#### Example Flux Query

```flux
// Get sentiment trend for a symbol over the last 30 days
from(bucket: "atlas_trad")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "sentiment_scores")
  |> filter(fn: (r) => r.symbol == "VWCE.DE")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
```

---

### 4. portfolio_snapshot

Periodic portfolio snapshots capturing total value, cash balance, and position counts. Written by the daily snapshot scheduler job and by the portfolio manager's snapshot method.

**Write sources**:
- `app/scheduler.py::JobScheduler._run_daily_snapshot()` -- daily midnight snapshots
- `app/core/portfolio.py::PortfolioManager.snapshot()` -- on-demand snapshots

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `currency` | string | Portfolio denomination currency (e.g., `EUR`) |
| `snapshot_type` | string | (optional) Type identifier for the snapshot |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `total_value` | float | Total portfolio value (cash + positions) in portfolio currency |
| `cash_balance` | float | Cash balance available |
| `cash` | float | (alternative key) Cash balance |
| `total_pnl` | float | Total unrealized profit/loss across all positions |
| `total_pnl_pct` | float | Total P&L as a percentage |
| `position_count` | integer | Number of open positions |
| `invested_value` | float | (optional) Total invested value excluding cash |
| `positions_json` | string | (optional) JSON-serialized position details |

#### Example Flux Query

```flux
// Get daily portfolio value trend over 90 days
from(bucket: "atlas_trad")
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "portfolio_snapshot")
  |> filter(fn: (r) => r._field == "total_value")
  |> aggregateWindow(every: 1d, fn: last, createEmpty: false)
```

```flux
// Get the latest portfolio snapshot
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "portfolio_snapshot")
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
```

---

### 5. transactions

Individual buy/sell transaction records. Written when a transaction is recorded through the portfolio API.

**Write source**: `app/core/portfolio.py::PortfolioManager.record_transaction()`

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `symbol` | string | Ticker symbol traded |
| `action` | string | Transaction type: `buy` or `sell` |
| `trigger` | string | What initiated the trade: `manual`, `signal`, `sparplan`, `rebalance` |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `quantity` | float | Number of shares/units traded |
| `price` | float | Price per share/unit at execution |
| `fee` | float | Transaction fee paid (EUR) |
| `total_cost` | float | (optional) Total cost including fees |
| `reason` | string | Human-readable reason for the trade |

#### Example Flux Query

```flux
// Get all transactions for a symbol
from(bucket: "atlas_trad")
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "transactions")
  |> filter(fn: (r) => r.symbol == "VWCE.DE")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"], desc: true)
```

```flux
// Calculate total fees paid in the last 30 days
from(bucket: "atlas_trad")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "transactions")
  |> filter(fn: (r) => r._field == "fee")
  |> sum()
```

---

### 6. fee_data

Flatex broker fee schedule data, scraped from web sources. Written by the daily fee scraping scheduler job.

**Write source**: `app/core/fee_scraper.py::scrape_fees()`

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `broker` | string | Broker identifier (currently always `flatex`) |
| `fee_type` | string | (optional) Fee category for granular tracking |
| `product` | string | (optional) Product/instrument the fee applies to |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `trade_fee` | float | Standard order fee (EUR) |
| `etf_sparplan_fee` | float | ETF savings plan (Sparplan) fee (EUR) |
| `premium_etf_fee` | float | Premium ETF flat fee (EUR) |
| `premium_etf_min` | float | Minimum order value for premium ETF pricing (EUR) |
| `amount` | float | (optional) Generic fee amount |
| `percentage` | float | (optional) Fee as a percentage |
| `min_amount` | float | (optional) Minimum fee amount |
| `notes` | string | (optional) Additional notes about the fee |

#### Example Flux Query

```flux
// Track fee changes over time
from(bucket: "atlas_trad")
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "fee_data")
  |> filter(fn: (r) => r.broker == "flatex")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
```

---

### 7. ml_predictions

ML model prediction results for each tracked symbol. Written after inference is run with a loaded LightGBM model.

**Write source**: `app/core/ml_inference.py::MLInference.write_predictions()`

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `symbol` | string | Ticker symbol |
| `signal` | string | Prediction direction: `buy`, `sell`, `neutral` |
| `model_version` | string | Version identifier of the model used |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `confidence` | float | Prediction confidence [0.0, 1.0] (probability of positive class) |
| `model_auc` | float | AUC of the model that produced this prediction |
| `predicted_direction` | string | (optional) Predicted direction as a string |
| `feature_importance_json` | string | (optional) JSON-serialized top feature importances |

#### Example Flux Query

```flux
// Get the latest ML predictions for all symbols
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "ml_predictions")
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
```

```flux
// Track prediction confidence over time for a symbol
from(bucket: "atlas_trad")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "ml_predictions")
  |> filter(fn: (r) => r.symbol == "VWCE.DE")
  |> filter(fn: (r) => r._field == "confidence")
  |> sort(columns: ["_time"])
```

---

### 8. llm_calls

Metrics for LLM API calls made through OpenClaw. Tracks latency, token usage, and success/failure rates per tier and task.

**Write source**: OpenClaw (external) or future instrumentation in the skill

#### Tags

| Name | Type | Description |
|------|------|-------------|
| `tier` | string | LLM tier: `tier_1`, `tier_2`, `tier_3` |
| `provider` | string | LLM provider: `ollama`, `gemini`, `claude` |
| `task` | string | Task type: `sentiment_classify`, `morning_summary`, `weekly_report`, `strategy_advice` |

#### Fields

| Name | Type | Description |
|------|------|-------------|
| `latency_ms` | float | Request latency in milliseconds |
| `input_tokens` | integer | Number of input tokens consumed |
| `output_tokens` | integer | Number of output tokens generated |
| `model` | string | Specific model name/ID used (e.g., `qwen2:0.5b`) |
| `success` | boolean | Whether the call succeeded |
| `error` | string | Error message if the call failed (empty on success) |

#### Example Flux Query

```flux
// Average latency per tier over the last 7 days
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "llm_calls")
  |> filter(fn: (r) => r._field == "latency_ms")
  |> group(columns: ["tier"])
  |> mean()
```

```flux
// Count LLM calls by tier and task
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "llm_calls")
  |> filter(fn: (r) => r._field == "success")
  |> group(columns: ["tier", "task"])
  |> count()
```

---

## Downsampling Notes

InfluxDB retention is set to **365 days**. For longer historical analysis, consider setting up downsampling tasks:

### Recommended Downsampling Tasks

| Source Measurement | Target Measurement | Aggregation | Window |
|-------------------|--------------------|-------------|--------|
| `price_data` | `price_data_weekly` | `last()` per field | 1 week |
| `portfolio_snapshot` | `portfolio_snapshot_weekly` | `last()` per field | 1 week |
| `signal_scores` | `signal_scores_daily` | `mean()` for score/confidence | 1 day |
| `llm_calls` | `llm_calls_daily` | `sum()` for tokens, `mean()` for latency | 1 day |

### Example Downsampling Task (Flux)

```flux
option task = {name: "downsample_prices_weekly", every: 1d, offset: 1h}

from(bucket: "atlas_trad")
  |> range(start: -task.every)
  |> filter(fn: (r) => r._measurement == "price_data")
  |> aggregateWindow(every: 1w, fn: last, createEmpty: false)
  |> to(bucket: "atlas_trad_downsampled", org: "homelab")
```

---

## Common Query Patterns

### Latest Value for a Measurement

```flux
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "MEASUREMENT_NAME")
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
```

### Time Series with Pivot (Multiple Fields as Columns)

```flux
from(bucket: "atlas_trad")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "MEASUREMENT_NAME")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
```

### Filter by Tag Value

```flux
from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "signal_scores")
  |> filter(fn: (r) => r.signal_type == "combined")
  |> filter(fn: (r) => r.symbol == "VWCE.DE")
```

### Aggregate Over Time Window

```flux
from(bucket: "atlas_trad")
  |> range(start: -90d)
  |> filter(fn: (r) => r._measurement == "portfolio_snapshot")
  |> filter(fn: (r) => r._field == "total_value")
  |> aggregateWindow(every: 1d, fn: last, createEmpty: false)
```

### Count Records by Tag

```flux
from(bucket: "atlas_trad")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "transactions")
  |> group(columns: ["symbol", "action"])
  |> count()
```

### Sum a Field Across Time

```flux
from(bucket: "atlas_trad")
  |> range(start: -30d)
  |> filter(fn: (r) => r._measurement == "transactions")
  |> filter(fn: (r) => r._field == "fee")
  |> sum()
```

### Join Two Measurements (Price + Signal)

```flux
prices = from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "price_data")
  |> filter(fn: (r) => r._field == "close")
  |> last()

signals = from(bucket: "atlas_trad")
  |> range(start: -7d)
  |> filter(fn: (r) => r._measurement == "signal_scores")
  |> filter(fn: (r) => r.signal_type == "combined")
  |> filter(fn: (r) => r._field == "score")
  |> last()

join(tables: {prices: prices, signals: signals}, on: ["symbol"])
```
