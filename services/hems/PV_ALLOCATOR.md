# PV Budget Allocator (pv_allocator.py)

**Status:** ✅ Phase 3.2 Implementation Complete

## Overview

The PV Budget Allocator distributes available PV surplus across multiple energy consumers using a fixed priority cascade. It ensures that solar energy is used optimally by prioritizing certain loads (battery charging, DHW heating) over others (EV charging) based on the PRIORITY_ORDER specification.

## Features

✅ **Priority Cascade Allocation**
- Input: available PV surplus (kW), list of devices with max power ratings
- PRIORITY_ORDER: battery charging → DHW heating → space heating → supplemental heaters → EV charging
- Algorithm: allocate sequentially to each tier until exhausted or device max capacity reached
- Output: dict of {device: allocated_power_kW}

✅ **Constraints & Limits**
- Battery SoC charge limit (default 80%): prevents overcharging
- Battery reserve minimum (default 20%): keeps backup capacity
- Min allocation threshold (default 0.5 kW): skip small surplus
- Device-level max power ratings: never exceed device capacity

✅ **Time-Aware Logic**
- DHW heating priority window (6:00–12:00 UTC): prioritize hot water in morning
- Outside priority window: DHW deprioritized in favor of space heating
- Extensible for seasonal/comfort mode overrides

✅ **Database Persistence**
- `hems.pv_allocation` table: allocation records with timestamp, surplus, allocation_dict, battery SoC
- `hems.pv_allocation_history` table: 5-min tick history for analytics/dashboards
- Timestamp, execution time, error tracking

✅ **Home Assistant Integration**
- Enforcement: calls HA services to adjust device power setpoints
- Dual-mode: orchestrator-based (preferred) or direct REST client fallback
- Handles: battery charger, DHW heater, space heater, supplemental switches, EV charger

✅ **InfluxDB Metrics**
- Per-tick recording: surplus, allocated, remaining, duration
- Per-device allocations as fields
- Historical analysis: allocation efficiency, cascade coverage

## Installation & Configuration

### Database Schema

Run migration to create tables:
```bash
psql -h 192.168.0.80 -U homelab homelab -f migrations/004_pv_allocation.sql
```

Creates:
- `hems.pv_allocation` (main records)
- `hems.pv_allocation_history` (time-series ticks)

### Configuration

```python
from pv_allocator import PVAllocator, PVAllocatorConfig

config = PVAllocatorConfig(
    min_allocation_kw=0.5,              # Skip allocations < 500W
    battery_charge_limit_pct=80.0,      # Don't charge above 80% SoC
    battery_reserve_pct=20.0,           # Keep 20% as backup
    dhw_priority_window_start_hour=6,   # Morning priority starts 6:00 UTC
    dhw_priority_window_end_hour=12,    # Morning priority ends 12:00 UTC
    use_orchestrator=True,              # Use orchestrator for HA calls (recommended)
    orchestrator_url="http://orchestrator:8100",
)

allocator = PVAllocator(
    ha_client=ha_client,                 # httpx.AsyncClient (if not using orchestrator)
    database=hems_db,                    # HEMSDatabase instance
    influxdb_write_api=influxdb_api,     # InfluxDB write API
    config=config,
)
```

## Usage

### Basic Allocation

```python
result = await allocator.allocate(
    surplus_available_kw=4.5,
    devices=[
        {
            "device_id": "battery",
            "priority": 1,  # or DevicePriority.BATTERY_CHARGING
            "max_power_kw": 5.0,
            "current_power_kw": 2.0,  # Already using 2 kW
            "state": "ready",
        },
        {
            "device_id": "dhw_heating",
            "priority": 2,
            "max_power_kw": 3.0,
            "current_power_kw": 0.0,
            "state": "ready",
        },
        {
            "device_id": "ev_charging",
            "priority": 5,
            "max_power_kw": 7.0,
            "current_power_kw": 0.0,
            "state": "idle",
        },
    ],
    battery_soc_pct=65.0,
)

print(result.allocation_dict)
# Output: {'battery': 3.0, 'dhw_heating': 1.5}
#   - Battery gets 3.0 kW (max capacity 5 - current 2)
#   - DHW gets 1.5 kW (remaining surplus)
#   - EV gets nothing (lower priority, surplus exhausted)

print(f"Total allocated: {result.total_allocated_kw} kW")
print(f"Remaining: {result.remaining_surplus_kw} kW")
```

