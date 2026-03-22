# Marketing Agent — Phase 0

FastAPI service for the marketing pipeline — Ghost CMS integration + content management scaffold.

## Overview

The Marketing Agent orchestrates content creation and distribution across multiple platforms (blog, LinkedIn, etc.). Phase 0 provides the infrastructure and schema for:

- **Signal collection** — curate external content/insights relevant to marketing
- **Topic management** — organize content around strategic pillars
- **Draft workflow** — track content through draft → review → approved → scheduled → published
- **Ghost CMS integration** — publish posts to Ghost blog via Admin API
- **Performance tracking** — measure engagement across platforms

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Marketing Agent (FastAPI)                                   │
├─────────────────────────────────────────────────────────────┤
│ /api/v1/signals    — Signal CRUD                            │
│ /api/v1/topics     — Topic management                       │
│ /api/v1/drafts     — Draft workflow                         │
├─────────────────────────────────────────────────────────────┤
│ Database (PostgreSQL @ 192.168.0.80:5432)                   │
│ ├─ signals                                                  │
│ ├─ topics                                                   │
│ ├─ content_pillars                                          │
│ ├─ drafts                                                   │
│ ├─ blog_posts (links to Ghost posts)                       │
│ ├─ linkedin_posts                                           │
│ ├─ voice_rules                                              │
│ └─ performance_snapshots                                    │
├─────────────────────────────────────────────────────────────┤
│ Ghost CMS (Docker @ layer8.schuettken.net)                  │
│ Database: MariaDB (LXC 221 @ 192.168.0.75:3306)            │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Clone & Setup

```bash
cd /home/hesch/.openclaw/workspace-nb9os/claude/services/marketing-agent
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and set:

```bash
cp .env.example .env
# Edit .env with actual credentials
```

### 3. Database Schema

Run the migration on the PostgreSQL server:

```bash
psql -h 192.168.0.80 -U homelab -d homelab < migrations/001_initial_schema.sql
```

### 4. Ghost CMS Setup

Set up Ghost in the `ghost/` subdirectory:

```bash
cd ghost/
# Create .env with Ghost credentials
cp docker-compose.yml your-deployment-location/
docker-compose up -d
```

### 5. Run Service

**Local development:**

```bash
pip install -r requirements.txt
python main.py
```

**Docker:**

```bash
docker build -t marketing-agent:latest -f Dockerfile ../../
docker run -p 8210:8210 \
  -e MARKETING_DB_URL="postgresql://..." \
  -e GHOST_ADMIN_API_KEY="..." \
  marketing-agent:latest
