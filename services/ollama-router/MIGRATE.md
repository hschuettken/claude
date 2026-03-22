# Ollama Router Migration Runbook

**Status:** Preparatory documentation (router deployment pending)  
**Target Router URL:** `http://192.168.0.50:{port}/v1` (native Ollama API compatible)  
**Last Updated:** 2026-03-22

---

## Overview

The **ollama-router** service consolidates multi-node Ollama access behind a unified, intelligent proxy. Instead of services hard-coding direct Ollama URLs (e.g., `http://192.168.0.23:11434`), they connect to the router, which:

- Routes requests to available nodes based on task type, model affinity, and load
- Provides consistent OpenAI-compatible (`/v1`) and native Ollama API endpoints
- Manages model lifecycle (loading, unloading, preload on startup)
- Exposes metrics (Prometheus) for monitoring
- Handles node health checks and failover

This runbook guides each service through the migration.

---

## Router Basics

### Endpoints

The router exposes **two API styles** on the same host:

#### 1. Native Ollama API (default)
```
Base URL: http://192.168.0.50:11434
Endpoints:
  POST /api/generate         → streaming chat/completion
  POST /api/chat             → streaming chat
  POST /api/embeddings       → embeddings
  GET  /api/tags             → list available models
  POST /api/pull             → pull model from registry
  DELETE /api/delete         → delete model
  GET  /api/ps               → running models
```

#### 2. OpenAI-Compatible API (`/v1`)
```
Base URL: http://192.168.0.50:11434/v1
Endpoints:
  POST /chat/completions     → OpenAI chat format
  POST /embeddings           → OpenAI embedding format
  GET  /models               → list available models
```

### Task-Type Prefixes

The router classifies requests by task type and routes to optimal models. Services can hint at task type in three ways:

| Method | Format | Example |
|--------|--------|---------|
| **Model prefix** | `{task}/{model_name}` | `fast/qwen2.5:7b-q4_K_M` |
| **Header** | `X-Task-Type: {task}` | `X-Task-Type: deep` |
| **Auto-infer** | (no hint; router uses heuristics) | keyword detection in prompt |

#### Defined Task Types

```yaml
fast:      Quick, low-latency responses (e.g., classification, simple Q&A)
           → Models: qwen2.5:7b-q4_K_M, llama3.1:8b-q4_K_M
           
deep:      Complex reasoning, multi-step analysis
           → Models: qwen2.5:32b-q4_K_M, qwen2.5:14b-q4_K_M
           
code:      Code generation, debugging, refactoring
           → Models: qwen2.5-coder:14b-q4_K_M, qwen2.5-coder:7b-q4_K_M
           
embedding: Vector embeddings for retrieval & semantic search
           → Models: nomic-embed-text, mxbai-embed-large
           
reasoning: Complex step-by-step reasoning (e.g., R1 models)
           → Models: deepseek-r1:14b-q4_K_M, qwen2.5:32b-q4_K_M
```

---

## Service Migrations

### 1. Orchestrator Service

**Current Setup:**
- Uses shared `Settings.ollama_url` (default: `http://ollama:11434`)
- LLM provider: `llama3` (or configurable via `llm_provider`)
- Embedding provider: auto-falls back to Ollama if not using Gemini/OpenAI
- Files: `config.py`, `llm/__init__.py`, `semantic_memory.py`

**Migration Steps:**

#### Step 1: Update Configuration

Edit `.env` or service environment:
```bash
# OLD
OLLAMA_URL=http://192.168.0.23:11434

# NEW
OLLAMA_URL=http://192.168.0.50:11434
```

No code changes needed. The existing `Settings.ollama_url` field is reused.

#### Step 2: Update LLM Provider Configuration

In your orchestrator `.env`:
```bash
# Use router's OpenAI-compatible endpoint for LLM
LLM_PROVIDER=openai
OPENAI_API_KEY=ollama
OPENAI_BASE_URL=http://192.168.0.50:11434/v1
OPENAI_MODEL=fast/qwen2.5:7b-q4_K_M
# or for heavier workloads:
# OPENAI_MODEL=deep/qwen2.5:32b-q4_K_M
```

**OR** keep Ollama mode but update the URL:
```bash
LLM_PROVIDER=ollama
OLLAMA_URL=http://192.168.0.50:11434
OLLAMA_MODEL=fast/qwen2.5:7b-q4_K_M
```

#### Step 3: Embedding Provider (Semantic Memory)

The `EmbeddingProvider` in `semantic_memory.py` auto-detects Ollama and uses:
```python
base_url = f"{s.ollama_url}/v1"
model = settings.ollama_embedding_model  # e.g., "nomic-embed-text"
```

**No migration needed** — it will automatically use the router's URL.

If you want to explicitly use task-type prefix for embeddings:
```bash
OLLAMA_EMBEDDING_MODEL=embedding/nomic-embed-text
```

#### Step 4: Validation

Once deployed, test the orchestrator's LLM and embedding calls:

