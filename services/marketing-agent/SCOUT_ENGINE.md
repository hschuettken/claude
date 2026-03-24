# Scout Engine — SearXNG Signal Monitor

## Overview

The Scout Engine is the intelligence layer of the Marketing Agent that automatically monitors the web for SAP, enterprise data, and AI-related signals. It uses SearXNG to periodically search for relevant content, scores it for relevance (0.0–1.0), categorizes by content pillar (1–6), deduplicates, and publishes NATS events for downstream processing.

**Status:** ✅ Fully implemented and integrated into `claude` repo

---

## Architecture

```
SearXNG Instance (192.168.0.84:8080)
        ↓
    [Scout Engine]
        ├─ SearchProfile Loader (5 default profiles)
        ├─ SearXNGClient (HTTP search)
        ├─ RelevanceScorer (0.0–1.0 scoring)
        ├─ Deduplication (SHA256 URL hash, 30-day window)
        ├─ APScheduler (async job scheduling)
        ├─ PostgreSQL (marketing.signals table)
        └─ NATS Publisher (signal.detected events)
        ↓
    REST API Endpoints
        ├─ GET /api/v1/marketing/signals (list/filter)
        ├─ GET /api/v1/marketing/signals/{id} (detail)
        ├─ PATCH /api/v1/marketing/signals/{id} (update status)
        ├─ POST /api/v1/marketing/signals/refresh (manual trigger)
        └─ GET /api/v1/marketing/scout/status (scheduler status)
```

---

## Components

### 1. SearXNG Client (`app/scout/searxng_client.py`)

HTTP client for querying SearXNG.

**Key Class:** `SearXNGClient`

```python
client = SearXNGClient(base_url="http://192.168.0.84:8080")

# Search
results = await client.search(
    query="SAP Datasphere new features",
    engines=["google", "bing", "duckduckgo"],
    max_results=10
)
# Returns: list[SearchResult]

# Health check
is_healthy = await client.health_check()

# Cleanup
await client.close()
```

**Features:**
- Async HTTP via `httpx`
- Multi-engine search (Google, Bing, DuckDuckGo, etc.)
- Graceful timeout handling (30s per request)
- Structured `SearchResult` objects (title, url, snippet, engine, engine_score)

---

### 2. Relevance Scorer (`app/scout/scorer.py`)

Scores search results for relevance on a 0.0–1.0 scale.

**Function:** `score_signal(title: str, snippet: str, url: str, pillar_id: int) -> float`

**Scoring Factors:**
- **SAP Keywords** (base): Data, Datasphere, Analytics, BTP, BusinessData, Cloud
  - Each match +0.08, capped at 0.25
- **Pillar Keywords** (specific): Depends on pillar (e.g., "AI", "LLM" for pillar 4)
  - Each match +0.10, capped at 0.35
- **Source Authority**:
  - High-authority (sap.com, community.sap.com, blogs.sap.com): +0.25
  - Medium-authority (linkedin.com, gartner.com, github.com): +0.15
- **Recency Boost**: +0.30 (this week), +0.10 (this month), +0.0 (older)

**Example:**
```python
from app.scout.scorer import score_signal

score = score_signal(
    title="SAP Datasphere Release Notes Q2 2025",
    snippet="New features announced for Datasphere...",
    url="https://sap.com/blogs/datasphere-release",
    pillar_id=2  # Release Notes pillar
)
# Returns: ~0.85 (high SAP keywords + authority + recency)
```

---

### 3. Search Profiles (`app/scout/profiles.py`)

5 pre-configured search profiles:

| Profile | Pillar | Interval | Example Queries |
|---------|--------|----------|-----------------|
| `sap_datasphere` | 1 | 4h | "SAP Datasphere new features", "SAP Business Data Cloud" |
| `sap_community` | 5 | 8h | "SAP Analytics Cloud site:community.sap.com" |
| `sap_release` | 2 | 24h | "SAP Datasphere release notes 2025", "SAP BTP roadmap" |
| `ai_enterprise` | 4 | 12h | "enterprise AI data architecture", "LLM integration" |
| `linkedin_signals` | 3 | 12h | "SAP data architect site:linkedin.com" |

**Pillars:**
1. SAP Datasphere / Data Integration
2. Release Notes / Roadmap
3. Thought Leadership / Insights
4. AI / Machine Learning
5. Community / Discussion
6. Governance / Security / Compliance

---

### 4. APScheduler (`app/scout/scheduler.py`)

Manages periodic search jobs using APScheduler.

**Key Class:** `ScoutScheduler`

