# Project Decisions & Learnings

## Architecture
- Services run as Python microservices in Docker, communicating via MQTT
- HA config files are in `HomeAssistant_config/` on main branch (capital H)
- KNX config is split into separate files under `KNX/` directory (referenced by HA config)
- InfluxDB token is exposed in configuration.yaml — should be moved to secrets.yaml
- Documentation lives in `docs/` in the repo AND in Claude memory files — always update both
- py-ha-automations (192.168.0.72) listed in IP sheet but not in Proxmox — possibly retired/replaced by this repo

## User Preferences
- Prefers Docker or Proxmox helper script LXCs for new services
- Prefers working on main branch — finds branch-per-session merging annoying
- Wants all learnings/decisions stored in BOTH `docs/` (repo) AND memory files — always keep in sync
- Already has extensive AI stack: Ollama, Open WebUI, ComfyUI, Flowise AI, SearXNG
- Uses n8n for workflow automation alongside Node-RED
- Has both CheckMK and LibreNMS for monitoring (dual monitoring stack)
- Uses Cloudflared for external access (no port forwarding)
- Pi-hole for DNS ad-blocking
- Vaultwarden for password management
- Heimdall as service dashboard
- MikroTik networking (MT24 core switch + MT8 PoE), TP-Link Omada WiFi APs (3 floors)
- Dual NAS: TrueNAS (VM 108, primary storage) + Synology DS214 (192.168.0.21, legacy)
- 3 weather data sources in HA: Open-Meteo, Met.no, OpenWeatherMap

## Development Learnings

### Orchestrator (session 01KZwqKkaRzi1qE3BaLa123M — 13 commits)
This was the largest single session, building the orchestrator service from scratch through iterative debugging:

1. **Python stdlib naming conflicts** — naming a file `calendar.py` shadows Python's built-in `calendar` module. When `email._parseaddr` does `import calendar`, it picks up the local file → circular import crash. Fix: renamed to `gcal.py`. Lesson: never name files after stdlib modules.

2. **google-generativeai → google-genai migration** — the `google-generativeai` package was deprecated/EOL and broke embedding calls. Migrated to the new `google-genai` SDK for both LLM chat and embeddings. The API surface changed significantly (different client init, method names, response shapes).

3. **Gemini embedding model saga** — `text-embedding-004` was shut down (Jan 2026). The working combination is `gemini-embedding-001` on the default `v1beta` API with `output_dimensionality=768`. Multiple iterations were needed to find this:
   - First tried `text-embedding-004` on v1beta → model not found
   - Tried v1 explicitly → still broken
   - Switched to `gemini-embedding-001` → works on default v1beta
   - Key lesson: always log actual API errors instead of silently swallowing them (that cost several debug rounds)

4. **Telegram markdown parsing** — proactive notifications (morning briefing, alerts) failed with markdown parse errors because `send_message()` lacked the plain-text fallback that `_reply()` already had. Fix: add the same `try MarkdownV2 → fallback to plain text` pattern to all send paths.

5. **LLM hallucinated tool parameters** — LLMs sometimes pass parameters that don't exist in the function signature (e.g. `days=3` to `get_pv_forecast()`). Fix: filter kwargs through `inspect.signature()` before calling the tool function. This is a defensive pattern worth using for all LLM tool-calling systems.

6. **Semantic memory design decisions**:
   - Pure-Python cosine similarity is sufficient — no need for ChromaDB/FAISS/PyTorch
   - LLM summarization before storage produces better search results than raw text dumps
   - Time-weighted scoring (85% similarity + 15% recency with 30-day half-life) makes recent memories rank higher when equally relevant
   - Nightly consolidation (3 AM) merges older conversation memories via LLM, reducing bloat
   - Scale: up to 5000 entries (~20 MB JSON), searches in milliseconds

7. **Google Calendar integration** — Service Account auth (no interactive OAuth) is the right approach for server-side services. Share calendars with the service account email. Credentials can be deployed as file mount or base64 env var.

### Smart EV Charging (session 01UDtRMu2KHYZ6JmfYdSu9tR — 8 commits)
Built and iterated the smart-ev-charging service:

1. **Sensor topology matters** — the PV surplus formula depends on understanding what each sensor measures:
   - Grid meter (`power_meter_active_power`): positive = exporting, negative = importing
   - PV input (`inverter_input_power`): single sensor for total DC input, not per-array
   - House power (`shelly3em_main_channel_total_power`): household only, excludes EV
   - Formula: `pv_available = grid_power + ev_power + battery_power - reserve`

2. **Battery-aware charging** — the grid meter implicitly accounts for battery behavior, but explicitly reading battery state enables:
   - Battery assist: limited discharge (max 2 kW, SoC > 20%) for EV when PV is close but insufficient
   - Dashboard visibility: battery power/SoC in MQTT status and HA entities
   - PV forecast quality gates battery aggressiveness (good day → more battery assist)

3. **EV SoC integration (Audi Connect)** — reading actual battery SoC is far better than manual energy targets:
   - Compute: `energy_needed = (target_soc% - current_soc%) × battery_capacity`
   - Auto-stop when target SoC reached (any mode, not just deadline)
   - Graceful fallback to manual `target_energy_kwh` when SoC sensor unavailable