```

## API Endpoints

### Signals

```
GET    /api/v1/signals                 — List signals
POST   /api/v1/signals                 — Create signal
GET    /api/v1/signals/{id}            — Get signal
DELETE /api/v1/signals/{id}            — Delete signal
```

### Topics

```
GET    /api/v1/topics                  — List topics
POST   /api/v1/topics                  — Create topic
GET    /api/v1/topics/{id}             — Get topic
```

### Drafts

```
GET    /api/v1/drafts                  — List drafts
POST   /api/v1/drafts                  — Create draft
GET    /api/v1/drafts/{id}             — Get draft
PUT    /api/v1/drafts/{id}             — Update draft
DELETE /api/v1/drafts/{id}             — Delete draft
```

## Database Schema

### Signals (marketing.signals)
Store external content/insights relevant to marketing strategy.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| title | varchar(255) | Signal title |
| url | varchar(2048) | Source URL |
| source | varchar(128) | Source name (e.g., 'HackerNews', 'LinkedIn') |
| relevance_score | float | 0.0-1.0 relevance to marketing |
| created_at | timestamp | Ingestion time |
| kg_node_id | varchar(128) | Link to knowledge graph node |

### Topics (marketing.topics)
Organize content around strategic pillars and audience segments.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| name | varchar(255) | Topic name |
| pillar | varchar(255) | Content pillar (e.g., 'Product', 'Leadership') |
| audience_segment | varchar(255) | Target audience (e.g., 'Enterprise', 'Developers') |
| created_at | timestamp | Creation time |

### Drafts (marketing.drafts)
Work-in-progress content across platforms.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| title | varchar(255) | Draft title |
| content | text | Draft content |
| status | varchar(32) | draft, review, approved, scheduled, published |
| topic_id | int | Link to topic (FK) |
| platform | varchar(64) | blog, linkedin, twitter, etc. |
| created_at | timestamp | Creation time |
| updated_at | timestamp | Last modified |

### Blog Posts (marketing.blog_posts)
Published blog posts via Ghost CMS.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| draft_id | int | Link to draft (FK) |
| ghost_post_id | varchar(64) | Ghost post UUID |
| published_at | timestamp | Publication timestamp |
| slug | varchar(255) | Ghost slug |
| tags | varchar(512) | Comma-separated tags |

### LinkedIn Posts (marketing.linkedin_posts)
Published LinkedIn posts.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| draft_id | int | Link to draft (FK) |
| content | text | LinkedIn post content |
| hook | varchar(512) | Opening line |
| posted_at | timestamp | When posted |

### Voice Rules (marketing.voice_rules)
Content generation guidelines (tone, messaging, etc.).

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| rule_type | varchar(32) | never_say, always_say |
| content | text | Rule text |
| created_at | timestamp | Creation time |

### Content Pillars (marketing.content_pillars)
Top-level content strategy buckets.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| name | varchar(255) | Pillar name |
| description | text | Pillar description |
| color | varchar(7) | Hex color code |
| target_audience | varchar(255) | Intended audience |

### Performance Snapshots (marketing.performance_snapshots)
Track engagement metrics for published content.

| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| post_id | int | Blog/LinkedIn post ID |
| platform | varchar(64) | blog, linkedin |
| views | int | View count |
| engagement_rate | float | Engagement percentage |
| recorded_at | timestamp | When recorded |

## Ghost Admin API Integration

The `ghost_client.py` module provides JWT-authenticated access to Ghost Admin API:

```python
from ghost_client import get_ghost_client

client = get_ghost_client()

# Create post
post = await client.create_post(
    title="My Post",
    html="<p>Content</p>",
    tags=["tag1", "tag2"],
    status="draft"
)

# Update post
updated = await client.update_post(post['id'], status="published")

# Get posts
posts = await client.get_posts(limit=10, filter_="status:published")
```

## Health Check

```bash
curl http://localhost:8210/health
```

Response:
```json
{
  "status": "ok",
  "service": "marketing-agent",
  "version": "0.1.0"
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| MARKETING_DB_URL | postgresql://homelab:homelab@192.168.0.80:5432/homelab | PostgreSQL connection string |
| GHOST_URL | https://layer8.schuettken.net | Ghost CMS base URL |
| GHOST_ADMIN_API_KEY | (required) | Ghost Admin API key (id:secret format) |
| MARKETING_PORT | 8210 | Service port |
| DEBUG | false | Debug mode |
| LOG_LEVEL | INFO | Logging level (DEBUG, INFO, WARNING, ERROR) |

## Phase 1 (Future)

- **Scout integration** — discover content signals from external sources
- **Draft generation** — LLM-powered content creation from signals
- **Multi-platform publishing** — scheduled publication to Ghost, LinkedIn, Twitter
- **Performance feedback loop** — analytics integration

## Development

### Tests

```bash
pytest tests/
```

### Type checking

```bash
mypy services/marketing-agent/
```

### Linting

```bash
ruff check services/marketing-agent/
```

## Notes

- Phase 0 is infrastructure + schema. Phase 1 adds Scout, generation, and scheduling.
- Ghost deployment is separate (ops-bridge managed). Marketing service connects via Admin API.
- PostgreSQL schema is auto-created by SQLAlchemy models on first startup (see `main.py` lifespan).
- For production, run migrations via `psql` before deploying service.
