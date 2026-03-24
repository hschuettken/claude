# Marketing Agent Phase 0 — Setup Guide

## Quick Start

This guide covers deploying Ghost CMS and the FastAPI backend for the Marketing Agent ("Signal & Semantics").

## Architecture

```
Marketing Agent (FastAPI on 8210)
  ├── PostgreSQL marketing schema (192.168.0.80:5432)
  └── Ghost CMS (https://layer8.schuettken.net)
      └── MariaDB at 192.168.0.75:3306 (ghost_layer8)
```

---

## Part 1: Ghost CMS Deployment

### Prerequisites

- Docker and docker-compose installed on docker1
- MariaDB running at LXC 221 (192.168.0.75:3306)
- Cloudflared tunnel running at LXC 201
- Domain: `layer8.schuettken.net` (registered, DNS configured)

### Step 1: Create Ghost Database

SSH to MariaDB host (LXC 221):

```bash
mysql -u root -p
# Enter root password

CREATE DATABASE IF NOT EXISTS ghost_layer8 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'ghost'@'%' IDENTIFIED BY 'your_ghost_password';
GRANT ALL PRIVILEGES ON ghost_layer8.* TO 'ghost'@'%';
FLUSH PRIVILEGES;
EXIT;
```

### Step 2: Deploy Ghost via Docker Compose

On docker1, navigate to the service directory:

```bash
cd /path/to/claude/services/marketing-agent
```

Create a `.env` file:

```bash
cat > .env << 'EOF'
GHOST_DB_PASSWORD=your_ghost_password
GHOST_ADMIN_API_KEY=key_id:secret_hex_here
EOF
```

Deploy Ghost:

```bash
docker-compose -f ghost/docker-compose.yml up -d
```

Verify Ghost is running:

```bash
curl -f http://localhost:2368/ghost/api/admin/site/ \
  -H "Authorization: Ghost $(python3 -c 'import jwt, time; payload = {"iat": int(time.time()), "exp": int(time.time()) + 600, "aud": "/admin/"}; secret_bytes = bytes.fromhex("secret_hex_here"); print(jwt.encode(payload, secret_bytes, algorithm="HS256", headers={"kid": "key_id_here"}))')" || echo "Health check failed"
```

### Step 3: Get Ghost Admin API Key

1. Open Ghost Admin: `http://docker1:2368/ghost` (or `https://layer8.schuettken.net/ghost` once tunnel is set up)
2. Log in with your Ghost credentials
3. Navigate to **Settings** → **Integrations**
4. Click **Add custom integration**
5. Name it: "Marketing Agent"
6. Copy the **Admin API Key** (format: `key_id:secret_hex`)
7. Update `.env` with the key and restart:

```bash
# Update .env with real API key
docker-compose -f ghost/docker-compose.yml restart
```

### Step 4: Configure Cloudflared Tunnel

Edit `homelab-bootstrap/services/cloudflared/config.yml` and add:

```yaml
ingress:
  - hostname: layer8.schuettken.net
    service: http://docker1:2368
```

Reload Cloudflared:

```bash
# On LXC 201 where Cloudflared runs
systemctl reload cloudflared
```

Verify it's accessible:

```bash
curl -I https://layer8.schuettken.net/ghost
# Should return 200 OK
```

### Step 5: Configure Ghost Newsletter

1. Go to Ghost Admin → **Settings** → **Portal**
2. Enable **Newsletter**
3. Set up email capture (optional SMTP configuration)
4. Add a **Subscribe** button to posts:
   - Settings → **General** → enable **Members**
   - Posts → Add Portal widget (button or form)

---

## Part 2: FastAPI Backend Deployment

### Prerequisites

- Python 3.12+
- PostgreSQL running at 192.168.0.80:5432
- Ghost Admin API key (from Part 1, Step 3)
- Virtual environment (recommended)

### Step 1: Install Dependencies

```bash
cd /path/to/claude/services/marketing-agent

python3.12 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
```

### Step 2: Configure Environment

Create a `.env` file (or edit existing):

```bash
cat > .env << 'EOF'
# Database
MARKETING_DB_URL=postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab

# Ghost
GHOST_ADMIN_API_KEY=key_id:secret_hex_from_step3
GHOST_URL=https://layer8.schuettken.net

# Server
MARKETING_PORT=8210
LOG_LEVEL=INFO

# Optional: Knowledge Graph (Neo4j)
# NEO4J_URL=bolt://192.168.0.84:7687
# NEO4J_USER=neo4j
# NEO4J_PASSWORD=your_password
EOF
```

### Step 3: Initialize Database

The app auto-creates the `marketing` schema and tables on startup. Test it:

```bash
python3 main.py
```

You should see:
```
Starting Marketing Agent service...
Database tables created/verified
```

Press `Ctrl+C` to stop.

### Step 4: Run the Service

**Development mode:**

```bash
python3 main.py
# API available at http://localhost:8210
# Swagger UI: http://localhost:8210/docs
# ReDoc: http://localhost:8210/redoc
```

**Docker deployment:**

```bash
docker-compose up -d

# Verify health:
curl http://localhost:8210/health | jq .
```

