# Marketing Agent & Ghost Integration Tests

This document outlines the integration tests for the Ghost publishing pipeline.

## Test Environment Setup

### Prerequisites
- Marketing agent service running on port 8210
- Ghost service running on docker1:2368 (or GHOST_URL env var)
- PostgreSQL database accessible with schema.marketing tables
- Ghost Admin API key configured in .env

### Service Health Check

```bash
# Test marketing-agent health
curl -s http://localhost:8210/health | jq .

# Expected output:
# {
#   "status": "ok",
#   "service": "marketing-agent",
#   "version": "0.1.0"
# }
```

## Integration Test Scenarios

### Test 1: Draft Creation (No Ghost Dependency)

**Objective**: Create a marketing draft and verify it's stored in the database

```bash
DRAFT_ID=$(curl -s -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Test: Cloud Architecture Patterns",
    "content": "<h2>Introduction</h2><p>This post explores modern cloud patterns.</p>",
    "summary": "Cloud architecture patterns for enterprise",
    "tags": ["Architecture", "Cloud", "SAP"],
    "seo_title": "Cloud Architecture Patterns Guide",
    "seo_description": "Learn modern cloud architecture patterns"
  }' | jq -r '.id')

echo "Created draft with ID: $DRAFT_ID"
```

**Expected Results**:
- HTTP 200 response
- Returned JSON includes `id`, `title`, `status: "draft"`, `platform: "blog"`
- Draft status in database: `SELECT * FROM marketing.drafts WHERE id = $DRAFT_ID;`

### Test 2: Draft Retrieval

**Objective**: Fetch the created draft and verify all fields

```bash
curl -s http://localhost:8210/api/v1/drafts/$DRAFT_ID | jq .

# Verify:
# - title matches input
# - content matches input
# - status == "draft"
# - tags array is correct
# - seo_title and seo_description are set
```

### Test 3: Draft Status Update to Approved

**Objective**: Update draft status from `draft` → `approved` (simulating AI review)

```bash
curl -s -X PUT http://localhost:8210/api/v1/drafts/$DRAFT_ID \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}' | jq .

# Verify status field in response shows "approved"
```

**Expected Results**:
- HTTP 200 response
- `status` field updated to "approved"
- `updated_at` timestamp changed

### Test 4: Publish to Ghost (Requires Ghost Service)

**Objective**: Publish the approved draft to Ghost CMS

```bash
PUBLISH_RESPONSE=$(curl -s -X POST http://localhost:8210/api/v1/drafts/$DRAFT_ID/publish \
  -H "Content-Type: application/json" \
  -d '{}')

echo "$PUBLISH_RESPONSE" | jq .

# Extract results
GHOST_POST_ID=$(echo "$PUBLISH_RESPONSE" | jq -r '.ghost_post_id')
GHOST_URL=$(echo "$PUBLISH_RESPONSE" | jq -r '.ghost_url')
SLUG=$(echo "$PUBLISH_RESPONSE" | jq -r '.slug')

echo "Ghost Post ID: $GHOST_POST_ID"
echo "Ghost URL: $GHOST_URL"
echo "Slug: $SLUG"
```

**Expected Results**:
- HTTP 200 response
- `status: "ok"`
- `ghost_post_id` returned (24-char hex string)
- `ghost_url` contains domain + slug
- `slug` generated from title
- `published_at` timestamp set

**Database Verification**:
```sql
-- Check draft updated
SELECT id, status, ghost_post_id, ghost_url, published_at 
FROM marketing.drafts 
WHERE id = <$DRAFT_ID>;

-- Check blog_posts record created
SELECT * FROM marketing.blog_posts 
WHERE draft_id = <$DRAFT_ID>;
```

### Test 5: Verify Post in Ghost Admin

**Objective**: Confirm post appears in Ghost Admin and is publicly accessible

```bash
# 1. Check Ghost API directly
curl -s -H "Authorization: Ghost $GHOST_ADMIN_API_KEY" \
  "https://layer8.schuettken.net/ghost/api/v3/admin/posts/?limit=1" | jq '.posts[0]'

# 2. Visit Ghost Admin
# https://layer8.schuettken.net/ghost/editor/posts/

# 3. Visit public post
curl -s "https://layer8.schuettken.net/$SLUG/" | grep -o "<title>.*</title>"
```

