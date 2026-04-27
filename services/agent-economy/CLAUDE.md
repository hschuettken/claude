# agent-economy — Autonomous Agent Economy

Implements an autonomous agent economy infrastructure for the homelab AI system.
Provides agent registry, task broker, budget governance, reputation scoring, and
self-spawning with approval workflow.

## Architecture

- **Framework**: FastAPI at port 8240
- **Storage**: PostgreSQL (192.168.0.80:5432) — `ae_agents`, `ae_tasks`, `ae_budget_log`, `ae_audit_log`, `ae_spawn_requests`
- **Auth**: Bifrost-style JWT bearer tokens (PyJWT, HS256)
- **Event Bus**: NATS JetStream — emits `task.*` events, subscribes to topic-driven task creation

## Key modules

| Module | Purpose |
|--------|---------|
| `registry.py` | Agent CRUD + TTL expiry + stats |
| `broker.py` | Task lifecycle (created → claimed → completed/failed) + NATS dispatch |
| `budget.py` | Token spend logging + per-agent budget summaries |
| `spawn.py` | Self-spawning requests + auto-approval below threshold + TTL agent creation |
| `auth.py` | JWT issue + decode (Bifrost-style) |
| `main.py` | FastAPI app + NATS subscriptions + Oracle registration |

## Agent types

`main` | `architect` | `dev` | `qa` | `devops` | `team-lead` | `backlog-agent` | `spec-retro` | `custom`

## Task lifecycle

```
created → claimed → completed
                 ↘ failed
```

NATS events emitted at each transition:
- `task.created`, `task.claimed`, `task.completed`, `task.failed`

## Event-driven task creation

Subscribes to these NATS subjects and auto-creates tasks:

| Subject | Task type | Priority |
|---------|-----------|---------|
| `energy.price.spike` | `energy_response` | 4 |
| `travel.intent.detected` | `travel_planning` | 3 |
| `infra.alert.critical` | `infra_remediation` | 5 |

Tasks are auto-dispatched to the highest-reputation capable agent if one is available.

## Reputation scoring

On completion: `new_score = (old_score * n + quality_score) / (n + 1)` (rolling quality average)
On failure: `new_score = old_score * 0.95` (5% decay per failure)

## Self-spawning

1. Agent calls `POST /api/v1/spawn/request` with template_name + purpose + capabilities
2. If active spawned agents < `AGENT_ECONOMY_SPAWN_AUTO_APPROVE_MAX` (default 3): auto-approved
3. Otherwise: stays `pending` until manual approval via `POST /api/v1/spawn/requests/{id}/approve`
4. On approval: agent created with `spawned_by` + `expires_at` (from `ttl_seconds`)
5. Background loop expires TTL agents every 60s

## API endpoints

- `GET /health`
- `POST /api/v1/auth/token` — issue JWT
- **Agents**: POST/GET/PATCH/DELETE `/api/v1/agents`, GET `/api/v1/agents/{id}/stats`
- **Tasks**: POST/GET `/api/v1/tasks`, POST `/api/v1/tasks/{id}/claim|complete|fail`
- **Budget**: POST/GET `/api/v1/budget/log`, GET `/api/v1/budget/summary/{agent_id}`
- **Spawn**: POST `/api/v1/spawn/request`, GET/POST `/api/v1/spawn/requests/{id}/approve|reject`
- `GET /api/v1/dashboard` — aggregated stats

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `AGENT_ECONOMY_DB_URL` | `postgresql://homelab:homelab@192.168.0.80:5432/homelab` | PostgreSQL DSN |
| `NATS_URL` | `nats://192.168.0.50:4222` | NATS server |
| `AGENT_ECONOMY_JWT_SECRET` | `changeme-in-production` | JWT signing secret |
| `AGENT_ECONOMY_JWT_EXPIRE_HOURS` | `24` | Token validity |
| `AGENT_ECONOMY_RATE_LIMIT_RPM` | `120` | Rate limit (req/min per agent) |
| `AGENT_ECONOMY_SPAWN_AUTO_APPROVE_MAX` | `3` | Max auto-approved spawned agents |
| `AGENT_ECONOMY_PORT` | `8240` | Service port |

## Testing

```bash
cd services/agent-economy
python -m pytest tests/ -v
```

Tests run without a real database (graceful no-op when pool is None).
