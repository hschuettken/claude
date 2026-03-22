# HEMS Phase 2 API Integration Guide

This guide shows how to integrate the new `api.py` Phase 2 endpoints into the main HEMS FastAPI application.

## Quick Start

### 1. Update main.py

In `main.py`, import and register the API router:

```python
from api import router as api_router

# In the app creation section:
app = FastAPI(
    title="HEMS",
    description="Home Energy Management System",
    version="2.0",
)

# Include both routers (existing routes + new API endpoints)
app.include_router(router)  # Existing routes from routes.py
app.include_router(api_router)  # Phase 2 API endpoints from api.py
```

### 2. Update requirements.txt

The new API endpoints require no additional dependencies beyond what's already in `requirements.txt`. Verify these are present:

```
fastapi>=0.115.0,<1.0
influxdb-client>=1.40.0,<2.0
asyncpg>=0.29.0,<1.0
httpx>=0.27.0,<1.0
```

### 3. Startup & Shutdown Integration (Optional)

If you need to initialize InfluxDB and PostgreSQL connections as FastAPI dependencies, add middleware in `main.py`:

```python
from contextlib import asynccontextmanager
from fastapi import Depends, Request
import influxdb_client
from influxdb_client.client.query_api import QueryApi
from database import HEMSDatabase

# Global instances
influx_client: Optional[influxdb_client.InfluxDBClient] = None
query_api: Optional[QueryApi] = None
db: Optional[HEMSDatabase] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup and shutdown."""
    global influx_client, query_api, db
    
    # Startup
    settings = HEMSSettings()
    
    # Initialize InfluxDB
    influx_client = influxdb_client.InfluxDBClient(
        url=settings.influxdb_url,
        token=settings.influxdb_token,
        org=settings.influxdb_org,
    )
    query_api = influx_client.query_api()
    
    # Initialize PostgreSQL
    db = HEMSDatabase(settings.hems_db_url)
    await db.init()
    
    logger.info("HEMS Phase 2 API initialized")
    
    yield
    
    # Shutdown
    if db:
        await db.close()
    if influx_client:
        influx_client.close()
    logger.info("HEMS Phase 2 API shutdown")

app = FastAPI(lifespan=lifespan, ...)
```

### 4. Dependency Injection (Optional)

To pass InfluxDB and PostgreSQL to API endpoints, add dependency resolvers:

```python
async def get_query_api() -> QueryApi:
    """Get InfluxDB QueryApi instance."""
    return query_api

async def get_db_pool() -> asyncpg.Pool:
    """Get PostgreSQL connection pool."""
    return db.pool if db else None

# Now endpoints can declare dependencies:
@router.get("/api/energy")
async def get_energy(
    period: str = "day",
    query_api: QueryApi = Depends(get_query_api),
) -> EnergyResponse:
    ...
```

## Endpoint Paths

After integration, the following endpoints will be available:

| Method | Path | Handler |
|--------|------|---------|
| GET | `/api/energy` | `get_energy()` |
| GET | `/api/analytics/{period}` | `get_analytics()` |
| GET | `/api/model/status` | `get_model_status()` |
| POST | `/api/model/retrain` | `retrain_model()` |
| GET | `/api/boiler` | `get_boiler_state()` |
| GET | `/api/decisions/latest` | `get_latest_decisions()` |
| POST | `/api/override/flow_temp` | `override_flow_temp()` |

## Testing After Integration

### 1. Run Unit Tests

```bash
cd /home/hesch/.openclaw/workspace-nb9os/claude/services/hems
pytest test_api.py -v
```

Expected output:
```
test_api.py::TestEnergyEndpoint::test_energy_day_period PASSED
test_api.py::TestEnergyEndpoint::test_energy_hour_period PASSED
...
test_api.py::TestIntegration::test_all_endpoints_available PASSED
======================== 60+ passed in 2.34s ========================
```

### 2. Start the Service

```bash
# With Docker
docker-compose up hems

# Or locally
cd /home/hesch/.openclaw/workspace-nb9os/claude/services/hems
uvicorn main:app --host 0.0.0.0 --port 8210 --reload
```

### 3. Test Endpoints

Using curl:

```bash
# GET /api/energy
curl http://localhost:8210/api/energy?period=day

# GET /api/analytics/day
curl http://localhost:8210/api/analytics/day

# GET /api/model/status
curl http://localhost:8210/api/model/status

# POST /api/model/retrain
curl -X POST http://localhost:8210/api/model/retrain \
  -H "Content-Type: application/json" \
  -d '{"epochs": 100, "batch_size": 32}'

# GET /api/boiler
curl http://localhost:8210/api/boiler

# GET /api/decisions/latest
curl http://localhost:8210/api/decisions/latest?limit=10

# POST /api/override/flow_temp
curl -X POST http://localhost:8210/api/override/flow_temp \
  -H "Content-Type: application/json" \
  -d '{
    "flow_temp_c": 55.0,
    "duration_minutes": 30,
    "reason": "User manual test"
  }'
```

### 4. Check API Documentation

