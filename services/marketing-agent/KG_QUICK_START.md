# KG Integration Quick Start Guide

## TL;DR

Task 108-Part4 adds Knowledge Graph context enrichment to draft generation.

**Files added:** `kg_query.py`, `kg_ingest.py`  
**Files modified:** `api/drafts.py`, `api/signals.py`, `api/topics.py`, `main.py`, `requirements.txt`  
**New endpoints:** `/api/v1/kg/*`  
**Documentation:** `KG_INTEGRATION.md`, `KG_IMPLEMENTATION_SUMMARY.md`, `VALIDATION_CHECKLIST.md`

## Setup

### 1. Install Dependencies

```bash
cd /home/hesch/.openclaw/workspace-nb9os/claude/services/marketing-agent
pip install -r requirements.txt  # Includes neo4j==5.14.1
```

### 2. Configure Environment

```bash
export NEO4J_URL=bolt://192.168.0.340:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=$(envctl get NEO4J_PASSWORD)
```

If `NEO4J_PASSWORD` not set, KG features degrade gracefully (no crash).

### 3. Start Service

```bash
python3 main.py
# Expected log: "[INFO] Connected to KG at bolt://192.168.0.340:7687"
```

## Usage

### Check KG Status

```bash
curl http://localhost:8210/api/v1/kg/status | jq .
```

Returns:
```json
{
  "query_available": true,
  "ingest_available": true,
  "node_counts": {
    "Signal": 45,
    "Topic": 12,
    "Post": 8,
    "ContentPillar": 6
  }
}
```

### Create Draft (with KG Context)

```bash
curl -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "SAP Datasphere Data Models",
    "content": "...",
    "tags": ["datasphere", "modeling"],
    "platform": "blog"
  }' | jq .kg_context
```

Response includes:
```json
{
  "kg_context": {
    "published_posts": [
      {"title": "...", "format": "blog", "status": "published", "published_at": "..."}
    ],
    "active_projects": [
      {"title": "...", "status": "in_progress", "priority": "high"}
    ],
    "pillar_stats": {
      "post_count": 12,
      "published_count": 10,
      "last_published": "2026-03-20T..."
    }
  }
}
```

### Query Content Pillars

```bash
curl http://localhost:8210/api/v1/kg/pillars | jq '.pillar_1'
```

### Get Topic Graph

```bash
curl http://localhost:8210/api/v1/kg/cluster/{topic_id} | jq .
```

## Architecture

```
Draft Creation Flow:
┌─────────────┐
│ POST /drafts│
└──────┬──────┘
       ├─→ Save to PostgreSQL
       ├─→ kg_ingest.ingest_draft_as_post() [Neo4j write]
       └─→ kg_query.get_*() [Neo4j read] → KG context
           └─→ Return DraftWithKGContext (includes kg_context)
```

## Key Classes

### `MarketingKGQuery` (kg_query.py)

Reads from Neo4j. Singleton: `get_kg_query()`

```python
kg_query = get_kg_query()
posts = await kg_query.get_published_posts_on_topic(["datasphere"])
projects = await kg_query.get_active_projects(["datasphere"])
stats = await kg_query.get_pillar_statistics(pillar_id=1)
cluster = await kg_query.get_topic_cluster("topic-42")
```

### `MarketingKGIngestion` (kg_ingest.py)

Writes to Neo4j. Singleton: `get_kg_ingest()`

```python
kg_ingest = get_kg_ingest()
await kg_ingest.ingest_signal(signal_id=1, title="...", url="...", ...)
await kg_ingest.ingest_topic(topic_id=1, title="...", signal_ids=[1,2], ...)
await kg_ingest.ingest_draft_as_post(draft_id=1, title="...", ...)
```

## Graceful Degradation

If KG unavailable (no NEO4J_PASSWORD):

1. **Startup:** Logs warning, service continues
2. **Draft creation:** Returns draft with `kg_context = null`
3. **KG endpoints:** Return `{"error": "Knowledge Graph unavailable"}`
4. **Ingestion:** Silently skips (logs warning)

**No crashes. Marketing agent works normally without KG.**

## Integration with Draft Writer (Task 128/129)

Draft writer can consume `kg_context` from response:

```python
response = await create_draft(DraftCreate(...), db)
kg_context = response.kg_context

# Inject into LLM prompt
system_prompt = f"""
You are a content writer...

## Previously Written Content
{format_posts(kg_context.published_posts)}

## Related Projects
{format_projects(kg_context.active_projects)}

## Pillar Stats
{format_stats(kg_context.pillar_stats)}

Use this to avoid repetition...
"""
```

## Monitoring

Key logs to watch:

```
[INFO] Connected to KG at bolt://192.168.0.340:7687
[INFO] Draft 42 enriched with KG context: 5 posts, 2 projects
[WARNING] Failed to connect to KG for ingestion: Connection refused
[ERROR] Error querying published posts: UNIQUE constraint violation
```

## Testing Quick Commands

```bash
# 1. Check status
curl http://localhost:8210/api/v1/kg/status

# 2. Create signal
curl -X POST http://localhost:8210/api/v1/signals \
  -H "Content-Type: application/json" \
  -d '{"title":"Test Signal","source":"test","relevance_score":0.9}'

# 3. Create draft
curl -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{"title":"Test","content":"...","platform":"blog"}'

# 4. Check pillars
curl http://localhost:8210/api/v1/kg/pillars

# 5. Verify in Neo4j (requires access)
# MATCH (p:Post) RETURN count(p) as draft_nodes;
```

## Troubleshooting

### "Knowledge Graph unavailable"

```bash
# Check if NEO4J_PASSWORD is set
env | grep NEO4J_PASSWORD

# Set it
export NEO4J_PASSWORD=$(envctl get NEO4J_PASSWORD)

# Restart service
```

### Neo4j connection timeout

```bash
# Verify connection to 192.168.0.340:7687
nc -zv 192.168.0.340 7687

# Check Neo4j running on LXC 340
ssh 192.168.0.340 "systemctl status neo4j"
```

### Drafts created but no KG nodes

```bash
# Check draft status
curl http://localhost:8210/api/v1/drafts/42 | jq .status

# If "draft", nodes are created. If more status changes, check logs for ingestion errors.
# On publish, status → "published" and KG is updated.
```

## Documentation Files

| File | Purpose |
|------|---------|
| `KG_INTEGRATION.md` | Comprehensive architecture & API reference |
| `KG_IMPLEMENTATION_SUMMARY.md` | What was implemented, acceptance criteria |
| `VALIDATION_CHECKLIST.md` | Testing procedures, feature completeness |
| `KG_QUICK_START.md` | This file — quick reference |

## Next Steps

1. **Seed ContentPillar nodes** in Neo4j (6 pillars with weights)
   - Create script: `/home/hesch/.openclaw/workspace-nb9os/claude/services/marketing-agent/seed_pillars.py`
   
2. **Deploy to staging** and test end-to-end

3. **Build draft writer UI** to display `kg_context` results

4. **Add NER layer** (Task 132 Round 21) to extract entities from posts

5. **Authority graph visualization** using `/api/v1/kg/cluster/{topic_id}` response

---

**Ready?** → `curl http://localhost:8210/api/v1/kg/status` 🚀
