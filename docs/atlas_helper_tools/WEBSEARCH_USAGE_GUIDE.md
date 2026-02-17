# LLM WebSearch — Usage Guide

> **Audience**: Other services, tools, and repos in the ecosystem that want to use the LLM WebSearch API.
> For internal architecture details see `ARCHITECTURE_GUIDELINES.md`. For dependency info see `TOOLS_AND_STACK.md`.

## Overview

LLM WebSearch is a self-hosted, Tavily-compatible web search pipeline. It connects SearXNG (meta-search), content extraction, optional LLM summarization, and SQLite persistence behind a single REST API.

**Base URLs**:
- **Traefik (preferred)**: `https://scout.local.schuettken.net` — reverse-proxied via Traefik on docker1
- **Direct**: `http://<host>:8888` (default: `http://192.168.0.50:8888` on docker1, or `http://localhost:8888` locally)
- **Docker internal**: `http://llm-websearch:8888` (from containers on the same Docker network)

---

## Quick Integration

### Drop-in Tavily replacement

Any tool that supports the Tavily API can switch to LLM WebSearch by changing the base URL:

```python
# Before (Tavily)
response = httpx.post("https://api.tavily.com/search", json={"query": "...", "api_key": "..."})

# After (LLM WebSearch) — no API key needed
response = httpx.post("http://localhost:8888/search", json={"query": "..."})
```

The `POST /search` endpoint accepts the same request schema and returns the same response schema as Tavily.

### Get LLM-ready context in one call

```python
resp = httpx.get("http://localhost:8888/context", params={"q": "solar panel efficiency 2025"})
llm_context = resp.json()["context"]  # pre-formatted markdown, ready for prompt injection
```

### MCP integration (Claude Desktop / openClawd)

```json
{
  "mcpServers": {
    "websearch": {
      "command": "llm-websearch",
      "args": ["mcp"]
    }
  }
}
```

---

## REST API Reference

### Search Endpoints

#### `POST /search` — Tavily-compatible search

The primary integration point. Supports all Tavily fields plus SearXNG extensions.

**Request body**:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | *required* | Search query |
| `search_depth` | `"basic"` \| `"advanced"` | `"basic"` | Basic = quick/standard; advanced = standard/deep |
| `include_answer` | bool | `true` | Include LLM-generated answer (requires summarizer backend) |
| `include_raw_content` | bool | `false` | Include full extracted text per result |
| `max_results` | int (1-20) | `5` | Number of results to return |
| `include_domains` | string[] | `[]` | Only include these domains |
| `exclude_domains` | string[] | `[]` | Exclude these domains |
| `categories` | string \| null | `null` | SearXNG category: general, news, science, it, files, images, music, social media |
| `time_range` | string \| null | `null` | Filter: `day`, `week`, `month`, `year` |
| `engines` | string[] \| null | `null` | Specific engines: google, bing, duckduckgo, wikipedia, arxiv, etc. |

**Search depth → pipeline mode mapping**:

| `search_depth` | `include_answer` | Pipeline mode | What happens |
|---|---|---|---|
| `basic` | `false` | quick | SearXNG snippets only |
| `basic` | `true` | standard | + page fetch & extraction |
| `advanced` | `false` | standard | + page fetch & extraction |
| `advanced` | `true` | deep | + per-page & aggregate LLM summaries |

**Response**:

```json
{
  "query": "solar panel efficiency",
  "answer": "Based on multiple sources, solar panel efficiency...",
  "results": [
    {
      "title": "Solar Panel Efficiency in 2025",
      "url": "https://example.com/solar",
      "content": "Extracted text or summary (up to ~2000 chars)...",
      "raw_content": "",
      "score": 0.85
    }
  ],
  "response_time": 2.34,
  "images": []
}
```

**Example**:

```bash
curl -X POST http://localhost:8888/search \
  -H "Content-Type: application/json" \
  -d '{"query": "home automation KNX vs Zigbee", "search_depth": "advanced", "include_answer": true, "max_results": 5}'
```

---

