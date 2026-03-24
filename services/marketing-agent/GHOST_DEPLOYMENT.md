# Ghost CMS Deployment & Marketing Agent Integration

## Overview

This guide covers deploying Ghost CMS on docker1 and wiring the marketing-agent service for end-to-end publishing from NB9OS drafts to Ghost blog posts.

## Architecture

```
NB9OS Frontend (DraftDetailPage)
    ↓
Marketing Agent API (/api/v1/drafts/{id}/publish)
    ↓
Ghost Admin API Client (ghost_client.py)
    ↓
Ghost CMS (docker1:2368)
    ↓
Cloudflared Tunnel (LXC 201)
    ↓
Public: https://layer8.schuettken.net
```

## Phase 1: Ghost CMS Deployment

### Prerequisites

- SSH access to docker1 (root@192.168.0.50)
- Docker & docker-compose installed on docker1
- MySQL service running (LXC 221 at 192.168.0.75:3306)
- Cloudflared tunnel access (LXC 201)
- ~2GB free space on docker1 for Ghost content

### Step 1: Deploy Ghost Container

**Option A: Automated Deployment (Recommended)**

```bash
# From workspace root
bash claude/services/marketing-agent/DEPLOY_GHOST.sh
```

This script will:
1. Create `/opt/ghost` directory on docker1
2. Copy docker-compose.yml
3. Generate secure database password
4. Start Ghost container
5. Wait for container to be healthy
6. Provide next steps

**Option B: Manual Deployment**

```bash
# 1. SSH to docker1
ssh root@192.168.0.50

# 2. Create Ghost directory
mkdir -p /opt/ghost
cd /opt/ghost

# 3. Copy docker-compose
# (Copy claude/services/marketing-agent/ghost/docker-compose.yml to /opt/ghost/)

# 4. Create .env with secure password
cat > .env << 'EOF'
GHOST_DB_PASSWORD=<GENERATE_SECURE_PASSWORD>
GHOST_URL=https://layer8.schuettken.net
NODE_ENV=production
GHOST_DB_HOST=192.168.0.75
GHOST_DB_USER=ghost
EOF

# 5. Start Ghost
docker-compose up -d

# 6. Check status
docker-compose logs -f ghost
```

### Step 2: Initialize Ghost Admin

Once Ghost container is running, complete the setup wizard:

1. Open: `https://layer8.schuettken.net/ghost/setup`
2. Create admin account:
   - Email: your-email@example.com
   - Name: Henning
   - Password: (choose strong password)
   - Blog Title: Layer 8
   
3. Complete initial setup wizard

4. In Ghost Admin Settings → Integrations:
   - Create new Integration named "marketing-agent"
   - Copy Admin API Key (format: `key_id:secret_hex`)
   - **Save this key** — you'll need it in the next step

### Step 3: Configure Content Structure

In Ghost Admin, create the following content tags/categories:

- **Product** — Product updates, features, releases
- **Leadership** — Strategy, decision-making, business
- **Innovation** — New ideas, experiments, research
- **Technical** — Architecture, implementation, deep dives
- **SAP Datasphere** — Datasphere-specific content
- **Architecture** — System design, patterns

These tags will be used to categorize drafts and posts.

### Step 4: Set Up Cloudflared Tunnel

The Ghost CMS needs public access via `layer8.schuettken.net`.

```bash
# 1. SSH to Cloudflared LXC (192.168.0.201)
ssh root@192.168.0.201

# 2. Edit cloudflared config
vi /etc/cloudflared/config.yaml

# 3. Add ingress rule for Ghost:
#    (Add this to the ingress section)
#    - hostname: layer8.schuettken.net
#      service: http://192.168.0.50:2368

# 4. Reload cloudflared
systemctl reload cloudflared

# 5. Test access
curl -I https://layer8.schuettken.net/
# Should return 200 OK
```

## Phase 2: Marketing Agent Integration

### Step 1: Update .env

Update `claude/services/marketing-agent/.env` with Ghost credentials:

```bash
# Ghost CMS Configuration
GHOST_ADMIN_API_KEY=key_id:secret_hex     # From Ghost Admin Integration
GHOST_URL=https://layer8.schuettken.net
GHOST_DOMAIN=layer8.schuettken.net

# Database
MARKETING_DB_URL=postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab

# Optional: NATS JetStream
NATS_URL=nats://192.168.0.50:4222
NATS_USER=homelab
NATS_PASSWORD=homelab

# Service port
MARKETING_PORT=8210
```

### Step 2: Database Setup

The marketing-agent expects these tables in PostgreSQL:

```sql
-- Ensure schema exists
CREATE SCHEMA IF NOT EXISTS marketing;

-- Draft table (auto-created by SQLAlchemy)
CREATE TABLE marketing.drafts (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    status VARCHAR(50) DEFAULT 'draft',
    platform VARCHAR(50) DEFAULT 'blog',
    tags TEXT[],
    topic_id INTEGER,
    signal_id INTEGER,
    ghost_post_id VARCHAR(255),
    ghost_url VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    published_at TIMESTAMP
);

-- Blog posts table (links drafts to Ghost posts)
CREATE TABLE marketing.blog_posts (
    id SERIAL PRIMARY KEY,
    draft_id INTEGER REFERENCES marketing.drafts(id),
    ghost_post_id VARCHAR(255) UNIQUE NOT NULL,
    published_at TIMESTAMP,
    slug VARCHAR(255) UNIQUE,
    tags TEXT[],
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes
CREATE INDEX idx_drafts_status ON marketing.drafts(status);
CREATE INDEX idx_drafts_topic_id ON marketing.drafts(topic_id);
CREATE INDEX idx_blog_posts_draft_id ON marketing.blog_posts(draft_id);
CREATE INDEX idx_blog_posts_ghost_id ON marketing.blog_posts(ghost_post_id);
```

### Step 3: Deploy Marketing Agent

**Option A: Docker Compose (Local or docker1)**

```bash
cd claude/services/marketing-agent

# Build image
docker build -t marketing-agent:latest .

# Run locally for testing
docker-compose up -d

# Verify health
curl http://localhost:8210/health
# Response: {"status": "ok", "service": "marketing-agent", "version": "0.1.0"}
```

**Option B: ops-bridge Deployment**

When ops-bridge is ready, deploy via:

```bash
curl -X POST http://192.168.0.50:8110/api/v1/services/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "repo": "marketing-agent",
    "version": "latest",
    "env": {
      "GHOST_ADMIN_API_KEY": "your_key_here",
      "GHOST_URL": "https://layer8.schuettken.net"
    }
  }'
```

## Phase 3: End-to-End Testing

### Test 1: Create a Draft

```bash
curl -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test: SAP Datasphere Best Practices",
    "content": "<h2>Introduction</h2><p>This is a test post demonstrating the Ghost publishing pipeline.</p>",
    "summary": "A test post for the marketing-agent",
    "tags": ["SAP Datasphere", "Technical"],
    "seo_title": "SAP Datasphere Best Practices Guide",
    "seo_description": "Learn how to design effective Datasphere data models"
  }'
```

Response:
```json
{
  "id": 1,
  "title": "Test: SAP Datasphere Best Practices",
  "status": "draft",
  "platform": "blog",
  "tags": ["SAP Datasphere", "Technical"],
  "created_at": "2026-03-24T02:00:00Z",
  "ghost_post_id": null
}
```

### Test 2: Approve Draft

In NB9OS frontend, change draft status to `approved`:

```bash
curl -X PUT http://localhost:8210/api/v1/drafts/1 \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}'
```

### Test 3: Publish to Ghost

```bash
curl -X POST http://localhost:8210/api/v1/drafts/1/publish \
  -H "Content-Type: application/json" \
  -d '{}'
```

Expected Response:
```json
{
  "status": "ok",
  "draft_id": 1,
  "ghost_post_id": "5f8c4b2e8f7f9d6c",
  "ghost_url": "https://layer8.schuettken.net/test-datasphere-best-practices/",
  "slug": "test-datasphere-best-practices",
  "published_at": "2026-03-24T02:05:00Z"
}
```

### Test 4: Verify in Ghost Admin

Navigate to: `https://layer8.schuettken.net/ghost/editor/posts/`

You should see your published post listed with:
- Title matching the draft
- Tags matching the categories
- Published status
- Correct slug

### Test 5: Verify Public Post

Navigate to: `https://layer8.schuettken.net/test-datasphere-best-practices/`

Post should be publicly accessible with proper formatting.

## Publishing Workflow

### Full Flow Diagram

```
1. NB9OS Frontend (/marketing/draft-detail)
   ↓ Create/Edit Draft
2. Draft Status: draft → review → approved
   ↓ (AI review in separate task)
3. NB9OS Frontend → Click "Publish Now"
   ↓ 
4. Marketing Agent API
   POST /api/v1/drafts/{id}/publish
   ↓ Validate status == approved
5. Ghost Admin API Client
   ↓ ghost_client.create_post()
   ↓ ghost_client.publish_post()
6. Blog Post Record Created
   ↓ ghost_post_id stored
7. NATS Event Published: post.published
   ↓ (triggers downstream: analytics, social, etc.)
8. Frontend Toast
   ↓ "Published! View on Ghost"
9. Public Blog Post
   ↓ https://layer8.schuettken.net/post-slug/
10. Analytics Tracking
    ↓ (future: performance feedback)
```

