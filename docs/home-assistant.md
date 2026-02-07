# Home Assistant Configuration

## Instance
- **Type**: HAOS 8.4 (VM 103 on Proxmox)
- **IP**: 192.168.0.40:8123
- **External**: homeassistant.schuettken.net (via Cloudflare tunnel)
- **Recorder**: purge_keep_days=3650 (10 years!)
- **InfluxDB**: v2, host=192.168.0.66, bucket=hass

## Integrations (from screenshot + config)

### Building Automation
- **KNX** — Primary building bus. Extensive config for climate, covers, lights, sensors, binary sensors, switches, numbers. Gateway at 192.168.0.30. Win10KNX VM for ETS.
- **Modbus** — AMTRON EV charger (TCP, 192.168.0.32:502)

### Energy
- **Huawei Solar** — 4 devices (inverter + strings). PV strings 1-4 mapped to East (1+2) and West (3+4).
- **Forecast.Solar** — 2 services (East + West arrays)
- **EPEX Spot** — 2 services (electricity spot market pricing)
- **Electricity Maps** — 1 service (carbon intensity)
- **Shelly** — 5 devices: Shelly 3EM (main panel energy meter) + Shelly Plus 1PM

### Climate / Comfort
- **Thermal Comfort** — 1 device
- **Open-Meteo** — 1 service (weather)
- **Meteorologisk institutt (Met.no)** — 1 service (weather)
- **OpenWeatherMap** — 1 service (weather)
- **Sun** — 1 service

### IoT Devices
- **ESPHome** — 3 devices: keller_flur_treppe_v3, heatdistreg-esp32, gaestewc_esp32
- **Shelly** — 5 devices
- **Reolink** — 2 devices (cameras)
- **Apple TV** — 1 device
- **LG webOS TV** — 1 device
- **LG ThinQ** — 1 device
- **HomeKit Bridge** — 1 service (exposing HA to Apple Home)
- **Thread** — 1 entry

### Automation / Development
- **Node-RED Companion** — 1 entry
- **Pyscript Python scripting** — 1 entry
- **MQTT** — 2 devices
- **HACS** — 10 services (custom components)

### Media
- **DLNA Digital Media Renderer** — 1 device
- **Radio Browser** — 1 entry
- **Internet Printing Protocol (IPP)** — 1 device

### Monitoring / Utility
- **Synology DSM** — 5 devices (NAS monitoring)
- **System Monitor** — 1 service
- **Speedtest.net** — 1 service
- **Watchman** — 1 service (monitors broken integrations)
- **Mobile App** — 8 devices (phones/tablets)
- **Backup** — 1 service
- **Local Calendar** — 1 entity
- **Workday** — 1 service
- **Home Assistant Supervisor** — 9 services

### Discovered but not configured
- **Tuya** (h.schuettken@gmail.com) — needs reconfiguration
- **Home Connect** (homeappliances) — needs reconfiguration (Bosch/Siemens appliances)
- **Withings** — health/fitness data, can be added

## KNX Room Layout & Entities

### Climate Zones (floor heating, KNX valve actuators)
**EG (Ground Floor):**
- Flur EG (7/3/50) — hallway
- Gästebad (7/3/60) — guest bathroom
- Bad EG (7/3/70) — ground floor bathroom
- Sport (7/3/80) — sport/gym room
- Wohnzimmer (7/3/90) — living room (has command_value + extended setpoint range)
- (Esszimmer — commented out, temp sensor at 7/3/110-112)
- (Küche — commented out)

**OG (Upper Floor):**
- Flur OG (7/3/150) — upper hallway
- Bad OG (7/3/160) — upper bathroom (2 zones: main + radiator)
- Gästezimmer (7/3/170) — guest room
- Büro (7/3/180) — office (has command_value)
- Ankleide (7/3/210) — dressing room
- Schlafzimmer (7/3/220) — bedroom

### KNX Sensors
- Temperature per room (7/3/xx)
- Humidity: Bad OG (rel+abs), Wohnzimmer (rel), Bad EG (rel)
- Illuminance: Bad OG, Flur OG, Wohnzimmer
- Heating valve positions (3/5/xx) for Büro, Bad OG, Wohnzimmer
- Bus diagnostics: current, voltage, traffic %, status text
- Terassentür temp sensor (7/3/110), Esszimmer/Küche wall (7/3/112)

### KNX Lights
**Simple switches:** Gäste WC Spiegel, Bad OG Duschlicht, Bad OG Spiegel, Bad EG Deckenlicht, Gästezimmer, Büro, Abstellraum, Ankleide, Sport, Außen 1-5, Küche LED Band
**Dimmable:** Flur OG Hängelampe, Esszimmer Deckenlicht, Flur EG/OG Spots, Küche Aufbau/Einbauspots, Schlafzimmer Deckenlicht, Bad OG Spots, Bad OG Dusche LED Band
**Steckdosen (outlets):** Wohnzimmer SD (2x), Flur EG SD, Küche SD iPad, Esszimmer SDs

### KNX Covers (Shutters/Blinds)
All rooms have shutters: Gästebad, Bad OG, Wohnzimmer (2x: links + Kamin), Bad EG, Esszimmer (2x: gr Fenster + Terassentür), Gästezimmer, Ankleide, Büro, Küche, Schlafzimmer, Sport, Markise (awning)

### KNX Binary Sensors
**Presence/Motion:** Bad OG Dusche (LK1), Wohnzimmer (3 zones: Küche, Esszimmer, Eingang)
**Window Contacts:** Every room has one (19 total), including per-window for Wohnzimmer (3), Küche (2+combined), plus combined sensor for Wohnzimmer/Esszimmer/Küche
**Heating status:** Per room heating on/off, Heizanforderung links/rechts/gesamt (heating demand)

### KNX Switches
- Fake scene triggers for KNX (TV, Essen, Kochen, putzen, duschen)
- Tag/Nacht auto/manual switches
- Presence lock objects (Sperrobjekte) per room
- Utility controls: Bad OG Lüftung, Keller Ölraum Ventilator, Zirkulationspumpe, Waschkeller Lüftung, Heizungspumpe
- Bad OG LED individual control (4 LEDs)

### KNX Numbers
- Heating valve override (Min/Max) for: Wohnzimmer, Büro, Bad OG

## Template Sensors (configuration.yaml)
- Market Grid Price Status (EPEX Spot based)
- PV Electricity Price (Market Adjusted) in €/kWh
- Grid electricity price in €/kWh
- PV string power calculations (V*I per string, East=1+2, West=3+4)
- Shelly 3EM total energy (A+B+C phases summed)
- Shelly 3EM total power (A+B+C phases summed)
- AMTRON EV charger: extensive Modbus sensor templates (status, metering, session data)
- AMTRON template numbers for Modbus control (HEMS current/power limits, safe current, timeout)
- AMTRON pause charging switch

## Integration Sensors (configuration.yaml)
- inverter_pv_east_energy (integration of east power)
- inverter_pv_west_energy (integration of west power)

## Heating System Notes (from comments)
- Oil-based heating with floor heating
- Flow rates per room documented (liter/min)
- Total flow: ~21.9 l/min = 1.314 m³/h
- Heating energy calculation: 1 liter heated by 15K = 17.4 Wh
- Commented-out heating power calculations per room exist