### Using Device Objects

```python
from pv_allocator import Device, DevicePriority

devices = [
    Device(
        device_id="battery",
        priority=DevicePriority.BATTERY_CHARGING,
        max_power_kw=5.0,
        current_power_kw=0.0,
        entity_id="number.battery_charger_setpoint",
    ),
    Device(
        device_id="dhw_heating",
        priority=DevicePriority.DHW_HEATING,
        max_power_kw=3.0,
        current_power_kw=0.0,
        entity_id="number.dhw_heater_target_power",
    ),
]

result = await allocator.allocate(
    surplus_available_kw=4.5,
    devices=devices,
    battery_soc_pct=70.0,
)
```

### Integration into Control Loop

```python
# In HEMS main.py control_loop()
async def pv_allocation_loop(allocator, ha_client, settings):
    """Run PV allocator every 5 minutes when surplus > 500W."""
    while True:
        try:
            # Fetch current PV surplus from HA
            surplus_response = await ha_client.get(
                "/api/states/sensor.pv_surplus_available"
            )
            surplus_kw = surplus_response.json()["state"] / 1000.0
            
            # Fetch battery SoC
            battery_response = await ha_client.get(
                "/api/states/sensor.battery_soc"
            )
            battery_soc = float(battery_response.json()["state"])
            
            # Only allocate if surplus meaningful
            if surplus_kw > 0.5:
                result = await allocator.allocate(
                    surplus_available_kw=surplus_kw,
                    devices=get_device_list(),  # Your device config
                    battery_soc_pct=battery_soc,
                )
                
                logger.info(
                    "PV Allocation: surplus=%.2f kW, allocated=%.2f kW, "
                    "remaining=%.2f kW, devices=%d",
                    result.surplus_available_kw,
                    result.total_allocated_kw,
                    result.remaining_surplus_kw,
                    result.num_devices,
                )
        except Exception as e:
            logger.error("PV allocation error: %s", e)
        
        # Run every 5 minutes (300 seconds)
        await asyncio.sleep(300)
```

## PRIORITY_ORDER Cascade

The allocation follows this fixed priority order:

| Priority | Device Type | Typical Max Power | Use Case |
|----------|-------------|------------------|----------|
| 1 | Battery Charging | 5.0 kW | Maximize self-consumption, reduce grid imports |
| 2 | DHW Heating | 3.0 kW | Hot water (morning priority window 6:00–12:00) |
| 3 | Space Heating | 3.0 kW | Floor heating (UFH), room comfort |
| 4 | Supplemental Heaters | 2.0 kW | IR heaters, space heaters (silent, instant response) |
| 5 | EV Charging | 7.0 kW | Electric vehicle (lowest priority, can use grid) |

**Cascade behavior:**
```
Example: 5.5 kW surplus available

1. Battery:           allocate min(5.5, 5.0) = 5.0 kW  → remaining 0.5 kW
2. DHW:               allocate min(0.5, 3.0) = 0.5 kW  → remaining 0.0 kW
3. Space Heating:     allocate min(0.0, 3.0) = 0.0 kW
4. Supplemental:      allocate min(0.0, 2.0) = 0.0 kW
5. EV Charging:       allocate min(0.0, 7.0) = 0.0 kW

Result: {'battery': 5.0, 'dhw': 0.5}
```

## Database Schema

### hems.pv_allocation

Main allocation records:

```sql
SELECT timestamp, surplus_available_kw, allocation_dict, battery_soc_pct
FROM hems.pv_allocation
ORDER BY timestamp DESC
LIMIT 5;

-- Output:
-- timestamp            | surplus | allocation_dict                    | battery_soc
-- 2026-03-22 10:30:45 | 4.5     | {"battery": 5.0, "dhw": 0.5}      | 68.5
-- 2026-03-22 10:25:40 | 3.2     | {"battery": 3.0, "dhw": 0.2}      | 70.0
-- ...
```

