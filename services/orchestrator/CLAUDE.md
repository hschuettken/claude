# orchestrator — AI-Powered Home Brain & Coordinator

The central intelligence layer that coordinates all services, communicates with users via Telegram, and makes proactive suggestions. Uses an LLM (Gemini by default, swappable) with function-calling to reason about the home state and interact with Home Assistant.

**Architecture**: Brain (LLM + tools) ↔ Telegram (user I/O) ↔ Proactive Engine (scheduled), all backed by Memory (persistent profiles/conversations) and connected to HA/InfluxDB/MQTT.

## LLM Providers

Configured via `LLM_PROVIDER` env var:

| Provider | Model Default | Env Var for API Key |
|----------|--------------|---------------------|
| `gemini` (default) | `gemini-2.0-flash` | `GEMINI_API_KEY` |
| `openai` | `gpt-4o` | `OPENAI_API_KEY` |
| `anthropic` | `claude-sonnet-4-20250514` | `ANTHROPIC_API_KEY` |
| `ollama` | `llama3` | — (uses `OLLAMA_URL`) |

## LLM Tools

Functions the AI can call to interact with the home:

- `get_entity_state` — Read any HA entity
- `get_home_energy_summary` — Full energy snapshot (PV, grid, battery, EV, house)
- `get_pv_forecast` — Today/tomorrow solar forecast with hourly breakdown
- `get_ev_charging_status` — Current EV charge mode, power, session energy
- `set_ev_charge_mode` — Change EV charge mode (with user confirmation)
- `get_ev_forecast_plan` — EV driving forecast, predicted trips, and charging plan (from ev-forecast via MQTT)
- `respond_to_ev_trip_clarification` — Forward user's answer to ev-forecast trip question
- `get_weather_forecast` — Current weather and short-term forecast
- `query_energy_history` — Historical data from InfluxDB (trends/analysis)
- `call_ha_service` — Control any HA device (with user confirmation)
- `get_user_preferences` / `set_user_preference` — Persistent user preferences
- `send_notification` — Send Telegram message to a specific user
- `get_energy_prices` — Grid, feed-in, EPEX spot, oil prices
- `get_calendar_events` — Read family or orchestrator Google Calendar events
- `check_household_availability` — Check who is home/away
- `create_calendar_event` — Create reminders/events on orchestrator's own calendar
- `recall_memory` — Semantic search over long-term memory
- `store_fact` — Store knowledge/facts in long-term semantic memory
- `store_learned_fact` — Store structured knowledge (destinations, patterns, preferences) in the knowledge store for cross-service use
- `get_learned_facts` — Query structured knowledge store before asking the user
- `update_memory_notes` / `read_memory_notes` — Maintain orchestrator's persistent memory.md notebook
- `request_service_refresh` — Send a command to a service (refresh forecast, retrain model, etc.)

## Communication

Telegram bot with commands `/start`, `/status`, `/forecast`, `/clear`, `/whoami`, `/help` plus free-text LLM conversation.

## Proactive Features

- **Morning briefing** (configurable time) — weather, PV forecast, energy plan for the day
- **Evening summary** — today's production, grid usage, savings
- **Optimization alerts** — excess PV, idle EV, battery strategy opportunities
- **EV charging calendar events** — auto-creates/updates all-day events on orchestrator calendar when ev-forecast reports charging needs. German summaries (e.g., "EV: 15 kWh laden bis 07:00 (Nicole → Lengerich)"). Deduplicated by tracking `{date: {event_id, summary}}` — only updated when the summary text changes. Stale events deleted when a date no longer needs charging.
- **EV trip clarification** — forwards ambiguous trip questions from ev-forecast to Telegram users. The Brain LLM recognizes context (pending clarifications injected into system prompt) and calls `respond_to_ev_trip_clarification` to route the answer back via MQTT.
- **Memory consolidation** — at 3 AM nightly, older conversation memories are grouped and merged by the LLM into denser entries

## Memory

Persistent in `/app/data/memory/`:

- Per-user conversation history (configurable max length)
- User profiles with learned preferences (sauna days, wake times, departure times)
- Decision log (what the orchestrator decided and why)

### Semantic Memory

