# Knowledge Graph Integration

The Marketing Agent integrates with a Neo4j Knowledge Graph to enrich content generation and enable intelligent draft writing.

## Architecture

### Components

1. **neo4j_singleton.py** — Neo4j connection management
   - Singleton pattern for shared connection
   - Health checks and graceful degradation
   - If Neo4j is unreachable, agent continues without KG features

2. **schema.py** — KG schema definitions
   - Node labels: Signal, Topic, Post, ContentPillar
   - Constraints and indexes
   - Seed data for 6 content pillars

3. **ingestion.py** — Auto-sync of marketing entities
   - Signal → KG Signal node (when signal detected)
   - Topic → KG Topic node (when topic created)
   - Draft → KG Post node (when draft approved/published)
   - Automatic relationship creation (CONTRIBUTES_TO, GENERATED, BELONGS_TO)

4. **query.py** — KG query service
   - Published posts lookup
   - Related Orbit tasks discovery
   - Pillar statistics
   - Topic cluster retrieval

5. **../api/knowledge_graph.py** — REST endpoints
   - GET /api/v1/marketing/kg/status
   - GET /api/v1/marketing/kg/pillars
   - GET /api/v1/marketing/kg/posts
   - GET /api/v1/marketing/kg/cluster/{topic_id}
   - GET /api/v1/marketing/kg/related-posts/{topic_title}

## Node Types

### Signal
```cypher
Signal {
    id: str (unique),
    title: str,
    url: str,
    pillar_id: int,
    relevance_score: float,
    detected_at: ISO datetime,
    status: str (new, read, used, archived),
    created_at: ISO datetime,
    updated_at: ISO datetime
}
```

**Relationships:**
- `Signal-[:BELONGS_TO]->ContentPillar`
- `Signal-[:CONTRIBUTES_TO]->Topic`

### Topic
```cypher
Topic {
    id: str (unique),
    title: str,
    summary: str,
    pillar_id: int,
    score: float (0.0-1.0),
    status: str (candidate, selected, drafted, published, archived),
    created_at: ISO datetime,
    updated_at: ISO datetime
}
```

**Relationships:**
- `Topic-[:BELONGS_TO]->ContentPillar`
- `Topic-[:GENERATED]->Post`

### Post
```cypher
Post {
    id: str (unique),
    title: str,
    format: str (blog, linkedin_teaser, linkedin_native),
    pillar_id: int,
    word_count: int,
    status: str (draft, review, approved, published),
    published_at: ISO datetime (nullable),
    url: str (nullable),
    created_at: ISO datetime,
    updated_at: ISO datetime
}
```

**Relationships:**
- `Post-[:BELONGS_TO]->ContentPillar`
- `Post-[:FOLLOWS_UP]->Post`

### ContentPillar
```cypher
ContentPillar {
    id: int (1-6, unique),
    name: str,
    weight: float
}
```

**Predefined Pillars:**
1. SAP deep technical (weight: 0.45)
2. SAP roadmap & features (weight: 0.20)
3. Architecture & decisions (weight: 0.15)
4. AI in the enterprise (weight: 0.10)
5. Builder / lab / infrastructure (weight: 0.07)
6. Personal builder lifestyle (weight: 0.03)

## Usage in Draft Generation

When the draft writer generates a blog post, it:

1. **Extracts keywords** from the topic title
2. **Queries KG** for:
   - Previously published posts on similar topics
   - Active Orbit tasks related to the topic
   - Content statistics for the pillar
3. **Injects context** into the LLM prompt to:
   - Avoid repeating coverage
   - Reference related posts
   - Draw connections to active projects
   - Identify coverage gaps

Example enriched prompt:
```
## Previously Published Posts
  - SAP Analytics Cloud for Advanced Forecasting (blog)
  - Machine Learning Models in BTP (linkedin_teaser)

## Related Active Projects
  - Analytics Platform Upgrade (in_progress)
  - ML Training Data Pipeline (active)

## Content Coverage for This Pillar
  - Total posts: 15
  - Published: 12
  - Last published: 2025-03-15
```

## Configuration

Set these environment variables:

```bash
NEO4J_URL=bolt://192.168.0.23:7687          # LXC 340 or actual Neo4j host
NEO4J_USER=neo4j                              # Neo4j username
NEO4J_PASSWORD=<password>                    # Neo4j password
```

Default Neo4j URL is `bolt://192.168.0.23:7687` (LXC 340 on Proxmox).

## Graceful Degradation

If Neo4j is unreachable:

1. Agent logs a warning at startup
2. KG features are disabled (not crashed)
3. Draft generation continues normally without enrichment
4. API endpoints return `{"status": "unavailable", ...}`

This ensures the marketing agent remains operational even if the KG infrastructure fails.

## Seeding ContentPillars

ContentPillar nodes are automatically seeded at service startup. To manually seed:

```bash
python migrations/seed_content_pillars.py
```

## Querying the KG

### Get all pillar statistics
```bash
curl http://localhost:8210/api/v1/marketing/kg/pillars
```

### Find posts on a topic
```bash
curl "http://localhost:8210/api/v1/marketing/kg/posts?topic_keywords=SAP,Analytics"
```

### Get topic cluster
```bash
curl http://localhost:8210/api/v1/marketing/kg/cluster/topic-123
```

### Check KG status
```bash
curl http://localhost:8210/api/v1/marketing/kg/status
```

## Future Enhancements (Round 21+)

- Named Entity Recognition (NER) → extract entities mentioned in posts
- Authority graph visualization
- Engagement-driven edge weights
- Automated topic recommendations based on KG patterns
