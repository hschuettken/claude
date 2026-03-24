# HEMS — Home Energy Management System

FastAPI service that orchestrates home energy: EV charging, boiler scheduling, PV-aware load shifting.

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Healthcheck — returns `{"status": "ok"}` |
| GET | `/api/v1/hems/status` | Service status, uptime, current mode |
| GET | `/api/v1/hems/schedule` | List all energy schedules |
| POST | `/api/v1/hems/schedule` | Create a new energy schedule |
| GET | `/api/v1/hems/mode` | Get current HEMS mode |
| POST | `/api/v1/hems/mode` | Set HEMS mode (auto/manual/off) |

## Port
**8210**

## Configuration
See [ENVCTL.md](./ENVCTL.md) for all config keys.

## Database
Run migration: `psql $HEMS_DB_URL -f migrations/001_hems_schema.sql`

Tables:
- `hems.schedules` — energy dispatch entries
- `hems.config` — runtime key-value config
- `hems.audit_log` — immutable event log

## InfluxDB
Create the `hems` telemetry bucket:
```bash
INFLUXDB_TOKEN=<token> bash scripts/setup_influxdb_bucket.sh
```

## Development
```bash
cd services/hems
HEMS_DATA_DIR=/tmp/hems HEMS_MODE=auto uvicorn main:create_app --factory --port 8210 --reload
```
