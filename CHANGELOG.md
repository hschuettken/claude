# Changelog

All notable changes to this project will be documented in this file.

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
