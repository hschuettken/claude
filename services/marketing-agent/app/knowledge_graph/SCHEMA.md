# Knowledge Graph Schema Extension — Marketing Entities

**Task 132, Part 1** — Neo4j schema for Signal, Topic, Post, and ContentPillar nodes.

## Overview

The Knowledge Graph (KG) now supports marketing entities in addition to existing Orbit goals, commits, events, and HA entities. This enables:

1. **Auto-ingestion**: When marketing entities are created, they're automatically written to Neo4j
2. **KG-enriched drafting**: Draft writer queries the KG for related posts, projects, and topic context
3. **Graph traversal**: Answer questions like "What topics are connected to SAP Datasphere?"

## Node Types

### Signal
Marketing signals/opportunities detected by Scout or manual input.

**Properties:**
- `id` (STRING, UNIQUE): Signal ID
- `title` (STRING): Signal title/headline
- `url` (STRING, nullable): Source URL
- `pillar_id` (INTEGER): Content pillar ID (1-6)
- `relevance_score` (FLOAT): 0.0-1.0
- `status` (STRING): new, read, used, archived
- `detected_at` (DATETIME): When signal was detected
- `created_at` (DATETIME): Record creation time
- `updated_at` (DATETIME): Last update time

**Constraints:**
- `CONSTRAINT signal_id UNIQUE`
- `INDEX signal_title`
- `INDEX signal_pillar`
- `INDEX signal_status`

**Relationships:**
- `(s:Signal)-[:BELONGS_TO]->(cp:ContentPillar)` — Signal belongs to a pillar
- `(s:Signal)-[:CONTRIBUTES_TO]->(t:Topic)` — Signal contributed to topic formation

### Topic
Content topics/ideas that can generate multiple posts.

**Properties:**
- `id` (STRING, UNIQUE): Topic ID
- `title` (STRING): Topic title
- `summary` (STRING): Brief summary/description
- `pillar_id` (INTEGER): Content pillar ID (1-6)
- `score` (FLOAT): 0.0-1.0 relevance/quality score
- `status` (STRING): candidate, selected, drafted, published, archived
- `created_at` (DATETIME): Record creation time
- `updated_at` (DATETIME): Last update time

**Constraints:**
- `CONSTRAINT topic_id UNIQUE`
- `INDEX topic_title`
- `INDEX topic_pillar`
- `INDEX topic_status`

**Relationships:**
- `(t:Topic)-[:BELONGS_TO]->(cp:ContentPillar)` — Topic belongs to a pillar
- `(s:Signal)-[:CONTRIBUTES_TO]->(t:Topic)` — Source signals for this topic
- `(t:Topic)-[:GENERATED]->(p:Post)` — Posts generated from this topic
- `(t:Topic)-[:TRACKED_BY]->(ot:OrbitTask)` — Associated Orbit task (future)

### Post
Published or draft content pieces.

**Properties:**
- `id` (STRING, UNIQUE): Post ID
- `title` (STRING): Post title
- `format` (STRING): blog, linkedin_teaser, linkedin_native
- `pillar_id` (INTEGER): Content pillar ID (1-6)
- `word_count` (INTEGER): Content length
- `status` (STRING): draft, review, approved, scheduled, published
- `published_at` (DATETIME, nullable): Publication timestamp
- `url` (STRING, nullable): Ghost or LinkedIn URL when published
- `created_at` (DATETIME): Record creation time
- `updated_at` (DATETIME): Last update time

**Constraints:**
- `CONSTRAINT post_id UNIQUE`
- `INDEX post_title`
- `INDEX post_format`
- `INDEX post_status`
- `INDEX post_pillar`

**Relationships:**
- `(p:Post)-[:BELONGS_TO]->(cp:ContentPillar)` — Post belongs to a pillar
- `(t:Topic)-[:GENERATED]->(p:Post)` — Post generated from topic
- `(p:Post)-[:FOLLOWS_UP]->(p2:Post)` — Follow-up post relationship

### ContentPillar
Static content strategy pillars (6 predefined).

**Properties:**
- `id` (INTEGER, UNIQUE): Pillar ID (1-6)
- `name` (STRING): Pillar name
- `weight` (FLOAT): Normalized weight (sum to 1.0)
- `created_at` (DATETIME): Seed creation time
- `updated_at` (DATETIME): Last update time

**Constraints:**
- `CONSTRAINT pillar_id UNIQUE`
- `INDEX pillar_name`

**Relationships:**
- `(s:Signal)-[:BELONGS_TO]->(cp:ContentPillar)`
- `(t:Topic)-[:BELONGS_TO]->(cp:ContentPillar)`
- `(p:Post)-[:BELONGS_TO]->(cp:ContentPillar)`

## Seeded Data

Six ContentPillar nodes are seeded at initialization:

```python
[
    {"id": 1, "name": "SAP deep technical", "weight": 0.45},
    {"id": 2, "name": "SAP roadmap & features", "weight": 0.20},
    {"id": 3, "name": "Architecture & decisions", "weight": 0.15},
    {"id": 4, "name": "AI in the enterprise", "weight": 0.10},
    {"id": 5, "name": "Builder / lab / infrastructure", "weight": 0.07},
    {"id": 6, "name": "Personal builder lifestyle", "weight": 0.03},
]
```

## Ingestion Flow

### Signal → KG

```
API: POST /api/v1/signals
  ↓
(save to PostgreSQL)
  ↓
KGHooks.on_signal_created()
  ↓
MarketingKGIngestion.ingest_signal()
  ↓
Neo4j: MERGE (s:Signal {id: ...}) + BELONGS_TO ContentPillar
```

### Topic → KG