```python
scheduler = get_scheduler()

# Start (called in FastAPI lifespan)
await scheduler.start()

# Trigger manual refresh of all profiles
result = await scheduler.trigger_refresh()
# Returns: {"job_id": "manual-refresh", "profiles_queued": 5, "run_info": {...}}

# Get status
status = scheduler.get_status()
# Returns: {"running": True, "jobs": [...], "last_runs": {...}}

# Stop (called on shutdown)
await scheduler.stop()
```

**Lifecycle:**
1. On startup, checks SearXNG health
2. Creates one APScheduler job per profile (async, coalesced, max_instances=1)
3. Each job runs `run_profile(profile)` on its configured interval
4. On shutdown, stops scheduler and closes HTTP client

---

### 5. Database Integration (`models.py`)

Signals are stored in `marketing.signals` table:

```sql
CREATE TABLE marketing.signals (
    id INT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    url VARCHAR(2048) NOT NULL,
    url_hash VARCHAR(64) UNIQUE,  -- SHA256 for dedup
    source VARCHAR(128),           -- "google", "bing", etc.
    source_domain VARCHAR(255),    -- extracted from url
    snippet TEXT,                  -- preview text
    relevance_score FLOAT,         -- 0.0-1.0
    pillar_id INT,                 -- 1-6
    search_profile_id VARCHAR(128),-- which profile found it
    status VARCHAR(32),            -- "new", "read", "used", "archived"
    raw_json TEXT,                 -- full result JSON
    created_at TIMESTAMP,
    detected_at TIMESTAMP
);
```

---

### 6. NATS Event Publishing (`app/scout/events.py`)

Publishes `signal.detected` events to NATS JetStream.

**Graceful Fallback:**
- If `NATS_URL` is not set: service starts normally, no events published
- If NATS unavailable: warning logged, service continues
- Only signals with `relevance_score >= 0.7` are published

**Event Payload:**
```json
{
    "event": "signal.detected",
    "signal_id": 42,
    "title": "SAP Datasphere Update",
    "url": "https://sap.com/news/...",
    "pillar_id": 1,
    "relevance_score": 0.85,
    "detected_at": "2026-03-23T00:36:00Z"
}
```

---

## Configuration

Set via environment variables or `.env` file:

```env
# SearXNG instance
SEARXNG_URL=http://192.168.0.84:8080

# NATS (optional)
NATS_URL=nats://nats.default.svc.cluster.local:4222

# Marketing DB
MARKETING_DB_URL=postgresql+asyncpg://user:pass@host/dbname

# Scout Engine
SCOUT_ENABLED=true
```

**Defaults (in `config.py`):**
- `SEARXNG_URL`: `http://192.168.0.84:8080`
- `NATS_URL`: `None` (optional)
- `SCOUT_ENABLED`: `True`

---

## REST API Endpoints

### List Signals (with Filtering)

```http
GET /api/v1/marketing/signals
  ?limit=50
  &offset=0
  &pillar_id=1
  &status=new
  &min_score=0.7
  &since=2026-03-20T00:00:00Z
  &search=datasphere
```

**Response:**
```json
{
  "items": [
    {
      "id": 42,
      "title": "SAP Datasphere Update",
      "url": "https://sap.com/...",
      "source": "google",
      "source_domain": "sap.com",
      "snippet": "...",
      "relevance_score": 0.85,
      "pillar_id": 1,
      "search_profile_id": "sap_datasphere",
      "status": "new",
      "detected_at": "2026-03-23T00:36:00Z",
      "created_at": "2026-03-23T00:36:00Z",
      "kg_node_id": null
    }
  ],
  "total": 120,
  "limit": 50,
  "offset": 0
}
```

### Get Signal Detail

```http
GET /api/v1/marketing/signals/42
```

### Update Signal Status

```http
PATCH /api/v1/marketing/signals/42
Content-Type: application/json

{
  "status": "read"  // or "used", "archived"
}
```

### Trigger Manual Refresh

```http
POST /api/v1/marketing/signals/refresh
```

**Response:** `202 Accepted`
```json
{
  "status": "queued",
  "message": "Scout refresh started in background",
  "job_id": "manual-refresh",
  "profiles_queued": 5,
  "run_info": {...}
}
```

### Scout Status

```http
GET /api/v1/marketing/scout/status
```

**Response:**
```json
{
  "running": true,
  "searxng_initialized": true,
  "jobs": [
    {
      "id": "scout_sap_datasphere",
      "name": "Scout: SAP Datasphere News",
      "next_run": "2026-03-23T04:00:00Z"
    }
  ],
  "last_runs": {
    "sap_datasphere": {
      "profile_name": "SAP Datasphere News",
      "run_at": "2026-03-23T00:36:00Z",
      "results_found": 10,
      "signals_inserted": 7,
      "signals_skipped": 3
    }
  }
}
```

### NATS Status

