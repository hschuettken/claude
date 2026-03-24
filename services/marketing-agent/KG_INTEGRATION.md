# Knowledge Graph Integration for Marketing Agent

## Overview

The Marketing Agent now integrates with the NB9OS Knowledge Graph (Neo4j) to:

1. **Enrich draft generation** with context about previously published posts, active projects, and pillar statistics
2. **Auto-sync marketing entities** to the KG for cross-system queries and graph analysis
3. **Provide KG query endpoints** for frontend tools and external consumers

## Architecture

### Components

#### 1. `kg_query.py` — Query Layer
Reads from the Knowledge Graph to provide context:
- `get_published_posts_on_topic()` — Find related published content
- `get_active_projects()` — Find related Orbit tasks/projects
- `get_pillar_statistics()` — Get content coverage stats per pillar
- `get_topic_cluster()` — Full KG graph for a topic (signals + posts)

**Degradation:** If KG unavailable, returns empty lists/dicts. Draft generation continues normally.

#### 2. `kg_ingest.py` — Ingestion Layer
Writes marketing entities to the Knowledge Graph:
- `ingest_signal()` — Create Signal nodes
- `ingest_topic()` — Create Topic nodes + CONTRIBUTES_TO relationships
- `ingest_draft_as_post()` — Create Post nodes + relationships

**Degradation:** If KG unavailable, logs warning but does not fail the operation.

#### 3. API Integration (in `api/drafts.py`)
- `POST /api/v1/drafts` — Create draft with KG context enrichment
- `GET /api/v1/drafts/{draft_id}` — Fetch draft with optional KG context
- `GET /api/v1/kg/status` — Check KG connection and node counts
- `GET /api/v1/kg/pillars` — Get stats for all 6 content pillars
- `GET /api/v1/kg/cluster/{topic_id}` — Get topic's full KG cluster
- `POST /api/v1/drafts/{draft_id}/publish` — Publish and update KG

## Environment Configuration

### Neo4j Connection

Set in `.env`:

```bash
NEO4J_URL=bolt://192.168.0.340:7687          # KG location (LXC 340)
NEO4J_USER=neo4j                             # Default user
NEO4J_PASSWORD=<from envctl>                 # Set via envctl
```

### Optional Degradation

If these env vars are not set, the KG layers gracefully degrade:
- Queries return empty results (no crash)
- Ingestion skips silently (no crash)
- Draft generation works normally

## Data Flow

### Signal Creation

```
POST /api/v1/signals
├─ Save to marketing.signals (PostgreSQL)
└─ → kg_ingest.ingest_signal()
    └─ MERGE Signal node in Neo4j
       └─ SET properties (title, url, relevance_score, etc.)
```

### Topic Creation

```
POST /api/v1/topics
├─ Save to marketing.topics (PostgreSQL)
└─ → kg_ingest.ingest_topic()
    └─ MERGE Topic node in Neo4j
       └─ CONTRIBUTES_TO from Signal nodes
```

### Draft Creation (with KG Context)

```
POST /api/v1/drafts
├─ Save to marketing.drafts (PostgreSQL)
├─ → kg_ingest.ingest_draft_as_post()
│   └─ MERGE Post node in Neo4j
│       └─ GENERATED from Topic node
└─ → kg_query enrichment (parallel)
    ├─ get_published_posts_on_topic(keywords)
    ├─ get_active_projects(keywords)
    └─ get_pillar_statistics(pillar_id)
    └─ Include in response as kg_context
```

### Draft Publishing

```
POST /api/v1/drafts/{draft_id}/publish
├─ Create post in Ghost CMS
├─ Update marketing.drafts status → "published"
└─ → kg_ingest.ingest_draft_as_post() with status="published"
    └─ Update Post node: status = "published"
```

## KG Schema (Neo4j)

### Node Labels

```cypher
Signal { id, title, url, pillar_id, relevance_score, detected_at, status, updated_at }
Topic { id, title, summary, pillar_id, score, status, created_at, updated_at }
Post { id, title, format, pillar_id, word_count, status, created_at, updated_at, published_at }
ContentPillar { id, name, weight }
OrbitTask { ... } // (from prior rounds)
```

### Relationships

```
(Signal)-[:BELONGS_TO]->(ContentPillar)
(Signal)-[:CONTRIBUTES_TO]->(Topic)
(Topic)-[:BELONGS_TO]->(ContentPillar)
(Topic)-[:GENERATED]->(Post)
(Post)-[:BELONGS_TO]->(ContentPillar)
(Topic)-[:TRACKED_BY]->(OrbitTask)  // optional, for future
```

## API Examples

### Create Draft with KG Context

```bash
curl -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "SAP Datasphere Data Models",
    "content": "...",
    "tags": ["datasphere", "modeling"],
    "topic_id": 5,
    "platform": "blog"
  }'
```

Response includes `kg_context`:

```json
{
  "id": 42,
  "title": "SAP Datasphere Data Models",
  "status": "draft",
  "kg_context": {
    "published_posts": [
      {
        "title": "Entity-Relationship Modeling in SAP Datasphere",
        "format": "blog",
        "status": "published",
        "published_at": "2026-03-15T10:30:00"
      }
    ],
    "active_projects": [
      {
        "title": "Datasphere Modeling Fundamentals",
        "status": "in_progress",
        "priority": "high"
      }
    ],
    "pillar_stats": {
      "post_count": 12,
      "published_count": 10,
      "last_published": "2026-03-20T14:15:00"
    }
  }
}
```