```
API: POST /api/v1/topics (with signal_ids)
  ↓
(save to PostgreSQL)
  ↓
KGHooks.on_topic_created(signal_ids=[...])
  ↓
MarketingKGIngestion.ingest_topic()
  ↓
Neo4j:
  MERGE (t:Topic {id: ...})
  BELONGS_TO ContentPillar
  Signal[*]-[:CONTRIBUTES_TO]->Topic
```

### Draft → Post (KG)

```
API: PUT /api/v1/drafts/{id} (status → 'approved'|'published')
  ↓
(update in PostgreSQL)
  ↓
KGHooks.on_draft_status_changed('approved')
  ↓
MarketingKGIngestion.ingest_draft_as_post()
  ↓
Neo4j:
  MERGE (p:Post {id: ...})
  BELONGS_TO ContentPillar
  Topic-[:GENERATED]->Post
```

## Query Examples

### Find all published posts for a topic

```cypher
MATCH (p:Post)
WHERE p.status IN ['approved', 'published']
  AND toLower(p.title) CONTAINS toLower('datasphere')
RETURN p.title, p.format, p.published_at
ORDER BY p.published_at DESC
LIMIT 5
```

### Get topic cluster (signals + posts)

```cypher
MATCH (t:Topic {id: $topic_id})
OPTIONAL MATCH (s:Signal)-[:CONTRIBUTES_TO]->(t)
OPTIONAL MATCH (t)-[:GENERATED]->(p:Post)
RETURN t, collect(DISTINCT s) as signals, collect(DISTINCT p) as posts
```

### Pillar statistics

```cypher
MATCH (p:Post)-[:BELONGS_TO]->(cp:ContentPillar {id: $pillar_id})
RETURN 
  count(p) as post_count,
  count(CASE WHEN p.status = 'published' THEN 1 END) as published_count,
  max(p.published_at) as last_published
```

### Get all node counts

```cypher
MATCH (n)
RETURN labels(n)[0] as label, count(n) as count
GROUP BY labels(n)[0]
```

## API Endpoints

### Knowledge Graph Status

```
GET /api/v1/marketing/kg/status
```

Response:
```json
{
  "neo4j_connected": true,
  "connection_error": null,
  "node_counts": {
    "Signal": 45,
    "Topic": 12,
    "Post": 8,
    "ContentPillar": 6,
    "Goal": 32,
    ...
  }
}
```

### Initialize/Verify Schema

```
POST /api/v1/marketing/kg/initialize
```

Response:
```json
{
  "success": true,
  "connected": true,
  "constraints_created": 16,
  "pillars_seeded": 6,
  "error": null
}
```

### Get Pillar Statistics

```
GET /api/v1/marketing/kg/pillars
```

Response:
```json
{
  "status": "ok",
  "pillars": {
    "1": {
      "name": "SAP deep technical",
      "post_count": 5,
      "published_count": 3,
      "last_published": "2026-03-20T10:30:00Z"
    },
    ...
  }
}
```

### Query Published Posts

```
GET /api/v1/marketing/kg/posts?topic_keywords=datasphere,modeling
```

Response:
```json
{
  "status": "ok",
  "keywords": ["datasphere", "modeling"],
  "posts": [
    {
      "title": "SAP Datasphere Modeling Fundamentals",
      "format": "blog",
      "status": "published",
      "published_at": "2026-03-15T14:20:00Z"
    },
    ...
  ]
}
```

### Get Topic Cluster

```
GET /api/v1/marketing/kg/cluster/{topic_id}
```

Response:
```json
{
  "status": "ok",
  "topic_id": "topic_123",
  "cluster": {
    "topic": {
      "id": "topic_123",
      "title": "Advanced Modeling Techniques",
      "pillar_id": 1,
      ...
    },
    "signals": [
      {"id": "sig_1", "title": "New Datasphere modeling feature", ...},
      ...
    ],
    "posts": [
      {"id": "post_1", "title": "Deep dive post", ...},
      ...
    ]
  }
}
```

## Configuration

Environment variables:

```bash
# Neo4j connection (used by both NB9OS KG and Marketing Agent)
NEO4J_URL=bolt://192.168.0.84:7687  # or http://... for HTTP transactional API
NEO4J_USER=neo4j
NEO4J_PASSWORD=<password>
```

## Error Handling & Graceful Degradation

If Neo4j is unavailable:

1. **Initialization**: Logs warning, sets `connected=False`, continues
2. **Ingestion**: Skips silently, logs at DEBUG level
3. **Queries**: Returns empty results, logs at DEBUG level
4. **API**: Returns `{"status": "unavailable"}` with HTTP 200 (not 503) to avoid alerting

The marketing-agent continues operating normally without KG enrichment.

## Testing

### Health Check

```bash
curl http://localhost:8210/api/v1/marketing/kg/status
```

### Initialize Schema

```bash
curl -X POST http://localhost:8210/api/v1/marketing/kg/initialize
```

### Create Test Signal

```bash
curl -X POST http://localhost:8210/api/v1/signals \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Signal", "source": "manual", "relevance_score": 0.8}'
```

Then verify in Neo4j:

```cypher
MATCH (s:Signal {title: "Test Signal"})
OPTIONAL MATCH (s)-[:BELONGS_TO]->(cp:ContentPillar)
RETURN s, cp
```

## Future Extensions (Task 132, Parts 2-6)

- **Part 2**: KG Ingestion Service — auto-sync from marketing-agent API
- **Part 3**: KG Query Layer — enrichment context for draft writer
- **Part 4**: Draft Writer Integration — inject KG context into prompts
- **Part 5**: REST API Endpoints — expose KG queries for frontend
- **Part 6**: Analytics & Performance — engagement data → KG weights

---

*Reference: `/home/hesch/.openclaw/workspace/tasks/20260322-132.md`*