#### `GET /search` — Convenience endpoint

Same response format, simpler query-param interface.

| Param | Default | Description |
|-------|---------|-------------|
| `q` | *required* | Search query |
| `mode` | `standard` | `quick` \| `standard` \| `deep` |
| `max_results` | `5` | 1-20 |
| `categories` | — | SearXNG category |
| `time_range` | — | `day` \| `week` \| `month` \| `year` |

```bash
curl "http://localhost:8888/search?q=python+asyncio+best+practices&mode=standard&max_results=3"
```

---

#### `GET /context` — LLM-ready text

Returns pre-formatted markdown optimized for injecting into an LLM prompt. No post-processing needed.

| Param | Default | Description |
|-------|---------|-------------|
| `q` | *required* | Search query |
| `mode` | `standard` | `quick` \| `standard` \| `deep` |
| `max_results` | `5` | 1-20 |

**Response**:

```json
{
  "query": "solar panel efficiency",
  "context": "# Web Search Results: solar panel efficiency\n\n## Sources\n### [1] ...",
  "response_time": 1.87
}
```

The `context` field contains structured markdown:

```markdown
# Web Search Results: {query}

## Summary                                    # deep mode only
{aggregated answer from LLM}

## Sources                                    # standard/deep mode
### [1] {title}
URL: {url}
{summary or extracted text, up to 2000 chars}

### [2] {title}
...

## Results                                    # quick mode (no page fetch)
### [1] {title}
URL: {url}
{SearXNG snippet}

## Warnings                                   # only if errors occurred
- {error description}
```

**This is the recommended endpoint for LLM tool-use integrations.** The output is designed to be token-efficient and factually organized.

---

### Health & Status

#### `GET /health`

```json
{
  "healthy": true,
  "services": [
    {"name": "searxng", "healthy": true, "latency_ms": 45.2, "detail": "OK — http://192.168.0.29"},
    {"name": "none", "healthy": true, "latency_ms": 0, "detail": "no check needed"}
  ],
  "timestamp": "2026-02-17T10:30:00+00:00"
}
```

#### `GET /stats`

```json
{
  "total_searches": 142,
  "total_pages": 580,
  "active_jobs": 3,
  "total_words": 1250000,
  "diffs_with_changes": 28,
  "total_tags": 5
}
```

---

### Search History

#### `GET /history?limit=20`

Returns recent searches as a list:

```json
[
  {
    "id": 42,
    "query": "home battery systems",
    "mode": "standard",
    "result_count": 5,
    "total_time": 2.1,
    "timestamp": "2026-02-17T09:00:00+00:00"
  }
]
```

#### `GET /history/search?q=solar&limit=10`

Full-text search across all stored page content. Returns matching pages with highlighted snippets.

#### `GET /history/{search_id}`

Full detail for a single search including all individual results. Returns 404 if not found.

---

### Scheduled Jobs

Schedule recurring searches that run automatically. Results are stored and diffed.

#### `GET /jobs` — List all jobs

#### `POST /jobs` — Create a job

| Param | Default | Description |
|-------|---------|-------------|
| `name` | *required* | Unique job identifier |
| `query` | *required* | Search query to run |
| `interval_minutes` | `60` | Minutes between runs |
| `categories` | `"general"` | SearXNG category |
| `mode` | `"standard"` | Pipeline mode |

```bash
curl -X POST "http://localhost:8888/jobs?name=ev-news&query=electric+vehicle+news&interval_minutes=120&mode=standard"
```

#### `DELETE /jobs/{name}` — Remove a job

---

### Diff Detection

Track what changed between scheduled search runs — new URLs, removed URLs, content changes.

#### `GET /diff?query=...&job_name=...&limit=20`

Returns diff reports. Both `query` and `job_name` are optional filters.

```json
[
  {
    "id": 7,
    "query": "electric vehicle news",
    "job_name": "ev-news",
    "new_count": 3,
    "removed_count": 1,
    "changed_count": 0,
    "timestamp": "2026-02-17T10:00:00+00:00",
    "diff_detail": {
      "new_urls": [{"url": "...", "title": "...", "snippet": "..."}],
      "removed_urls": [{"url": "...", "title": "..."}],
      "changed_urls": []
    }
  }
]
```

