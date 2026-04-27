# cognitive-layer — External Brain v2

AI-powered personal knowledge layer for the homelab. Provides a PostgreSQL-backed
knowledge graph, memory ingestion pipelines, thought continuity tracking, cognitive
load monitoring, daily briefings, and periodic reflection reports.

## Architecture

- **Framework**: FastAPI at port 8230
- **Storage**: PostgreSQL (192.168.0.80:5432) with pgvector extension
- **Knowledge Graph**: `kg_nodes` + `kg_edges` tables (flat FK — no Neo4j/graph DB)
- **Embeddings**: pgvector column on `kg_nodes` (not yet auto-populated — manual upsert)
- **LLM**: Local llm-router at 192.168.0.50:8070 with `qwen2.5:3b` (never Anthropic/OpenAI direct)
- **Event Bus**: NATS JetStream — subscribes `ha.state.>` for real-time HA event ingestion

## Key modules

| Module | Purpose |
|--------|---------|
| `knowledge_graph.py` | Node/edge CRUD (upsert by source+source_id) |
| `ingestion/chat_export.py` | Parse ChatGPT/Claude JSON exports → KG nodes |
| `ingestion/git_activity.py` | Poll GitHub API → git_commit nodes |
| `ingestion/ha_events.py` | NATS `ha.state.>` → ha_event nodes |
| `ingestion/calendar.py` | Orbit calendar proxy → meeting/calendar_event nodes |
| `ingestion/orbit.py` | Orbit tasks/goals → orbit_task/orbit_goal nodes |
| `continuity.py` | Thought Continuity Engine — open thread tracking |
| `cognitive_load.py` | Mental-debt score (0–100) |
| `briefing.py` | LLM-generated daily morning narrative (cached) |
| `reflection.py` | Daily / weekly / monthly reflection reports |

## Node types

`page` | `meeting` | `chat` | `git_commit` | `ha_event` | `calendar_event` |
`orbit_task` | `orbit_goal` | `thought` | `concept`

## Edge relation types

`RELATES_TO` | `BLOCKS` | `DEPENDS_ON` | `PART_OF` | `CREATED_BY` |
`DISCUSSED_IN` | `LEADS_TO`

## API endpoints

- `GET /health`
- `POST /api/v1/nodes` — create KG node
- `GET /api/v1/nodes` — list nodes (filterable by type/source)
- `GET /api/v1/nodes/search?q=` — full-text label search
- `GET /api/v1/nodes/{id}/neighbours` — adjacency with edges
- `POST /api/v1/edges` — create edge
- `GET /api/v1/threads` — list thought threads
- `GET /api/v1/cognitive-load` — current debt score + breakdown
- `GET /api/v1/briefing` — today's briefing (generates if missing)
- `GET /api/v1/reflection/daily|weekly|monthly`
- `POST /api/v1/ingest/git|calendar|orbit|chat-export|all`
- `POST /api/v1/threads/maintenance` — nightly thread maintenance

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `COGNITIVE_DB_URL` | `postgresql://homelab:homelab@192.168.0.80:5432/homelab` | PostgreSQL DSN |
| `LLM_ROUTER_URL` | `http://192.168.0.50:8070` | LLM router base URL |
| `COGNITIVE_LLM_MODEL` | `qwen2.5:3b` | Local model for briefing/reflection |
| `NATS_URL` | `nats://192.168.0.50:4222` | NATS server |
| `NB9OS_API_URL` | `http://192.168.0.50:8060` | Orbit/nb9os API for task/calendar data |
| `GITHUB_TOKEN` | — | GitHub PAT for commit ingestion |
| `GITHUB_OWNER` | `hschuettken` | GitHub owner |
| `COGNITIVE_PORT` | `8230` | Service port |

## Testing

```bash
cd services/cognitive-layer
python -m pytest tests/ -v
```

Tests run without a real database (mock/in-memory fallback in db.py).

## Design decisions

- **No graph DB**: Neo4j adds operational complexity. Flat FK in PostgreSQL is
  sufficient for the relationship types needed here (depth-1 neighbourhood queries,
  FK aggregation). If graph traversal depth > 2 becomes a requirement, revisit.
- **Dual-write embeddings**: pgvector column exists but auto-population is deferred.
  Embeddings require the LLM router to support an `/embeddings` endpoint.
- **LLM Model**: `qwen2.5:3b` chosen for low latency on local hardware. Swap via
  `COGNITIVE_LLM_MODEL`. Briefings and reflections degrade gracefully when LLM is
  unreachable (returns a simple template-rendered fallback).