Vector-based long-term recall, persistent in `/app/data/memory/semantic_store.json`:

- Embeds conversation snippets, learned facts, and decisions as vectors for semantic retrieval
- Uses the configured LLM provider's embedding API: Gemini `text-embedding-004` (default), OpenAI `text-embedding-3-small`, or Ollama `nomic-embed-text`
- Pure-Python cosine similarity — no heavy deps (ChromaDB/FAISS/PyTorch not needed)
- **LLM summarization**: conversations are distilled into concise memory entries before storage, producing better search results and less noise
- **Time-weighted scoring**: cosine similarity (85%) blended with recency (15%, 30-day half-life)
- **Nightly consolidation** at 3 AM: older conversation memories grouped and merged into denser entries (e.g. 50 EV charging conversations → 2-3 consolidated knowledge entries)
- LLM can explicitly store facts via `store_fact` and search via `recall_memory`
- Relevant memories auto-injected into LLM context before each response (similarity ≥ 0.5)
- Categories: `conversation`, `fact`, `decision`
- Scale: up to 5000 entries (~20 MB JSON), searches in milliseconds
- Enable/disable via `ENABLE_SEMANTIC_MEMORY` (default true)

### Smart Conversation Memory

Two complementary layers on top of semantic memory that close the learning feedback loop:

- **Knowledge Store** (`knowledge.py`, `/app/data/memory/knowledge.json`): Typed, structured facts that services can query programmatically. Types: `destination` (place + distance), `person_pattern`, `preference`, `correction`, `general`. Published via MQTT (`homelab/orchestrator/knowledge-update`) so downstream services consume learned knowledge automatically.
- **Memory Document** (`memory.md`, `/app/data/memory/memory.md`): A living Markdown document the LLM reads and maintains — like CLAUDE.md but for the AI's own notes. Injected into the system prompt on every conversation. Updated via `update_memory_notes`. Capped at 4000 chars (`MEMORY_DOCUMENT_MAX_SIZE`).

**Auto-extraction**: After each conversation turn, the LLM extracts structured facts (destinations with distances, person patterns, preferences, corrections) and stores them with confidence=0.7 (LLM-inferred). User-confirmed facts get confidence=1.0.

**Trip clarification auto-learning**: When a clarification is resolved (user confirms distance via Telegram), the destination+distance is stored in the knowledge store AND published to ev-forecast, so the same question never needs asking again.

**Cross-service knowledge distribution**: ev-forecast subscribes to `homelab/orchestrator/knowledge-update` and maintains a local `learned_destinations.json` cache. On distance lookup: config destinations → learned destinations → geocoding → default 50km.

**Smart disambiguation**: When learned destinations have multiple entries for the same name (e.g., "Sarah" → Bocholt 80km, "Sarah" → Ibbenbüren 10km), ev-forecast generates disambiguation questions.

**Config env vars**: `ENABLE_KNOWLEDGE_STORE` (default true), `MEMORY_DOCUMENT_MAX_SIZE` (4000), `KNOWLEDGE_AUTO_EXTRACT` (true)

## Google Calendar

Optional, via Service Account:

- Family calendar (read-only) — absences, business trips, appointments
- Orchestrator calendar (read/write) — reminders, scheduled actions
- Uses `google-api-python-client` with Service Account auth (no interactive OAuth)

### Setup

1. **Google Cloud Console** — create project, enable Calendar API, create Service Account, download JSON key, note the service account email.

2. **Share the family calendar** (read-only)
   - Google Calendar → hover calendar → Settings → Share with specific people → add service account email → "See all event details" → copy Calendar ID

3. **Create the orchestrator calendar** (read/write)
   - Click + next to "Other calendars" → Create new calendar → "Home Orchestrator"
   - Share with the service account email with "Make changes to events"
   - Copy the Calendar ID

4. **Deploy credentials** — either file mount (`docker cp key.json orchestrator:/app/data/google-credentials.json`) or base64 env var (`base64 -w0 key.json` → `GOOGLE_CALENDAR_CREDENTIALS_JSON`)

