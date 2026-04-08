# dashboard — NiceGUI Web Dashboard

A modern dark-themed web dashboard built with [NiceGUI](https://nicegui.io/) (Python, Quasar/Vue under the hood). Real-time monitoring, Home Assistant controls, and a chat interface to the orchestrator — all in the browser.

**Tech stack**: NiceGUI 2.x (FastAPI + uvicorn + Quasar + Vue + Tailwind). Pure Python, no separate frontend build step.

## Pages

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `/` | Energy overview (PV, grid, battery, house, EV), PV forecast, EV charging status, service health mini-view |
| Services | `/services` | Service health grid with status, uptime, memory, last heartbeat. Orchestrator activity section. |
| Controls | `/controls` | EV charging controls (charge mode, target SoC, departure time, full-by-morning), quick actions (refresh/retrain), safe mode toggle |
| Chat | `/chat` | Chat with the orchestrator AI via MQTT. Quick prompts, markdown rendering, typing indicator. |

## Architecture

**Does NOT use BaseService.** Creates MQTT, HA, and InfluxDB clients manually and integrates with NiceGUI's lifecycle via `app.on_startup` / `app.on_shutdown`. MQTT callbacks update a thread-safe `DashboardState` object; NiceGUI pages poll the state with `ui.timer` for live updates (~3s refresh).

## Chat integration

The dashboard sends chat messages to the orchestrator via MQTT:

1. Dashboard publishes to `homelab/orchestrator/command/dashboard` with `{"command": "chat", "message": "...", "request_id": "...", "user_name": "Dashboard"}`
2. Orchestrator processes through Brain (same LLM + tools as Telegram)
3. Orchestrator publishes response to `homelab/dashboard/chat-response` with `{"request_id": "...", "response": "..."}`

## HA entities

Via MQTT auto-discovery, "Homelab Dashboard" device, 2 entities:

- `binary_sensor` — Service online/offline
- `sensor` — Uptime

## MQTT subscriptions

`homelab/+/heartbeat`, `homelab/pv-forecast/updated`, `homelab/smart-ev-charging/status`, `homelab/ev-forecast/plan`, `homelab/ev-forecast/vehicle`, `homelab/orchestrator/activity`, `homelab/health-monitor/status`, `homelab/dashboard/chat-response`

## MQTT events

`homelab/dashboard/heartbeat`

## HA polling

Periodically reads energy sensors, EV entities, PV forecast entities, and control entities (input_select, input_number, input_boolean, input_datetime) via the REST API. Default interval: 10 seconds.

## Config env vars

`DASHBOARD_PORT` (8085), `DASHBOARD_TITLE`, `DASHBOARD_USER_NAME` (name shown in chat), `HA_POLL_INTERVAL` (10), `UI_REFRESH_INTERVAL` (3). All entity IDs are configurable with sensible defaults matching the existing HA setup. Uses the same `HA_URL`, `HA_TOKEN`, `MQTT_*` settings as other services.

## Access

`http://<server-ip>:8085` directly, or via Traefik reverse proxy at `https://cockpit.local.schuettken.net` (configurable via `TRAEFIK_DASHBOARD_HOST`). No authentication (intended for local network / VPN use only).
