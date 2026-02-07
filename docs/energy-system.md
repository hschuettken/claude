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
- **Vehicle**: Tesla Model 3 (192.168.0.93)
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
- **Commented-out EV charging automation config**: PV-surplus charging logic was being developed
  - Parameters for: min/max amps, grid reserve, hysteresis, ramp step, import cutoff
  - Battery assist policy, PV share requirements, boost mode with deadline

## Electricity Pricing
- **EPEX Spot** — 2 services (spot market prices, sensor.epex_spot_data_price_2)
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

## Automation Opportunities (from config analysis)
1. **PV surplus EV charging** — Config scaffolding exists (commented out), ready to be built as a service
2. **Heating optimization** — Per-room valve data + weather + occupancy → optimize oil consumption
3. **Shutter automation** — All shutters KNX-controlled, window contacts available → sun/heat/security automation
4. **Energy dashboard** — All data flows to InfluxDB, Grafana available for visualization
