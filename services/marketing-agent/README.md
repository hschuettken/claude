# Marketing Agent Service

**Phase 0 scaffold** — FastAPI backend for content drafting and Ghost CMS publishing pipeline.

## Architecture

```
Marketing Agent (FastAPI on 192.168.0.80:8210)
    ├── PostgreSQL (marketing schema on 192.168.0.80:5432)
    └── Ghost API (https://layer8.schuettken.net)
        └── MariaDB (192.168.0.75:3306)
```

## Tables (8-table schema)

All tables in PostgreSQL `marketing` schema:

1. **signals** — Marketing opportunities detected by Scout or manual input
2. **topics** — Content categorization (Product, Engineering, Thought Leadership, etc.)
3. **drafts** — Content drafts before publishing
4. **blog_posts** — Published Ghost blog posts
5. **linkedin_posts** — LinkedIn-specific content
6. **voice_rules** — Brand voice guidelines (never say / always say)
7. **content_pillars** — Content strategy pillars (Product, Engineering, Culture)
8. **performance_snapshots** — Analytics from Plausible/Ghost

## Installation

### Prerequisites

- Python 3.12+
- PostgreSQL running on 192.168.0.80:5432
- Ghost 6.x running (docker1, 192.168.0.50:2368 or tunnel)
- Ghost Admin API key (see setup below)

### Setup

1. **Clone and navigate to service directory**:
   ```bash
   cd /path/to/claude/services/marketing-agent
   ```

2. **Create virtual environment**:
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with real values
   ```

5. **Initialize database** (creates `marketing` schema and tables):
   ```bash
   # Tables are auto-created on first app startup
   python main.py
   # Let it run for a few seconds, then Ctrl+C
   ```

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `MARKETING_DB_URL` | PostgreSQL connection string | Yes | — |
| `GHOST_ADMIN_API_KEY` | Ghost API key (format: `id:secret`) | Yes | — |
| `GHOST_URL` | Ghost base URL | No | `https://layer8.schuettken.net` |
| `MARKETING_PORT` | API port | No | `8210` |

### Getting Ghost Admin API Key

1. Access Ghost Admin: https://layer8.schuettken.net/ghost/
2. Navigate to **Settings** → **Integrations**
3. Create a new **Custom Integration** named "Marketing Agent"
4. Copy the **Admin API Key** (format: `key_id:secret_hex`)
5. Store in `.env`:
   ```
   GHOST_ADMIN_API_KEY=key_id:secret_hex
   ```

## Development

### Run Locally

```bash
python main.py
# API will be available at http://localhost:8210
```

### API Documentation

Swagger UI: http://localhost:8210/docs
ReDoc: http://localhost:8210/redoc

## API Endpoints

### Signals API

```http
POST   /api/v1/signals              # Create signal
GET    /api/v1/signals              # List signals (with filters)
GET    /api/v1/signals/{signal_id}  # Get signal
PUT    /api/v1/signals/{signal_id}  # Update signal
DELETE /api/v1/signals/{signal_id}  # Delete signal
```

Example:
```bash
curl -X POST http://localhost:8210/api/v1/signals \
  -H "Content-Type: application/json" \
  -d '{
    "title": "AI Marketing Trends 2024",
    "url": "https://example.com/ai-trends",
    "source": "scout",
    "relevance_score": 0.85,
    "kg_node_id": "node_123"
  }'
```

### Topics API

```http
POST   /api/v1/topics              # Create topic
GET    /api/v1/topics              # List topics
GET    /api/v1/topics/{topic_id}   # Get topic
PUT    /api/v1/topics/{topic_id}   # Update topic
```

Example:
```bash
curl -X POST http://localhost:8210/api/v1/topics \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI & Machine Learning",
    "pillar": "Engineering",
    "audience_segment": "Developers"
  }'
```

### Drafts API

```http
POST   /api/v1/drafts                      # Create draft
GET    /api/v1/drafts                      # List drafts
GET    /api/v1/drafts/{draft_id}           # Get draft
PUT    /api/v1/drafts/{draft_id}           # Update draft
DELETE /api/v1/drafts/{draft_id}           # Delete draft
POST   /api/v1/drafts/{draft_id}/publish   # Publish to Ghost
```

Example (create draft):
```bash
curl -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Getting Started with FastAPI",
    "content": "<h1>FastAPI</h1><p>Fast, modern Python framework...</p>",
    "summary": "Introduction to FastAPI",
    "topic_id": 1,
    "tags": ["engineering", "python"],
    "seo_title": "FastAPI Tutorial for Beginners"
  }'
```

