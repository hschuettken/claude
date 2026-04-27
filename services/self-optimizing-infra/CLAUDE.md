# self-optimizing-infra — Self-Optimizing Infrastructure

Monitors the entire homelab infrastructure across three layers (L0/L1/L2),
automatically detects and remediates issues using a rule-based decision engine,
generates monthly resource optimization proposals, and runs scheduled chaos
resilience experiments.

## Architecture

- **Framework**: FastAPI at port 8242
- **Storage**: PostgreSQL (192.168.0.80:5432) — decision rules, decisions, proposals, chaos runs
- **Event Bus**: NATS JetStream — subscribes `heartbeat.>` (L0), publishes alerts
- **Integrations**: Proxmox API, Bootstrap bridge REST, K3s API, ops-bridge

## Key modules

| Module | Purpose |
|--------|---------|
| `monitors.py` | L0 (NATS heartbeats), L1 (Proxmox/Bootstrap/K3s polling), L2 snapshot |
| `decision_engine.py` | Rule CRUD, condition evaluation, auto-approve execution |
| `evolution.py` | Monthly utilization analysis + optimization proposal generation |
| `chaos.py` | Chaos experiment runner (service_kill, latency_injection, node_failure) |
| `main.py` | FastAPI app + background loops + NATS + Oracle registration |
| `models.py` | Pydantic models |
| `db.py` | asyncpg pool + graceful no-op when DB unavailable |
| `config.py` | Settings from env vars |

## Monitoring layers

| Layer | What it tracks | How |
|-------|---------------|-----|
| L0 | Homelab service agent health | NATS `heartbeat.*` subscriptions |
| L1 | Infra nodes (Proxmox VMs, Bootstrap nodes, K3s nodes) | REST polling every 2 minutes |
| L2 | Aggregate infra state for decision engine | Computed on-demand from L0+L1 |

## Decision Engine (Phase 1)

Rule evaluation runs every 60 seconds. Conditions: `heartbeat_missing`, `cpu_high`,
`mem_high`, `node_down`. Actions: `restart_service`, `alert_telegram`, `create_task`,
`reboot_node`.

**Auto-approve policy:**
- `low` risk → auto-approved and executed immediately
- `medium` risk → auto-approved but held 10 minutes (human can reject within window)
- `high` risk → requires explicit `POST /api/v1/decisions/{id}/approve`

5 default rules are seeded on first start.

## Infra Evolution (Phase 2)

Monthly analysis runs on day 1 of each month at 04:00 UTC. Analyzes service uptime
and node utilization trends, generates proposals (scale_cpu, scale_memory,
expand_storage, improve_reliability, decommission_node). Proposals are persisted and
reviewed via REST API.

## Chaos Testing (Phase 3)

Weekly chaos sweep runs Sunday 03:00 UTC (when `SOI_CHAOS_ENABLED=true`). Kills up to
30% of services, measures recovery time, computes resilience score. In default mode
(`chaos_enabled=false`) experiments are simulated without actual service disruption.

## Database tables

| Table | Purpose |
|-------|---------|
| `soi_service_health` | L0 service health snapshots |
| `soi_decision_rules` | Decision engine rules |
| `soi_decisions` | Decision history + execution status |
| `soi_evolution_proposals` | Infra optimization proposals |
| `soi_chaos_runs` | Chaos experiment results |

## NATS subjects

| Subject | Direction | Purpose |
|---------|-----------|---------|
| `heartbeat.>` | subscribe | L0 service health tracking |
| `infra.alert.critical` | publish | High-risk decision triggered |
| `infra.decision.created` | publish | New decision record |

## API endpoints

- `GET /health`
- `GET /api/v1/monitors/services` — L0 service health
- `GET /api/v1/monitors/nodes` — L1 node health
- `GET /api/v1/monitors/snapshot` — L2 unified snapshot
- `POST /api/v1/monitors/poll` — Trigger L1 poll
- `GET /api/v1/decisions/rules` — List decision rules
- `POST /api/v1/decisions/rules` — Create rule
- `GET|POST /api/v1/decisions/rules/{id}/enable|disable`
- `GET /api/v1/decisions` — List decisions (filter by status)
- `POST /api/v1/decisions/{id}/approve|reject`
- `POST /api/v1/decisions/evaluate` — Trigger evaluation cycle
- `GET /api/v1/evolution/proposals` — List proposals
- `POST /api/v1/evolution/proposals/{id}/approve|reject|implement`
- `POST /api/v1/evolution/analyze` — Trigger analysis
- `GET /api/v1/evolution/report` — Full evolution report
- `GET /api/v1/chaos/runs` — List chaos runs
- `POST /api/v1/chaos/runs` — Start experiment
- `POST /api/v1/chaos/sweep` — Trigger full sweep
- `GET /api/v1/chaos/resilience-report` — Resilience report
- `GET /api/v1/dashboard` — Aggregated stats

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `SOI_DB_URL` | `postgresql://homelab:homelab@192.168.0.80:5432/homelab` | PostgreSQL DSN |
| `NATS_URL` | `nats://192.168.0.50:4222` | NATS server |
| `ORACLE_URL` | `http://192.168.0.50:8225` | Integration Oracle |
| `SOI_PORT` | `8242` | Service port |
| `PROXMOX_URL` | `https://192.168.0.10:8006` | Proxmox API URL |
| `PROXMOX_TOKEN_ID` | — | Proxmox API token (user@pam!token-name) |
| `PROXMOX_TOKEN_SECRET` | — | Proxmox API token secret |
| `PROXMOX_VERIFY_SSL` | `false` | Verify Proxmox TLS cert |
| `BOOTSTRAP_URL` | `http://192.168.0.50:8235` | Bootstrap bridge REST API |
| `OPS_BRIDGE_URL` | `http://192.168.0.50:8220` | Ops-bridge for service control |
| `OPS_BRIDGE_TOKEN` | — | Ops-bridge auth token |
| `K3S_API_URL` | `https://192.168.0.60:6443` | K3s API server |
| `K3S_TOKEN` | — | K3s bearer token |
| `SOI_HEARTBEAT_TIMEOUT_S` | `300` | Seconds before service marked offline |
| `SOI_DECISION_LOOP_S` | `60` | Decision evaluation interval (seconds) |
| `SOI_L1_POLL_S` | `120` | L1 poll interval (seconds) |
| `SOI_EVOLUTION_DAY` | `1` | Day of month for evolution analysis |
| `SOI_CHAOS_ENABLED` | `false` | Enable real service disruption in chaos tests |
| `SOI_CHAOS_CRON` | `0 3 * * 0` | Chaos sweep schedule (cron-style) |
| `SOI_CHAOS_MAX_KILL_FRACTION` | `0.3` | Max fraction of services to kill in sweep |

## Testing

```bash
cd services/self-optimizing-infra
python -m pytest tests/ -v
```

Tests run without a real database or NATS connection.
