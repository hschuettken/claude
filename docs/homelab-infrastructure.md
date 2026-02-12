# Homelab Infrastructure

## Proxmox Host
- **Hostname**: pve1 | **IP**: 192.168.0.20
- **CPUs**: 8 cores | **RAM**: ~91% used (heavily loaded)
- **Uptime**: 164+ days (very stable)
- **Backup**: PBS (Proxmox Backup Server) at 192.168.0.44 + LXC 200

## Network Equipment
| IP | Device | Type | Notes |
|---|---|---|---|
| 192.168.0.2 | MT 24 | MikroTik 24-port switch | Core switch |
| 192.168.0.4 | MT 8 port POE | MikroTik 8-port PoE | PoE switch |
| 192.168.0.10 | AP EG | WiFi AP | Ground floor |
| 192.168.0.11 | AP Keller | WiFi AP | Basement |
| 192.168.0.12 | AP OG | WiFi AP | Upper floor |
| 192.168.0.64 | omada | TP-Link Omada controller | LXC 206 |

## Virtual Machines (QEMU)
| ID | Name | IP | CPUs | RAM% | Purpose |
|---|---|---|---|---|---|
| 103 | haos8.4 | .40 | 6 | 94.1% | Home Assistant OS |
| 162 | Win10KNX | .43 | 4 | 21.9% | KNX ETS programming |
| 102 | docker1 | .50 | 4 | 19.3% | Production Docker (Traefik + Portainer) |
| 105 | dockerDev | .51 | 4 | 89.1% | Development Docker |
| 108 | truenas1 | .42 | 4 | 78.0% | TrueNAS storage |
| 104 | pbs | .44 | 2 | 32.9% | Proxmox Backup Server |

## LXC Containers
| ID | Name | IP | CPUs | RAM% | Category |
|---|---|---|---|---|---|
| 206 | omada | .64 | 2 | 84.0% | Network management |
| 208 | influxdb | .66 | 2 | 7.5% | Time-series DB |
| 211 | checkmk | .69 | 2 | 22.5% | Monitoring |
| 209 | grafana | .67 | 1 | 17.5% | Dashboards |
| 205 | node-red | .60 | 1 | 37.5% | Automation flows |
| 222 | mongodb | — | 1 | 23.7% | Database (for n8n/flowise?) |
| 212 | vscode | .70 | 2 | 8.7% | VS Code Server |
| 201 | cloudflared | .61 | 1 | 7.5% | Cloudflare tunnel (external access) |
| 219 | searxng | — | 2 | 5.6% | Self-hosted search |
| 223 | redis | — | 1 | 2.6% | Cache/queue |
| 218 | openwebui | — | 4 | 8.3% | LLM web UI |
| 202 | pihole | .63 | 1 | 21.1% | DNS ad-blocking |
| 114 | librenms2 | — | 2 | 8.2% | Network monitoring |
| 200 | proxmox-backup-server | .62 | 4 | 1.7% | Backup |
| 214 | n8n | .71 | 4 | 16.8% | Workflow automation |
| 215 | mqtt | .73 | 2 | 4.6% | Mosquitto MQTT broker |
| 210 | heimdall-dashboard | .68 | 1 | 12.3% | Service dashboard |
| 207 | vaultwarden | .65 | 4 | 1.6% | Password manager |
| 221 | mariadb | — | 1 | 12.5% | SQL database |
| 110 | mqtt-temp | — | 2 | 2.2% | MQTT temp/test instance |
| 220 | comfyui | — | 4 | 6.3% | AI image generation |
| 216 | ollama | — | 4 | 1.1% | Local LLM runtime |
| 217 | flowiseai | — | 4 | 9.7% | AI workflow builder |

## IoT / Smart Home Devices
| IP | Device | Protocol |
|---|---|---|
| 192.168.0.30 | KNX Gateway | KNX/IP |
| 192.168.0.31 | Huawei_WR | Solar inverter |
| 192.168.0.32 | AMTRON | EV charger (Modbus TCP) |
| 192.168.0.21 | ds214 | Synology NAS |
| 192.168.0.90 | HomePod | AirPlay |
| 192.168.0.91 | LG TV | webOS |
| 192.168.0.92 | RXV473 | Yamaha AV receiver |
| 192.168.0.93 | Audi A6 Avant e-tron | WiFi (Audi Connect) |
| 192.168.0.221 | Shelly Plus 1PM | HTTP/MQTT |
| 192.168.0.222 | Shelly EM3 | HTTP/MQTT (main panel meter) |
| 192.168.0.230 | keller_flur_treppe_v3 | ESPHome |
| 192.168.0.231 | heatdistreg-esp32 | ESPHome (heating distribution) |
| 192.168.0.232 | gaestewc_esp32 | ESPHome (guest WC sensor) |

## Personal Devices
| IP | Device |
|---|---|
| 192.168.0.100 | MacBook Pro |
| 192.168.0.101 | Work laptop |
| 192.168.0.102 | Redmi Note |
| 192.168.0.103 | iPhone 8 |
| 192.168.0.104 | iPhone Nicole |
| 192.168.0.105 | iPhone HP |

## Docker (VM 102 - docker1)
Currently running: **Traefik** (reverse proxy) + **Portainer** (management)
This repo's services are intended for this VM or dockerDev (VM 105).

## Homelab Automation Services (this repo)
All services run as Docker containers via `docker-compose.yml`, communicating via MQTT:

| Service | Purpose | Key Integrations |
|---------|---------|-----------------|
| **pv-forecast** | AI solar production forecast (Gradient Boosting ML) | InfluxDB, Open-Meteo, Forecast.Solar, HA |
| **smart-ev-charging** | Wallbox control (PV surplus, deadline, battery-aware) | AMTRON Modbus, HA, Audi Connect (SoC) |
| **ev-forecast** | EV driving forecast & charging planner | Dual Audi Connect, Google Calendar, PV forecast |
| **orchestrator** | AI-powered home brain (LLM + tools + Telegram) | Gemini/OpenAI/Anthropic/Ollama, HA, MQTT, Google Calendar |

All services use MQTT auto-discovery to register entities in HA and publish heartbeats every 60s. Each has a `diagnose.py` for step-by-step connectivity testing.

## Notes
- Proxmox RAM is heavily used (~91%). HA VM alone takes 94% of its allocated RAM.
- dockerDev (VM 105) at 89% memory — also loaded.
- The system has been running 164+ days without restart — very stable.
- Two MQTT instances: production (LXC 215, .73) and temp/test (LXC 110).
- AI stack: Ollama + Open WebUI + ComfyUI + Flowise AI + SearXNG — all on LXCs.
- Secrets managed via SOPS + age encryption (`.env.enc`). Plain `.env` is gitignored.
