# HEMS Phase 2 Internal API Documentation

## Overview

The HEMS Phase 2 internal API (`api.py`) provides 7 advanced endpoints for energy analytics, thermal monitoring, neural network management, and manual control overrides.

All endpoints are async, return ISO-8601 timestamps, and are designed to integrate with InfluxDB (time-series data) and PostgreSQL (control decisions, model metadata).

---

## Endpoints

### 1. GET `/api/energy` — Energy Consumption Analytics

**Summary:** Fetch total energy consumed and breakdown by source (boiler, pump, PV, supplemental heat).

**Query Parameters:**
- `period` (string, default: "day"): `hour`, `day`, or `month`

**Response (200 OK):**
```json
{
  "total_consumed_kwh": 18.2,
  "period": "day",
  "period_start": "2026-03-21T09:38:00+00:00",
  "period_end": "2026-03-22T09:38:00+00:00",
  "breakdown": {
    "boiler": 15.4,
    "circulation_pump": 2.8,
    "supplemental_heat": 0.0,
    "pv_exported": 8.2,
    "pv_used": 12.6
  },
  "timestamp": "2026-03-22T09:38:00+00:00"
}
```

**Error Responses:**
- `400 Bad Request`: Invalid period (must be hour/day/month)
- `503 Service Unavailable`: InfluxDB connection failed

**Implementation Notes:**
- Queries InfluxDB `hems` bucket for measurements: `energy.boiler`, `energy.pump`, `energy.supplemental`, `energy.pv_exported`, `energy.pv_used`
- Time windows: hour=60m, day=24h, month=30d
- Currently returns synthetic demo data; production queries InfluxDB Flux API

---

### 2. GET `/api/analytics/{period}` — Thermal System Analytics

**Summary:** Fetch thermal statistics (room temperature, setpoint, boiler runtime, PV utilization).

**Path Parameters:**
- `period` (string): `hour`, `day`, `week`, or `month`

**Response (200 OK):**
```json
{
  "period": "day",
  "period_start": "2026-03-21T09:38:00+00:00",
  "period_end": "2026-03-22T09:38:00+00:00",
  "thermal_stats": {
    "avg_room_temp_c": 21.2,
    "current_room_temp_c": 21.5,
    "avg_setpoint_c": 21.0,
    "boiler_runtime_minutes": 45.0,
    "boiler_on_duty_cycle": 3.1,
    "pv_utilization_percent": 68.5,
    "mixing_valve_avg_position": 65.0
  },
  "timestamp": "2026-03-22T09:38:00+00:00"
}
```

**Error Responses:**
- `400 Bad Request`: Invalid period (must be hour/day/week/month)
- `503 Service Unavailable`: InfluxDB connection failed

**Implementation Notes:**
- Aggregates from InfluxDB: `thermal.room_temp`, `thermal.setpoint`, `thermal.boiler_runtime`, `thermal.mixing_valve_position`, `energy.pv_utilization`
- Duty cycle = (boiler_runtime_minutes / period_minutes) * 100
- Currently returns synthetic demo data; production queries InfluxDB for time-series aggregation

---

### 3. GET `/api/model/status` — Neural Network Model Status

**Summary:** Check NN model readiness, training progress, and accuracy metrics.

**Response (200 OK):**
```json
{
  "status": "ready",
  "model_id": "hems-thermal-v2",
  "last_trained": "2026-03-22T03:38:00+00:00",
  "training_loss": 0.012,
  "accuracy": 0.945,
  "retraining_progress": null,
  "timestamp": "2026-03-22T09:38:00+00:00"
}
```

**Possible Status Values:**
- `idle`: Model ready, no active training
- `training`: Initial training in progress
- `retraining`: Retraining (from POST /api/model/retrain) in progress
- `ready`: Model trained and ready for inference
- `error`: Training/inference error occurred

**Fields:**
- `retraining_progress`: Float 0-1, only present if `status == "retraining"`
- `training_loss`: Last training loss (may be None)
- `accuracy`: Model accuracy 0-1 (may be None)

**Error Responses:**
- `500 Internal Server Error`: Database query failed
- `503 Service Unavailable`: PostgreSQL connection failed