```bash
# 1. Test router health
curl http://192.168.0.50:11434/api/tags

# 2. Test orchestrator LLM (OpenAI-compatible)
curl -X POST http://192.168.0.50:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "fast/qwen2.5:7b-q4_K_M",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# 3. Test embeddings
curl -X POST http://192.168.0.50:11434/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "embedding/nomic-embed-text",
    "input": "Hello world"
  }'
```

---

### 2. Atlas Helper Tools – WebSearch Service

**Current Setup:**
- Summarizer backend: `OllamaSummarizer` (in `summarizer.py`)
- Config: `LLM_WEBSEARCH_OLLAMA_URL`, `LLM_WEBSEARCH_OLLAMA_MODEL`, etc.
- Files: `src/llm_websearch/summarizer.py`, `diagnose.py`, `src/llm_websearch/config.py`

**Migration Steps:**

#### Step 1: Update Environment Variables

Edit `.env` or Docker compose for the websearch service:
```bash
# OLD
LLM_WEBSEARCH_OLLAMA_URL=http://192.168.0.20:11434
LLM_WEBSEARCH_OLLAMA_MODEL=qwen2:0.5b
LLM_WEBSEARCH_OLLAMA_FAST_MODEL=qwen2:0.5b
LLM_WEBSEARCH_OLLAMA_DEEP_MODEL=qwen2:7b-q4_K_M

# NEW
LLM_WEBSEARCH_OLLAMA_URL=http://192.168.0.50:11434
LLM_WEBSEARCH_OLLAMA_MODEL=fast/qwen2:0.5b
LLM_WEBSEARCH_OLLAMA_FAST_MODEL=fast/qwen2.5:7b-q4_K_M
LLM_WEBSEARCH_OLLAMA_DEEP_MODEL=deep/qwen2.5:32b-q4_K_M
```

#### Step 2: Task-Type Prefixes in Summarizer

The `OllamaSummarizer._generate()` method calls:
```python
self.base_url = settings.ollama_url.rstrip("/")
self.model = model or settings.ollama_model
```

When you set:
```bash
LLM_WEBSEARCH_OLLAMA_FAST_MODEL=fast/qwen2.5:7b-q4_K_M
LLM_WEBSEARCH_OLLAMA_DEEP_MODEL=deep/qwen2.5:32b-q4_K_M
```

The router's `classify_request()` function will:
1. Detect the `fast/` or `deep/` prefix
2. Strip it and resolve the model name from the task routing table
3. Route the request to the appropriate node

**No code changes needed** — prefixes are handled transparently.

#### Step 3: Context Length (Important)

The `OllamaSummarizer` respects `LLM_WEBSEARCH_OLLAMA_CONTEXT_LENGTH`:
```bash
LLM_WEBSEARCH_OLLAMA_CONTEXT_LENGTH=4096
```

Ensure this matches the actual model's context window:
- `qwen2:0.5b` → ~2048 tokens
- `qwen2.5:7b-q4_K_M` → ~4096 tokens (or higher, check model card)
- `qwen2.5:32b-q4_K_M` → ~8192 tokens

The websearch service dynamically sizes prompts to fit, so **if in doubt, check the model's specs** and update the env var.

#### Step 4: Validation

Test the websearch summarizer:

```bash
# 1. Start a test query with debug logging
curl -X POST http://websearch-service:8080/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "latest AI research",
    "summarizer": "ollama",
    "task_type": "fast"
  }'

# 2. Check diagnose output
curl http://websearch-service:8080/diagnose
# Should show:
#   [2/N] Ollama (http://192.168.0.50:11434) ... OK
#   - Reachable: yes
#   - Model qwen2.5:7b-q4_K_M loaded: yes
```

---

### 3. Other Services Using Ollama

If you have additional services that use Ollama directly, follow this pattern:

#### Generic Migration Template

**Step 1: Locate Ollama URL**
```bash
grep -rn "ollama_url\|OLLAMA_URL\|11434" /path/to/service/ \
  --include="*.py" --include="*.yaml" --include="*.env"
```

**Step 2: Update Configuration**

If your service directly constructs Ollama URLs:
```python
# OLD
base_url = "http://192.168.0.23:11434"

# NEW
base_url = os.getenv("OLLAMA_URL", "http://192.168.0.50:11434")
```

Or update your `.env`:
```bash
OLLAMA_URL=http://192.168.0.50:11434
```

**Step 3: Use Task-Type Prefixes**

When selecting a model for a request, include the task type:

```python
# OLD
model = "qwen2:7b"

# NEW (fast request)
model = "fast/qwen2.5:7b-q4_K_M"

# OR (reasoning-heavy request)
model = "reasoning/deepseek-r1:14b-q4_K_M"
```

**Step 4: Test**

```bash
# Test native Ollama API
curl http://192.168.0.50:11434/api/tags

# Test OpenAI-compatible API (if your service uses it)
curl http://192.168.0.50:11434/v1/models
```

---

## API Usage Examples

### Example 1: Generate Completion (Native Ollama API)

