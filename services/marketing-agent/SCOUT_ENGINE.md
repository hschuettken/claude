# Scout Engine — SearXNG Signal Monitor

The **Scout Engine** is the intelligence layer of the Marketing Agent that continuously monitors the web for relevant content opportunities and stores them as marketing signals in the `marketing.signals` table.

## Architecture

```
┌─────────────────────────────────────┐
│  APScheduler (lifespan)             │
│  Manages profiles + job scheduling  │
└────────────┬────────────────────────┘
             │
    ┌────────▼────────┐
    │ Scout Profiles  │  search_profiles.yaml
    │ (5 profiles)    │  - Queries per profile
    └────────┬────────┘  - Engines
             │           - Interval
             │
    ┌────────▼────────────────────┐
    │ run_scout_profile()          │
    │ (async job runner)           │
    └────────┬─────────────────────┘
             │
    ┌────────▼────────┐
    │ SearXNG Client  │  http://192.168.0.84:8080
    │ (httpx)         │
    └────────┬────────┘
             │
    ┌────────▼────────────────────┐
    │ Scorer                       │  Relevance: 0.0–1.0
    │ (keywords, recency, domain)  │  Pillar classification
    └────────┬─────────────────────┘
             │
    ┌────────▼────────┐
    │ Database        │  marketing.signals
    │ (deduplication) │  url_hash unique index
    └────────┬────────┘
             │
    ┌────────▼────────┐
    │ NATS Events     │  signal.detected
    │ (optional)      │  (if NATS available)
    └─────────────────┘
```

## Configuration

### Environment Variables

```bash
SEARXNG_URL=http://192.168.0.84:8080    # SearXNG endpoint
SCOUT_ENABLED=true                       # Enable/disable scheduler
MARKETING_DB_URL=postgresql://...        # Database connection
NATS_URL=nats://...                      # Optional NATS for events
```

### Search Profiles (scout/profiles.yaml)

Define search profiles in YAML with:
- **id**: Unique identifier
- **name**: Human-readable name
- **queries**: List of search queries per profile
- **engines**: Which search engines to use (google, bing, duckduckgo)
- **pillar**: Content pillar (1-6) for classification
- **interval_hours**: How often to run this profile

**Default Profiles:**
1. **sap_datasphere** (4h): SAP Datasphere product news
2. **sap_community** (8h): SAP community discussions
3. **sap_release** (24h): Release notes and announcements
4. **ai_enterprise** (12h): Enterprise AI trends
5. **linkedin_signals** (12h): Thought leadership

## Components

### 1. SearXNG Client (`scout/searxng_client.py`)

Async HTTP client for SearXNG API.

```python
from scout import SearXNGClient

client = SearXNGClient(base_url="http://192.168.0.84:8080")

# Execute search
results = await client.search(
    query="SAP Datasphere new features",
    engines=["google", "bing"],
    max_results=10
)

# Health check
is_alive = await client.health_check()
```

**Features:**
- Async/await with httpx
- Configurable timeout
- Result parsing (title, url, snippet, engine, score)
- Health checks

### 2. Relevance Scorer (`scout/scorer.py`)

Scores signals 0.0–1.0 based on:

**Scoring Components:**
- **SAP Keywords** (0.0–0.2): Presence of SAP/data terminology
- **Pillar Keywords** (0.0–0.25): Pillar-specific keywords
- **Domain Authority** (0.0–0.2): High/medium authority sources
- **Recency** (0.0–0.3): Publication date boost

```python
from scout import score_signal

score = score_signal(
    result=search_result,
    pillar_id=1,  # Datasphere pillar
    base_score=0.5
)
# Returns float 0.0–1.0
```

**Authority Domains:**
- **High** (0.2 boost): sap.com, community.sap.com, blogs.sap.com
- **Medium** (0.1 boost): linkedin.com, gartner.com, medium.com, github.com

### 3. Scheduler (`scout/scheduler.py`)

APScheduler-based job orchestrator.

```python
from scout import ScoutScheduler

scheduler = ScoutScheduler(
    db_url="postgresql://...",
    searxng_url="http://192.168.0.84:8080"
)

# Start in FastAPI lifespan
await scheduler.start()

# Manual refresh
results = await scheduler.refresh_all()

# Status
status = await scheduler.get_status()
```

**Features:**
- One job per profile with configurable interval
- Automatic retry on SearXNG timeout
- Database deduplication (url_hash)
- NATS event publishing (optional)
- Graceful degradation if SearXNG unavailable

## Database Schema

### signals table (enhanced)

```sql
CREATE TABLE marketing.signals (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    url VARCHAR(1024),
    snippet TEXT,                      -- Search result snippet
    source_domain VARCHAR(255),         -- e.g., sap.com
    source VARCHAR(100) NOT NULL,       -- scout, manual, research
    relevance_score FLOAT DEFAULT 0.0,  -- 0.0–1.0
    pillar_id INTEGER,                  -- 1–6 content pillar
    status VARCHAR(50) DEFAULT 'new',   -- new, read, used, archived
    url_hash VARCHAR(64) UNIQUE,        -- sha256(url) for dedup
    search_profile_id VARCHAR(100),      -- Profile that found it
    raw_json JSONB,                     -- Full SearXNG result
    detected_at TIMESTAMP DEFAULT now(),
    kg_node_id VARCHAR(100),            -- Knowledge graph link
    created_at TIMESTAMP DEFAULT now()
);

CREATE INDEX idx_signals_status ON marketing.signals(status);
CREATE INDEX idx_signals_pillar ON marketing.signals(pillar_id);
CREATE INDEX idx_signals_url_hash ON marketing.signals(url_hash);
CREATE INDEX idx_signals_detected_at ON marketing.signals(detected_at);
```

