# HEMS — envctl Configuration Keys

Manage via envctl: `GET/PUT http://192.168.0.50:8201/config/{KEY}` with `X-API-Key: super_secure_api_key`

| Key | Default | Description |
|-----|---------|-------------|
| `HEMS_MODE` | `auto` | Operating mode: `auto` \| `manual` \| `off` |
| `HEMS_ORCHESTRATOR_URL` | `http://orchestrator:8000` | Internal URL of the Orchestrator service |
| `HEMS_HA_TOKEN` | _(empty)_ | Home Assistant long-lived access token |
| `HEMS_DB_URL` | `postgresql://homelab:homelab@192.168.0.80:5432/homelab` | PostgreSQL connection string |

## Set via envctl (examples)

```bash
# Set mode to manual
curl -X PUT http://192.168.0.50:8201/config/HEMS_MODE \
  -H "X-API-Key: super_secure_api_key" \
  -H "Content-Type: application/json" \
  -d '"manual"'

# Set HA token
curl -X PUT http://192.168.0.50:8201/config/HEMS_HA_TOKEN \
  -H "X-API-Key: super_secure_api_key" \
  -H "Content-Type: application/json" \
  -d '"<your-ha-token>"'
```

## Modes

| Mode | Behaviour |
|------|-----------|
| `auto` | HEMS autonomously optimises energy use based on schedules, PV forecast, and prices |
| `manual` | Schedules are respected as-is; no autonomous optimisation |
| `off` | All scheduling disabled; HEMS remains up for status queries only |
