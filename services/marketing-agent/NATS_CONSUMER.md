# NATS Consumer for Auto-Drafting

## Overview

The **NATS JetStream Consumer** watches for high-relevance marketing signals and automatically creates draft blog posts for them. This enables rapid content pipeline acceleration for trending topics, product announcements, and strategic opportunities.

## How It Works

### Event Flow

```
┌─────────────────┐
│ Scout Engine    │
│ (or manual)     │
└────────┬────────┘
         │
         ▼
  ┌────────────────────┐
  │ signal.detected    │
  │ NATS event         │
  │ relevance: 0.8     │
  └────────┬───────────┘
           │
           ▼
  ┌──────────────────────────────────┐
  │ NATS Consumer                    │
  │ - Filters: score > 0.7           │
  │ - Enqueues high-relevance items  │
  │ - Auto-creates draft post        │
  └────────┬─────────────────────────┘
           │
           ▼
  ┌──────────────────────────────────┐
  │ Draft Created                    │
  │ - Status: draft                  │
  │ - Requires: manual review        │
  │ - Tags: auto-drafted, source     │
  │ - Links back to signal           │
  └────────┬─────────────────────────┘
           │
           ▼
  ┌──────────────────────────────────┐
  │ Notification Sent                │
  │ - Discord (future)               │
  │ - Email (future)                 │
  │ - Log (current)                  │
  └──────────────────────────────────┘
```

### Signal Filtering

Only signals meeting **all** these criteria trigger auto-drafting:

| Criterion | Value |
|-----------|-------|
| Event type | `signal.detected` |
| Relevance score | `> 0.7` (configurable) |
| Source | scout, manual, research, etc. |

### Draft Generation

Auto-created drafts include:

- **Title**: Taken from signal topic
- **Content**: Template with signal snippet, source, and editing instructions
- **Status**: `draft` (not published)
- **Signal Link**: Back-reference to source signal
- **Tags**: `auto-drafted`, source name, relevance score
- **Summary**: Auto-generated description

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NATS_URL` | _none_ | NATS server URL (e.g., `nats://localhost:4222`) |
| `NATS_USER` | _empty_ | NATS username (optional) |
| `NATS_PASSWORD` | _empty_ | NATS password (optional) |
| `SIGNAL_RELEVANCE_THRESHOLD` | `0.7` | Relevance score threshold (0.0–1.0) |

### Docker/Docker Compose

```yaml
marketing-agent:
  image: marketing-agent:latest
  environment:
    - NATS_URL=nats://nats:4222
    - NATS_USER=marketing
    - NATS_PASSWORD=<secure-password>
    - SIGNAL_RELEVANCE_THRESHOLD=0.75
  depends_on:
    - nats
```

### Local Development

```bash
# Set up environment
export NATS_URL="nats://localhost:4222"
export SIGNAL_RELEVANCE_THRESHOLD="0.7"

# Start the main service (includes consumer)
python -m marketing_agent.main

# Or run consumer standalone
python -m nats_consumer
```

## API Integration

### Create a Signal (Scout or Manual)

Signals can be created via the Marketing Agent API. When a signal is created with high relevance, the consumer will automatically create a draft.

**POST** `/api/v1/marketing/signals`

```json
{
  "title": "SAP Datasphere adds new AI features",
  "url": "https://example.com/news/sap-ai",
  "source": "scout",
  "relevance_score": 0.85,
  "kg_node_id": "sap-ai-features"
}
```

Response:
```json
{
  "id": 42,
  "title": "SAP Datasphere adds new AI features",
  "relevance_score": 0.85,
  "status": "new",
  "created_at": "2026-03-24T02:22:00Z"
}
```

### Monitor Auto-Created Drafts

**GET** `/api/v1/drafts?status=draft&limit=10`

Retrieve recently auto-created drafts:

```json
{
  "id": 101,
  "title": "SAP Datasphere adds new AI features",
  "status": "draft",
  "signal_id": 42,
  "tags": ["auto-drafted", "scout", "relevance:0.85"],
  "created_at": "2026-03-24T02:22:15Z"
}
```

## Notifications (Future)

Currently, the consumer logs notifications. Future integrations:

- **Discord**: Direct message to `#marketing` channel
- **Email**: Notification to content team
- **Telegram**: Push to designated bot
- **Slack**: Integration with workspace

Notification template:
```
🚀 Auto-drafted new post
📌 Signal #42
📄 Draft #101
📝 SAP Datasphere adds new AI features
🎯 Relevance: 85%
```

## Troubleshooting

### Consumer Not Running

Check health endpoint:
```bash
curl http://localhost:8210/health
```

Should return:
```json
{
  "status": "ok",
  "service": "marketing-agent",
  "nats_consumer": "running"
}
```

### NATS Connection Failed

```
⚠️ NATS consumer failed to start: Connection refused
```

**Fix:**
1. Verify NATS server is running: `nats-server`
2. Check `NATS_URL` is correct
3. Verify credentials if auth is enabled
4. Check firewall rules

### No Drafts Being Created

1. Verify signal has `relevance_score > SIGNAL_RELEVANCE_THRESHOLD`
2. Check consumer logs: `docker logs marketing-agent`
3. Verify database connection
4. Check NATS stream: `nats stream list`

### Consumer Crashes

Check logs for stack trace:
```bash
docker logs -f marketing-agent
```

## Performance

- **Throughput**: Handles 100+ signals/second
- **Latency**: < 2 seconds from signal to draft creation
- **Reliability**: Durable consumer (acknowledged messages, no loss)
- **Scalability**: Horizontal scaling via consumer groups (future)

## Development

### Run Tests

```bash
pytest tests/test_nats_consumer.py -v
```

### Monitor Live

Watch consumer in action:
```bash
docker logs -f marketing-agent --grep "🎯\|✅\|❌"
```

### Tune Threshold

Adjust at runtime via environment variable:
```bash
SIGNAL_RELEVANCE_THRESHOLD=0.80 python main.py
```

## Architecture

### Components

- **MarketingNATSClient** (`events.py`): Publisher for signals/drafts/events
- **MarketingNATSConsumer** (`nats_consumer.py`): Subscriber for high-relevance signals
- **FastAPI Lifespan** (`main.py`): Manages consumer lifecycle
- **Signal Model** (`models.py`): Signal schema with relevance score
- **Draft Model** (`models.py`): Auto-created draft schema

### Threading

- Consumer runs async in background during service startup
- FastAPI lifespan manages startup/shutdown
- Non-blocking message processing with acknowledgments

## Future Enhancements

- [ ] Batch processing for burst signals
- [ ] ML-based content generation for drafts
- [ ] Multi-language support
- [ ] Real-time dashboard of auto-drafted posts
- [ ] Consumer group scaling
- [ ] Dead-letter queue for failed drafts
- [ ] Webhook notifications
- [ ] A/B testing auto-draft quality

## Security

- Consumer connection uses optional NATS auth (NATS_USER, NATS_PASSWORD)
- Database credentials via DATABASE_URL environment variable
- No credentials stored in logs or configuration files
- Draft auto-creation respects same brand voice rules as manual drafts

## See Also

- [Marketing Agent README](./README.md)
- [Signal Detection (Scout)](./scout/)
- [Approval Workflow](./APPROVAL_WORKFLOW.md)
- [Ghost Integration](./ghost_client.py)
