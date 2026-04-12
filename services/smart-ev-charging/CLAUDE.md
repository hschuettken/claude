# smart-ev-charging — Smart EV Charging Controller

Controls the Amtron wallbox via HEMS power limit (Modbus register 1002) to optimize EV charging based on PV surplus, user preferences, and departure deadlines.

## Charge modes

Selected via `input_select.ev_charge_mode`:

| Mode | Behavior |
|------|----------|
| **Auto** | Default. Smart + auto-drain-PV-battery + multi-day PV awareness from ev-forecast weekly plan. `input_boolean.ev_drain_pv_battery` is a disable toggle (not enable). Subscribes to `energy.ev.weekly_plan` NATS. |
| **Ready By** | One-action target SoC + deadline. Set `input_number.ev_ready_by_target_soc` + `input_datetime.ev_ready_by_deadline`. System picks PV-only if forecast sufficient, else grid+PV. |
| **PV Only** | Never grid. Multi-day completion estimate via `estimated_completion_days`. |
| Off | Wallbox paused (HEMS = 0 W) |
| PV Surplus | Dynamic tracking of solar surplus only (legacy, use PV Only instead) |
| Smart | PV surplus + grid fill by departure (legacy, use Auto instead) |
| Eco | Fixed ~5 kW constant |
| Fast | Fixed 11 kW maximum |
| Manual | Service hands off — user controls wallbox directly via HA |
| Manual Until | Charge to target kWh/SoC then stop |

**"Full by Morning" modifier** (`input_boolean.ev_full_by_morning`): When enabled with PV Surplus or Smart mode, escalates to grid charging as departure deadline approaches. In Auto mode this happens automatically.

## EV SoC integration (Audi Connect)

When `EV_SOC_ENTITY` is configured, reads the car's actual SoC and computes energy needed: `(target_soc% - current_soc%) × capacity`. Charging stops automatically when target SoC is reached (any mode). Falls back to manual `target_energy_kwh` vs session energy when SoC is unavailable.

## PV surplus formula

Grid meter: positive = exporting, negative = importing.

```
pv_available = grid_power + ev_power + battery_power - reserve
```

The grid meter sees the net of everything behind it. When the battery charges (battery_power > 0), the EV reclaims that power. When discharging (< 0), available is reduced to only count real PV surplus.

## Battery assist

On top of PV-only surplus, the strategy allows limited battery discharge for EV charging. Gated by:

- SoC > floor (20%)
- PV forecast quality (good day → more aggressive)
- Max discharge rate cap (2 kW default) to protect battery longevity

Battery assist only kicks in when PV is producing but surplus alone isn't enough for the wallbox minimum.

## PV surplus continuation

After the plan target (energy/SoC) is reached, the service continues PV surplus charging opportunistically. PV into the car is more valuable than feeding back to the grid (25 ct/kWh reimbursement vs 7 ct/kWh feed-in), so the car acts as a profitable energy sink.

## Economics

Grid import 25 ct/kWh (fixed), feed-in 7 ct/kWh, employer reimburses 25 ct/kWh. No EPEX spot market. PV charging = +18 ct/kWh profit, grid charging = cost-neutral.

## Energy priority order

Home consumption > Home battery charging > EV surplus charging > Grid feed-in.

The PV surplus formula ensures the EV only gets power that would otherwise be exported to the grid, never stealing from household loads or the home battery.

## Control loop

Every 30 s — read HA state → calculate target power → write HEMS limit → publish MQTT status.

## HA input helpers

Defined in `HomeAssistant_config/configuration.yaml`:

- `input_select.ev_charge_mode` — Charge mode selector
- `input_boolean.ev_full_by_morning` — Deadline mode
- `input_datetime.ev_departure_time` — When the car leaves
- `input_number.ev_target_soc_pct` — Target SoC % (default 80)
- `input_number.ev_target_energy_kwh` — Fallback manual energy target
- `input_number.ev_battery_capacity_kwh` — Total EV battery capacity

## HA output sensors

Via MQTT auto-discovery, "Smart EV Charging" device, 24 entities:

- `binary_sensor` — Service online/offline, Vehicle Connected, Full by Morning active
- `sensor` (core) — Charge Mode, Target Power (W), Actual Power (W), Session Energy (kWh), PV Available (W), Status text, Home Battery Power (W), Home Battery SoC (%), House Power (W)
- `sensor` (EV) — EV SoC (%), Energy Needed (kWh)
- `sensor` (decision context) — PV Surplus before assist (W), Battery Assist Power (W), Battery Assist Reason, PV DC Power (W), Grid Power (W), PV Forecast Remaining (kWh), Energy Remaining to Target (kWh), Target Energy (kWh)
- `sensor` (deadline) — Deadline Hours Left, Deadline Required Power (W)
- `sensor` (reasoning) — Decision Reasoning (with full_reasoning, battery_assist_reason, deadline details as JSON attributes)

## MQTT events

`homelab/smart-ev-charging/status`, `homelab/smart-ev-charging/heartbeat`

## Config env vars

`EV_SOC_ENTITY`, `EV_GRID_PRICE_CT`, `EV_FEED_IN_TARIFF_CT`, `EV_REIMBURSEMENT_CT`, `WALLBOX_MAX_POWER_W`, `WALLBOX_MIN_POWER_W`, `ECO_CHARGE_POWER_W`, `GRID_RESERVE_W`, `CONTROL_INTERVAL_SECONDS`, `BATTERY_MIN_SOC_PCT`, `BATTERY_EV_ASSIST_MAX_W`, `PV_FORECAST_GOOD_KWH`, `SAFE_MODE_ENTITY`. Entity IDs have sensible defaults matching the Amtron + Sungrow + Shelly setup.