5. **Configure `.env`**:
   ```
   GOOGLE_CALENDAR_CREDENTIALS_FILE=/app/data/google-credentials.json
   GOOGLE_CALENDAR_FAMILY_ID=<family calendar ID>
   GOOGLE_CALENDAR_ORCHESTRATOR_ID=<orchestrator calendar ID>
   ```

6. **Verify**: `docker compose restart orchestrator && docker compose logs -f orchestrator` → look for `google_calendar_enabled  family_cal=True  orchestrator_cal=True`

## MQTT

Subscribes to `homelab/+/heartbeat` and `homelab/+/updated` to track all service states. Also subscribes to `homelab/ev-forecast/plan` (creates calendar events for charging needs) and `homelab/ev-forecast/clarification-needed` (forwards trip questions).

## HA entities

Via MQTT auto-discovery, "Home Orchestrator" device, 15 entities:

- `binary_sensor` — Service online/offline, Proactive Suggestions enabled, Morning/Evening Briefing enabled
- `sensor` — Uptime, LLM Provider, Messages Today, Tool Calls Today, Suggestions Sent Today, Last Tool Used, Last Decision, Last Suggestion, Services Online
- `sensor` (reasoning) — Orchestrator Reasoning (with `full_reasoning`, `services_tracked`, `last_decision_time` as JSON attributes)

## REST API + MCP Server

Optional, port 8100. Exposes orchestrator capabilities for programmatic access and AI agent integration (OpenClaw).

- **REST API** at `/api/v1/*` — standard HTTP endpoints
- **MCP server** at `/mcp` — Model Context Protocol (SSE transport)

Both require `X-API-Key` header. API server only starts when `ORCHESTRATOR_API_KEY` is configured.

REST endpoints:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/_health` | Healthcheck (no auth) |
| `GET` | `/api/v1/status` | Service status + activity |
| `GET` | `/api/v1/tools` | List all tools with schemas |
| `GET` | `/api/v1/vision` | NB9OS Home Brain vision + live area status |
| `POST` | `/api/v1/tools/execute` | Execute a tool directly (bypasses LLM) |
| `POST` | `/api/v1/chat` | Full Brain reasoning loop |

MCP tools: all 23 orchestrator tools + `chat_with_orchestrator` (full Brain reasoning).

MCP resources: `homelab://status`, `homelab://energy`, `homelab://pv-forecast`, `homelab://ev-charging`, `homelab://ev-forecast`, `homelab://weather`, `homelab://energy-prices`, `homelab://tools`.

**Access**: `http://<server-ip>:8100` directly, or via Traefik at `https://api.local.schuettken.net`.

OpenClaw MCP config:
```json
{
  "mcpServers": {
    "homelab": {
      "url": "http://orchestrator:8100/mcp/sse",
      "headers": {"X-API-Key": "YOUR_KEY"}
    }
  }
}
```

## Config env vars

`LLM_PROVIDER`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_CHAT_IDS`, `MORNING_BRIEFING_TIME`, `ENABLE_PROACTIVE_SUGGESTIONS`, `ENABLE_SEMANTIC_MEMORY`, `ENABLE_KNOWLEDGE_STORE`, `MEMORY_DOCUMENT_MAX_SIZE`, `KNOWLEDGE_AUTO_EXTRACT`, `GRID_PRICE_CT`, `FEED_IN_TARIFF_CT`, `OIL_PRICE_PER_KWH_CT`, `HOUSEHOLD_USERS`, `GOOGLE_CALENDAR_CREDENTIALS_FILE`, `GOOGLE_CALENDAR_FAMILY_ID`, `GOOGLE_CALENDAR_ORCHESTRATOR_ID`, `ORCHESTRATOR_API_KEY`, `ORCHESTRATOR_API_PORT` (8100), `ORCHESTRATOR_API_HOST` (0.0.0.0). Most entity IDs have sensible defaults.

## Example use cases

- "Do you need to charge your car tomorrow?" → checks PV forecast, EV battery, schedule
- "Can you turn on the wood-firing oven tomorrow at 5 PM to save oil?" → weather check, heating demand analysis
- "Do you need your sauna tomorrow, or can we use more PV for the IR panels?" → preference check, PV forecast comparison
- "How much did PV save us this month?" → InfluxDB historical query + cost calculation