Example (publish to Ghost):
```bash
curl -X POST http://localhost:8210/api/v1/drafts/1/publish \
  -H "Content-Type: application/json"

# Response:
# {
#   "status": "ok",
#   "draft_id": 1,
#   "ghost_post_id": "abc123",
#   "ghost_url": "https://layer8.schuettken.net/getting-started-with-fastapi",
#   "slug": "getting-started-with-fastapi",
#   "published_at": "2026-03-24T01:30:00.000Z"
# }
```

## Database Migrations

Migrations are in `migrations/` directory. They're idempotent SQL scripts.

To manually run migration:
```bash
psql -h 192.168.0.80 -U homelab -d homelab -f migrations/001_initial_schema.sql
```

The app auto-creates tables on startup, so manual migration is optional.

## Integration with Ghost

### Publishing Flow

1. **Draft Created** → `POST /api/v1/drafts`
   - Creates record in `marketing.drafts`

2. **Draft Reviewed** → `PUT /api/v1/drafts/{id}`
   - Update status to `approved`

3. **Draft Published** → `POST /api/v1/drafts/{id}/publish`
   - Calls Ghost Admin API to create post
   - Publishes post immediately
   - Stores `ghost_post_id` in drafts table
   - Creates `blog_posts` record

4. **Analytics** → (Future: Plausible integration)
   - `performance_snapshots` table tracks views, engagement

### Testing Ghost Integration

```bash
# Verify Ghost is accessible
curl -s https://layer8.schuettken.net/ghost | head -10

# Verify API key format
echo "GHOST_ADMIN_API_KEY should be: key_id:secret_hex"

# Test direct Ghost API (requires API key)
# Get Ghost version:
curl -H "Authorization: Ghost $(python -c 'import jwt, time; payload = {\"iat\": int(time.time()), \"exp\": int(time.time()) + 600, \"aud\": \"/admin/\"}; secret_bytes = bytes.fromhex(\"secret_hex_here\"); print(jwt.encode(payload, secret_bytes, algorithm=\"HS256\", headers={\"kid\": \"key_id_here\"}))' )" \
  https://layer8.schuettken.net/ghost/api/admin/site/
```

## Deployment

### Docker

```bash
# Build image
docker build -t marketing-agent:latest .

# Run container
docker run -d \
  --name marketing-agent \
  -p 8210:8210 \
  -e MARKETING_DB_URL="postgresql+asyncpg://..." \
  -e GHOST_ADMIN_API_KEY="..." \
  marketing-agent:latest
```

### ops-bridge Registration

To register with ops-bridge for automated deployment:

```bash
# Add to ops-bridge services.yml or via API
curl -X POST http://ops.local.schuettken.net/api/services \
  -H "Authorization: Bearer <token>" \
  -d '{
    "name": "marketing-agent",
    "service_type": "fastapi",
    "image": "marketing-agent:latest",
    "port": 8210,
    "health_check": "/health",
    "env_vars": {
      "MARKETING_DB_URL": "postgresql+asyncpg://...",
      "GHOST_ADMIN_API_KEY": "..."
    }
  }'
```

## Monitoring

### Health Check

```bash
curl http://localhost:8210/health
# Response: {"status": "ok", "service": "marketing-agent", "version": "0.1.0"}
```

### Logs

```bash
# If running with Python
tail -f /var/log/marketing-agent.log

# If Docker
docker logs -f marketing-agent
```

## Future Enhancements (Phase 1+)

- [ ] Scout integration — auto-detect signals
- [ ] Draft generation — LLM-powered content creation
- [ ] LinkedIn API integration — auto-post to LinkedIn
- [ ] Plausible analytics integration — track performance
- [ ] Email newsletter integration
- [ ] Content approval workflow
- [ ] Webhook notifications (NATS events)

## References

- Ghost Admin API: https://ghost.org/docs/admin-api/
- FastAPI: https://fastapi.tiangolo.com/
- SQLAlchemy async: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Pydantic: https://docs.pydantic.dev/latest/

## Support

For issues, check:
1. Ghost Admin API key format: `key_id:secret_hex`
2. PostgreSQL connection: `psql -U homelab -h 192.168.0.80 -d homelab`
3. Ghost connectivity: `curl https://layer8.schuettken.net/ghost`
4. Service logs: `docker logs marketing-agent` or Python stdout

---

**Created**: 2026-03-24  
**Task**: 122 — Marketing Agent Phase 0  
**Status**: Scaffold complete, ready for Phase 1 (Scout, drafting, publishing)
