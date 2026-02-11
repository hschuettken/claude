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

## Current Gaps / Opportunities
1. Docker VMs (102/105) are underutilized — only Traefik + Portainer on prod
2. This repo's services (pv-forecast etc.) not yet deployed to Docker
3. EV charging automation was in progress (commented-out config) — prime candidate for a new service
4. Home Connect and Tuya integrations failing — need reconfiguration
5. Withings discovered but not added
6. Proxmox host RAM at 91% — consider consolidation before adding more services

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
