# Scout Engine Quick Start

## What is the Scout Engine?

An automated web signal monitor that:
- Searches SearXNG for SAP, data, and AI content
- Scores results 0.0–1.0 for relevance
- Stores signals in PostgreSQL
- Publishes NATS events for downstream processing
- Exposes REST API for querying

---

## Start the Service

### Docker Compose (Recommended)
```bash
cd /home/hesch/.openclaw/workspace-nb9os/claude
docker-compose up marketing-agent -d
```

### Development (Uvicorn)
```bash
cd /home/hesch/.openclaw/workspace-nb9os/claude/services/marketing-agent
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8210
```

---

## Verify It's Running

```bash
# Health check
curl http://localhost:8210/health
# Response: {"status": "ok", "service": "marketing-agent", "version": "0.1.0"}

# Scout status
curl http://localhost:8210/api/v1/marketing/scout/status
# Response: {"running": true, "jobs": [...], "last_runs": {...}}
```

---

## List Signals

```bash
# Get first 50 signals
curl http://localhost:8210/api/v1/marketing/signals

# Filter by pillar (1-6)
curl "http://localhost:8210/api/v1/marketing/signals?pillar_id=1"

# Filter by status
curl "http://localhost:8210/api/v1/marketing/signals?status=new"

# Filter by score (0.0-1.0)
curl "http://localhost:8210/api/v1/marketing/signals?min_score=0.7"

# Search in title/snippet
curl "http://localhost:8210/api/v1/marketing/signals?search=datasphere"
```

---

## Trigger Manual Refresh

```bash
curl -X POST http://localhost:8210/api/v1/marketing/signals/refresh
# Response: 202 Accepted
# Runs all 5 profiles immediately in background
```

---

## Update Signal Status

```bash
# Mark signal 42 as read
curl -X PATCH http://localhost:8210/api/v1/marketing/signals/42 \
  -H "Content-Type: application/json" \
  -d '{"status": "read"}'

# Valid statuses: new, read, used, archived
```

---

## Configuration

Set environment variables:

```bash
export SEARXNG_URL=http://192.168.0.84:8080
export NATS_URL=nats://nats.default.svc.cluster.local:4222  # optional
export MARKETING_DB_URL=postgresql+asyncpg://user:pass@host/db
export SCOUT_ENABLED=true
```

---

## Check Logs

```bash
# Docker
docker logs marketing-agent -f

# Uvicorn
# Logs appear in console

# Look for:
# [INFO] Running profile: SAP Datasphere News
# [INFO] Profile completed: 10 results, 7 new signals, 3 duplicates
```

---

## Search Profiles (5 Default)

| Profile | Interval | Pillar | Example Query |
|---------|----------|--------|---------------|
| sap_datasphere | 4h | 1 | SAP Datasphere new features |
| sap_community | 8h | 5 | SAP Analytics Cloud site:community.sap.com |
| sap_release | 24h | 2 | SAP Datasphere release notes 2025 |
| ai_enterprise | 12h | 4 | enterprise AI data architecture 2025 |
| linkedin_signals | 12h | 3 | SAP data architect site:linkedin.com |

---

## API Endpoints

```
GET  /api/v1/marketing/signals              # List (paginated)
GET  /api/v1/marketing/signals/{id}         # Detail
PATCH /api/v1/marketing/signals/{id}        # Update status
POST /api/v1/marketing/signals/refresh      # Manual trigger
GET  /api/v1/marketing/scout/status         # Scheduler status
```

---

## Signal Object

```json
{
  "id": 42,
  "title": "SAP Datasphere Q2 2025 Release",
  "url": "https://sap.com/news/datasphere-q2-2025",
  "source": "google",
  "source_domain": "sap.com",
  "snippet": "New features in SAP Datasphere...",
  "relevance_score": 0.85,
  "pillar_id": 1,
  "search_profile_id": "sap_datasphere",
  "status": "new",
  "detected_at": "2026-03-23T00:36:00Z",
  "created_at": "2026-03-23T00:36:00Z",
  "kg_node_id": null
}
```

---

## Troubleshooting

### No signals after 24h?
- Check SearXNG: `curl http://192.168.0.84:8080/`
- Check database: `psql -U homelab -d homelab -c "SELECT COUNT(*) FROM marketing.signals"`
- Check logs: `docker logs marketing-agent -f`

### NATS not available?
- This is OK — service gracefully continues without event publishing
- Set `NATS_URL` if you want event publishing enabled

### Service won't start?
- Verify DB connection: `MARKETING_DB_URL` is correct
- Verify migrations applied: `psql -f migrations/004_add_search_profiles_table.sql`
- Check logs for import errors

---

## Testing

```bash
# Run test suite (requires pytest)
cd services/marketing-agent
pytest test_scout_engine.py -v

# Or quick validation
python3 test_scout_engine.py
```

---

## Full Documentation

- **Architecture:** `SCOUT_ENGINE.md`
- **Deployment:** `DEPLOYMENT.md`
- **Task Spec:** `/home/hesch/.openclaw/workspace-nb9os/atlas/tasks/20260322-128.md`

---

## Expected Behavior

**First 24 Hours:**
- All 5 profiles run at least once
- 80–140 signals inserted
- Scores range from 0.0–1.0
- High-relevance signals (>= 0.7) published to NATS

**Ongoing:**
- Profiles run every 4–24 hours (configured per profile)
- New signals added daily
- Duplicates skipped (30-day window)
- Status can be updated (new → read → used → archived)

---

## Questions?

See `SCOUT_ENGINE.md` for detailed documentation.