### hems.pv_allocation_history

5-min tick history for analytics:

```sql
SELECT tick_timestamp, surplus_available_kw, allocated_total_kw, 
       remaining_kw, execution_time_ms
FROM hems.pv_allocation_history
ORDER BY tick_timestamp DESC
LIMIT 10;

-- Useful for:
-- - Calculating daily allocation efficiency
-- - Tracking cascade depth (how many priority tiers used)
-- - Performance monitoring (execution_time_ms)
-- - Analytics dashboards
```

## Monitoring & Dashboards

### InfluxDB Queries

Daily allocation summary:
```influx
from(bucket: "hems")
  |> range(start: -1d)
  |> filter(fn: (r) => r._measurement == "pv_allocator")
  |> aggregateWindow(every: 1h, fn: mean)
```

Per-device hourly allocation:
```influx
from(bucket: "hems")
  |> range(start: -1d)
  |> filter(fn: (r) => r._measurement == "pv_allocator")
  |> filter(fn: (r) => r._field =~ /allocated_.*_kw/)
  |> aggregateWindow(every: 1h, fn: sum)
```

### Example Dashboard Panels

1. **Allocation Waterfall** — Show cascade by priority:
   - X-axis: time
   - Y-axis stacked: allocated_battery, allocated_dhw, allocated_space, allocated_supplemental, allocated_ev

2. **Remaining Surplus Gauge** — Real-time status:
   - Current remaining_kw unallocated
   - Color: green (< 0.5 kW), yellow (0.5–1.5 kW), red (> 1.5 kW)

3. **Daily Allocation Efficiency** — Total surplus vs total allocated:
   - (total_allocated / total_surplus) * 100%
   - Target: > 90% efficiency

## Testing

Run comprehensive unit tests:

```bash
cd claude/services/hems
python3 -m pytest test_pv_allocator.py -v
```

**Test Coverage (23 tests):**

✅ Priority cascade logic (5 tests)
✅ Device capacity constraints (5 tests)
✅ Battery SoC limits (2 tests)
✅ Min allocation threshold (2 tests)
✅ Database persistence (1 test)
✅ HA enforcement (1 test)
✅ Edge cases (6 tests)
✅ Result serialization (1 test)

All tests pass with mocked dependencies (no real HA/database needed).

## Troubleshooting

### Allocations not being enforced

**Check:**
1. Orchestrator running? `curl http://orchestrator:8100/health`
2. HA service endpoints configured correctly (see `entity_map` in code)
3. HA token valid? Check logs for 401/403 errors
4. Entity IDs exist in HA? `curl http://ha:8123/api/states`

### Surplus not allocated to expected device

**Likely cause:** Device max capacity exceeded or SoC limit active

**Debug:**
```python
print(result.allocation_dict)
print(result.total_allocated_kw)
print(result.remaining_surplus_kw)
print(result.errors)  # Check for error messages
```

### Database records not persisting

**Check:**
1. PostgreSQL running? `psql -h 192.168.0.80 -c "SELECT 1"`
2. Migration applied? `SELECT table_name FROM information_schema.tables WHERE table_schema = 'hems'`
3. Database pool initialized? Check HEMS startup logs

## Future Enhancements

- [ ] **Dynamic PRIORITY_ORDER**: Override cascade based on day-of-week, season, occupancy mode
- [ ] **Cost-aware allocation**: Adjust priorities based on grid tariff
- [ ] **Weather-driven**: Predict cloud cover, pre-charge battery before clouds
- [ ] **EV schedule integration**: Prioritize EV charging if charging window ending soon
- [ ] **Thermal inertia**: Allocate to space heating based on demand forecast, not current demand
- [ ] **Battery strategy module**: Coordinate with battery discharge strategy for next day

## References

- **Spec:** `atlas/projects/hems/03_PHASE_PLAN.md` — Phase 3.2 PV Budget Allocator
- **HEMS Spec:** `atlas/projects/hems/01_SPEC_ADAPTED.md` — §7.4 PV Orchestration
- **Database:** `migrations/004_pv_allocation.sql`
- **Tests:** `test_pv_allocator.py`
- **Integration:** Control loop integration in `main.py`