```http
GET /api/v1/marketing/scout/system/nats-status
```

---

## Running the Service

### Start (Containerized via docker-compose)

The `marketing-agent` service runs as part of the Claude ecosystem in Docker. See `claude/docker-compose.yml`.

### Environment Setup

1. **Database:** Ensure PostgreSQL is running and migrations applied
2. **SearXNG:** Accessible at configured URL (gracefully handles downtime)
3. **NATS (optional):** If `NATS_URL` is set, NATS will be used; otherwise skipped

### Health Checks

- `GET /health` → Returns `{"status": "ok", "service": "marketing-agent"}`
- `GET /api/v1/marketing/scout/status` → Shows scheduler health and job history

---

## Monitoring & Logging

All components log via Python's standard `logging` module at `DEBUG` level:

```
[INFO] Marketing Agent starting up...
[INFO] Initializing Scout Engine...
[INFO] Scout scheduler started successfully
[INFO] Running profile: SAP Datasphere News
[DEBUG] Searching: SAP Datasphere new features 2025
[DEBUG] Searching: SAP Datasphere release notes
...
[INFO] Profile 'SAP Datasphere News' completed: 10 results, 7 new signals, 3 duplicates
[DEBUG] Published signal.detected event: 42
```

**Key Metrics to Monitor:**
- `signals_inserted` per run
- `signals_skipped` (duplicates)
- `relevance_score` distribution (should be 0.0–1.0, rarely > 0.9)
- Job run duration (should complete within 2-3 minutes per profile)
- NATS publish success rate (if enabled)

---

## Deduplication Strategy

**URL Hash:** SHA256 hash of the full URL
- Stored in `Signal.url_hash` with unique index
- Same exact URL detected within 30 days is skipped

**Why 30 days?**
- Signals don't change much in value within a month
- Avoids re-ingesting old content
- Can be tuned via `ScoutScheduler.dedup_window_days`

**Example:**
```python
url = "https://sap.com/news/datasphere-2025"
hash = hashlib.sha256(url.encode()).hexdigest()
# hash = "a3f1d9c4e2b8f6a9c1e3d7f9b5a2d8e6..."
```

---

## Acceptance Criteria ✅

- [x] SearXNG client can execute searches and parse results
- [x] All 5 default search profiles configured and running
- [x] APScheduler running in FastAPI lifespan, jobs fire on schedule
- [x] `marketing.signals` table populating with relevance scores (0.0–1.0)
- [x] Deduplication working (no duplicate URLs within 30 days)
- [x] Pillar IDs correctly assigned (1–6) based on profile
- [x] REST API endpoints operational (list, get, update, refresh, status)
- [x] NATS publish: graceful fallback if unavailable
- [x] Comprehensive logging per profile (results, new signals, duplicates)
- [x] Error handling for SearXNG timeouts, partial failures, NATS issues

---

## Testing

Run the test suite:

```bash
cd /home/hesch/.openclaw/workspace-nb9os/claude/services/marketing-agent

# Run pytest (requires pytest, httpx, nats-py installed)
pytest test_scout_engine.py -v

# Or run quick validation:
python3 test_scout_engine.py
```

**Manual Testing:**

```bash
# Start marketing-agent service (via docker-compose or uvicorn)
uvicorn main:app --host 0.0.0.0 --port 8210 --reload

# List signals
curl http://localhost:8210/api/v1/marketing/signals

# Trigger refresh
curl -X POST http://localhost:8210/api/v1/marketing/signals/refresh

# Get status
curl http://localhost:8210/api/v1/marketing/scout/status
```

---

## Future Enhancements (Out of Scope)

- LinkedIn API integration (currently via Google site-restricted search)
- Competitor monitoring beyond search
- Signal ranking by user feedback / performance
- Machine learning-based relevance scoring (instead of heuristics)
- Multi-language support
- Image/video search results

---

## Known Limitations

1. **SearXNG Availability:** Service gracefully degrades if SearXNG is down; jobs complete but return 0 results
2. **Search Latency:** Each search takes 2–5s depending on SearXNG performance; optimize by reducing engines per profile if needed
3. **No Real-time:** Minimum interval is 4 hours; near-real-time would require streaming/webhook approach
4. **No Query Optimization:** All profiles run independently; no shared query caching across profiles

---

## Deployment Status

**Code:** ✅ Implemented in `/home/hesch/.openclaw/workspace-nb9os/claude/services/marketing-agent/`

**Deployment Path:** Via `claude` repo docker-compose, ops-bridge integration

**Health:** Check `/health` endpoint after deployment

---

## Contact

Questions? Check the task spec: `/home/hesch/.openclaw/workspace-nb9os/atlas/tasks/20260322-128.md`