4. **HA helper cleanup** — removed ~25 redundant Amtron template sensors that just mirrored Modbus values with no transformation. Kept only the 8 value-adding transforms + 3 binary sensors.

5. **Economics are fixed-rate** — no EPEX spot market. Grid import 25 ct/kWh, feed-in 7 ct/kWh, EV reimbursement 25 ct/kWh. PV charging = +18 ct/kWh profit.

6. **Charge modes evolved** — final set: Off, PV Surplus, Smart, Eco (5 kW), Fast (11 kW), Manual. "IQ Charge" and "Full Charge" were renamed for clarity.

### Health Checks & Diagnostics (session 0191K6ga22NgU41LTjVWpVXh)
1. **diagnose.py pattern** — every service now has a step-by-step diagnostic script (`python diagnose.py --step <name>`). This is invaluable for debugging connectivity and configuration issues without reading logs.

2. **Inter-service commands via MQTT** — the orchestrator can send commands (`refresh`, `retrain`, `refresh_vehicle`) to other services via `homelab/orchestrator/command/{service-name}`. This allows the AI to trigger on-demand updates when a user asks for fresh data.

3. **Reasoning sensors** — rich JSON-attribute sensors in HA that expose the full reasoning/decision context. These are critical for debugging why a service made a particular decision, visible directly in the HA dashboard.

### EV Forecast (session 01wAxKxQ...)
1. **Dual Audi Connect accounts** — Henning and Nicole each have an account for the same car. Only the person who last drove sees valid data. The service tries both and picks the one with valid sensors.

2. **Calendar-based trip prediction** — events parsed by prefix (`H:` = Henning, `N:` = Nicole). Known destinations mapped to distances via configurable lookup. Ambiguous trips trigger Telegram clarification via orchestrator.

3. **Vehicle**: Audi A6 Avant e-tron (83 kWh gross / 76 kWh net), ~22 kWh/100km. Previously Tesla Model 3 (listed in some older docs).

### General Learnings
1. **MQTT auto-discovery** is the right pattern for HA integration — services register entities automatically on startup, no manual HA config needed.
2. **File-based healthcheck** (write timestamp → check recency) works well with Docker HEALTHCHECK.
3. **Always log errors before swallowing them** — silent `except: pass` costs hours of debugging.
4. **InfluxDB entity_id quirk** — entity IDs are stored WITHOUT the domain prefix (`sensor.`). The `shared/influx_client.py` handles stripping automatically.
5. **PV energy sensors are `total_increasing` (cumulative)** — diff consecutive values for per-hour kWh, don't assume midnight resets.
6. **Sunrise/sunset from Open-Meteo** replaces hardcoded 5–21 UTC range. Physics constraint: zero prediction when GHI < 5 W/m².
7. **ML model versioning** — models saved with feature list. On load, validated against current features. Auto-retrain if features changed.

### Combined Sensor Architecture (this session)
1. **Mileage-based active account detection** — more reliable than SoC-based. Mileage always updates when driving.
2. **Combined HA template sensors** — HA handles account combining, ev-forecast reads unified sensors. Simpler code, clearer separation of concerns.
3. **PV surplus continuation** — after plan target reached, continue charging from PV surplus. PV into car > feed-in to grid.
4. **Infrastructure hardening** — MQTT dead-letter errors, global safe mode, state persistence, correlation IDs, shared retry/backoff.

## Current Gaps / Opportunities
1. Home Connect and Tuya integrations failing — need reconfiguration
2. Withings discovered but not added
3. Proxmox host RAM at 91% — consider consolidation before adding more services
4. Heating optimization service — per-room valve data + weather + occupancy → optimize oil consumption
5. Shutter automation — all shutters KNX-controlled, window contacts available → sun/heat/security automation

## KNX Address Scheme
- 1/x/xx — Lights (1=switch, 3=brightness, 4=state, 5=brightness state)
- 2/x/xx — Outlets/switches (1=switch, 4=state)
- 3/x/xx — Heating (2=target temp, 3=setpoint shift, 4=shift state, 5=active/valve, 6=modes, 7=lock)
- 4/x/xx — Covers (1=move, 2=stop, 3=position, 5=position state)
- 5/4/xx — Window contacts
- 7/3/xx — Temperature sensors
- 7/4/xx — Humidity sensors
- 8/1/xx — Presence/motion sensors
- 8/5/xx — Illuminance sensors
- 8/7/xx — Presence lock objects
- 9/0/xx — Bus diagnostics + day/night
- 9/3/xx — Fake scene triggers
- 9/4/xx — Bad OG individual LEDs

Room numbering: last 2 digits = room (50=Flur EG, 60=Gästebad, 70=Bad EG, 80=Sport, 90=Wozi, 110=Esszimmer, 130=Küche, 150=Flur OG, 160=Bad OG, 170=Gästezimmer, 180=Büro, 200=Abstellraum, 210=Ankleide, 220=Schlafzimmer, 230=Markise, 240=Außen)
