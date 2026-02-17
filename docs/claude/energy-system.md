# Energy System

## Solar PV
- **Inverter**: Huawei (192.168.0.31), integrated via Huawei Solar HA integration (4 devices)
- **East Array**: Strings 1+2 (sensor.inverter_pv_1_* + sensor.inverter_pv_2_*)
- **West Array**: Strings 3+4 (sensor.inverter_pv_3_* + sensor.inverter_pv_4_*)
- **Forecast**: Forecast.Solar (2 services, East+West) + custom pv-forecast ML service
- **Calculated sensors**: inverter_pv_east_power, inverter_pv_west_power (template: V*I per string, sum per array)
- **Energy tracking**: integration sensors for East/West energy (kWh, trapezoidal)

## Energy Metering
- **Main Panel**: Shelly 3EM (192.168.0.222) — 3-phase energy meter
  - Per-phase: power (W) and energy (kWh) for channels A, B, C
  - Template sensors sum all 3 phases for total power and total energy
  - Total energy uses monotonic guard (prevents backward resets)
- **Additional**: Shelly Plus 1PM (192.168.0.221)

## EV Charging
- **Wallbox**: Mennekes AMTRON (192.168.0.32)
- **Protocol**: Modbus TCP (port 502, slave 1)
- **Vehicle**: Audi A6 Avant e-tron (83 kWh gross / 76 kWh net, ~22 kWh/100km)
- **Vehicle connectivity**: Dual Audi Connect accounts (Henning + Nicole) — only the last driver's account shows valid data. Active account detected via mileage comparison (mileage always updates when driving, more reliable than SoC-based detection). Combined via HA template sensors.
- **Modbus registers** (extensive, defined in configuration.yaml):
  - Identity: firmware, protocol version, model, device name (regs 100-174)
  - Status: OCPP CP status (104), vehicle state (122), availability (124), relay (140), plug lock (152)
  - Current limits: safe current (131), operator limit (134), min/max charge (712/715)
  - HEMS control: current limit 0.1A precision (1001), power limit W (1002)
  - Metering: per-phase energy/power/current/voltage (200-226), totals (218-220)
  - Session: signaled current (706), start/end times (707-711), session energy (716), duration (718)
- **Control templates**:
  - AMTRON HEMS Current Limit [A] — writes to reg 1001 (value * 10)
  - AMTRON HEMS Power Limit [W] — writes to reg 1002
  - AMTRON Safe Current [A] — writes to reg 131
  - AMTRON Communication Timeout [s] — writes to reg 132
  - AMTRON Pause Charging switch — sets both limits to 0 / restores
- **Smart EV Charging service** (smart-ev-charging): controls wallbox via HEMS power limit (reg 1002)
  - Charge modes: Off, PV Surplus, Smart (PV + grid fill by departure), Eco (5 kW), Fast (11 kW), Manual
  - PV surplus formula: `pv_available = grid_power + ev_power + battery_power - reserve`
  - Battery assist: limited discharge (max 2 kW) for EV when PV close but insufficient, gated by SoC > 20%
  - EV SoC integration: reads actual battery SoC from Audi Connect, computes energy needed
  - "Full by Morning" modifier: escalates to grid charging as deadline approaches if PV won't suffice
  - 24 HA entities via MQTT auto-discovery (binary sensors, core status, EV state, decision context, reasoning)
- **EV Forecast service** (ev-forecast): predicts driving needs from family calendar
  - Calendar events parsed by prefix: `H:` = Henning drives, `N:` = Nicole drives
  - Known destinations mapped to distances via configurable lookup
  - Generates smart charging plans: sets charge mode, target energy, departure time in HA helpers
  - Ambiguous trips trigger Telegram clarification via orchestrator
  - 13 HA entities via MQTT auto-discovery
  - **PV surplus continuation**: after plan target SoC is reached, charging continues from PV surplus rather than stopping. PV into car > feed-in to grid.

### Energy Priority
Home energy is allocated in this priority order:
1. **Home consumption** — household loads always served first
2. **Home battery** — charge the 7 kWh Sungrow battery
3. **EV surplus charging** — excess PV into the car
4. **Grid feed-in** — remaining surplus exported at 7 ct/kWh

### EV Charging HA Helpers
- `input_select.ev_charge_mode` — Charge mode selector (Off/PV Surplus/Smart/Eco/Fast/Manual)
- `input_boolean.ev_full_by_morning` — Deadline mode toggle
- `input_datetime.ev_departure_time` — When the car leaves
- `input_number.ev_target_soc_pct` — Target SoC % (default 80)
- `input_number.ev_target_energy_kwh` — Fallback manual energy target
- `input_number.ev_battery_capacity_kwh` — Total EV battery capacity

## Electricity Pricing
- **Fixed rates** (no EPEX spot market used for EV charging decisions):
  - Grid import: 25 ct/kWh
  - Feed-in tariff: 7 ct/kWh
  - EV reimbursement (employer): 25 ct/kWh
  - PV charging profit: +18 ct/kWh (25 ct reimbursement − 7 ct feed-in opportunity cost)
  - Grid charging: cost-neutral (25 ct cost = 25 ct reimbursement)
- **EPEX Spot** — 2 services (spot market prices, sensor.epex_spot_data_price_2) — configured in HA but not used for charging decisions
- **Electricity Maps** — carbon intensity
- **Template sensors**:
  - Market Grid Price Status (1 if price > 0, else 0)
  - PV Electricity Price (Market Adjusted) — input_number.price_per_kwh_electricity_pv / 100
  - Grid price in €/kWh — input_number.price_per_kwh_electricity_grid / 100

## Heating (Oil-based)
- Oil-fired boiler with floor heating distribution
- KNX-controlled valve actuators per room
- Heating pump (KNX switch: Keller Heizungspumpe)
- Circulation pump (KNX switch: Keller Zirkulationspumpe)
- Oil room ventilator (KNX switch: Keller Ölraum Ventilator)
- Binary sensors for heating demand: per-room + links/rechts/gesamt
- Heating valve position sensors for monitored rooms (Büro, Bad OG, Wohnzimmer)
- Flow rates documented per room (total ~21.9 l/min, 1.314 m³/h)
- Energy calc: 1 m³ heated by 15K = 17.4 kWh

## Home Battery
- **Battery**: 7 kWh / 3.5 kW max (Sungrow)
- **Sensors**: `sensor.batteries_charge_discharge_power` (W, positive=charging, negative=discharging), `sensor.batteries_state_of_capacity` (%, SoC)
- **EV charging interaction**: battery charge power is reclaimed in PV surplus formula. Battery assist allows limited discharge (max 2 kW, SoC > 20%) for EV charging when PV is close but insufficient.

## Automation Opportunities (remaining)
1. **Heating optimization** — Per-room valve data + weather + occupancy → optimize oil consumption
2. **Shutter automation** — All shutters KNX-controlled, window contacts available → sun/heat/security automation
3. **Energy dashboard** — All data flows to InfluxDB, Grafana available for visualization