### Scheduled Publishing

For future publication:

```bash
curl -X POST http://localhost:8210/api/v1/drafts/1/schedule \
  -H "Content-Type: application/json" \
  -d '{
    "publish_at": "2026-03-25T10:00:00Z"
  }'
```

This creates a scheduled Ghost post that will automatically publish at the specified time.

## API Endpoints Reference

### Drafts

- `GET /api/v1/drafts` — List all drafts
- `GET /api/v1/drafts/{id}` — Get draft details
- `POST /api/v1/drafts` — Create new draft
- `PUT /api/v1/drafts/{id}` — Update draft
- `DELETE /api/v1/drafts/{id}` — Delete draft

### Publishing

- `POST /api/v1/drafts/{id}/publish` — Publish draft to Ghost
- `POST /api/v1/drafts/{id}/schedule` — Schedule future publication
- `GET /api/v1/drafts/{id}/ghost-status` — Check Ghost post status

### Signals

- `GET /api/v1/signals` — List marketing signals
- `POST /api/v1/signals/refresh` — Refresh signal detection

### Topics

- `GET /api/v1/topics` — List topics
- `GET /api/v1/topics/{id}/score` — Get topic relevance score

## Error Handling

### Common Errors

**401 Unauthorized**
- Cause: Invalid Ghost API key
- Fix: Verify `GHOST_ADMIN_API_KEY` in .env matches Ghost Admin Integration key

**404 Not Found**
- Cause: Ghost post ID not found
- Fix: Verify Ghost container is running and API is accessible

**400 Bad Request - Draft is already published**
- Cause: Attempting to publish a draft that's already published
- Fix: Create a new draft for the next post

**500 Internal Server Error**
- Cause: Ghost API unreachable or database error
- Fix: Check Ghost container status, verify database connection

## Monitoring & Maintenance

### Health Checks

```bash
# Check marketing-agent health
curl http://localhost:8210/health

# Check Ghost health
curl https://layer8.schuettken.net/ghost/setup
```

### Logs

```bash
# Docker compose logs (local)
docker-compose logs -f marketing-agent
docker-compose logs -f ghost

# SSH to docker1
ssh root@192.168.0.50
cd /opt/ghost
docker-compose logs -f ghost
```

### Database Maintenance

```bash
# Backup marketing database
pg_dump homelab | gzip > backup_$(date +%Y%m%d).sql.gz

# Check Ghost database size
mysql -h 192.168.0.75 -u ghost -p -e "SELECT table_name, ROUND(((data_length + index_length) / 1024 / 1024), 2) MB FROM information_schema.TABLES WHERE table_schema = 'ghost' ORDER BY MB DESC;"
```

## Troubleshooting

### Ghost Container Won't Start

```bash
# SSH to docker1
ssh root@192.168.0.50

# Check logs
cd /opt/ghost
docker-compose logs ghost

# Common issues:
# - Port 2368 already in use: change port in docker-compose.yml
# - Database connection failed: verify MySQL service at 192.168.0.75:3306
# - Insufficient disk space: check with `df -h`
```

### Publishing Fails

```bash
# Check marketing-agent service
curl http://localhost:8210/health

# Test Ghost API directly
curl -X GET https://layer8.schuettken.net/ghost/api/v3/admin/posts/ \
  -H "Authorization: Ghost $(YOUR_GHOST_API_KEY)"

# Check database connection
psql postgresql://homelab:homelab@192.168.0.80:5432/homelab -c "SELECT COUNT(*) FROM marketing.drafts;"
```

### Cloudflared Tunnel Not Working

```bash
# SSH to LXC 201
ssh root@192.168.0.201

# Check cloudflared service
systemctl status cloudflared

# Check logs
journalctl -u cloudflared -n 50 -f

# Test Ghost accessibility from docker1
docker exec ghost curl -I http://localhost:2368/
```

## Next Steps

1. **LinkedIn Publishing** — Add support for auto-posting to LinkedIn
2. **Analytics Integration** — Track post performance metrics
3. **Content Scheduling** — AI-driven optimal publish time suggestions
4. **Multi-language Support** — Translate posts to other languages
5. **Email Newsletter** — Ghost's built-in newsletter feature integration

## References

- [Ghost CMS Documentation](https://ghost.org/docs/)
- [Ghost Admin API](https://ghost.org/docs/admin-api/)
- [Docker Compose Ghost Example](https://github.com/TryGhost/Ghost-CLI)
- [Cloudflared Tunnel Setup](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)
