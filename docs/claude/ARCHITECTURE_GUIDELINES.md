# Architecture & Coding Guidelines

> **Purpose**: Reusable architecture patterns and coding conventions for Python microservice projects. Copy this file into new repositories and adapt as needed.

---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [Service Architecture](#2-service-architecture)
3. [Configuration Management](#3-configuration-management)
4. [Logging](#4-logging)
5. [Client Wrappers & External APIs](#5-client-wrappers--external-apis)
6. [Retry & Resilience](#6-retry--resilience)
7. [Inter-Service Communication](#7-inter-service-communication)
8. [State Persistence](#8-state-persistence)
9. [Error Handling](#9-error-handling)
10. [Docker & Containerization](#10-docker--containerization)
11. [Health Checks & Diagnostics](#11-health-checks--diagnostics)
12. [Secrets Management](#12-secrets-management)
13. [Development Workflow](#13-development-workflow)
14. [API & File Exchange Between Tools](#14-api--file-exchange-between-tools)
15. [Security](#15-security)
16. [Code Style](#16-code-style)
17. [Testing](#17-testing)

---

## 1. Project Structure

Organize the repository with clear separation between shared code, individual services, infrastructure config, and scripts.

```
/
├── CLAUDE.md                    # AI assistant instructions (project-specific)
├── docs/
│   └── ARCHITECTURE_GUIDELINES.md  # This file
├── shared/                      # Shared Python library (mounted into every container)
│   ├── __init__.py
│   ├── config.py                # Pydantic settings (base)
│   ├── log.py                   # Structured logging setup
│   ├── service.py               # BaseService class
│   ├── retry.py                 # Exponential backoff decorator
│   └── <client_wrappers>.py     # API client wrappers
├── base/                        # Shared Docker base image
│   ├── Dockerfile
│   └── requirements.txt         # Pinned shared dependencies
├── services/                    # One directory per microservice
│   ├── my-service/
│   │   ├── Dockerfile
│   │   ├── requirements.txt     # Service-specific deps only
│   │   ├── main.py              # Entry point
│   │   ├── config.py            # Service-specific settings
│   │   ├── healthcheck.py       # Docker HEALTHCHECK script
│   │   └── diagnose.py          # Step-by-step connectivity diagnostic
│   └── example-service/         # Template for new services
├── infrastructure/              # Config for infra containers (broker, DB, etc.)
├── scripts/                     # Build, deploy, scaffold, and utility scripts
├── docker-compose.yml           # Production orchestration
├── docker-compose.override.example.yml  # Dev mode template
├── .env.example                 # Template for secrets
└── .gitignore
```

### Principles

- **One directory per service.** Each service is self-contained with its own Dockerfile, requirements, config, and entry point.
- **Shared code lives in `shared/`.** Mounted read-only into every container at runtime. Never duplicated into service directories.
- **Base image for common dependencies.** All services extend a single base image that contains the Python runtime and shared packages.
- **Infrastructure is configuration, not code.** Broker configs, DB schemas, and similar go in `infrastructure/`.

---

## 2. Service Architecture

### The BaseService Pattern

Every service inherits from a `BaseService` class that wires up all shared infrastructure automatically. This eliminates boilerplate and ensures consistency.

```python
import asyncio
from shared.service import BaseService

class MyService(BaseService):
    name = "my-service"  # Used in MQTT topics, logging, healthcheck

    async def run(self) -> None:
        self.logger.info("service_started")
        self.mqtt.connect_background()

        # Subscribe to commands
        self.mqtt.subscribe(
            f"homelab/orchestrator/command/{self.name}",
            self._on_command,
        )

        # Service-specific logic here...

        await self.wait_for_shutdown()

if __name__ == "__main__":
    service = MyService()
    asyncio.run(service.start())
```

### What BaseService provides

| Attribute              | Description                                              |
|------------------------|----------------------------------------------------------|
| `self.settings`        | Pydantic config loaded from env vars / `.env`            |
| `self.logger`          | Structured logger bound with service name                |
| `self.mqtt`            | MQTT pub/sub client                                      |
| `self.ha`              | Async HTTP client for external APIs                      |
| `self.influx`          | Time-series DB query client                              |
| `self.publish(e, d)`   | Shorthand for MQTT publish to `homelab/{name}/{event}`   |
| `self.wait_for_shutdown()` | Block until SIGTERM/SIGINT                          |

### Service lifecycle

```
__init__()          # Wire up clients, settings, logger
    ↓
start()             # Register signal handlers, call run()
    ↓
run()               # Service-specific logic (implement this)
    ↓
wait_for_shutdown() # Block until signal received
    ↓
shutdown()          # Publish offline status, close all clients
```

### Extending settings

Services that need additional configuration extend the base settings:

```python
from shared.config import Settings as BaseSettings

class MyServiceSettings(BaseSettings):
    poll_interval_seconds: int = 30
    target_entity_id: str = "sensor.my_entity"

class MyService(BaseService):
    name = "my-service"

    def __init__(self) -> None:
        super().__init__(settings=MyServiceSettings())
        self.settings: MyServiceSettings  # Narrow type for IDE support
```

### Key rules

- **Async by default.** Services use `asyncio`. External API clients should be async where possible.
- **One service, one responsibility.** Each service has a clearly bounded domain.
- **Services never import each other.** Communication happens exclusively through message passing (MQTT) or shared state stores (database, HA entities).

---

## 3. Configuration Management

### Pydantic BaseSettings

All configuration flows through Pydantic `BaseSettings`. Environment variables automatically map to field names.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Unknown env vars are silently dropped
    )

    # Infrastructure
    ha_url: str = "http://homeassistant.local:8123"
    ha_token: str = ""
    mqtt_host: str = "mqtt"
    mqtt_port: int = 1883

    # Logging
    log_level: str = "INFO"

    # Operational
    heartbeat_interval_seconds: int = 60  # 0 to disable
```

### Rules

- **`extra="ignore"` is mandatory** when multiple services share a single `.env` file. Without this, unknown variables cause validation errors.
- **Every field has a sensible default.** Services should start with zero configuration when possible and only require explicit config for credentials and environment-specific values.
- **Env var mapping is automatic**: `MY_CUSTOM_VAR` -> `my_custom_var`.
- **Never hardcode credentials, URLs, or entity IDs.** Everything configurable goes through settings.
- **Comma-separated values** should be parsed via computed properties:

```python
@property
def allowed_ids(self) -> list[int]:
    if not self.allowed_ids_csv:
        return []
    return [int(x.strip()) for x in self.allowed_ids_csv.split(",") if x.strip()]
```

### Environment file hierarchy

| File             | Purpose                               | Git status   |
|------------------|---------------------------------------|--------------|
| `.env.example`   | Template with placeholder values      | Committed    |
| `.env`           | Actual secrets and config             | Gitignored   |
| `.env.enc`       | Encrypted secrets (SOPS/age)          | Committed    |

---

## 4. Logging

### Structured logging with structlog

Use event-based structured logging everywhere. The event name is the primary searchable identifier.

```python
# CORRECT — structured, searchable, parseable
self.logger.info("forecast_completed", today_kwh=42.3, model="gradient_boosting")
self.logger.warning("sensor_unavailable", entity_id="sensor.temp", fallback=0.0)
self.logger.exception("control_cycle_error")  # Includes traceback automatically

# WRONG — unstructured, hard to search and aggregate
self.logger.info(f"Forecast completed: {today_kwh} kWh using {model}")
self.logger.warning("Sensor " + entity_id + " is unavailable, using fallback")
```

### Rules

- **Event names are snake_case noun phrases**: `forecast_completed`, `sensor_read`, `connection_lost`.
- **Context goes in keyword arguments**, not in the message string.
- **Never use f-strings or string concatenation** in log messages.
- **Use `.exception()` for caught exceptions** — it includes the traceback automatically.
- **Log level guidelines**:
  - `DEBUG`: Internal state, loop iterations, raw API responses
  - `INFO`: Service lifecycle events, successful operations, results
  - `WARNING`: Recoverable issues, fallback values, retries
  - `ERROR`: Failed operations that affect functionality
  - `EXCEPTION`: Caught exceptions with traceback

### Setup

Initialize the logger once per service, lazily:

```python
import structlog

def get_logger(service_name: str) -> structlog.stdlib.BoundLogger:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),  # Human-readable for containers
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    return structlog.get_logger(service=service_name)
```

---

## 5. Client Wrappers & External APIs

### Wrapper design principles

Every external system gets a dedicated client wrapper in `shared/`. Wrappers provide:

1. **Connection management** — lazy initialization, reconnection, explicit close
2. **Authentication** — token injection, credential handling
3. **Error normalization** — translate HTTP errors, timeouts, and protocol errors into consistent exceptions
4. **Sensible defaults** — timeouts, retries, content types
5. **Domain-specific convenience methods** — hide raw API details behind meaningful operations

### HTTP API client pattern

```python
import httpx

class APIClient:
    def __init__(self, base_url: str, token: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy init — creates client on first use, recreates if closed."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=30.0,
            )
        return self._client

    async def get(self, path: str) -> dict:
        client = await self._get_client()
        response = await client.get(path)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
```

### Message broker client pattern (MQTT)

```python
class MQTTClient:
    def __init__(self, host: str, port: int, client_id: str) -> None:
        self._client = mqtt.Client(client_id=client_id)
        self._subscriptions: dict[str, Callable] = {}  # topic -> handler

    def connect_background(self) -> None:
        """Non-blocking connection for async services."""
        self._client.connect(self._host, self._port)
        self._client.loop_start()  # Runs on background thread

    def subscribe(self, topic: str, handler: Callable) -> None:
        self._subscriptions[topic] = handler
        self._client.subscribe(topic)

    def publish(self, topic: str, payload: dict, retain: bool = False) -> None:
        self._client.publish(topic, json.dumps(payload), retain=retain)

    def _on_connect(self, client, userdata, flags, rc) -> None:
        """Re-subscribe on reconnect to survive broker restarts."""
        for topic in self._subscriptions:
            client.subscribe(topic)
```

### Rules

- **Wrap every external dependency.** Never scatter raw `httpx.get()` or `paho.Client()` calls throughout service code.
- **Lazy client initialization.** Create connections on first use, not at import time or `__init__`.
- **Re-subscribe on reconnect.** Message broker clients must restore their subscriptions when the connection drops and reconnects.
- **Explicit `close()`.** Provide a shutdown method and call it during service teardown.
- **Auto-serialize payloads.** MQTT wrappers should auto-serialize dicts to JSON and auto-deserialize incoming messages.
- **Publish errors to dead-letter topics.** When a message handler fails, publish the error context (original topic, payload, traceback) to an error topic instead of silently dropping it.

```python
def _publish_error(self, topic: str, payload: Any, exc: Exception) -> None:
    self._client.publish(f"homelab/errors/{self._client_id}", json.dumps({
        "original_topic": topic,
        "error": str(exc),
        "error_type": type(exc).__name__,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": self._client_id,
    }))
```

---

## 6. Retry & Resilience

### Exponential backoff decorator

```python
import asyncio
import functools
from typing import TypeVar, Callable

T = TypeVar("T")

def async_retry(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        await asyncio.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
```

### Usage

```python
@async_retry(max_retries=2, base_delay=1.0, exceptions=(httpx.ConnectError, httpx.ConnectTimeout))
async def get_state(self, entity_id: str) -> dict:
    ...
```

### Rules

- **Specify exception types explicitly.** Never retry on all exceptions — logic errors (KeyError, ValueError) should not be retried.
- **Apply selectively.** Not every API call needs retry. Use it for operations where transient network failures are expected.
- **Log each retry** at WARNING level so retries are visible in logs.
- **Set reasonable maximums.** `max_retries=3` and `max_delay=60s` are sensible defaults. Don't retry indefinitely.
- **Idempotency matters.** Only retry operations that are safe to repeat (GET requests, sensor reads). Be cautious with writes.

---

## 7. Inter-Service Communication

### MQTT topic convention

```
{project}/{service-name}/{event-type}
```

Examples:
```
homelab/pv-forecast/updated          # Service published new data
homelab/pv-forecast/heartbeat        # Service is alive
homelab/smart-charging/status        # Current state snapshot
homelab/errors/pv-forecast           # Dead-letter error messages
```

### Communication patterns

#### 1. Event broadcasting

Services publish events when something notable happens. Other services subscribe to topics they care about.

```python
# Publisher
self.publish("updated", {
    "today_kwh": 42.3,
    "tomorrow_kwh": 38.1,
    "timestamp": datetime.now(timezone.utc).isoformat(),
})

# Subscriber
self.mqtt.subscribe("homelab/pv-forecast/updated", self._on_forecast_updated)
```

#### 2. Command pattern

A coordinator service sends commands to worker services:

```
{project}/coordinator/command/{target-service}
```

Payload: `{"command": "refresh"}`, `{"command": "retrain"}`, etc.

```python
# Target service subscribes to its command topic
self.mqtt.subscribe(
    f"homelab/orchestrator/command/{self.name}",
    self._on_command,
)

def _on_command(self, topic: str, payload: dict) -> None:
    command = payload.get("command", "")
    if command == "refresh":
        asyncio.run_coroutine_threadsafe(self._refresh(), self._loop)
    else:
        self.logger.debug("unknown_command", command=command)
```

#### 3. Request/response pattern

For synchronous-feeling interactions over async MQTT, use a `request_id`:

```python
# Requester
request_id = str(uuid4())
self.mqtt.publish("homelab/coordinator/command/dashboard", {
    "command": "chat",
    "message": "How much PV today?",
    "request_id": request_id,
})
# Listen for response with matching request_id on a response topic

# Responder
self.mqtt.publish("homelab/dashboard/chat-response", {
    "request_id": original_request_id,
    "response": "Today's forecast is 42.3 kWh.",
})
```

#### 4. Demand publisher pattern

Services publish **what they need** (demand), never how to fulfill it. The coordinator or controller decides what to do.

```python
# ev-forecast publishes demand — NOT "turn on charger at 11kW"
self.publish("plan", {
    "energy_needed_kwh": 15.0,
    "deadline": "2025-01-15T07:00:00",
    "urgency": "medium",
    "trace_id": self._trace_id,
})
```

#### 5. Shared state via external store

When two services need a handoff point but shouldn't depend on each other, use an external state store (database, key-value store, or HA input helpers):

```
Service A writes → External Store ← Service B reads (on its own schedule)
```

This fully decouples the services — neither needs to know the other exists.

### Cross-service correlation IDs

Include a `trace_id` in MQTT payloads to correlate related events across services:

```python
import uuid

trace_id = str(uuid.uuid4())
self.publish("plan", {"trace_id": trace_id, "energy_needed_kwh": 15.0})

# Downstream service captures the trace_id
def _on_plan(self, topic: str, payload: dict) -> None:
    self._current_trace_id = payload.get("trace_id", "")
```

### MQTT thread to asyncio bridge

MQTT callbacks (paho) run on a synchronous background thread. To schedule async work safely:

```python
def _on_message(self, topic: str, payload: dict) -> None:
    asyncio.run_coroutine_threadsafe(
        self._handle_async(payload),
        self._loop,
    )
```

Capture `self._loop = asyncio.get_event_loop()` at service startup.

---

## 8. State Persistence

### JSON file pattern

Services persist critical state to disk for faster restart recovery. This avoids re-querying slow external APIs and preserves session counters.

```python
from pathlib import Path
import json

STATE_FILE = Path("/app/data/state.json")

def save_state(self) -> None:
    """Non-fatal save — never crashes the service."""
    try:
        state = {
            "last_value": self._last_value,
            "session_counter": self._counter,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        self.logger.debug("state_save_failed", exc_info=True)

def load_state(self) -> None:
    """Non-fatal load — missing or corrupt state is silently ignored."""
    try:
        if not STATE_FILE.exists():
            return
        data = json.loads(STATE_FILE.read_text())
        self._last_value = data.get("last_value")
        self._counter = data.get("session_counter", 0)
    except Exception:
        pass  # Will re-fetch on first run
```

### Rules

- **Save and load are both non-fatal.** Catch all exceptions. A corrupt state file should never prevent the service from starting.
- **Load before first external API call.** This prevents thundering-herd re-fetching on restart.
- **Use named Docker volumes** at `/app/data` to survive container restarts.
- **Include a `saved_at` timestamp** so you can tell how stale the persisted state is.
- **Keep state minimal.** Only persist what's expensive to recompute. Don't persist derived data that can be recalculated quickly.

---

## 9. Error Handling

### Catch-log-continue for operational loops

The main loop of a service should never crash due to a single operation failure:

```python
while not self._shutdown_event.is_set():
    try:
        await self._control_cycle()
    except Exception:
        self.logger.exception("control_cycle_error")
    await asyncio.sleep(self.settings.poll_interval_seconds)
```

### Fail-open for non-critical checks

When a safety or permission check can't reach its data source, default to allowing the action:

```python
async def is_maintenance_mode(self) -> bool:
    try:
        state = await self.ha.get_state(self.settings.maintenance_entity)
        return state.get("state", "off") == "on"
    except Exception:
        return False  # Fail open — allow actions if check fails
```

### Default values for sensor reads

All external sensor reads should have explicit defaults. Treat "unavailable" and "unknown" states identically to missing data:

```python
async def read_float(self, entity_id: str, default: float = 0.0) -> float:
    try:
        state = await self.ha.get_state(entity_id)
        val = state.get("state", str(default))
        if val in ("unavailable", "unknown", ""):
            return default
        return float(val)
    except Exception:
        self.logger.warning("read_float_failed", entity_id=entity_id)
        return default
```

### Dead-letter error topics

MQTT handler failures are automatically published to `{project}/errors/{service}`, including the original topic, payload, error message, and timestamp. This provides centralized error visibility without losing context.

### Graceful shutdown signaling

On shutdown, publish an explicit offline status before disconnecting:

```python
async def shutdown(self) -> None:
    self.publish("heartbeat", {"status": "offline", "service": self.name})
    self.mqtt.disconnect()
    await self.ha.close()
```

This lets monitoring services distinguish graceful stops from crashes.

### Rules summary

| Scenario                     | Strategy                                      |
|------------------------------|-----------------------------------------------|
| Main loop iteration fails    | Catch, log, continue to next iteration        |
| Sensor read fails            | Return sensible default                       |
| Non-critical check fails     | Fail open (allow the action)                  |
| MQTT handler fails           | Publish to dead-letter topic, continue        |
| Service shutting down        | Publish offline status, close clients cleanly |
| State file corrupt           | Ignore, re-fetch from source on next run      |

---

## 10. Docker & Containerization

### Base image

A single shared base image contains the Python runtime and common dependencies. All service images extend it.

```dockerfile
# base/Dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/base-requirements.txt
RUN pip install --no-cache-dir -r /tmp/base-requirements.txt \
    && rm /tmp/base-requirements.txt
ENV PYTHONPATH="/app:/app/shared:${PYTHONPATH}"
WORKDIR /app
```

### Service Dockerfile

```dockerfile
# services/my-service/Dockerfile
FROM homelab-base:latest

COPY services/my-service/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY services/my-service/ /app/

HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "main.py"]
```

### Docker Compose pattern

```yaml
services:
  my-service:
    build:
      context: .                              # Repo root as build context
      dockerfile: services/my-service/Dockerfile
    restart: unless-stopped
    env_file: .env                            # All secrets/config
    volumes:
      - ./shared:/app/shared:ro               # Shared library (read-only)
      - my_service_data:/app/data             # Persistent state (named volume)
    depends_on:
      - mqtt
    networks:
      - internal

volumes:
  my_service_data:

networks:
  internal:
    driver: bridge
```

### Dev override

The override file (gitignored) mounts live source code for instant iteration without image rebuilds:

```yaml
# docker-compose.override.yml (gitignored, copy from .example)
services:
  my-service:
    volumes:
      - ./services/my-service:/app            # Live mount source code
      - ./shared:/app/shared:ro
      - my_service_data:/app/data
    environment:
      - LOG_LEVEL=DEBUG
    ports:
      - "5678:5678"                           # Debugger port
```

### Dependency management

| Scope                          | File                                    | Rebuild after change        |
|--------------------------------|-----------------------------------------|-----------------------------|
| Shared across all services     | `base/requirements.txt`                 | Base image + all services   |
| Specific to one service        | `services/<name>/requirements.txt`      | That service only           |

### Rules

- **Build context is repo root.** This lets Dockerfiles copy from both `services/` and `shared/`.
- **Shared code is volume-mounted, not baked in.** Update shared code without rebuilding any service image.
- **Mount shared code read-only** (`:ro`). Services should never write to shared code at runtime.
- **Named volumes for persistent data.** Never use bind mounts for state that must survive rebuilds.
- **`--start-period` on HEALTHCHECK.** Give services time to complete their first operation before Docker marks them unhealthy.
- **No exposed ports by default.** Only expose ports explicitly needed (dashboards, debuggers).
- **`restart: unless-stopped`.** Services auto-restart after crashes but stay down after manual `docker compose stop`.

---

## 11. Health Checks & Diagnostics

### File-based health check

Services write a timestamp to a file after each successful operation. A separate script checks if the timestamp is recent.

```python
# In the service (write after each successful operation)
from pathlib import Path
import time

HEALTHCHECK_FILE = Path("/app/data/healthcheck")

def touch_healthcheck(self) -> None:
    try:
        HEALTHCHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEALTHCHECK_FILE.write_text(str(time.time()))
    except OSError:
        pass
```

```python
# healthcheck.py (Docker HEALTHCHECK script)
import sys
import time
from pathlib import Path

HEALTHCHECK_FILE = Path("/app/data/healthcheck")
MAX_AGE_SECONDS = 300  # 5 minutes

def main() -> None:
    if not HEALTHCHECK_FILE.exists():
        sys.exit(1)
    age = time.time() - float(HEALTHCHECK_FILE.read_text().strip())
    sys.exit(0 if age <= MAX_AGE_SECONDS else 1)

if __name__ == "__main__":
    main()
```

This approach decouples health signaling from the health check script — no process introspection, no PID tracking, no race conditions.

### MQTT heartbeat

Every service publishes a heartbeat on a regular interval:

```json
{
  "status": "online",
  "service": "my-service",
  "uptime_seconds": 3661.2,
  "memory_mb": 42.3
}
```

Override `health_check()` to add service-specific fields:

```python
def health_check(self) -> dict[str, Any]:
    extra = {}
    if self._last_operation_age > 7200:
        extra["status"] = "degraded"
        extra["reason"] = "operation stale"
    return extra
```

### Diagnostic scripts

Every service ships a standalone `diagnose.py` that tests connectivity to each dependency in isolation. This is invaluable for debugging deployment issues.

```python
# diagnose.py
import argparse
import asyncio

PASS = "\033[92m PASS \033[0m"
FAIL = "\033[91m FAIL \033[0m"
WARN = "\033[93m WARN \033[0m"

def check_config() -> dict:
    """Validate that all required config is present."""
    ...

async def check_api(settings) -> None:
    """Test API connectivity and authentication."""
    ...

def check_database(settings) -> None:
    """Test database connectivity and query execution."""
    ...

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--step", choices=["config", "api", "database", "all"], default="all")
    args = parser.parse_args()

    settings = check_config()  # Always runs first

    if args.step in ("api", "all"):
        asyncio.run(check_api(settings))
    if args.step in ("database", "all"):
        check_database(settings)

if __name__ == "__main__":
    main()
```

Usage:
```bash
docker compose run --rm my-service python diagnose.py
docker compose run --rm my-service python diagnose.py --step api
```

### Rules

- **Config check runs first.** If config is invalid, skip all other steps.
- **Each step is independent.** One failure doesn't block subsequent checks.
- **Colored terminal output.** Use ANSI codes for PASS/FAIL/WARN to make results scannable.
- **Runnable without the main service.** `diagnose.py` imports settings and clients directly, not the service class.

---

## 12. Secrets Management

### SOPS + age encryption

```bash
# Encrypt
sops --encrypt --age $(cat .sops/age-key.pub) .env > .env.enc

# Decrypt
sops --decrypt .env.enc > .env

# Edit in-place
sops .env.enc
```

### .sops.yaml config

```yaml
creation_rules:
  - path_regex: \.env\.enc$
    age: "age1..."  # Public key (safe to commit)
```

### Rules

- **Never commit plain `.env`.** It must be in `.gitignore`.
- **Commit `.env.enc`** (encrypted) and `.env.example` (template with placeholder values).
- **Back up the age private key** in a password manager. If lost, secrets cannot be decrypted.
- **Git pre-commit hooks** should verify that `.env` is not being committed.
- **One `.env` file for all services.** Use `extra="ignore"` in Pydantic settings so services ignore variables they don't use.

---

## 13. Development Workflow

### First-time setup

```bash
# 1. Decrypt secrets (or copy .env.example and fill in values)
./scripts/secrets-decrypt.sh

# 2. Install git hooks
./scripts/install-hooks.sh

# 3. Build base image
./scripts/build-base.sh

# 4. Start everything
docker compose up --build
```

### Dev mode (code hot-reload)

```bash
# 1. Enable dev override
cp docker-compose.override.example.yml docker-compose.override.yml

# 2. Start service with live code mount
docker compose up my-service

# 3. Edit code locally, then restart to pick up changes
docker compose restart my-service

# 4. Watch logs
docker compose logs -f my-service
```

### VS Code debugger

The base image includes `debugpy`. Set `DEBUG_SERVICE=my-service` in the override, and the service pauses at startup waiting for the debugger to attach.

```python
def _maybe_start_debugger(self) -> None:
    debug_service = os.environ.get("DEBUG_SERVICE", "")
    if debug_service != self.name:
        return
    import debugpy
    debugpy.listen(("0.0.0.0", 5678))
    self.logger.info("debugger_waiting", port=5678)
    debugpy.wait_for_client()
```

### Scaffolding new services

Provide a script that generates a new service from the template:

```bash
./scripts/new-service.sh my-new-service
# Creates: services/my-new-service/{Dockerfile, requirements.txt, main.py, healthcheck.py, diagnose.py}
```

Then add the service to `docker-compose.yml` following the existing pattern.

---

## 14. API & File Exchange Between Tools

When multiple tools or repositories need to interact, follow these patterns to ensure stability and compatibility.

### API interaction patterns

#### 1. Versioned API contracts

When services expose HTTP APIs to each other, version the endpoints:

```
/api/v1/forecast
/api/v1/status
```

Never break existing versions. Add new versions for breaking changes.

#### 2. Schema-first communication

Define shared data schemas that both producer and consumer agree on:

```python
# shared/schemas.py
from pydantic import BaseModel
from datetime import datetime

class ForecastPayload(BaseModel):
    today_kwh: float
    tomorrow_kwh: float
    hourly: list[float]
    generated_at: datetime

class ServiceStatus(BaseModel):
    status: str  # "online" | "offline" | "degraded"
    service: str
    uptime_seconds: float
    memory_mb: float
```

Use Pydantic models for validation on both sides. If the schemas are shared between repos, publish them as a package or use a shared schema repo.

#### 3. MQTT message contracts

Document the payload structure for every MQTT topic. Each message should include:

- **`timestamp`** — ISO 8601 UTC timestamp of when the message was produced
- **`service`** — name of the producing service
- **`trace_id`** — correlation ID for cross-service tracing (when applicable)
- **Semantic versioning in topic** — if you need to evolve payloads: `homelab/v2/pv-forecast/updated`

#### 4. Idempotent message handling

Consumers must handle duplicate messages gracefully. Use `request_id` or `trace_id` for deduplication:

```python
def _on_message(self, topic: str, payload: dict) -> None:
    msg_id = payload.get("request_id") or payload.get("trace_id")
    if msg_id and msg_id in self._processed_ids:
        return  # Already handled
    self._processed_ids.add(msg_id)
    # ... process message ...
```

### File exchange patterns

#### 1. Shared volumes (same host)

Mount a named Docker volume into multiple containers:

```yaml
services:
  producer:
    volumes:
      - shared_data:/data/shared

  consumer:
    volumes:
      - shared_data:/data/shared:ro  # Read-only for consumers

volumes:
  shared_data:
```

#### 2. File format conventions

- **JSON** for structured data exchange (human-readable, schema-validatable)
- **CSV** for tabular data (forecasts, time series)
- **Markdown** for reports and documentation
- Include a `_metadata` field or header with schema version:

```json
{
  "_metadata": {
    "schema_version": "1.0",
    "produced_by": "pv-forecast",
    "produced_at": "2025-01-15T10:00:00Z"
  },
  "data": { ... }
}
```

#### 3. Atomic file writes

When writing files that other processes read, use atomic writes to prevent partial reads:

```python
import tempfile
import os

def atomic_write(path: Path, content: str) -> None:
    """Write to a temp file first, then rename (atomic on same filesystem)."""
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp_path, path)  # Atomic rename
    except Exception:
        os.unlink(tmp_path)
        raise
```

### Cross-repo integration checklist

When setting up a new repo that needs to interact with existing tools:

- [ ] Define the communication channel (MQTT, HTTP API, shared files)
- [ ] Document the message/API schema in both repos
- [ ] Use Pydantic models for payload validation on both sides
- [ ] Include `trace_id` for cross-service correlation
- [ ] Handle the "other side is down" case (timeouts, retries, defaults)
- [ ] Test with the other service stopped — does your service degrade gracefully?
- [ ] Add the new service to the monitoring/health-check system
- [ ] Document the integration in both repos' CLAUDE.md

---

## 15. Security

### General rules

- **Never commit secrets.** Use encrypted secret files (`.env.enc`) or external secret managers.
- **Validate at system boundaries.** Validate user input, external API responses, and incoming messages. Trust internal code and framework guarantees.
- **Principle of least privilege.** Containers run as non-root. File mounts are read-only where possible. API tokens have minimal required scopes.
- **No SQL/query injection.** Use parameterized queries for databases. For InfluxDB Flux, avoid building queries from user input with string concatenation.

### Container security

```dockerfile
# Run as non-root user
RUN useradd -r -s /bin/false appuser
USER appuser
```

```yaml
# docker-compose.yml
services:
  my-service:
    read_only: true                      # Read-only root filesystem
    tmpfs:
      - /tmp                             # Writable temp
    security_opt:
      - no-new-privileges:true
```

### Network security

- All services on an internal bridge network — no default port exposure.
- Only expose ports that need external access (dashboards, APIs).
- Use TLS for any external-facing endpoints.
- Internal service-to-service traffic can use plain TCP within the Docker network.

---

## 16. Code Style

### General conventions

- **Python 3.12+** — use modern syntax (type unions with `|`, `match` statements, etc.)
- **Type hints on all function signatures.** Parameters and return types.
- **Async by default.** Use `asyncio` for I/O-bound operations.
- **No f-strings in log messages.** Use structured keyword arguments.
- **Snake_case** for variables, functions, file names. **PascalCase** for classes.
- **Constants** in UPPER_SNAKE_CASE at module level.

### Import ordering

```python
# 1. Standard library
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

# 2. Third-party
import httpx
import structlog
from pydantic import BaseModel

# 3. Local/shared
from shared.config import Settings
from shared.service import BaseService
```

### Docstrings

Add docstrings only where the function's purpose or behavior isn't obvious from its name and signature. Don't add docstrings to simple getters, setters, or self-explanatory methods.

```python
async def calculate_surplus(
    self,
    grid_power: float,
    ev_power: float,
    battery_power: float,
) -> float:
    """Calculate available PV surplus for EV charging.

    Grid meter: positive = exporting, negative = importing.
    Battery: positive = charging, negative = discharging.
    """
    return grid_power + ev_power + battery_power - self.settings.grid_reserve_w
```

### Avoid over-engineering

- Don't create abstractions for one-time operations.
- Don't add error handling for scenarios that can't happen.
- Don't design for hypothetical future requirements.
- Three similar lines of code is better than a premature abstraction.
- A bug fix doesn't need surrounding code cleaned up.

---

## 17. Testing

### Test structure

```
tests/
├── conftest.py           # Shared fixtures
├── test_my_service.py    # Service-level tests
├── test_shared/
│   ├── test_config.py
│   └── test_retry.py
└── integration/
    └── test_mqtt_flow.py
```

### Testing client wrappers

Mock external dependencies at the HTTP/protocol level, not at the wrapper level:

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_get_state_retries_on_timeout():
    client = APIClient(base_url="http://test", token="test")
    with patch.object(client, "_get_client") as mock:
        mock_http = AsyncMock()
        mock_http.get.side_effect = [httpx.ConnectTimeout("timeout"), mock_response]
        mock.return_value = mock_http

        result = await client.get_state("sensor.temp")
        assert mock_http.get.call_count == 2
```

### Testing MQTT interactions

Use a mock MQTT client that captures published messages:

```python
class MockMQTTClient:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, topic: str, payload: dict, **kwargs) -> None:
        self.published.append((topic, payload))

    def subscribe(self, topic: str, handler) -> None:
        self._handlers[topic] = handler
```

### Rules

- **Test behavior, not implementation.** Assert on outputs and side effects, not internal method calls.
- **Mock at the boundary.** Mock HTTP responses, MQTT messages, and file I/O — not internal functions.
- **Integration tests for critical paths.** Test the full MQTT message flow between services using a real (or in-memory) broker.
- **Don't test framework code.** If Pydantic validates your config, you don't need a test for that.
