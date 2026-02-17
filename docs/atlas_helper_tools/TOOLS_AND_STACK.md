# Tools & Stack Documentation

> **Purpose**: Complete reference of the tools, dependencies, infrastructure, scripts, and operational patterns used in the `atlas_helper_tools` repository. This repo hosts a self-hosted, LLM-ready web search pipeline — a free Tavily alternative.

---

## Table of Contents

1. [Runtime & Language](#1-runtime--language)
2. [Python Dependencies](#2-python-dependencies)
3. [Infrastructure Stack](#3-infrastructure-stack)
4. [Docker & Orchestration](#4-docker--orchestration)
5. [Configuration](#5-configuration)
6. [API Endpoints](#6-api-endpoints)
7. [CLI Commands](#7-cli-commands)
8. [Operational Scripts](#8-operational-scripts)
9. [LLM Backend Configuration](#9-llm-backend-configuration)

---

## 1. Runtime & Language

| Component        | Version / Tool                  | Notes                                           |
|------------------|---------------------------------|-------------------------------------------------|
| Language         | Python 3.12                     | `python:3.12-slim` Docker base                  |
| Async framework  | `asyncio` (stdlib)              | Async HTTP calls via `httpx`                    |
| Package manager  | `pip` via `pyproject.toml`      | setuptools backend, no Poetry/PDM               |
| Type checking    | Type hints on all signatures    | `mypy` available in dev dependencies            |

---

## 2. Python Dependencies

Defined in `pyproject.toml` using setuptools.

### Runtime Dependencies

| Package              | Version Constraint   | Purpose                                      |
|----------------------|----------------------|----------------------------------------------|
| `httpx`              | `>=0.27,<1`          | HTTP client for SearXNG and Ollama calls     |
| `trafilatura`        | `>=1.12,<2`          | Primary web content extraction               |
| `beautifulsoup4`     | `>=4.12,<5`          | Fallback content extraction                  |
| `lxml`               | `>=5.0,<6`           | HTML/XML parser (used by trafilatura & BS4)  |
| `pydantic`           | `>=2.5,<3`           | Data validation & response models            |
| `pydantic-settings`  | `>=2.1,<3`           | Layered config from env vars / YAML files    |
| `pyyaml`             | `>=6.0,<7`           | YAML config file parsing                     |
| `typer[all]`         | `>=0.12,<1`          | CLI framework (includes rich + shellingham)  |
| `fastapi`            | `>=0.115,<1`         | REST API framework (Tavily-compatible)       |
| `uvicorn[standard]`  | `>=0.30,<1`          | ASGI server for FastAPI                      |
| `apscheduler`        | `>=3.10,<4`          | Scheduled job execution (cron-style)         |
| `rich`               | `>=13.7,<14`         | Terminal formatting & progress display       |
| `structlog`          | `>=24.1,<26`         | Structured logging (event + kwargs)          |

### Dev Dependencies

| Package              | Purpose                                      |
|----------------------|----------------------------------------------|
| `pytest`             | Test runner                                  |
| `pytest-asyncio`     | Async test support                           |
| `pytest-httpx`       | Mock httpx requests in tests                 |
| `ruff`               | Linter & formatter                           |
| `mypy`               | Static type checker                          |

### Adding dependencies

Update `pyproject.toml` and rebuild the Docker image. No separate requirements files are needed since this is a single-service repository.

---

## 3. Infrastructure Stack

### Core infrastructure (Docker Compose)

| Component    | Image / Tool                   | Port   | Purpose                                    |
|--------------|--------------------------------|--------|--------------------------------------------|
| websearch    | Custom (`python:3.12-slim`)    | 8888   | Main API server + search pipeline          |
| SearXNG      | `searxng/searxng:latest`       | 8080   | Meta-search engine (aggregates results)    |
| Redis        | `redis:7-alpine`               | (internal) | SearXNG result caching                |
| Ollama       | `ollama/ollama` (optional)     | 11434  | LLM summarization backend                 |

### External integrations

| System         | Protocol   | Purpose                                  | Location                        |
|----------------|------------|------------------------------------------|---------------------------------|
| SearXNG        | HTTP REST  | Web search queries                       | `192.168.0.29` (existing LXC)  |
| Ollama         | HTTP REST  | LLM summarization of search results      | Host machine                   |

### Default LLM model

| Setting              | Value           | Notes                                    |
|----------------------|-----------------|------------------------------------------|
| Model                | `qwen2:0.5b`   | Lightweight, CPU-only                    |
| Context window       | 4096 tokens     | Dynamic token budgeting ensures fit      |

---

## 4. Docker & Orchestration

### Image structure

```
python:3.12-slim
  └── websearch (custom image)
        ├── pyproject.toml dependencies installed
        ├── Application code
        └── Operational scripts (healthcheck.py, diagnose.py)
```

### Key files

| File                                       | Purpose                                              |
|--------------------------------------------|------------------------------------------------------|
| `services/websearch/Dockerfile`            | Single Dockerfile for the websearch service          |
| `docker-compose.yml`                       | Production orchestration (all services)              |
| `docker-compose.override.example.yml`      | Dev mode template (volume mounts, debug ports)       |

### Docker Compose service pattern

```yaml
websearch:
  build:
    context: .                                    # Repo root
    dockerfile: services/websearch/Dockerfile
  ports:
    - "8888:8888"
  volumes:
    - websearch-data:/app/data
    - websearch-shared:/app/shared
  networks:
    - websearch-net
```

### Network topology

All services share a single `websearch-net` bridge network. The websearch service exposes port 8888 for API access. SearXNG exposes port 8080. Redis is internal only.

### Volume strategy

| Volume              | Type          | Purpose                                          |
|---------------------|---------------|--------------------------------------------------|
| `websearch-data`    | Named volume  | Persistent service data (database, history, state) |
| `websearch-shared`  | Named volume  | Shared data between services                     |
| `redis-data`        | Named volume  | SearXNG cache persistence                        |

### Key conventions

- **Build context is repo root** so the Dockerfile can access all project files.
- **`restart: unless-stopped`** — auto-restart on crash, stay down after manual stop.
- **HEALTHCHECK** uses a file-based timestamp mechanism with HTTP fallback. A `healthcheck.py` script checks the timestamp file freshness (< 5 minutes) and falls back to an HTTP health endpoint if the file is stale.
- **One `.env` / `config.yml` for the service** — Pydantic's `extra="ignore"` drops irrelevant vars.

---

## 5. Configuration

### Layered configuration system

Configuration is resolved in the following priority order (highest wins):

1. **Environment variables** with `LLM_WEBSEARCH_` prefix
2. **`config.yml`** file (human-readable defaults)
3. **Pydantic BaseSettings defaults** (code-level fallbacks)

Pydantic BaseSettings with `extra="ignore"` handles all configuration loading.

### Key configuration settings

#### Search & Infrastructure

| Setting              | Default                              | Description                              |
|----------------------|--------------------------------------|------------------------------------------|
| `searxng_url`        | `http://192.168.0.29:8080`           | SearXNG instance URL                     |

#### LLM / Summarization

| Setting              | Default                              | Description                              |
|----------------------|--------------------------------------|------------------------------------------|
| `summarizer_backend` | `ollama`                             | Backend for LLM summarization            |
| `ollama_model`       | `qwen2:0.5b`                         | Ollama model name                        |
| `ollama_context_length` | `4096`                            | Model context window in tokens           |

#### Environment variable prefix

All settings can be overridden via environment variables with the `LLM_WEBSEARCH_` prefix. For example:

```bash
LLM_WEBSEARCH_SEARXNG_URL=http://my-searxng:8080
LLM_WEBSEARCH_OLLAMA_MODEL=llama3
LLM_WEBSEARCH_OLLAMA_CONTEXT_LENGTH=8192
```

---

## 6. API Endpoints

The websearch service exposes a Tavily-compatible REST API on port 8888.

### Search endpoints

| Method | Path            | Description                                      |
|--------|-----------------|--------------------------------------------------|
| POST   | `/search`       | Tavily-compatible search (primary integration point) |
| GET    | `/search`       | Convenience search (query params)                |
| GET    | `/context`      | LLM-ready text context (pre-formatted for prompts) |

### Operational endpoints

| Method          | Path            | Description                                      |
|-----------------|-----------------|--------------------------------------------------|
| GET             | `/health`       | Service health report (SearXNG, Ollama, DB status) |
| GET             | `/history`      | Search history with pagination                   |
| GET             | `/stats`        | Database statistics and usage metrics            |

### Job management endpoints

| Method          | Path            | Description                                      |
|-----------------|-----------------|--------------------------------------------------|
| GET             | `/jobs`         | List scheduled jobs                              |
| POST            | `/jobs`         | Create a scheduled job                           |
| DELETE          | `/jobs`         | Remove a scheduled job                           |

### Content endpoints

| Method          | Path            | Description                                      |
|-----------------|-----------------|--------------------------------------------------|
| GET             | `/diff`         | Diff reports (content change tracking)           |
| GET             | `/feed/{job}`   | RSS/Atom feed for a scheduled job                |

### Tag management endpoints

| Method          | Path            | Description                                      |
|-----------------|-----------------|--------------------------------------------------|
| GET             | `/tags`         | List all tags                                    |
| POST            | `/tags`         | Create a tag                                     |
| DELETE          | `/tags`         | Delete a tag                                     |

---

## 7. CLI Commands

The CLI is built with Typer and installed as the `llm-websearch` entry point.

### Core commands

| Command                                    | Description                                      |
|--------------------------------------------|--------------------------------------------------|
| `llm-websearch search <query>`             | Run a search and display results                 |
| `llm-websearch serve`                      | Start the FastAPI/Uvicorn API server             |
| `llm-websearch health`                     | Check service health (SearXNG, Ollama, DB)       |

### Job scheduling

| Command                                    | Description                                      |
|--------------------------------------------|--------------------------------------------------|
| `llm-websearch schedule add`               | Add a scheduled search job                       |
| `llm-websearch schedule list`              | List all scheduled jobs                          |
| `llm-websearch schedule remove`            | Remove a scheduled job                           |
| `llm-websearch schedule run`               | Run a scheduled job immediately                  |
| `llm-websearch schedule start`             | Start the job scheduler                          |

### History & data

| Command                                    | Description                                      |
|--------------------------------------------|--------------------------------------------------|
| `llm-websearch history show`               | Display search history                           |
| `llm-websearch history search`             | Search through history                           |
| `llm-websearch history export`             | Export history to file                           |
| `llm-websearch history stats`              | Show history statistics                          |

### Configuration management

| Command                                    | Description                                      |
|--------------------------------------------|--------------------------------------------------|
| `llm-websearch config show`               | Display current configuration                    |
| `llm-websearch config set`                | Update a configuration value                     |

### Content tracking

| Command                                    | Description                                      |
|--------------------------------------------|--------------------------------------------------|
| `llm-websearch diff show`                 | Show diff reports                                |
| `llm-websearch diff detail`               | Show detailed diff information                   |

### Tags

| Command                                    | Description                                      |
|--------------------------------------------|--------------------------------------------------|
| `llm-websearch tag list`                   | List all tags                                    |
| `llm-websearch tag create`                | Create a new tag                                 |
| `llm-websearch tag add`                   | Add a tag to a search result                     |
| `llm-websearch tag show`                  | Show tag details                                 |
| `llm-websearch tag remove`               | Remove a tag from a result                       |
| `llm-websearch tag delete`               | Delete a tag entirely                            |

### Feed & integration

| Command                                    | Description                                      |
|--------------------------------------------|--------------------------------------------------|
| `llm-websearch feed <job>`                | Generate RSS/Atom feed for a scheduled job       |
| `llm-websearch mcp`                       | Start MCP (Model Context Protocol) server        |

---

## 8. Operational Scripts

### healthcheck.py

Docker HEALTHCHECK script used by the container runtime.

- **Primary**: Checks a file-based timestamp at `/app/data/healthcheck`. The service writes a timestamp after each successful operation. The script verifies the file is recent (< 5 minutes).
- **Fallback**: If the file check fails, performs an HTTP GET to the `/health` endpoint.
- Exit code 0 = healthy, exit code 1 = unhealthy.

```dockerfile
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD ["python", "healthcheck.py"]
```

### diagnose.py

Comprehensive 8-section diagnostic script for troubleshooting. Run inside the container:

```bash
docker compose exec websearch python diagnose.py
```

Sections cover connectivity (SearXNG, Ollama), database integrity, configuration validation, and more. Steps are independent — one failure does not block subsequent checks. Produces color-coded terminal output (PASS/FAIL/WARN) via Rich.

---

## 9. LLM Backend Configuration

The summarization pipeline uses Ollama with dynamic token budgeting to fit prompts within the model's context window regardless of which model is configured.

### Current model: qwen2:0.5b (CPU-only)

| Setting                  | Default     | Description                                      |
|--------------------------|-------------|--------------------------------------------------|
| `ollama_model`           | `qwen2:0.5b` | Model name (any Ollama-compatible model)       |
| `ollama_context_length`  | `4096`      | Context window in tokens                         |
| `summarizer_max_tokens`  | `256`       | Maximum output tokens for summarization          |
| `chars_per_token`        | `3.5`       | Character-to-token estimation ratio              |
| `summarizer_temperature` | `0.3`       | Generation temperature (lower = more focused)    |

### Dynamic token budgeting

The pipeline calculates available input tokens as:

```
available_input = ollama_context_length - summarizer_max_tokens - system_prompt_tokens
```

Content is then truncated to fit within `available_input` using the `chars_per_token` ratio. This ensures prompts never exceed the model's context window, regardless of input size.

### Changing the model

To switch to a different model:

1. Pull the new model: `ollama pull <model-name>`
2. Update `ollama_model` in `config.yml` or set `LLM_WEBSEARCH_OLLAMA_MODEL=<model-name>`
3. Update `ollama_context_length` to match the new model's window (set `LLM_WEBSEARCH_OLLAMA_CONTEXT_LENGTH=<value>`)
4. Optionally adjust `chars_per_token` if the new model uses a different tokenizer

The dynamic budgeting system handles the rest automatically.

---

## Content Extraction Pipeline

The search pipeline uses a two-tier content extraction strategy:

1. **Primary: trafilatura** — Specialized web content extraction. Handles article text, removes boilerplate, preserves structure. Used for the majority of pages.
2. **Fallback: beautifulsoup4 + lxml** — Used when trafilatura fails or returns insufficient content. More permissive extraction, handles edge cases.

Both extractors feed into the LLM summarization step (when enabled) to produce concise, LLM-ready text output.

---

## Search Pipeline Flow

```
Client request (/search or /context)
  │
  ├─→ SearXNG meta-search (via httpx)
  │     └─→ Returns ranked URLs + snippets
  │
  ├─→ Content extraction (trafilatura → BS4 fallback)
  │     └─→ Full-text content from top results
  │
  ├─→ LLM summarization (optional, via Ollama)
  │     └─→ Concise, query-focused summaries
  │
  └─→ Response formatting
        ├─→ /search: Tavily-compatible JSON
        └─→ /context: Plain text for LLM consumption
```