#### `GET /diff/latest?query=...`

Returns the most recent diff for a specific query.

---

### RSS / Atom Feeds

#### `GET /feed/{job_name}?fmt=rss`

Returns XML feed of a scheduled job's search results. Useful for feed readers or monitoring dashboards.

| Param | Default | Options |
|-------|---------|---------|
| `fmt` | `rss` | `rss`, `atom` |

```bash
curl "http://localhost:8888/feed/ev-news?fmt=atom" -o ev-news.atom.xml
```

---

### Tags

Organize searches and URLs with labels.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tags` | GET | List all tags |
| `/tags?name=important&color=#ef4444` | POST | Create tag |
| `/tags/{tag_name}/items?item_type=url&item_id=https://...` | POST | Tag a URL |
| `/tags/{tag_name}/items` | GET | List items with tag |
| `/tags/{tag_name}` | DELETE | Delete tag |

---

## MCP Server (Model Context Protocol)

For Claude Desktop, openClawd, or any MCP-compatible client. Transport: JSON-RPC 2.0 over stdio.

### Setup

```json
{
  "mcpServers": {
    "websearch": {
      "command": "llm-websearch",
      "args": ["mcp"]
    }
  }
}
```

### Available Tools

#### `web_search`

Standard search. Returns extracted page content as markdown context.

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | yes | — | Search query |
| `max_results` | int | no | 5 | 1-20 |
| `categories` | string | no | `"general"` | SearXNG category |
| `time_range` | string | no | — | `day` \| `week` \| `month` \| `year` |

#### `web_search_deep`

Full pipeline with LLM summarization. Slower, but returns an aggregated answer.

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `query` | string | yes | — | Search query |
| `max_results` | int | no | 5 | 1-10 |

#### `search_knowledge_base`

Search previously stored content. Does **not** hit the web — searches the local SQLite database.

| Input | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `keyword` | string | yes | — | Full-text search keyword |
| `limit` | int | no | 10 | Max results |

#### `health_check`

No inputs. Returns service status markdown.

All MCP tools return pre-formatted markdown text (same format as `GET /context`).

---

## CLI Usage

Install: `pip install -e services/websearch` or use the Docker container.

### Quick examples

```bash
# Search from the terminal
llm-websearch search "home assistant KNX integration" --mode standard --output table

# Get JSON output for piping
llm-websearch search "python structlog tutorial" --output json

# Get LLM-ready context
llm-websearch search "solar forecasting ML" --output context

# Check service health
llm-websearch health

# Start the API server
llm-websearch serve --port 8888

# Schedule a recurring search
llm-websearch schedule add --name daily-tech --query "technology news" --interval 1440

# Run a scheduled job immediately
llm-websearch schedule run daily-tech

# Search stored content (offline)
llm-websearch history search "machine learning"

# View what changed between runs
llm-websearch diff detail "technology news"
```

### CLI output formats

The `--output` flag on the `search` command supports:

| Format | Description | Best for |
|--------|-------------|----------|
| `table` | Rich-formatted terminal table | Human reading |
| `json` | Tavily-compatible JSON | Piping to other tools |
| `context` | LLM-ready markdown | Feeding to an LLM |

---

## Integration Patterns

### Python (httpx)

```python
import httpx

WEBSEARCH_URL = "http://localhost:8888"

def web_search(query: str, max_results: int = 5) -> dict:
    """Tavily-compatible search."""
    resp = httpx.post(f"{WEBSEARCH_URL}/search", json={
        "query": query,
        "search_depth": "basic",
        "max_results": max_results,
    })
    resp.raise_for_status()
    return resp.json()

def get_context(query: str) -> str:
    """Get LLM-ready context string."""
    resp = httpx.get(f"{WEBSEARCH_URL}/context", params={"q": query})
    resp.raise_for_status()
    return resp.json()["context"]

def deep_search(query: str) -> dict:
    """Search with AI summarization."""
    resp = httpx.post(f"{WEBSEARCH_URL}/search", json={
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "max_results": 5,
    })
    resp.raise_for_status()
    return resp.json()
```