---

## Part 3: Register with ops-bridge

To enable automated deployment, health checks, and monitoring:

1. SSH to ops-bridge host
2. Edit `homelab-bootstrap/ops-bridge/config.yml`:

```yaml
repos:
  - name: marketing-agent
    type: fastapi
    image: marketing-agent:latest
    port: 8210
    health_check: /health
    environment:
      MARKETING_DB_URL: "postgresql+asyncpg://..."
      GHOST_ADMIN_API_KEY: "..."
      GHOST_URL: "https://layer8.schuettken.net"
```

3. Reload ops-bridge:

```bash
systemctl reload ops-bridge
```

---

## Testing the Integration

### 1. Health Check

```bash
curl http://localhost:8210/health | jq .
```

Expected response:

```json
{
  "status": "ok",
  "service": "marketing-agent",
  "version": "0.1.0"
}
```

### 2. Create a Signal

```bash
curl -X POST http://localhost:8210/api/v1/signals \
  -H "Content-Type: application/json" \
  -d '{
    "title": "SAP Datasphere 2026 Roadmap",
    "url": "https://sap.com/datasphere-2026",
    "source": "manual",
    "relevance_score": 0.85
  }' | jq .
```

### 3. Create a Topic

```bash
curl -X POST http://localhost:8210/api/v1/topics \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Datasphere Semantic Layer Design",
    "pillar": "SAP Deep Technical",
    "score": 0.9
  }' | jq .
```

### 4. Create a Draft

```bash
curl -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Building Trustworthy Semantic Models in SAP Datasphere",
    "content": "<h1>Introduction</h1><p>Semantic modeling is critical...</p>",
    "summary": "How to design trustworthy semantic layers",
    "topic_id": 1,
    "tags": ["datasphere", "semantic-layer", "enterprise-data"],
    "seo_title": "SAP Datasphere Semantic Modeling Guide"
  }' | jq .
```

### 5. List Drafts

```bash
curl http://localhost:8210/api/v1/drafts | jq .
```

---

## Troubleshooting

### Ghost doesn't start

1. Check MariaDB is running: `ping 192.168.0.75`
2. Verify database exists: `mysql -h 192.168.0.75 -u ghost -p ghost_layer8 -e "SELECT 1;"`
3. Check logs: `docker logs marketing-ghost`

### API doesn't start

1. Check PostgreSQL: `psql -h 192.168.0.80 -U homelab -d homelab -c "SELECT 1;"`
2. Check logs: `docker logs marketing-agent` or check stdout
3. Verify imports: `python3 -c "from main import app; print('OK')"`

### Tunnel doesn't work

1. Check Cloudflared status: `systemctl status cloudflared`
2. Verify config: `cat /etc/cloudflared/config.yml`
3. Check DNS: `nslookup layer8.schuettken.net`

### API key issues

- Format must be `key_id:secret_hex` (with colon)
- Copy directly from Ghost Admin, not from screenshots
- Verify in `.env`: no quotes, no extra spaces

---

## Database Schema

The PostgreSQL `marketing` schema contains:

| Table | Purpose |
|-------|---------|
| `signals` | Marketing opportunities detected by Scout or manual input |
| `topics` | Content topics and categorization |
| `drafts` | Content drafts before publishing |
| `blog_posts` | Published Ghost posts (linked to drafts) |
| `linkedin_posts` | LinkedIn-specific content variants |
| `voice_rules` | Brand voice guidelines ("never say" / "always say") |
| `content_pillars` | Content strategy pillars (6 categories) |
| `performance_snapshots` | Analytics from Ghost/Plausible |

---

## API Endpoints

### Signals
- `POST /api/v1/signals` — Create signal
- `GET /api/v1/signals` — List signals
- `GET /api/v1/signals/{id}` — Get signal
- `PUT /api/v1/signals/{id}` — Update signal
- `DELETE /api/v1/signals/{id}` — Delete signal

### Topics
- `POST /api/v1/topics` — Create topic
- `GET /api/v1/topics` — List topics
- `GET /api/v1/topics/{id}` — Get topic
- `PUT /api/v1/topics/{id}` — Update topic

### Drafts
- `POST /api/v1/drafts` — Create draft
- `GET /api/v1/drafts` — List drafts
- `GET /api/v1/drafts/{id}` — Get draft
- `PUT /api/v1/drafts/{id}` — Update draft
- `DELETE /api/v1/drafts/{id}` — Delete draft
- `POST /api/v1/drafts/{id}/publish` — Publish to Ghost

---

## Next Steps (Phase 1+)

- [ ] Scout Engine — auto-detect signals from SearXNG
- [ ] Draft generation — LLM-powered content creation
- [ ] LinkedIn API integration — cross-post to LinkedIn
- [ ] Plausible analytics — track post performance
- [ ] Email newsletter — send digests
- [ ] Content calendar — plan and schedule posts
- [ ] Approval workflow — Henning review/rejection flow
- [ ] Voice rules engine — enforce brand voice during generation

---

**Created**: 2026-03-24  
**Task**: 122 — Marketing Agent Phase 0  
**Status**: Production-ready scaffold
