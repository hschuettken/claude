# Architecture & Coding Guidelines — atlas_helper_tools (LLM WebSearch)

> **Purpose**: Repo-specific architecture patterns, conventions, and decisions for the **atlas_helper_tools** repository. This document extends the ecosystem-wide [ARCHITECTURE_GUIDELINES.md](../claude/ARCHITECTURE_GUIDELINES.md) with details specific to this repository's single service: a self-hosted, LLM-ready web search pipeline — a free Tavily alternative.

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
18. [LLM Integration](#18-llm-integration)
19. [Database](#19-database)

---

## 1. Project Structure

This repository hosts a single service (`websearch`) rather than the multi-service pattern used by other ecosystem repos. There is no `shared/` library or `base/` image — the websearch service is fully self-contained.

```
/
├── CLAUDE.md                       # AI assistant instructions
├── docs/
│   ├── claude/                     # Shared ecosystem docs (read-only, synced)
│   │   ├── ARCHITECTURE_GUIDELINES.md
│   │   └── TOOLS_AND_STACK.md
│   └── atlas_helper_tools/         # This repo's docs
│       └── ARCHITECTURE_GUIDELINES.md  # This file
├── services/
│   └── websearch/
│       ├── Dockerfile
│       ├── pyproject.toml          # Package metadata, dependencies, tool config
│       ├── config.yml              # Human-readable default configuration
│       ├── healthcheck.py          # Docker HEALTHCHECK script (HTTP-based)
│       ├── diagnose.py             # 8-section diagnostic script
│       └── src/llm_websearch/
│           ├── __init__.py
│           ├── config.py           # Pydantic BaseSettings (layered resolution)
│           ├── models.py           # Pydantic data models for the entire pipeline
│           ├── search.py           # SearXNG client wrapper
│           ├── extractor.py        # Content extraction (trafilatura + BeautifulSoup)
│           ├── summarizer.py       # Multi-backend: Ollama, Claude CLI, passthrough
│           ├── database.py         # SQLite + FTS5 persistence layer
│           ├── pipeline.py         # Central orchestrator (search -> extract -> summarize -> store -> export)
│           ├── export.py           # File share exporter (JSON, Markdown, knowledge base)
│           ├── scheduler.py        # Background job scheduler (threaded polling loop)
│           ├── difftracker.py      # Change detection between search runs
│           ├── feeds.py            # RSS 2.0 / Atom feed generation
│           ├── mcp_server.py       # MCP JSON-RPC 2.0 server (stdio)
│           ├── api.py              # FastAPI application (Tavily-compatible REST API)
│           └── cli.py              # Typer CLI with sub-commands
├── config/
│   └── searxng/
│       ├── settings.yml            # SearXNG engine configuration
│       └── limiter.toml            # SearXNG rate limiting
├── docker-compose.yml              # Production orchestration
├── .env.example                    # Template for environment overrides
└── .gitignore
```

### Principles

- **Single service, self-contained.** Unlike other ecosystem repos, there is no `shared/` library or `BaseService` pattern. The websearch service is a standalone Python package (`llm-websearch`) with its own `pyproject.toml`.
- **Package-based structure.** All source code lives under `src/llm_websearch/`, following Python's `src`-layout convention. The package is installed via `pip install -e .` in the Dockerfile.
- **Pipeline architecture.** The codebase is organized around a linear pipeline pattern rather than event-driven microservice loops. Each module handles one stage of the pipeline.
- **Configuration as code.** A `config.yml` file provides human-readable defaults, with environment variables and CLI flags available as overrides.

---

## 2. Service Architecture

### No BaseService Pattern

This repo does **not** use the ecosystem's `BaseService` class. The websearch service is HTTP/REST oriented (not MQTT-based) and uses a synchronous pipeline pattern orchestrated by the `Pipeline` class.

### The Pipeline Pattern

The `Pipeline` class in `pipeline.py` is the central orchestrator. It wires together all components and executes the search pipeline end-to-end.

```python
from llm_websearch.pipeline import Pipeline
from llm_websearch.models import SearchMode

with Pipeline() as pipe:
    result = pipe.run("python web scraping", mode=SearchMode.STANDARD)
    print(result.to_llm_context())
```

### Pipeline stages

```
SearXNG search
    |
    v
Content extraction (trafilatura + BeautifulSoup fallback)
    |
    v
LLM summarization (optional — Ollama, Claude CLI, or passthrough)
    |
    v
SQLite storage (with FTS5 indexing and diff tracking)
    |
    v
File export (JSON + Markdown to shared directory)
```

### Three search modes

| Mode       | Pipeline stages                          | Use case                     |
|------------|------------------------------------------|------------------------------|
| `quick`    | Search only (snippets from SearXNG)      | Fast lookups, link discovery |
| `standard` | Search + page fetch + content extraction | Default for most queries     |
| `deep`     | Full pipeline including LLM summaries    | Comprehensive research       |

### Component architecture

| Component           | Module            | Responsibility                                     |
|---------------------|-------------------|------------------------------------------------------|
| `SearXNGClient`     | `search.py`       | Wraps the SearXNG JSON API                           |
| `ContentExtractor`  | `extractor.py`    | Parallel page fetching + text extraction             |
| `BaseSummarizer`    | `summarizer.py`   | Abstract interface for LLM backends                  |
| `Database`          | `database.py`     | SQLite persistence with FTS5 full-text search        |
| `FileExporter`      | `export.py`       | Writes results to a structured shared directory      |
| `DiffTracker`       | `difftracker.py`  | Detects new/removed/changed URLs between runs        |
| `SearchScheduler`   | `scheduler.py`    | Runs saved jobs on a recurring interval              |
| `FeedGenerator`     | `feeds.py`        | Produces RSS 2.0 / Atom XML from results             |
| `MCPServer`         | `mcp_server.py`   | JSON-RPC 2.0 server over stdio for Claude Desktop    |
| `create_app()`      | `api.py`          | FastAPI application factory (Tavily-compatible)      |
| `app`               | `cli.py`          | Typer CLI with sub-commands                          |

### Pipeline lifecycle

```
Pipeline.__init__()     # Instantiate all components (SearXNG, extractor, summarizer, DB, exporter)
    |
Pipeline.run()          # Execute search -> extract -> summarize -> store -> export
    |
Pipeline.close()        # Close HTTP clients, database connection
```

The `Pipeline` supports context manager usage (`with Pipeline() as pipe: ...`) for automatic cleanup.

### Key rules

- **Synchronous by default.** The pipeline uses synchronous Python. Parallelism is achieved through `ThreadPoolExecutor` in the content extractor (concurrent page fetching). The FastAPI app runs via uvicorn but the pipeline itself is sync.
- **One pipeline instance per process.** The FastAPI app creates one `Pipeline` instance and reuses it across requests. The CLI creates a new instance per command.
- **Factory functions for configuration.** Use `get_settings()` to build settings and `create_summarizer()` to instantiate the correct backend.

---

## 3. Configuration Management

### Layered resolution

Configuration flows through four layers, with later layers overriding earlier ones:

```
Hardcoded defaults (in Settings class)
    |
    v
config.yml (YAML file — human-readable, primary config)
    |
    v
Environment variables (prefixed with LLM_WEBSEARCH_)
    |
    v
CLI flags (--host, --port, --mode, etc.)
```

### Pydantic BaseSettings

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_WEBSEARCH_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    searxng_url: str = "http://192.168.0.29"
    summarizer_backend: str = "none"       # ollama | claude | none
    ollama_model: str = "qwen2:0.5b"
    ollama_context_length: int = 4096
    database_path: str = "./data/websearch.db"
    api_port: int = 8888
    # ... (see config.py for full list)
```

### The `get_settings()` factory

Settings are never instantiated directly. Always use `get_settings()`, which merges YAML config with overrides:

```python
from llm_websearch.config import get_settings

# Default: loads config.yml + env vars
settings = get_settings()

# With explicit overrides (e.g., from CLI flags)
settings = get_settings(api_port=9999, summarizer_backend="ollama")
```

### YAML config file

The `config.yml` file at `services/websearch/config.yml` is the primary configuration source for human-readable defaults. It is searched in this order:

1. Path in `LLM_WEBSEARCH_CONFIG_FILE` env var (if set)
2. `./config.yml` (current working directory)
3. `./config.yaml`
4. `/etc/llm-websearch/config.yml`

### Environment variable mapping

All settings map directly to environment variables with the `LLM_WEBSEARCH_` prefix:

| Setting               | Environment variable                    |
|-----------------------|-----------------------------------------|
| `searxng_url`         | `LLM_WEBSEARCH_SEARXNG_URL`            |
| `summarizer_backend`  | `LLM_WEBSEARCH_SUMMARIZER_BACKEND`     |
| `ollama_model`        | `LLM_WEBSEARCH_OLLAMA_MODEL`           |
| `ollama_context_length` | `LLM_WEBSEARCH_OLLAMA_CONTEXT_LENGTH` |
| `database_path`       | `LLM_WEBSEARCH_DATABASE_PATH`          |
| `api_port`            | `LLM_WEBSEARCH_API_PORT`               |

### Rules

- **No `extra="ignore"`.** Unlike the shared ecosystem pattern (which uses a single `.env` for multiple services), this repo uses `env_prefix="LLM_WEBSEARCH_"` for namespacing. Unrecognized env vars with the prefix will raise validation errors.
- **YAML is primary.** Use `config.yml` for defaults, environment variables for deployment-specific overrides, and CLI flags for one-off changes.
- **Every field has a sensible default.** The service starts with zero configuration against a local SearXNG instance.
- **Never hardcode URLs or credentials.** All external endpoints go through settings.

---

## 4. Logging

### structlog (ecosystem standard)

This repo uses `structlog` for structured, event-based logging. Configuration is centralised in `log.py`.

```python
from .log import get_logger

logger = get_logger(__name__)

# Correct — snake_case event names, context in kwargs
logger.info("search_completed", query=query, results=len(results), elapsed=f"{elapsed:.2f}s")
logger.warning("ollama_summarize_failed", url=page.url, error=str(exc))
logger.exception("pipeline_store_failed")

# Wrong — f-strings or %-style formatting
logger.info(f"Found {len(results)} results for {query}")
logger.info("Found %d results", len(results))
```

### Conventions

- **Module-level logger**: `logger = get_logger(__name__)` at the top of every module (imported from `.log`).
- **Event names**: snake_case descriptors: `search_completed`, `extraction_failed`, `pipeline_done`.
- **Context as kwargs**: All variable data passed as keyword arguments, never interpolated into the message string.
- **`.exception()` for caught exceptions**: Automatically includes the traceback.
- **Log level guidelines** follow the ecosystem standard:
  - `DEBUG`: Token budget calculations, prompt sizes, internal state
  - `INFO`: Pipeline stage completions, search results, stored records
  - `WARNING`: Fallback to alternative extraction/summarization, recoverable failures
  - `ERROR`: Failed operations (search, storage, export)

### Logging setup

Logging is initialised via `setup_logging()` from `log.py`. The CLI and API both call this at startup:

```python
from .log import setup_logging

# In CLI
setup_logging("DEBUG" if verbose else "INFO")

# In API (create_app)
setup_logging(cfg.log_level)
```

The `log_level` setting is configurable via `config.yml` or `LLM_WEBSEARCH_LOG_LEVEL` env var.

---

## 5. Client Wrappers & External APIs

### SearXNG client (`search.py`)

Wraps the SearXNG JSON API with structured input/output:

```python
class SearXNGClient:
    def __init__(self, settings: Settings) -> None:
        self._client = httpx.Client(timeout=20, follow_redirects=True)

    def search(self, query: str, *, categories=None, ...) -> SearchResponse:
        """Execute a search and return structured results."""

    def health_check(self) -> ServiceHealth:
        """Check whether SearXNG is reachable."""

    def close(self) -> None:
        self._client.close()
```

### Content extractor (`extractor.py`)

Uses `ThreadPoolExecutor` for parallel page fetching with a two-tier extraction strategy:

1. **Primary**: `trafilatura` (precision-oriented extraction with metadata)
2. **Fallback**: `BeautifulSoup` with lxml (when trafilatura returns < 50 chars)

```python
class ContentExtractor:
    def extract_pages(self, results: list[SearchResult], *, max_pages=None) -> list[PageContent]:
        """Fetch and extract content in parallel. Skips blocklisted domains."""
```

### Summarizer backends (`summarizer.py`)

All backends implement the `BaseSummarizer` abstract class:

```python
class BaseSummarizer(ABC):
    @abstractmethod
    def summarize_page(self, page: PageContent, query: str) -> PageSummary: ...

    @abstractmethod
    def aggregate(self, pages, query, page_summaries=None) -> AggregatedSummary: ...

    def health_check(self) -> ServiceHealth: ...
```

Three implementations:

| Backend                | Class                   | When to use                           |
|------------------------|-------------------------|---------------------------------------|
| `none` (passthrough)   | `PassthroughSummarizer` | No LLM available; truncates text      |
| `ollama`               | `OllamaSummarizer`      | Local LLM with dynamic token budgeting|
| `claude`               | `ClaudeSummarizer`      | Claude CLI (`claude --print`)         |

Backend selection is handled by the `create_summarizer()` factory based on `settings.summarizer_backend`.

### Rules

- **All HTTP clients use `httpx`** (both sync `httpx.Client` and, where needed, the API client). No `requests` library.
- **Explicit timeouts on every client.** SearXNG: 20s. Content extraction: 15s (configurable). Ollama: 300s (CPU inference can be slow). Claude CLI: 120s subprocess timeout.
- **Lazy client initialization** is not used here — clients are created in `__init__()` and closed explicitly in `close()`.
- **Fallback on failure.** When Ollama or Claude summarization fails, the code automatically falls back to `PassthroughSummarizer` rather than raising.

---

## 6. Retry & Resilience

### No retry decorator

This repo does not use the ecosystem's `async_retry` decorator. Resilience is achieved through:

1. **Fallback strategies**: If trafilatura fails, fall back to BeautifulSoup. If Ollama fails, fall back to passthrough truncation.
2. **Per-page error isolation**: Content extraction uses `ThreadPoolExecutor` — one page failure does not block others. Failed pages are recorded with `extraction_method="failed"`.
3. **Catch-log-continue in storage/export**: The pipeline catches and logs exceptions in `_store()` and `_export()` without failing the entire run.

### Domain blocklist

The extractor skips social media and other domains that yield poor text extraction:

```python
skip_domains:
  - youtube.com
  - facebook.com
  - instagram.com
  - twitter.com
  - x.com
  - tiktok.com
  - reddit.com
  - linkedin.com
  - pinterest.com
```

---

## 7. Inter-Service Communication

### Primary: HTTP REST API (Tavily-compatible)

The main communication channel is the FastAPI REST API on port 8888. It provides drop-in Tavily compatibility:

```
POST /search          # Tavily-compatible search (SearchRequest -> SearchResponse)
GET  /search          # Convenience GET endpoint (?q=...&mode=...&max_results=...)
GET  /context         # LLM-ready plain text context string
GET  /health          # Service health report
GET  /history         # Recent search history
GET  /history/search  # Full-text search across stored content
GET  /stats           # Database statistics
POST /jobs            # Create scheduled search job
GET  /jobs            # List scheduled jobs
DELETE /jobs/{name}   # Remove a scheduled job
GET  /diff            # View diff reports
GET  /diff/latest     # Latest diff for a query
GET  /feed/{job_name} # RSS or Atom feed for a job (?fmt=rss|atom)
GET  /tags            # List tags
POST /tags            # Create a tag
POST /tags/{name}/items  # Tag a URL or search
GET  /tags/{name}/items  # Get items with a tag
DELETE /tags/{name}   # Delete a tag
```

### Tavily API compatibility

The `POST /search` endpoint accepts a Tavily-compatible request body:

```json
{
  "query": "python web scraping",
  "search_depth": "basic",
  "include_answer": true,
  "include_raw_content": false,
  "max_results": 5,
  "include_domains": [],
  "exclude_domains": []
}
```

`search_depth` mapping: `basic` maps to `QUICK` or `STANDARD` (depending on `include_answer`), `advanced` maps to `STANDARD` or `DEEP`.

### MCP server (Model Context Protocol)

The MCP server (`mcp_server.py`) exposes the pipeline as tools for Claude Desktop or any MCP-compatible client. It communicates over stdio using JSON-RPC 2.0.

Available tools:

| Tool name             | Description                                      |
|-----------------------|--------------------------------------------------|
| `web_search`          | Standard search with content extraction          |
| `web_search_deep`     | Deep search with LLM summarization               |
| `search_knowledge_base` | FTS search across previously stored content    |
| `health_check`        | Check backend service health                     |

Configuration for Claude Desktop:

```json
{"command": "llm-websearch", "args": ["mcp"]}
```

### RSS/Atom feeds

Scheduled jobs can produce RSS 2.0 or Atom feeds via `GET /feed/{job_name}?fmt=rss|atom`. Feeds are also exportable to files via the CLI `feed` command.

### No MQTT

This repo does not use MQTT. There are no heartbeat topics, no command patterns, and no dead-letter error topics. Communication is exclusively HTTP-based (REST API) and stdio-based (MCP).

---

## 8. State Persistence

### SQLite database (not JSON state files)

This repo does not use the ecosystem's `state.json` pattern. All persistent state lives in a SQLite database at `database_path` (default: `./data/websearch.db`).

The database stores:

| Table              | Purpose                                          |
|--------------------|--------------------------------------------------|
| `searches`         | Search metadata (query, mode, timing, errors)    |
| `search_results`   | Individual result rows per search                |
| `page_content`     | Extracted page text (deduplicated by URL)         |
| `page_content_fts` | FTS5 virtual table for full-text search          |
| `scheduled_jobs`   | Persistent job definitions for the scheduler     |
| `search_diffs`     | Diff reports between search runs                 |
| `tags`             | Tag/label definitions                            |
| `tagged_items`     | Tag-to-item associations                         |

### File exports (shared directory)

In addition to the database, results are exported to a structured file share directory:

```
shared/
├── latest/              # Always the most recent result
├── by_query/<slug>/     # Results grouped by query
├── scheduled/<job>/     # Scheduled job output
├── knowledge_base/      # Rolling summary document (all_summaries.md)
├── diffs/               # Diff reports (JSON + Markdown)
└── feeds/               # RSS/Atom feed files
```

---

## 9. Error Handling

### Pipeline error isolation

Each pipeline stage handles its own errors. A failure in one stage does not crash the entire run:

```python
# In Pipeline.run()
try:
    search_resp = self.searxng.search(query, ...)
except SearXNGError as exc:
    result.errors.append(f"Search failed: {exc}")
    return result  # Return partial result with errors

# Storage failures are caught and logged, not propagated
def _store(self, result, job_name=None):
    try:
        self.database.store_pipeline_result(result)
    except Exception:
        logger.exception("[pipeline] failed to store result")
```

### Summarizer fallback chain

When an LLM backend fails, it falls back to passthrough truncation rather than raising:

```python
# In OllamaSummarizer.summarize_page()
try:
    text, tokens, elapsed = self._generate(prompt, system=self.system_prompt)
    return PageSummary(url=page.url, summary=text, backend="ollama", ...)
except Exception as exc:
    logger.warning("Ollama summarization failed for %s: %s", page.url, exc)
    return PassthroughSummarizer().summarize_page(page, query)
```

### Content extraction resilience

- Pages are fetched in parallel via `ThreadPoolExecutor`. One page failure does not block others.
- Failed pages are recorded with `extraction_method="failed"` and included in results (so the caller knows which pages could not be extracted).
- Blocklisted domains are silently skipped.

### Rules summary

| Scenario                          | Strategy                                        |
|-----------------------------------|-------------------------------------------------|
| SearXNG search fails              | Return partial result with error message         |
| Page fetch times out              | Record as `extraction_method="failed"`, continue |
| Trafilatura returns empty text    | Fall back to BeautifulSoup                       |
| LLM summarization fails           | Fall back to passthrough truncation              |
| Database storage fails            | Log exception, continue (result still returned)  |
| File export fails                 | Log exception, continue                          |
| Scheduler job fails               | Log exception, continue to next job              |

---

## 10. Docker & Containerization

### Container architecture

The `docker-compose.yml` defines four services (one optional):

| Service      | Image                    | Port  | Purpose                         |
|--------------|--------------------------|-------|----------------------------------|
| `websearch`  | Built from Dockerfile    | 8888  | Main API server                  |
| `searxng`    | `searxng/searxng:latest` | 8080  | Meta-search engine               |
| `redis`      | `redis:7-alpine`         | —     | SearXNG cache backend            |
| `ollama`     | `ollama/ollama:latest`   | 11434 | Local LLM (optional, commented)  |

### Dockerfile

The websearch Dockerfile is self-contained (no base image dependency):

```dockerfile
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends libxml2-dev libxslt1-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies (layer cached)
COPY pyproject.toml .
RUN pip install --no-cache-dir \
    httpx trafilatura beautifulsoup4 lxml \
    pydantic pydantic-settings pyyaml \
    typer rich fastapi "uvicorn[standard]" apscheduler

# Application code
COPY src/ ./src/
COPY config.yml .
COPY healthcheck.py .
COPY diagnose.py .

RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/data /app/shared

EXPOSE 8888

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["python", "-m", "uvicorn", "llm_websearch.api:app", "--host", "0.0.0.0", "--port", "8888"]
```

### Docker Compose configuration

```yaml
services:
  websearch:
    build:
      context: ./services/websearch
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "8888:8888"
    environment:
      LLM_WEBSEARCH_SEARXNG_URL: "http://searxng:8080"
      LLM_WEBSEARCH_OLLAMA_URL: "http://ollama:11434"
      LLM_WEBSEARCH_SUMMARIZER_BACKEND: "none"
      LLM_WEBSEARCH_DATABASE_PATH: "/app/data/websearch.db"
      LLM_WEBSEARCH_SHARE_DIR: "/app/shared"
    volumes:
      - websearch-data:/app/data        # Database persistence
      - websearch-shared:/app/shared    # Exported files
    depends_on:
      searxng:
        condition: service_healthy
    networks:
      - websearch-net
```

### Named volumes

| Volume            | Mount point    | Purpose                        |
|-------------------|----------------|--------------------------------|
| `websearch-data`  | `/app/data`    | SQLite database                |
| `websearch-shared`| `/app/shared`  | Exported files (JSON, MD, RSS) |
| `redis-data`      | `/data`        | Redis persistence for SearXNG  |

### Ollama deployment

Ollama is commented out in docker-compose.yml by default. Two deployment strategies:

1. **Local container**: Uncomment the `ollama` service in docker-compose.yml. Optionally enable GPU passthrough for NVIDIA.
2. **External instance**: Point `LLM_WEBSEARCH_OLLAMA_URL` to an existing Ollama instance (e.g., `http://192.168.0.29:11434`).

### Build context

Unlike other ecosystem repos (which use the repo root as build context), this repo's build context is `./services/websearch`. The Dockerfile copies from within that directory only.

### Rules

- **`restart: unless-stopped`** on all services.
- **`depends_on` with `condition: service_healthy`** ensures SearXNG is ready before the websearch service starts.
- **Named volumes for all persistent data.** Never use bind mounts for state.
- **`--start-period=15s`** on healthcheck gives the service time to initialize.
- **SearXNG drops all capabilities** (`cap_drop: ALL`) and only adds `CHOWN`, `SETGID`, `SETUID`.

---

## 11. Health Checks & Diagnostics

### Health check (`healthcheck.py`)

The Docker HEALTHCHECK uses a dual-mode approach — file-based primary with HTTP fallback:

1. **File-based (primary)**: The API writes a timestamp to `/app/data/healthcheck` on every successful `/health` call. The healthcheck script stats this file — if it was written within the last 120 seconds, the service is healthy. This is fast and avoids network overhead.
2. **HTTP fallback**: If the file doesn't exist yet (startup phase), it falls back to querying the `/health` endpoint.

```python
def main() -> int:
    # Try file-based check first (fast, no network)
    file_result = _check_file()
    if file_result is True:
        print("OK")
        return 0
    if file_result is False:
        print("UNHEALTHY — healthcheck file stale", file=sys.stderr)
        return 1

    # File doesn't exist yet (startup?) — fall back to HTTP
    if _check_http():
        print("OK")
        return 0
    return 1
```

The `/health` endpoint aggregates health from:
- **SearXNG**: Sends a test search query, checks response
- **Summarizer**: Ollama checks model availability; Claude checks CLI presence; passthrough always healthy

### Diagnostic script (`diagnose.py`)

An 8-section diagnostic script tests each component in isolation:

| Section | Name               | Tests                                                    |
|---------|--------------------|----------------------------------------------------------|
| 1       | SearXNG            | Connectivity, JSON API response, search quality          |
| 2       | Ollama             | Connectivity, model availability, generation test        |
| 3       | Database           | Directory writable, schema tables, FTS5 initialization   |
| 4       | File Share         | Directory structure, write permissions, existing exports |
| 5       | API Server         | Root endpoint, health, OpenAPI docs, search, Tavily POST, context |
| 6       | Python Package     | Import of all 15 modules                                 |
| 7       | Pipeline           | End-to-end quick search, `to_llm_context()`, `to_dict()` |
| 8       | Extended Features  | DiffTracker, FeedGenerator, MCPServer, models, API endpoints |

Usage:
```bash
# From inside the container
python diagnose.py

# From the host
docker exec llm-websearch python diagnose.py
```

Output uses ANSI color codes (PASS/FAIL/WARN/SKIP) with a summary at the end.

### Rules

- **Config check runs first implicitly.** The diagnostic reads the same env vars as the service.
- **Each section is independent.** Failure in one section does not prevent later sections from running.
- **Ollama section is skipped** when `summarizer_backend != "ollama"`.
- **Exit code 0** even with warnings. Exit code 1 only for hard failures.

---

## 12. Secrets Management

### Minimal secrets surface

This repo has very few secrets. The main configuration is non-sensitive (search engine URLs, model names, file paths). There are no API tokens, no database passwords, and no credentials in the default setup.

### Environment file hierarchy

| File           | Purpose                              | Git status   |
|----------------|--------------------------------------|--------------|
| `.env.example` | Template with default values         | Committed    |
| `.env`         | Actual environment overrides         | Gitignored   |
| `config.yml`   | Human-readable defaults              | Committed    |

### Rules

- **No secrets in `config.yml`.** The committed config file contains only non-sensitive defaults.
- **Never commit `.env`.** Use `.env.example` as a template.
- **CORS is open by default** (`allow_origins=["*"]`). Restrict in production if the API is exposed beyond the local network.

---

## 13. Development Workflow

### First-time setup

```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start all services
docker compose up --build

# 3. Verify everything is working
docker exec llm-websearch python diagnose.py
```

### Local development (without Docker)

```bash
cd services/websearch

# 1. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install in development mode
pip install -e ".[dev]"

# 3. Start a local SearXNG (or point to an existing instance)
export LLM_WEBSEARCH_SEARXNG_URL=http://192.168.0.29

# 4. Run the CLI
llm-websearch search "python web scraping"

# 5. Or start the API server
llm-websearch serve --reload

# 6. Run the MCP server
llm-websearch mcp
```

### CLI commands

```bash
# Search
llm-websearch search "query" --mode standard --output table|json|context

# API server
llm-websearch serve --host 0.0.0.0 --port 8888 --reload

# Health check
llm-websearch health

# Scheduled jobs
llm-websearch schedule add --name my-job --query "topic" --interval 60
llm-websearch schedule list
llm-websearch schedule run my-job
llm-websearch schedule start    # Foreground daemon

# Search history
llm-websearch history show
llm-websearch history search "keyword"
llm-websearch history export --format json
llm-websearch history stats

# Diff tracking
llm-websearch diff show
llm-websearch diff detail "query"

# Tags
llm-websearch tag create "important" --color "#ff0000"
llm-websearch tag add "important" "https://example.com"
llm-websearch tag list
llm-websearch tag show "important"

# RSS feeds
llm-websearch feed my-job --format rss|atom

# MCP server
llm-websearch mcp

# Configuration
llm-websearch config show
llm-websearch config set ollama_model "llama3:8b"
```

### Code quality tools

Configured in `pyproject.toml`:

| Tool  | Purpose           | Config                          |
|-------|-------------------|---------------------------------|
| ruff  | Linting + format  | `target-version = "py311"`, `line-length = 100`, rules: E, F, I, N, W, UP |
| mypy  | Type checking     | `python_version = "3.11"`, `strict = true` |
| pytest | Testing          | With `pytest-asyncio` and `pytest-httpx` |

---

## 14. API & File Exchange Between Tools

### Tavily-compatible API contract

The `POST /search` endpoint is designed as a drop-in replacement for the Tavily Search API. Any tool that integrates with Tavily can point at this service instead by changing the base URL.

Request schema:
```python
class SearchRequest(BaseModel):
    query: str
    search_depth: SearchDepth = SearchDepth.BASIC    # basic | advanced
    include_answer: bool = True
    include_raw_content: bool = False
    max_results: int = Field(default=5, ge=1, le=20)
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
```

Response schema:
```python
class SearchResponse(BaseModel):
    query: str
    answer: str = ""
    results: list[SearchResultItem]    # title, url, content, raw_content, score
    response_time: float = 0.0
    images: list[str] = Field(default_factory=list)
```

### LLM context endpoint

`GET /context?q=...&mode=...` returns a plain text string optimized for injection into LLM prompts. The output is structured Markdown with headers, source URLs, and either extracted text or summaries.

### File exchange format

Exported files use two formats:

- **JSON**: Full pipeline result including `_meta` block with mode, timing, errors, and counts
- **Markdown**: LLM-ready context string (same output as `to_llm_context()`)

JSON exports include a metadata block:
```json
{
  "_meta": {
    "mode": "standard",
    "total_time": 3.45,
    "timestamp": "2025-01-15T10:00:00+00:00",
    "errors": [],
    "result_count": 5,
    "pages_fetched": 5,
    "summaries": 0
  },
  "query": "...",
  "results": [...],
  "answer": ""
}
```

### MCP tool contracts

All MCP tool responses return plain text (LLM-ready context strings). No structured JSON is returned to the MCP client — the content is always a `text` block in the MCP response.

---

## 15. Security

### Container security

- **SearXNG drops all capabilities** and only adds the minimum required (`CHOWN`, `SETGID`, `SETUID`).
- **Websearch container** does not run as a named non-root user in the current Dockerfile, but the service itself does not require elevated privileges.
- **Redis** runs with `--loglevel warning` to reduce information leakage.

### Network security

- All services communicate on an internal bridge network (`websearch-net`).
- Only `websearch` (port 8888) and `searxng` (port 8080) expose ports to the host.
- No TLS by default — intended for local network deployment behind a reverse proxy.

### API security

- **CORS is fully open** (`allow_origins=["*"]`). Restrict `allow_origins` in production.
- **No authentication** on the API. Add a reverse proxy with authentication for external-facing deployments.
- **No rate limiting** on the API itself. SearXNG has its own rate limiter (`config/searxng/limiter.toml`).

### Data security

- **No secrets in config files.** The `config.yml` and `.env.example` contain only non-sensitive defaults.
- **Parameterized SQL queries throughout.** No string interpolation in SQL statements.
- **User-Agent spoofing** in the content extractor (mimics Chrome browser headers) to avoid being blocked by websites.

---

## 16. Code Style

### General conventions

- **Python 3.11+** — uses modern syntax (type unions with `|`, `from __future__ import annotations`).
- **Type hints on all function signatures.** Parameters and return types.
- **Synchronous by default.** `asyncio` is not used in the pipeline — FastAPI/uvicorn handles async at the web layer.
- **`from __future__ import annotations`** at the top of every module for PEP 604 union syntax in older Python versions.
- **Snake_case** for variables, functions, file names. **PascalCase** for classes.
- **Constants** in UPPER_SNAKE_CASE at module level.
- **Line length**: 100 characters (configured in ruff).

### Import ordering

```python
# 1. Future annotations
from __future__ import annotations

# 2. Standard library
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 3. Third-party
import httpx
from pydantic import BaseModel, Field

# 4. Local package
from .config import Settings, get_settings
from .log import get_logger
from .models import PipelineResult, SearchMode
```

### Docstrings

Module-level docstrings describe the module's role in the pipeline. Function docstrings use Google or NumPy style (not reStructuredText) and are only added where behavior is not obvious:

```python
"""Pipeline orchestrator — wires search -> extract -> summarize -> store -> export."""

def run(self, query: str, *, mode: SearchMode = SearchMode.STANDARD, ...) -> PipelineResult:
    """Execute the pipeline in the requested mode.

    Modes
    -----
    - **quick** — SearXNG search only, return snippets.
    - **standard** — search + page fetch/extract, no summarisation.
    - **deep** — full pipeline with per-page and aggregate summaries.
    """
```

### Context managers

All components with closeable resources support context manager usage:

```python
class Pipeline:
    def __enter__(self) -> Pipeline:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
```

---

## 17. Testing

### Test dependencies

Declared in `pyproject.toml` under `[project.optional-dependencies]`:

```toml
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
    "ruff>=0.5",
    "mypy>=1.10",
]
```

### Testing approach

- **`pytest-httpx`** for mocking HTTP requests to SearXNG and Ollama at the transport level.
- **Mock at the boundary**: Mock `httpx.Client` responses, not internal methods.
- **Pipeline integration tests**: Create a `Pipeline` with mocked clients and verify end-to-end behavior.
- **Model validation tests**: Pydantic models can be tested by constructing instances and verifying serialization (`to_dict()`, `to_llm_context()`, `to_json()`).

### Rules

- **Test behavior, not implementation.** Assert on `PipelineResult` contents, not internal method calls.
- **Use `pytest-httpx` for HTTP mocking.** This captures the actual HTTP requests and responses.
- **Don't test Pydantic validation.** If a field has a default, don't write a test for the default value.
- **Test the three search modes.** Each mode has different pipeline stages — ensure `quick`, `standard`, and `deep` produce the expected result structure.

---

## 18. LLM Integration

### Ollama backend

The `OllamaSummarizer` is designed to work with small models (e.g., `qwen2:0.5b`) on constrained hardware. Key design decisions:

#### Dynamic token budgeting

Prompts are dynamically sized to fit within the configured context length. The system calculates how much content can be included after accounting for the system prompt, prompt overhead text, and reserved output tokens:

```python
def _max_content_chars(self, overhead_text: str) -> int:
    used = (
        self._estimate_tokens(self.system_prompt)
        + self._estimate_tokens(overhead_text)
        + self.max_tokens   # reserved for output
        + 20                # safety margin
    )
    remaining_tokens = max(self.context_length - used, 200)
    return int(remaining_tokens * self.chars_per_token)
```

#### Model swapping

All model parameters are configurable — swap models by changing config only, no code changes:

| Setting                    | Default     | Purpose                           |
|----------------------------|-------------|-----------------------------------|
| `ollama_model`             | `qwen2:0.5b`| Model name                       |
| `ollama_context_length`    | `4096`      | Context window (tokens)           |
| `summarizer_max_tokens`    | `256`       | Max output tokens                 |
| `summarizer_temperature`   | `0.3`       | Generation temperature            |
| `chars_per_token`          | `3.5`       | Character-to-token ratio estimate |

#### Aggregate summarization

For multi-source answers, the token budget is distributed evenly across sources:

```python
per_source_chars = max(total_content_chars // n_sources, 100)
```

### Claude CLI backend

Uses `subprocess.run(["claude", "--print", "-p", prompt])` to call the Claude CLI. Falls back to passthrough if the CLI is not installed or returns an error.

### Passthrough (no-LLM) backend

Truncates text to a configurable length. Used when no LLM is available, and as the fallback when LLM backends fail.

---

## 19. Database

### SQLite with WAL mode

The database uses SQLite with Write-Ahead Logging for concurrent read/write access:

```python
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
```

### Full-text search (FTS5)

The `page_content_fts` virtual table enables full-text search across stored page content. FTS is kept in sync via triggers on INSERT, UPDATE, and DELETE on the `page_content` table.

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS page_content_fts USING fts5(
    url, title, extracted_text, summary,
    content='page_content',
    content_rowid='id'
);
```

### URL deduplication

Pages are deduplicated by URL. On re-fetch, the existing row is updated (preserving `first_seen`, incrementing `fetch_count`), and the `content_hash` is recomputed for change detection.

### Content hashing for diff detection

A SHA-256 hash (first 16 hex chars) of normalized page content is stored alongside each page. The `DiffTracker` uses these hashes to detect content changes between search runs:

```python
def _content_hash(text: str) -> str:
    normalised = " ".join(text.split()).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()[:16]
```

### Schema versioning

Schema extensions are applied additively using `IF NOT EXISTS` and `ALTER TABLE ... ADD COLUMN` (with duplicate-column errors caught and silently ignored). No formal migration framework is used.

### Rules

- **Parameterized queries only.** No string formatting or concatenation in SQL.
- **Context manager for cursors.** All database operations use `with self._cursor() as cur:` which auto-commits on success and rolls back on exception.
- **Non-blocking for the pipeline.** Database operations are synchronous but fast (SQLite is in-process). The pipeline does not await any database I/O.
- **Named volumes for persistence.** The database file lives in `/app/data/` which is backed by a Docker named volume.