### Check KG Status

```bash
curl http://localhost:8210/api/v1/kg/status
```

Response:

```json
{
  "query_available": true,
  "ingest_available": true,
  "neo4j_url": "bolt://192.168.0.340:7687",
  "node_counts": {
    "Signal": 45,
    "Topic": 12,
    "Post": 8,
    "ContentPillar": 6
  }
}
```

### Get Content Pillar Stats

```bash
curl http://localhost:8210/api/v1/kg/pillars
```

Response:

```json
{
  "pillar_1": {
    "post_count": 12,
    "published_count": 10,
    "last_published": "2026-03-20T14:15:00"
  },
  "pillar_2": {
    "post_count": 5,
    "published_count": 4,
    "last_published": "2026-03-18T09:45:00"
  },
  ...
}
```

### Get Topic Cluster

```bash
curl http://localhost:8210/api/v1/kg/cluster/topic-42
```

Response:

```json
{
  "topic": {
    "id": "topic-42",
    "title": "SAP Datasphere Modeling",
    "score": 0.85,
    "status": "active"
  },
  "signals": [
    {
      "id": "signal-101",
      "title": "New SAP Datasphere feature...",
      "relevance_score": 0.92
    }
  ],
  "posts": [
    {
      "id": "post-8",
      "title": "SAP Datasphere Data Models",
      "format": "blog",
      "status": "published"
    }
  ]
}
```

## Error Handling & Degradation

### If KG Unavailable at Startup

```
[WARNING] Failed to connect to KG for ingestion: Connection refused
[INFO] Knowledge Graph ingestion layer unavailable (optional)
```

The service **still starts** and works normally, just without KG features.

### If KG Unavailable on First Draft

```python
kg_context = None  # Returned as null
# Draft generation proceeds normally without context
```

### If KG Becomes Unavailable Mid-Session

Future API calls to `/api/v1/kg/*` return:

```json
{
  "error": "Knowledge Graph unavailable"
}
```

Ingestion operations silently skip (log warning).

## Testing

### Unit Tests (in marketing-agent tests/)

```python
# Test KG query degradation
async def test_kg_query_unavailable():
    kg_query = MarketingKGQuery()
    kg_query._available = False
    
    posts = await kg_query.get_published_posts_on_topic(["datasphere"])
    assert posts == []

# Test draft creation with KG context
async def test_create_draft_with_kg_context():
    response = await client.post(
        "/api/v1/drafts",
        json={
            "title": "Test Draft",
            "content": "Test content",
            "tags": ["test"],
        },
    )
    assert response.status_code == 200
    assert response.json()["kg_context"] is not None
```

### Integration Test

```bash
# Verify KG status endpoint
curl http://localhost:8210/api/v1/kg/status | jq .

# Should show:
# {
#   "query_available": true,
#   "ingest_available": true,
#   "node_counts": { "Signal": N, "Topic": M, ... }
# }
```

## Monitoring & Logging

### Key Log Messages

```
[INFO] Connected to KG at bolt://192.168.0.340:7687
[INFO] Ingested Signal 45: "New SAP feature"
[INFO] Draft 42 enriched with KG context: 5 posts, 2 projects
[WARNING] Failed to connect to KG for ingestion: Connection timeout
[ERROR] Error querying published posts: UNIQUE constraint violation
```

### Metrics

Track in your monitoring (Prometheus, etc.):

- `kg_connection_status` — 1 if available, 0 if not
- `kg_node_count` — Total nodes by type
- `draft_kg_context_available` — % of drafts with context
- `kg_query_latency_ms` — Time for KG queries

## Future Enhancements

1. **NER (Named Entity Recognition)** — Extract entities from posts, link to KG graph
2. **Authority Graph** — Post → Topic → Pillar → Audience weight analysis
3. **Engagement Feedback Loop** — Use analytics to adjust edge weights in graph
4. **Draft Suggestions** — Use KG to recommend topics based on active projects
5. **Cross-Domain Links** — Connect posts to related external content
6. **Performance Snapshots** — Store analytics in KG for trend analysis

## Troubleshooting

### "KG unavailable" at startup

**Cause:** Neo4j not running or credentials incorrect

**Solution:**
```bash
# Check Neo4j is running
ssh 192.168.0.340 "systemctl status neo4j"

# Verify credentials
export NEO4J_PASSWORD=$(envctl get NEO4J_PASSWORD)
echo $NEO4J_PASSWORD  # Should not be empty
```

### Signal ingestion fails but draft creation works

**Cause:** KG query available but ingest not (likely different credentials)

**Solution:**
```bash
# Check both env vars set
env | grep NEO4J
# If only query working, check ingest driver init logs
```

### "Post" nodes not appearing in Neo4j

**Cause:** Draft is still in "draft" status. Ingestion happens on creation but update is on publish.

**Solution:**
```bash
# Check draft status
curl http://localhost:8210/api/v1/drafts/42 | jq .status

# Publish draft to trigger KG update
curl -X POST http://localhost:8210/api/v1/drafts/42/publish
```

## References

- **Task 132:** KG → Marketing Agent Integration spec
- **Task 117:** HenningGPT RAG + KG context engine
- **KG Schema:** `/home/hesch/.openclaw/workspace/services/nb9os/knowledge-graph/schema.cypher`
- **Neo4j Docs:** https://neo4j.com/docs/
