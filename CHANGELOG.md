# Changelog

All notable changes to this project will be documented in this file.

## [2026-04-17] — PR 4: Orchestrator Brain → LLM Router (feat/brain-llm-router-pr4)

### Fixed
- **orchestrator/llm**: Anthropic path now routes through llm-router (:8070) instead of
  calling the Anthropic SDK directly. This fixes the Opus 4.7 `temperature=` 400 error —
  the router normalises parameters per model capability and never forwards `temperature`
  to models that reject it.

### Changed
- **orchestrator/config**: `anthropic_model` default changed from the hallucinated
  `claude-sonnet-4-20250514` to the router alias `"sonnet"`. Router resolves this to the
  current claude-sonnet generation without the orchestrator needing to track model versions.
- **orchestrator/llm**: `create_provider("anthropic")` now returns `RouterLLMProvider`
  (new `llm/router_llm.py`) instead of `AnthropicProvider`. The `anthropic` package is
  still in requirements.txt for non-Brain use; it is no longer imported by the factory.

### Added
- **orchestrator/llm/router_llm.py**: New `RouterLLMProvider` — delegates to
  `llm-router /v1/chat/completions`, converts between unified `Message`/`LLMResponse`
  types and OpenAI-compat wire format, raises `httpx.HTTPStatusError` on router errors.
- **orchestrator/tests/test_router_llm.py**: 7 new tests — happy path, no-temperature
  assertion, tool call parsing, 503 error handling, factory routing, and message conversion.

### Scope decisions (documented)
- Gemini/OpenAI/Ollama provider paths left as direct-provider calls for this PR (they
  accept `temperature`; router migration for them deferred to a later PR to keep the
  blast radius minimal).

## [2026-04-17] — QA round 1 fixes (feat/brain-llm-router-pr4)

### Fixed

**router_llm.py: stdlib logger kwargs crash in empty-choices branch**

`logger.warning("router_llm_empty_choices", raw=str(data)[:200])` raised
`TypeError: Logger._log() got an unexpected keyword argument 'raw'` because the
orchestrator uses stdlib `logging`, not structlog. All other warning/error calls in
the file already use positional `%s` format args — this one was inconsistent.

Fix: `logger.warning("router_llm_empty_choices raw=%.200s", str(data))`

Also changed `LLMResponse(content=None)` → `LLMResponse(content=None, tool_calls=[])`
to be explicit (though the default_factory already initialises the field to `[]`).

1 new test in `tests/test_router_llm.py`:
- `test_empty_choices_returns_empty_response_no_crash` — mocks router response with
  `{"choices": []}`, asserts no exception is raised and result has `content=None`,
  `tool_calls=[]`.

## [2026-03-10] — NB9OS Dev Team Session 2

### Fixed
- **ollama-router**: Fixed KeyError `node_manager` caused by Starlette 0.52 changing `State._state` behavior. Now uses `setattr(app.state, k, v)` instead of direct `_state` dict assignment. (T1-2)
- **orchestrator**: Fixed `ev_calendar_update_skipped: reason=no_event_loop` that fired every 30min. MQTT callbacks now use `call_soon_threadsafe` for cross-thread asyncio coroutine scheduling. (B7)

### Added
- **smart-ev-charging**: Watchdog async task that monitors control loop heartbeat. If no cycle completes within the timeout (default 300s), publishes MQTT alert to `homelab/smart-ev-charging/watchdog`, registers HA binary sensor via MQTT discovery, and hard-exits to trigger Docker restart. (T1-3)

  New configuration variables:
  | Variable | Default | Description |
  |----------|---------|-------------|
  | `WATCHDOG_TIMEOUT_SECONDS` | `300` | Max seconds between control loop cycles before alert |
  | `WATCHDOG_CHECK_INTERVAL_SECONDS` | `30` | How often the watchdog checks for a heartbeat |
  | `WATCHDOG_RESTART_ON_FREEZE` | `true` | Whether to hard-exit (triggering Docker restart) on freeze |