## REST API Endpoints

### List Signals

```http
GET /api/v1/marketing/signals?source=scout&status=new&pillar_id=1&min_relevance=0.7&limit=50&offset=0
```

**Query Parameters:**
- `source`: Filter by source (scout, manual, research)
- `status`: Filter by status (new, read, used, archived)
- `pillar_id`: Filter by pillar (1–6)
- `min_relevance`: Min relevance score (0.0–1.0)
- `limit`: Results per page (max 100)
- `offset`: Pagination offset

**Response:**
```json
[
  {
    "id": 42,
    "title": "SAP Datasphere Q2 Roadmap",
    "url": "https://sap.com/blog/...",
    "snippet": "Latest roadmap updates...",
    "source_domain": "sap.com",
    "source": "scout",
    "relevance_score": 0.92,
    "pillar_id": 1,
    "status": "new",
    "search_profile_id": "sap_datasphere",
    "detected_at": "2025-03-24T14:30:00Z",
    "created_at": "2025-03-24T14:30:00Z"
  }
]
```

### Get Single Signal

```http
GET /api/v1/marketing/signals/{id}
```

### Update Signal Status

```http
PATCH /api/v1/marketing/signals/{id}
Content-Type: application/json

{
  "status": "read"  # or "used" or "archived"
}
```

### Manual Refresh

```http
POST /api/v1/marketing/signals/refresh
```

Triggers immediate run of all scout profiles.

**Response:**
```json
{
  "status": "queued",
  "message": "Scout refresh triggered",
  "note": "Check /api/v1/marketing/scout/status for results"
}
```

### Scout Status

```http
GET /api/v1/marketing/scout/status
```

Returns scheduler status, profile info, and signal counts.

**Response:**
```json
{
  "running": true,
  "profiles": [
    {
      "id": "sap_datasphere",
      "name": "SAP Datasphere News",
      "interval_hours": 4,
      "pillar": 1,
      "job_id": "scout_sap_datasphere",
      "next_run_time": "2025-03-24T18:00:00Z",
      "last_run": "2025-03-24T14:00:00Z"
    }
  ],
  "total_signals": 847,
  "signals_today": 23,
  "searxng_url": "http://192.168.0.84:8080"
}
```

## Lifecycle

### Startup (FastAPI lifespan)

1. Create `marketing` schema
2. Create tables (SQLAlchemy)
3. Load search profiles from YAML
4. Initialize SearXNG client
5. Register APScheduler jobs (one per profile)
6. Start scheduler
7. Log readiness

### Runtime (per job interval)

For each search profile:

1. Execute all queries in profile
2. Fetch results from SearXNG (max 15 per query)
3. For each result:
   - Compute `url_hash = sha256(url)`
   - Check if hash exists (deduplication)
   - If new:
     - Score relevance (0.0–1.0)
     - Extract domain
     - Store as Signal with status='new'
4. Commit batch to DB
5. Publish NATS events (if NATS available)
6. Log execution stats (found, inserted, duplicates, errors)

### Shutdown

1. Stop APScheduler
2. Close database connections
3. Close SearXNG client

## Error Handling

### SearXNG Timeout
- Caught and logged as warning
- Job continues with next query
- Does NOT halt the profile

### SearXNG Unavailable
- Health check fails at startup
- Scout logs error and exits gracefully
- Service continues without Scout

### Database Errors
- Transaction rolls back
- Error logged
- Job continues

### NATS Unavailable
- Optional — service continues without event bus
- Logs warning at startup

## Deduplication Strategy

1. **In-Run Dedup**: Track URLs seen in current profile run (set)
2. **Database Dedup**: Query signals table by `url_hash` before insert
3. **URL Hash**: `sha256(url)` for deterministic lookup

This prevents duplicates within a run and across multiple runs.

## Testing

Run unit tests:

```bash
cd marketing-agent
python3 -m pytest scout/test_scout.py -v
```

**Test Coverage:**
- SearchResult parsing
- Text normalization and keyword matching
- Date parsing and recency scoring
- Relevance scoring (pillar-specific)
- Score clamping (0.0–1.0)

## Monitoring

### Logs to Watch

```
✅ SearXNG health check: OK
🔍 Scout: Running profile 'SAP Datasphere News'
  Query 'SAP Datasphere features': 12 results
    📌 New signal: "Q2 Roadmap" (score: 0.92, url: sap.com/...)
    Duplicate (DB): example.com/article
✅ Profile 'sap_datasphere': found=12, new=5, dups=7, errors=0
🚀 Scout scheduler started with 5 profiles
```

### Metrics

- **Signals/day**: Check `GET /scout/status` → `signals_today`
- **Profile latency**: Log timestamps in run_scout_profile
- **SearXNG health**: Health check every startup
- **NATS health**: Log at startup and on publish failure

## Future Enhancements (Out of Scope)

- LinkedIn API integration (vs. search-based)
- Competitor monitoring
- User feedback-based signal ranking
- Scheduled digest emails
- Signal clustering and deduplication by content similarity
- ML-based relevance scoring