**Implementation Notes:**
- Queries PostgreSQL `hems.model_metadata` table for status, loss, accuracy
- Currently returns synthetic data; production queries: `SELECT * FROM hems.model_metadata WHERE id = 'primary_model'`

---

### 4. POST `/api/model/retrain` — Trigger Neural Network Retraining

**Summary:** Queue async model retraining with configurable epochs and batch size.

**Request Body:**
```json
{
  "include_recent_data": true,
  "epochs": 50,
  "batch_size": 32
}
```

**Request Fields:**
- `include_recent_data` (bool, default: true): Include last 24h data in training
- `epochs` (int, default: 50, bounds: 1-500): Training epochs
- `batch_size` (int, default: 32, bounds: 1-256): Batch size

**Response (200 OK):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Retraining job 550e8400-e29b-41d4-a716-446655440000 queued successfully",
  "estimated_duration_seconds": 180,
  "timestamp": "2026-03-22T09:38:00+00:00"
}
```

**Response Fields:**
- `job_id` (string): UUID for tracking async job
- `status` (string): `queued` or `running`
- `estimated_duration_seconds` (int): Estimated training time

**Error Responses:**
- `400 Bad Request`: Invalid epochs or batch_size (out of bounds)
- `500 Internal Server Error`: Failed to queue job

**Implementation Notes:**
- Creates job record: `INSERT INTO hems.training_jobs (id, status, epochs, batch_size, include_recent_data, created_at, expires_at) VALUES (...)`
- Queues background task to run async training worker
- Job records include status field (queued → running → completed/error)
- Clients poll job_id status via GET `/api/model/job/{job_id}` (future endpoint)

---

### 5. GET `/api/boiler` — Current Boiler State

**Summary:** Fetch current boiler operational state, power, temperatures, and runtime.

**Response (200 OK):**
```json
{
  "state": "on",
  "power_kw": 18.5,
  "flow_temp_c": 55.0,
  "return_temp_c": 48.2,
  "runtime_minutes": 12.0,
  "last_state_change": "2026-03-22T09:26:00+00:00",
  "modulation_percent": 85.0,
  "error_code": null,
  "timestamp": "2026-03-22T09:38:00+00:00"
}
```

**State Values:**
- `off`: Boiler idle
- `ignition`: Starting ignition sequence
- `on`: Boiler operating at fixed power
- `modulating`: Modulating burner (variable power)
- `error`: Error state (check `error_code`)

**Fields:**
- `power_kw`: Current power output (0-30kW typical)
- `flow_temp_c`: Flow temperature setpoint (20-80°C)
- `return_temp_c`: Return temperature reading (20-80°C, ≤ flow_temp)
- `runtime_minutes`: Minutes in current cycle
- `modulation_percent`: Burner modulation (0-100%, only if modulating)
- `error_code`: Error identifier (only if state == error)

**Error Responses:**
- `500 Internal Server Error`: InfluxDB query failed
- `503 Service Unavailable`: InfluxDB connection failed

**Implementation Notes:**
- Queries InfluxDB latest values: `boiler.state`, `boiler.power_kw`, `boiler.flow_temp`, `boiler.return_temp`, `boiler.runtime_minutes`, `boiler.modulation_percent`, `boiler.error_code`
- Currently returns synthetic data; production queries InfluxDB for latest measurement per field

---

### 6. GET `/api/decisions/latest` — Last Control Decisions

**Summary:** Fetch the last N control decisions made by HEMS controller.

**Query Parameters:**
- `limit` (int, default: 5, bounds: 1-50): Number of decisions to return

**Response (200 OK):**
```json
{
  "decisions": [
    {
      "id": "dec-001",
      "timestamp": "2026-03-22T09:36:00+00:00",
      "decision_type": "boiler_setpoint",
      "target_value": 60.0,
      "device": "boiler",
      "reason": "Room temp below setpoint, increasing flow temp",
      "actual_value": 60.0
    },
    {
      "id": "dec-002",
      "timestamp": "2026-03-22T09:30:00+00:00",
      "decision_type": "mixer_position",
      "target_value": 72.0,
      "device": "mixer",
      "reason": "Adjusting mixing valve for better response",
      "actual_value": 71.5
    }
  ],
  "count": 2,
  "timestamp": "2026-03-22T09:38:00+00:00"
}
```

**Decision Types:**
- `boiler_setpoint`: Flow temperature adjustment
- `mixer_position`: Mixing valve position (0-100)
- `pump_on_off`: Circulation pump state
- `flow_temp`: Direct flow temp override

**Fields:**
- `decision_type`: Type of control decision
- `target_value`: Intended value (temp in °C, position 0-100)
- `actual_value`: Value actually applied (may differ due to constraints)
- `reason`: Explanation for decision (for auditability)

**Error Responses:**
- `500 Internal Server Error`: Database query failed
- `503 Service Unavailable`: PostgreSQL connection failed

**Implementation Notes:**
- Queries PostgreSQL: `SELECT * FROM hems.control_decisions ORDER BY timestamp DESC LIMIT $1`
- Decisions ordered newest-first
- Limit clamped to 1-50 range (defaults to 5)
- Currently returns synthetic decisions; production queries PostgreSQL audit log

---

### 7. POST `/api/override/flow_temp` — Manual Flow Temperature Override

**Summary:** Temporarily override boiler flow temperature setpoint.

**Request Body:**
```json
{
  "flow_temp_c": 55.0,
  "duration_minutes": 30,
  "reason": "User manual adjustment via web UI"
}
```

**Request Fields:**
- `flow_temp_c` (float, bounds: 20-80): Override temperature (°C)
- `duration_minutes` (int, default: 30, bounds: 5-1440): Duration (5min to 24h)
- `reason` (string): Reason for override (for audit trail)

**Response (200 OK):**
```json
{
  "override_id": "550e8400-e29b-41d4-a716-446655440000",
  "flow_temp_c": 55.0,
  "duration_minutes": 30,
  "expires_at": "2026-03-22T10:08:00+00:00",
  "message": "Flow temp override 550e8400-e29b-41d4-a716-446655440000 active until 2026-03-22T10:08:00+00:00",
  "timestamp": "2026-03-22T09:38:00+00:00"
}
```

**Response Fields:**
- `override_id` (string): UUID for tracking this override session
- `expires_at` (string): ISO-8601 expiration timestamp

**Error Responses:**
- `422 Unprocessable Entity`: Invalid temperature (not 20-80) or duration (not 5-1440)
- `500 Internal Server Error`: Failed to create override

**Implementation Notes:**
- Persists to PostgreSQL: `INSERT INTO hems.flow_temp_overrides (id, flow_temp_c, duration_minutes, reason, created_at, expires_at) VALUES (...)`
- Boiler controller polls overrides table or receives signal via Redis
- Override expires after `duration_minutes` (cleanup via scheduled task or polling)
- Audit logged with reason for manual override
- Can be revoked early via DELETE `/api/override/{override_id}` (future endpoint)

---

## Data Formats

### ISO-8601 Timestamps
All timestamps use ISO-8601 format with UTC timezone:
```
2026-03-22T09:38:00+00:00
```

### Temperature Units
All temperatures in **Celsius (°C)**.

### Energy Units
All energy in **kilowatt-hours (kWh)**.

### Power Units
All power in **kilowatts (kW)**.

### Time Ranges
All time ranges in **minutes** or **seconds** as specified.

---

## Database Tables (PostgreSQL)

The API assumes these PostgreSQL tables exist:

### `hems.model_metadata`
```sql
CREATE TABLE hems.model_metadata (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL, -- idle, training, retraining, ready, error
  last_trained TIMESTAMP WITH TIME ZONE,
  training_loss FLOAT,
  accuracy FLOAT,
  retraining_progress FLOAT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

### `hems.training_jobs`
```sql
CREATE TABLE hems.training_jobs (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL, -- queued, running, completed, error
  epochs INTEGER,
  batch_size INTEGER,
  include_recent_data BOOLEAN,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  started_at TIMESTAMP WITH TIME ZONE,
  completed_at TIMESTAMP WITH TIME ZONE,
  error_message TEXT,
  expires_at TIMESTAMP WITH TIME ZONE
);
```

### `hems.control_decisions`
```sql
CREATE TABLE hems.control_decisions (
  id TEXT PRIMARY KEY,
  timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
  decision_type TEXT NOT NULL,
  target_value FLOAT,
  device TEXT,
  reason TEXT,
  actual_value FLOAT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX idx_control_decisions_timestamp ON hems.control_decisions(timestamp DESC);
```

### `hems.flow_temp_overrides`
```sql
CREATE TABLE hems.flow_temp_overrides (
  id TEXT PRIMARY KEY,
  flow_temp_c FLOAT NOT NULL,
  duration_minutes INTEGER NOT NULL,
  reason TEXT,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);
CREATE INDEX idx_flow_temp_overrides_expires ON hems.flow_temp_overrides(expires_at);
```

---

## InfluxDB Measurements

The API expects these InfluxDB measurements in the `hems` bucket:

### Energy Measurements
- `energy.boiler` (kWh)
- `energy.pump` (kWh)
- `energy.supplemental` (kWh)
- `energy.pv_exported` (kWh)
- `energy.pv_used` (kWh)

### Thermal Measurements
- `thermal.room_temp` (°C)
- `thermal.setpoint` (°C)
- `thermal.boiler_runtime` (minutes)
- `thermal.mixing_valve_position` (0-100)

### Boiler Measurements
- `boiler.state` (off, ignition, on, modulating, error)
- `boiler.power_kw` (kW)
- `boiler.flow_temp` (°C)
- `boiler.return_temp` (°C)
- `boiler.runtime_minutes` (minutes)
- `boiler.modulation_percent` (0-100)
- `boiler.error_code` (string or null)

### PV Measurements
- `energy.pv_utilization` (%)

---

## Testing

Run unit tests with:
```bash
pytest test_api.py -v
```

Tests include:
- **Endpoint structure validation**: All required fields present
- **Type checking**: Values match expected types
- **Range validation**: Numeric values in valid ranges
- **Error handling**: Invalid inputs return appropriate HTTP status codes
- **Integration tests**: All 7 endpoints available and respond with timestamps
- **Data consistency**: Derived values (e.g., total energy = sum of breakdown) are correct

**Test Coverage:**
- 60+ unit tests covering all 7 endpoints
- Mocked InfluxDB queries (no external dependencies)
- Mocked PostgreSQL connections
- FastAPI TestClient for HTTP-level testing

---

## Future Enhancements

1. **GET `/api/model/job/{job_id}`** — Poll retraining job status
2. **DELETE `/api/override/{override_id}`** — Revoke manual override early
3. **GET `/api/decisions/{id}`** — Fetch single decision details
4. **POST `/api/decisions/analyze`** — Analyze decision patterns
5. **GET `/api/energy/forecast`** — Energy consumption forecast
6. **WebSocket `/ws/live/boiler`** — Real-time boiler state stream

---

## Integration Notes

### With Main HEMS Service
- Import router: `from api import router`
- Include in FastAPI app: `app.include_router(router)`
- Middleware injects `query_api` (InfluxDB) and `db_pool` (PostgreSQL) via dependency injection

### With Orchestrator
- Report retraining job completion back to orchestrator
- Signal override events for logging/alerting
- Sync decision history for optimization

### With Home Assistant
- Call endpoints from HA automations for diagnostics
- Feed energy analytics into HA energy management
- Trigger overrides from HA UI

---

## Rate Limiting (Future)

Recommended limits:
- GET endpoints: 100 req/min per client
- POST endpoints: 20 req/min per client
- Burst: 10 req/sec

(Currently no rate limiting; add via middleware)

---

## Security Considerations

1. **Authentication**: Should require API token in `Authorization: Bearer <token>` header
2. **HTTPS**: Use TLS in production
3. **CORS**: Restrict to allowed origins (orchestrator, web UI)
4. **Input validation**: All endpoints validate type, range, format
5. **Audit logging**: All manual overrides logged with reason
6. **Database**: Use parameterized queries to prevent SQL injection

---

## Version History

- **v2.0** (2026-03-22): Initial Phase 2 API with 7 endpoints, async design, InfluxDB + PostgreSQL integration
- **v1.0** (Prior): Legacy schedule/status endpoints in routes.py

---

## Contact & Support

For issues, feature requests, or questions:
- Check HEMS README.md for setup
- Review test_api.py for usage examples
- Consult database schema for data structure