**Expected Results**:
- Ghost API returns the post with matching title
- Post visible in Ghost Admin Posts list
- Public URL accessible with HTTP 200
- Post title appears in page `<title>`

### Test 6: Schedule Publication

**Objective**: Schedule a draft for future publication

```bash
# Create another draft
DRAFT_ID_2=$(curl -s -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Scheduled: Future Content",
    "content": "<p>This will be published tomorrow</p>",
    "tags": ["Future"],
    "status": "approved"
  }' | jq -r '.id')

# Schedule for tomorrow
TOMORROW=$(date -u -d "+1 day" +%Y-%m-%dT%H:%M:%SZ)

curl -s -X POST http://localhost:8210/api/v1/drafts/$DRAFT_ID_2/schedule \
  -H "Content-Type: application/json" \
  -d "{\"publish_at\": \"$TOMORROW\"}" | jq .
```

**Expected Results**:
- HTTP 200 response
- `status: "scheduled"`
- Post appears in Ghost with status "scheduled"
- Post will auto-publish at scheduled time

### Test 7: Draft Listing with Filters

**Objective**: List drafts with various filters

```bash
# List all drafts
curl -s "http://localhost:8210/api/v1/drafts" | jq '.count, (.drafts | length)'

# Filter by status
curl -s "http://localhost:8210/api/v1/drafts?status=published" | jq '.drafts'

# Filter by tag
curl -s "http://localhost:8210/api/v1/drafts?tags=Architecture" | jq '.drafts'

# Pagination
curl -s "http://localhost:8210/api/v1/drafts?skip=0&limit=5" | jq '.drafts | length'
```

**Expected Results**:
- List endpoints return arrays of drafts
- Filters reduce results appropriately
- Pagination limits results correctly

### Test 8: Error Scenarios

**Objective**: Verify proper error handling

#### 8a: Publish Non-Existent Draft

```bash
curl -s -X POST http://localhost:8210/api/v1/drafts/99999/publish \
  -H "Content-Type: application/json" \
  -d '{}'

# Expected: HTTP 404, {"detail": "Draft 99999 not found"}
```

#### 8b: Publish Unapproved Draft

```bash
# Create draft (status = "draft")
DRAFT_ID_3=$(curl -s -X POST http://localhost:8210/api/v1/drafts \
  -H "Content-Type: application/json" \
  -d '{"title": "Test", "content": "<p>Test</p>"}' | jq -r '.id')

# Try to publish without approving
curl -s -X POST http://localhost:8210/api/v1/drafts/$DRAFT_ID_3/publish \
  -H "Content-Type: application/json" \
  -d '{}'

# Expected: HTTP 400, error about draft not approved
```

#### 8c: Invalid Ghost API Key

```bash
# Set invalid key
export GHOST_ADMIN_API_KEY="invalid:key123"

# Try to publish
curl -s -X POST http://localhost:8210/api/v1/drafts/$DRAFT_ID/publish

# Expected: HTTP 500 with Ghost API error
```

### Test 9: Knowledge Graph Integration (Optional)

**Objective**: Verify KG context injection in draft responses

```bash
curl -s http://localhost:8210/api/v1/drafts/$DRAFT_ID | jq '.kg_context'

# Expected: Object with:
# {
#   "published_posts": [...],
#   "active_projects": [...],
#   "pillar_stats": {...}
# }
```

### Test 10: NATS Event Publishing (Optional)

**Objective**: Verify NATS events are published

```bash
# Subscribe to NATS (requires nats-cli)
nats sub --server=nats://localhost:4222 "post.published"

# Publish a draft (in another terminal)
curl -s -X POST http://localhost:8210/api/v1/drafts/$DRAFT_ID/publish

# Should see event: post.published with draft_id, ghost_id, ghost_url
```

## Automated Test Script

Here's a bash script to run all tests:

```bash
#!/bin/bash

set -e

MARKETING_URL="http://localhost:8210"
GHOST_URL="https://layer8.schuettken.net"

echo "🧪 Running Marketing Agent Integration Tests"
echo ""

# Test 1: Health Check
echo "Test 1: Health Check"
curl -s "$MARKETING_URL/health" | jq .
echo ""

# Test 2: Create Draft
echo "Test 2: Create Draft"
DRAFT=$(curl -s -X POST "$MARKETING_URL/api/v1/drafts" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Integration Test Post",
    "content": "<p>Test content</p>",
    "tags": ["test"]
  }')
DRAFT_ID=$(echo "$DRAFT" | jq -r '.id')
echo "Created draft: $DRAFT_ID"
echo ""

# Test 3: Update to Approved
echo "Test 3: Approve Draft"
curl -s -X PUT "$MARKETING_URL/api/v1/drafts/$DRAFT_ID" \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}' | jq '.status'
echo ""

# Test 4: Publish to Ghost
echo "Test 4: Publish to Ghost"
PUBLISH=$(curl -s -X POST "$MARKETING_URL/api/v1/drafts/$DRAFT_ID/publish" \
  -H "Content-Type: application/json" \
  -d '{}')
GHOST_URL=$(echo "$PUBLISH" | jq -r '.ghost_url')
echo "Published to: $GHOST_URL"
echo ""

# Test 5: Verify Public Access
echo "Test 5: Verify Public Access"
if curl -s "$GHOST_URL" | grep -q "Integration Test Post"; then
    echo "✅ Post is publicly accessible"
else
    echo "❌ Post not found at public URL"
fi
echo ""

echo "✅ All integration tests completed"
```

Save as `test_integration.sh` and run:

```bash
bash test_integration.sh
```

## Troubleshooting Integration Tests

### Connection Refused

```bash
# Check marketing-agent service
docker ps | grep marketing-agent

# Check service logs
docker logs marketing-agent

# Verify port is open
netstat -tuln | grep 8210
```

### Ghost API Errors

```bash
# Verify Ghost API key
echo $GHOST_ADMIN_API_KEY

# Test Ghost API directly
curl -X GET "https://layer8.schuettken.net/ghost/api/v3/admin/posts/" \
  -H "Authorization: Ghost $GHOST_ADMIN_API_KEY"

# Check Ghost logs
docker logs ghost
```

### Database Errors

```bash
# Test database connection
psql postgresql://homelab:homelab@192.168.0.80:5432/homelab \
  -c "SELECT COUNT(*) FROM marketing.drafts;"

# Check database tables
psql postgresql://homelab:homelab@192.168.0.80:5432/homelab \
  -c "\dt marketing.*"
```

## Performance Benchmarks

### Expected Response Times

- Create Draft: < 200ms
- Publish to Ghost: 500ms - 2s (depends on Ghost API)
- List Drafts: < 100ms
- Get Single Draft: < 50ms

### Load Testing

For basic load testing:

```bash
# Install Apache Bench
apt-get install apache2-utils

# Test draft creation
ab -n 100 -c 10 -p draft.json -T application/json http://localhost:8210/api/v1/drafts

# Test list endpoint
ab -n 1000 -c 50 http://localhost:8210/api/v1/drafts
```

## Acceptance Criteria

All the following must pass for Task 97 (Ghost Deployment) to be complete:

- [ ] `curl http://localhost:8210/health` returns 200 OK
- [ ] Create draft endpoint works and stores in DB
- [ ] Publish endpoint requires "approved" status
- [ ] Published posts appear in Ghost Admin
- [ ] Published posts are publicly accessible
- [ ] Ghost URL returned in publish response
- [ ] No import/compile errors
- [ ] All error cases return appropriate HTTP status codes
- [ ] Database relationships (drafts → blog_posts) work correctly
- [ ] NATS events published (if NATS_URL configured)

## Next Steps After Integration Tests

1. **QA Verification** — Run full test suite with QA agent
2. **Frontend Testing** — Test NB9OS publish button integration
3. **Performance Testing** — Load test and optimization
4. **Monitoring Setup** — Health checks and alerting
5. **Production Deployment** — Deploy to live environment
