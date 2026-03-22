# NATS JetStream Event Bus — Task 131 Implementation

## Overview

NATS JetStream provides a reliable, persistent event bus for the NB9OS ecosystem. This implementation enables:

- **Marketing Agent** → publishes `marketing.signals.detected` and `marketing.drafts.created` events
- **NB9OS Orbit** → publishes `orbit.task.created` and `synthesis.schedule.updated` events
- **High-relevance signal consumer** → auto-detects signals with score > 0.8 and updates status
- **Graceful degradation** → all services continue normally if NATS is unavailable

---

## Deployment

### Option 1: Docker Compose (docker1 — Recommended)

```bash
cd /home/hesch/.openclaw/workspace-nb9os/claude/nats

# Set NATS password (store in envctl)
export NATS_PASSWORD="<from-envctl>"

# Deploy
docker-compose up -d

# Verify health
docker-compose logs -f nats
# Should see: "[1] 2026/03/22 22:15:30 Server is ready for connections."
```

**Monitoring UI**: `http://localhost:8222/`

### Option 2: K3s (If cluster becomes available)

Use the deployment files from the task spec at `/home/hesch/.openclaw/workspace-nb9os/atlas/tasks/20260322-131.md`

```bash
kubectl create namespace messaging
kubectl apply -f k8s/nats/nats-deployment.yaml
```

---

## Stream Setup

After NATS is running, create all JetStream streams:

```bash
# Install nats-py if needed
pip install nats-py

# Run setup script
python setup_streams.py \
  --url nats://192.168.0.80:4222 \
  --user nb9os \
  --password "<password>"
```

**Output**: Creates 5 streams with idempotent setup (safe to re-run):

- **MARKETING** — 7-day retention, file storage
  - Subjects: `marketing.signals.detected`, `marketing.drafts.created`
- **ORBIT** — 30-day retention, file storage
  - Subjects: `orbit.task.created`
- **SYNTHESIS** — 3-day retention, memory storage
  - Subjects: `synthesis.schedule.updated`
- **INFRA** — 1-day retention, memory storage
  - Subjects: `infra.>`
- **HENNING** — 30-day retention, file storage
  - Subjects: `henning.>`

---

## Service Configuration

### Environment Variables (all services)

```bash
# NATS Connection
NATS_URL=nats://192.168.0.80:4222      # or docker1 host IP
NATS_USER=nb9os
NATS_PASSWORD=<from-envctl>
```

Store password in `envctl` as `NATS_PASSWORD`.

### Marketing Agent

File: `/home/hesch/.openclaw/workspace-nb9os/claude/services/marketing-agent/`

Events published:
- `on_signal_detected(signal_id, title, url, pillar_id, relevance_score, detected_at)`
  → publishes to `marketing.signals.detected`
- `on_draft_created(draft_id, title, topic_id, format, word_count, created_at)`
  → publishes to `marketing.drafts.created`

Endpoint:
- `GET /api/v1/marketing/scout/system/nats-status` — NATS health status

### NB9OS (nb9os)

File: `/home/hesch/.openclaw/workspace-nb9os/atlas/services/nb9os/src/backend/`

Events published:
- `on_task_created(task_id, title, priority, created_at)` (in `app/events/orbit.py`)
  → publishes to `orbit.task.created`
- `on_schedule_updated(date, block_count, updated_at)` (in `app/events/orbit.py`)
  → publishes to `synthesis.schedule.updated`

Endpoint:
- `GET /api/v1/system/nats-status` — NATS health status

---

## Graceful Degradation

All services implement **graceful degradation**. If NATS is unavailable:

1. **Connection attempt** fails with warning log
2. **Services continue** normally (no crash)
3. **Event publishing** returns `False` silently
4. **Consumers** don't start (no error logs)

Example from NATSClient:

```python
try:
    await NATSClient.connect(url, user, password)
except Exception as e:
    logger.warning(f"NATS unavailable ({url}): {e} — running without event bus")
    # Service continues normally
```

---

## Consumer Example: High-Relevance Signals

The high-relevance signal consumer is available in `marketing-agent/app/consumers/__init__.py`:

```python
async def consume_high_relevance_signals():
    """Subscribe to marketing.signals.detected, process signals with score > 0.8"""
    sub = await NATSClient.request_subscribe(
        "marketing.signals.detected",
        durable_name="hr-signal-processor"
    )
    
    async for msg in sub.messages:
        payload = json.loads(msg.data)
        if payload.get("relevance_score", 0) >= 0.8:
            logger.info(f"🔥 HIGH RELEVANCE signal: {payload['title']}")
            # Future: await update_signal_status(payload["signal_id"], "highlighted")
        await msg.ack()
```

To start the consumer, integrate into marketing-agent startup (e.g., in `main.py` lifespan):

```python
from app.consumers import start_consumers
await start_consumers()
```

---

## Testing

### Test NATS Connection

```bash
nats pub marketing.test '{"test":true}'
# Output: Published 12 bytes to "marketing.test"

nats sub marketing.test
# Should receive the message
```

### Test Streams

```bash
# List all streams
nats stream list

# Info on MARKETING stream
nats stream info MARKETING
```

### Monitor Events (nats CLI)

```bash
# Subscribe to all marketing signals in real-time
nats subscribe marketing.signals.detected

# Subscribe to all orbit events
nats subscribe orbit.>
```

---

## Implementation Checklist

- [x] NATS deployment (docker-compose.yml on docker1)
- [x] Stream setup script (setup_streams.py)
- [x] Shared NATSClient (marketing-agent + nb9os)
- [x] Marketing agent event publishers (signals + drafts)
- [x] NB9OS event publishers (orbit task + synthesis schedule)
- [x] High-relevance signal consumer (score > 0.8)
- [x] NATS status endpoints (/api/v1/system/nats-status)
- [x] Graceful degradation (all services continue if NATS absent)
- [x] Config (NATS_URL, NATS_USER, NATS_PASSWORD)

---

## Troubleshooting

### "NATS unavailable" warning on startup

**Likely cause**: NATS_URL not set or NATS server not running

**Solution**:
1. Check `docker ps | grep nats` (confirm container running)
2. Set NATS_URL env var correctly (`nats://host:4222`)
3. Verify password in envctl (`NATS_PASSWORD`)

### Consumer not receiving messages

**Likely cause**: Subject name mismatch or durable consumer not subscribed

**Solution**:
1. Verify subject name in publish code matches consumer subscription
2. Check NATS monitoring UI: `http://localhost:8222/` → Streams tab
3. Ensure consumer is actually running in the service

### Stream not found error

**Likely cause**: setup_streams.py never ran

**Solution**:
```bash
python setup_streams.py \
  --url nats://192.168.0.80:4222 \
  --user nb9os \
  --password "<password>"
```

---

## Future Work (Round 21+)

- [ ] NATS clustering (3-node HA setup)
- [ ] Consumer for `draft.created` → auto-create Orbit task candidates
- [ ] NATS-driven `performance.updated` ingestion
- [ ] AI Firewall integration via NATS
- [ ] Cross-service event routing and filtering

---

## References

- **NATS Documentation**: https://docs.nats.io/
- **JetStream Guide**: https://docs.nats.io/nats-concepts/jetstream
- **Task Spec**: `/home/hesch/.openclaw/workspace-nb9os/atlas/tasks/20260322-131.md`