```bash
curl -X POST http://192.168.0.50:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "fast/qwen2.5:7b-q4_K_M",
    "prompt": "What is Artificial Intelligence?",
    "stream": false
  }' | jq '.response'
```

### Example 2: Chat Completion (OpenAI-Compatible)

```bash
curl -X POST http://192.168.0.50:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "X-Task-Type: deep" \
  -d '{
    "model": "qwen2.5:32b-q4_K_M",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Explain quantum mechanics in simple terms."}
    ],
    "temperature": 0.7,
    "max_tokens": 1024
  }'
```

### Example 3: Embeddings

```bash
curl -X POST http://192.168.0.50:11434/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{
    "model": "embedding/nomic-embed-text",
    "input": "The quick brown fox jumps over the lazy dog"
  }' | jq '.data[0].embedding'
```

### Example 4: List Available Models

```bash
curl http://192.168.0.50:11434/api/tags | jq '.models[].name'
```

---

## Troubleshooting

### Symptom: "Connection refused" or timeout

**Causes:**
- Router not deployed yet
- Wrong IP address (check `192.168.0.50` is correct for your setup)
- Firewall blocking port 11434

**Remediation:**
```bash
# Check router is running
curl -I http://192.168.0.50:11434/api/tags

# Verify from orchestrator/websearch container
docker exec <container_id> curl http://192.168.0.50:11434/api/tags
```

### Symptom: "Model not found" error

**Causes:**
- Task-type prefix doesn't match configured routing table
- Model not loaded on any node
- Typo in model name

**Remediation:**
```bash
# Check available models
curl http://192.168.0.50:11434/api/tags | jq '.models[].name'

# Verify model is loaded on a node
curl http://192.168.0.50:11434/api/ps | jq '.models[]'

# Check router config for task mappings
curl http://192.168.0.50:11434/admin/config | jq '.routing.task_model_map'
```

### Symptom: Slow responses or inconsistent latency

**Causes:**
- Node overloaded
- Model not in memory (cold start)
- Network latency to router or backend nodes

**Remediation:**
```bash
# Check node status & load
curl http://192.168.0.50:11434/admin/status | jq '.nodes[]'

# Check metrics
curl http://192.168.0.50:11434/metrics

# Verify balancer strategy (should route to least-loaded node)
curl http://192.168.0.50:11434/admin/config | jq '.routing.default_strategy'
```

### Symptom: Embeddings returning different dimensions

**Cause:**
- Using different embedding models or older Ollama API

**Remediation:**
- Ensure `embedding/` prefix routes to consistent models: `nomic-embed-text` (768 dims) or `mxbai-embed-large` (1024 dims)
- Update websearch or orchestrator config to use one consistently

---

## Deployment Checklist

- [ ] Router deployed and running on `192.168.0.50:11434`
- [ ] All target Ollama nodes reachable and configured in router's `config.yaml`
- [ ] Task routing table populated (see `config.yaml` `routing.task_model_map`)
- [ ] Models preloaded on startup (check `lifecycle.preload_on_startup: true`)
- [ ] Router health endpoint responding: `curl http://192.168.0.50:11434/api/tags`
- [ ] Orchestrator `.env` updated with router URL
- [ ] Orchestrator embedding provider tested
- [ ] WebSearch service `.env` updated with router URL and task-type models
- [ ] WebSearch summarizer tested with fast/deep task types
- [ ] Other services identified and migrated (if any)
- [ ] Monitoring/alerting configured (Prometheus metrics available at `/metrics`)
- [ ] Fallback plan documented (if router goes down, revert to direct Ollama URLs)

---

## Rollback Plan

If the router fails or causes issues:

1. **Revert to direct Ollama URLs** immediately:
   ```bash
   # In orchestrator .env
   OLLAMA_URL=http://192.168.0.23:11434  # or original address
   
   # In websearch .env
   LLM_WEBSEARCH_OLLAMA_URL=http://192.168.0.20:11434
   ```

2. **Restart services:**
   ```bash
   docker-compose restart orchestrator websearch
   ```

3. **No code changes required** — configuration is external.

---

## References

- **Router Source:** `/home/hesch/.openclaw/workspace-nb9os/claude/services/ollama-router/`
- **Task Classifier:** `router/task_classifier.py` (prefix/header/auto-detection logic)
- **Orchestrator:** `/home/hesch/.openclaw/workspace-nb9os/claude/services/orchestrator/`
  - LLM provider: `llm/__init__.py`
  - Embeddings: `semantic_memory.py`
- **WebSearch:** `/home/hesch/.openclaw/workspace-nb9os/atlas_helper_tools/services/websearch/`
  - Summarizer: `src/llm_websearch/summarizer.py`
  - Config: `src/llm_websearch/config.py`
- **Shared Config:** `/home/hesch/.openclaw/workspace-nb9os/claude/shared/config.py` (base `Settings` with `ollama_url`)

---

**Migration Owner:** dev-3  
**Approval Required From:** architect  
**Expected Completion:** Post-router deployment