FastAPI auto-generates interactive API docs:
- **Swagger UI**: http://localhost:8210/docs
- **ReDoc**: http://localhost:8210/redoc

## Current Status & TODO

### ✅ Completed
- [x] All 7 endpoints implemented with full Pydantic models
- [x] Comprehensive unit tests (60+ test cases)
- [x] API documentation (API.md)
- [x] Synthetic demo data (no external dependencies required)
- [x] Async design with error handling
- [x] Input validation (bounds, types, enums)
- [x] ISO-8601 timestamps on all responses
- [x] Proper HTTP status codes (200, 400, 422, 500, 503)

### 🔄 In Progress (Production Ready)
When ready to connect to real databases:

1. **InfluxDB Integration** (Endpoint 1, 2, 5)
   - Implement InfluxDB Flux queries in `get_energy()`, `get_analytics()`, `get_boiler_state()`
   - Use provided `query_influxdb()` helper function
   - Example: Query `energy.boiler` measurement for period

2. **PostgreSQL Integration** (Endpoint 3, 4, 6, 7)
   - Create database tables (schema in API.md)
   - Implement queries in endpoints using `query_postgres()` helper
   - Create background worker for async retraining jobs

3. **Real NN Model Integration** (Endpoint 3, 4)
   - Load pre-trained model from disk
   - Implement inference in boiler controller
   - Implement retraining worker with PyTorch/TensorFlow

### 📋 Future Endpoints
- `GET /api/model/job/{job_id}` — Poll retraining job status
- `DELETE /api/override/{override_id}` — Revoke override
- `WebSocket /ws/live/boiler` — Real-time state stream
- `GET /api/energy/forecast` — Energy forecast

## Configuration

The API respects these environment variables (from `config.py`):

```bash
# InfluxDB
INFLUXDB_URL=http://192.168.0.50:8086
INFLUXDB_TOKEN=your-token-here
INFLUXDB_ORG=homelab
INFLUXDB_BUCKET=hems

# PostgreSQL
HEMS_DB_URL=postgresql://homelab:password@192.168.0.80:5432/homelab

# API
API_HOST=0.0.0.0
API_PORT=8210
```

## Architecture

```
┌─────────────────────────────────────────┐
│         FastAPI Application             │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────────────────────────┐  │
│  │     /api/* endpoints (api.py)    │  │
│  │  - /api/energy                   │  │
│  │  - /api/analytics/{period}       │  │
│  │  - /api/model/status             │  │
│  │  - /api/model/retrain            │  │
│  │  - /api/boiler                   │  │
│  │  - /api/decisions/latest         │  │
│  │  - /api/override/flow_temp       │  │
│  └──────────────────────────────────┘  │
│            ↓         ↓                   │
│  ┌──────────────────────────────────┐  │
│  │  Existing /api/v1/* routes       │  │
│  │  (routes.py)                     │  │
│  └──────────────────────────────────┘  │
│                                         │
└──────────┬──────────────────┬───────────┘
           │                  │
     ┌─────▼──────┐    ┌──────▼─────┐
     │ InfluxDB   │    │ PostgreSQL  │
     │ (Time-series   │ (Config,    │
     │  Energy,       │  Decisions, │
     │  Thermal)      │  Overrides) │
     └────────────┘    └─────────────┘
```

## Monitoring & Debugging

### Check API Health

```bash
curl http://localhost:8210/health
```

### View Logs

```bash
# Docker
docker logs hems

# Local
# Logs written to stdout with timestamps and log levels
```

### Debug a Specific Endpoint

```bash
# Enable verbose logging in api.py
import logging
logging.basicConfig(level=logging.DEBUG)

# Then test endpoint
curl http://localhost:8210/api/boiler -v
```

## Common Issues

### 1. "Database pool not initialized"
**Cause**: PostgreSQL connection not established at startup.
**Solution**: Ensure `HEMSDatabase.init()` is called in app startup handler.

### 2. "InfluxDB query failed"
**Cause**: InfluxDB unreachable or token invalid.
**Solution**: Check `INFLUXDB_URL` and `INFLUXDB_TOKEN` environment variables.

### 3. Endpoints return synthetic data
**Expected behavior** in demo mode. To use real data:
1. Ensure InfluxDB and PostgreSQL are running
2. Create required tables (schema in API.md)
3. Uncomment real queries in endpoints (marked with "In production:")
4. Test with `pytest test_api.py` first

### 4. POST /api/model/retrain always returns 200
**Expected behavior** — endpoint validates input and queues job. 
To check job status, implement `GET /api/model/job/{job_id}` endpoint.

## Next Steps

1. **Integrate with InfluxDB** → Uncomment Flux queries in endpoints
2. **Integrate with PostgreSQL** → Create schema, uncomment SQL queries
3. **Implement retraining worker** → Background task that trains NN model
4. **Add authentication** → Require API token in Authorization header
5. **Add rate limiting** → Middleware to prevent abuse
6. **Monitor in production** → Set up alerting for failed queries

---

**For detailed API documentation, see `API.md`**

**For test examples, see `test_api.py`**