### From the orchestrator (LLM tool call)

```python
# In an LLM tool definition
def search_web(query: str) -> str:
    """Search the web and return context for the LLM."""
    resp = httpx.get("http://localhost:8888/context", params={
        "q": query,
        "mode": "standard",
        "max_results": 5,
    })
    return resp.json()["context"]
```

### curl one-liners

```bash
# Quick search
curl -s "http://localhost:8888/search?q=weather+tomorrow&mode=quick" | jq '.results[].title'

# Deep search with answer
curl -s -X POST http://localhost:8888/search \
  -H "Content-Type: application/json" \
  -d '{"query":"best home battery 2025","search_depth":"advanced","include_answer":true}' \
  | jq '.answer'

# Health check
curl -s http://localhost:8888/health | jq '.healthy'

# LLM context
curl -s "http://localhost:8888/context?q=python+best+practices&max_results=3" | jq -r '.context'
```

### n8n / workflow automation

Use the HTTP Request node:
- **URL**: `http://llm-websearch:8888/search` (Docker network name)
- **Method**: POST
- **Body**: `{"query": "{{$node.trigger.json.query}}", "max_results": 5}`

---

## Search Modes Explained

| Mode | What it does | Speed | Token cost | Best for |
|------|-------------|-------|-----------|----------|
| **quick** | SearXNG snippets only | ~1s | 0 | Fast lookups, URL discovery, existence checks |
| **standard** | + fetch pages + extract clean text | ~3-5s | 0 | Research, fact-checking, content gathering |
| **deep** | + per-page LLM summary + aggregate answer | ~15-60s (CPU) | ~500-1500 tokens | Complex questions needing synthesis |

**Recommendation**: Use `standard` for most integrations. Use `quick` for high-volume or latency-sensitive cases. Use `deep` only when you need a synthesized answer and have an LLM backend configured.

---

## Configuration for Consumers

### Access methods

| From | URL | Notes |
|------|-----|-------|
| Same Docker network | `http://llm-websearch:8888` | Fastest, no TLS overhead |
| Host or another VM | `https://scout.local.schuettken.net` | Via Traefik, preferred |
| Host (direct) | `http://192.168.0.50:8888` | Bypasses Traefik |
| Local development | `http://localhost:8888` | When running locally |

No authentication is required. CORS is open (`*`).

### Traefik reverse proxy

The websearch API is exposed via Traefik at **`https://scout.local.schuettken.net`**. This requires:

1. The Traefik stack running on docker1 (192.168.0.50)
2. DNS resolving `scout.local.schuettken.net` to the docker1 IP (via Pi-hole, local DNS, or `/etc/hosts`)
3. The external `traefik` Docker network existing (`docker network create traefik`)

HTTP requests are automatically redirected to HTTPS.

### Environment variables (for Docker consumers)

```env
# Point your service to websearch (preferred — via Traefik)
WEBSEARCH_URL=https://scout.local.schuettken.net
# Or from the same Docker network
WEBSEARCH_URL=http://llm-websearch:8888
# Or direct (bypasses Traefik)
WEBSEARCH_URL=http://192.168.0.50:8888
```

---

## Limitations & Notes

- **Summarization requires Ollama**: Deep mode only produces AI summaries if `summarizer_backend=ollama` (or `claude`) is configured. Default is `none` (passthrough truncation).
- **Current LLM**: qwen2:0.5b on CPU — deep mode is slow (~30-60s) and summaries are basic. Upgrading the model will automatically improve quality (just change config).
- **Rate limiting**: No built-in rate limiting. SearXNG has its own rate limiting per engine.
- **No auth**: The API has no authentication. Secure via network-level controls (firewall, Docker network isolation).
- **SQLite**: Single-writer. Fine for homelab use, not for high-concurrency production.
