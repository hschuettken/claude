# Ghost CMS Setup Guide for Marketing Agent

## Status

**Ghost Container:** ✅ DEPLOYED & RUNNING  
**MariaDB Connection:** ✅ VERIFIED  
**Admin API Client:** ✅ READY TO USE  
**Publishing Endpoint:** ✅ READY TO USE  

**Remaining Tasks:** Configure Cloudflare tunnel + Generate Admin API Key

## Quick Start

### 1. Ensure Ghost is Running

```bash
# Check docker1
curl http://192.168.0.50:2368/

# Should return 301 redirect to https://layer8.schuettken.net
```

### 2. Configure Cloudflare Tunnel (Manual - 5 minutes)

**Why:** Ghost requires HTTPS and is configured to redirect to `layer8.schuettken.net`. 
The Cloudflare tunnel bridges traffic from the public internet to Ghost on docker1.

**Steps:**

```bash
# 1. SSH to LXC 201 (Cloudflared host)
ssh root@192.168.0.201

# 2. Edit the cloudflared config
vi /etc/cloudflared/config.yaml

# 3. Find the 'ingress:' section and add this rule BEFORE the catch-all:
#
#   - hostname: layer8.schuettken.net
#     service: http://192.168.0.50:2368

# 4. Save and reload cloudflared
systemctl reload cloudflared

# 5. Verify tunnel is working
curl -s https://layer8.schuettken.net/ | head -10
# Should return Ghost HTML (not timeout/connection error)
```

**Config Template:**
See `/home/hesch/.openclaw/workspace-nb9os/homelab-bootstrap/config/cloudflared-ghost.yml`

### 3. Generate Ghost Admin API Key (Manual - 2 minutes)

**Why:** The marketing agent needs a valid Ghost Admin API key to create and publish posts.

**Steps:**

```bash
# 1. Access Ghost admin in your browser
https://layer8.schuettken.net/ghost/admin

# 2. Complete initial setup if needed:
#    - Email
#    - Password
#    - Site name

# 3. Navigate to Settings → Integrations → Create custom integration
#    - Name: "NB9OS Marketing Agent"
#    - Select all permissions for Admin API

# 4. Copy the generated "Admin API Key" (format: {id}:{secret})

# 5. Store it in your environment or envctl
export GHOST_ADMIN_API_KEY="your_id:your_secret_here"

# Or for docker deployment:
# Add to docker-compose.yml environment variables or .env file
```

### 4. Set Environment Variables

```bash
# In the marketing-agent container or service:

export GHOST_API_URL="https://layer8.schuettken.net"
export GHOST_ADMIN_API_KEY="<from-step-3>"

# Alternative for direct docker1 access:
export GHOST_API_URL="http://192.168.0.50:2368"
```

### 5. Test the Integration

```python
import asyncio
from ghost_client import GhostAdminAPIClient

async def test():
    async with GhostAdminAPIClient() as client:
        # Create a draft
        post = await client.create_post(
            title="Test Post",
            html="<p>This is a test post</p>",
            status="draft"
        )
        print(f"Created post: {post['id']}")
        
        # Publish it
        published = await client.publish_post(post['id'])
        print(f"Published! URL: {published['url']}")

asyncio.run(test())
```

## Architecture

```
NB9OS (FastAPI)
    └─→ POST /api/marketing/drafts/{id}/publish
        └─→ GhostAdminAPIClient (ghost_client.py)
            └─→ Ghost Admin API
                └─→ ghost:6 (docker1:2368)
                    └─→ MariaDB (LXC 221:3306)
```

## API Key Format

Ghost Admin API keys consist of:

```
{id}:{secret}

id:     24-character hex string  (e.g., "bea72072efdc77b3da8f80e8")
secret: 64-character hex string  (e.g., "7a41009e519706a8b36c04c4c781b1ee...")
```

The client uses JWT authentication with the secret to sign each request.

## Common Issues

### Connection Refused on 192.168.0.50:2368

**Symptom:** `curl http://192.168.0.50:2368/` fails with connection refused

**Solution:** Check if Ghost container is running on docker1:
```bash
# On docker1:
docker ps | grep ghost
# Should show the ghost:latest container

# If not running:
cd /path/to/ghost/docker-compose.yml
docker-compose up -d
```

### Timeout on https://layer8.schuettken.net

**Symptom:** Browser hangs or times out when accessing the domain

**Solution:** Cloudflare tunnel is not configured or not running

```bash
# Check tunnel status on LXC 201:
ssh root@192.168.0.201
systemctl status cloudflared
journalctl -u cloudflared -n 50

# Reload if needed:
systemctl reload cloudflared
```

### 401 Unauthorized from Ghost API

**Symptom:** `GhostAdminAPIClient` returns 401 errors

**Possible causes:**
1. API key not set or malformed (must be `{id}:{secret}`)
2. API key not registered in Ghost database
3. Ghost URL is wrong (should be domain for HTTPS, not IP:port)

**Solution:**
```bash
# Verify environment variables
echo $GHOST_ADMIN_API_KEY  # Should be 24:64 format, not empty
echo $GHOST_API_URL         # Should be https://layer8.schuettken.net

# Test with curl (install jq first):
curl -s http://192.168.0.50:2368/ghost/api/admin/site/ \
  -H "Authorization: Ghost <token>" | jq .
```

### Database Connection Error

**Symptom:** Ghost starts but shows database connection error in logs

**Solution:** Verify MariaDB is accessible from docker1

```bash
# From docker1:
mysql -h 192.168.0.75 -u ghost -p -D ghost_layer8

# Should connect without error
# Password: ghost_layer8_2026 (from docker-compose.yml)
```

## Files

| File | Purpose |
|------|---------|
| `ghost_client.py` | GhostAdminAPIClient class for JWT-authenticated API calls |
| `GHOST_SETUP_GUIDE.md` | This file |
| `/homelab-bootstrap/ghost/docker-compose.yml` | Ghost container deployment |
| `/homelab-bootstrap/config/cloudflared-ghost.yml` | Cloudflare tunnel config template |

## Next Steps

1. ✅ Ghost is running on docker1
2. ✅ FastAPI client is ready
3. ⏳ **Configure Cloudflare tunnel** (manual SSH)
4. ⏳ **Generate Ghost Admin API key** (manual browser)
5. ✅ Test publishing via NB9OS

Once steps 3-4 are complete, the publishing pipeline is fully functional!
