# ollama-router — Multi-Node Ollama Load Balancer

Routes Ollama-compatible LLM requests across multiple local Ollama nodes, providing load balancing, model affinity routing, and idle model unloading. Exposes both Ollama-native and OpenAI-compatible APIs.

## Architecture

FastAPI service that proxies requests to backend Ollama nodes. **No BaseService** — standalone FastAPI app with `asynccontextmanager` lifespan.

## Key components

Under `services/ollama-router/router/`:

- `main.py` — FastAPI app factory, lifespan, router registration
- `node_manager.py` — Health tracking for each Ollama node
- `model_manager.py` — Model lifecycle (preload on startup, idle unload)
- `balancer.py` — Load balancer with pluggable strategies
- `task_classifier.py` — Classifies request task type (fast/deep/code/embedding/reasoning)
- `api_ollama.py` — Ollama-native API (`/api/generate`, `/api/chat`, `/api/tags`, etc.)
- `api_openai.py` — OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`, etc.)
- `api_admin.py` — Admin endpoints (`/admin/nodes`, `/admin/models`, `/admin/reload`)
- `config.py` — Pydantic settings loaded from `config.yaml`
- `metrics.py` — Prometheus metrics endpoint

## Routing strategies

Configured in `config.yaml`:

- `model_affinity` (default) — route to the node that has the model already loaded; fall back to least-busy
- `round_robin` — cycle through healthy nodes
- `least_busy` — pick node with fewest in-flight requests

## Task-to-model mapping

`routing.task_model_map` in `config.yaml`:

| Task | Purpose |
|------|---------|
| `fast` | Quick queries — small models (e.g. `qwen2.5:7b-q4_K_M`) |
| `deep` | Complex reasoning — large models (e.g. `qwen2.5:32b-q4_K_M`) |
| `code` | Code generation — coder-tuned models |
| `embedding` | Vector embeddings — `nomic-embed-text`, `mxbai-embed-large` |
| `reasoning` | Chain-of-thought — `deepseek-r1:14b`, `qwen2.5:32b` |

## Lifecycle

- On startup: preloads configured default models on each node (when `preload_on_startup: true`)
- Idle unload: models unused for `idle_unload_minutes` (default 15) are unloaded to free VRAM/RAM
- `auto_pull: false` — models must be pre-installed on nodes; the router will NOT pull missing models

## Port

11434 (same as native Ollama — drop-in replacement for any client configured to talk to Ollama).

## Config

`services/ollama-router/config.yaml` (mounted read-only at `/app/config.yaml`). Edit on the host and restart the container — no rebuild needed. Use `GET /admin/reload` for hot config reload without restart.

## No HA/MQTT integration

This is a pure LLM infrastructure service.
