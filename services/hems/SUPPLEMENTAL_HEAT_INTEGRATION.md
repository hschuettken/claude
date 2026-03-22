# Supplemental Heat Controller Integration Guide

## Overview

The `supplemental_heat.py` module provides automatic control of IR heaters and space heaters based on PV solar surplus. It's designed to utilize excess solar generation that would otherwise be fed back to the grid.

## Features

- **Surplus Detection**: Monitors PV generation vs household load
- **Smart Activation**: Requires minimum surplus (3 kW default) for minimum duration (15 min default) before turning on
- **Safe Deactivation**: Turns off when surplus drops below threshold (1.5 kW default) or daily max hours exceeded (4 hours default)
- **Daily Limits**: Prevents excessive runtime with configurable max daily hours
- **InfluxDB Logging**: Records all state transitions and runtime metrics
- **Home Assistant Integration**: Controls IR heater switches via Home Assistant (switch.ir_heater_1, switch.ir_heater_2, etc.)
- **Orchestrator-Compatible**: Works with or without direct HA token via orchestrator tool calls

## Configuration

### Default Configuration

```python
from supplemental_heat import SupplementalHeatConfig, SupplementalHeatController

config = SupplementalHeatConfig()
# Defaults:
# - min_surplus_kw: 3.0
# - off_threshold_kw: 1.5
# - min_duration_min: 15.0
# - max_daily_hours: 4.0
# - entity_names: ["switch.ir_heater_1", "switch.ir_heater_2"]
# - use_orchestrator: True
```

### Custom Configuration

```python
config = SupplementalHeatConfig(
    min_surplus_kw=2.5,        # Lower threshold to be more aggressive
    off_threshold_kw=1.0,      # Turn off earlier
    min_duration_min=10.0,     # Faster activation
    max_daily_hours=6.0,       # Allow longer daily runtime
    entity_names=["switch.ir_heater_main", "switch.space_heater"],
)

controller = SupplementalHeatController(config=config)
```

## Home Assistant Setup

### Required Entities

The controller needs switch entities for the IR heaters. In Home Assistant, these can be:

1. **Smart switches with relays** (e.g., Shelly, Sonoff)
2. **Climate entities** with custom automation
3. **Input booleans** with associated automations

Example automation in `automations.yaml`:

```yaml
- alias: "IR Heater 1 Control"
  trigger:
    platform: state
    entity_id: switch.ir_heater_1
  action:
    - service: homeassistant.turn_on
      target:
        entity_id: switch.ir_heater_relay_1
```

Or for direct relay control via GPIO/relay module:

```yaml
switch:
  - platform: mqtt
    name: "IR Heater 1"
    command_topic: "home/heating/ir_heater_1/command"
    state_topic: "home/heating/ir_heater_1/state"
```

## Integration into HEMS Control Loop

### Option 1: Integration in `main.py` Control Loop (Recommended)

Modify `control_loop()` in `main.py`:

```python
from supplemental_heat import SupplementalHeatController, SupplementalHeatConfig

# Global instance (initialize in lifespan)
_supplemental_heat_controller: Optional[SupplementalHeatController] = None

async def control_loop(settings: HEMSSettings) -> None:
    """Background control loop — runs every 10 seconds."""
    global _supplemental_heat_controller
    
    # ... existing boiler/mixer logic ...
    
    # Call supplemental heat controller
    # Fetch PV surplus data from sensors
    solar_power_w = await _fetch_solar_power()  # From sensor.solar_current_power
    household_load_w = await _fetch_household_load()  # From sensor.household_power
    
    if _supplemental_heat_controller:
        result = await _supplemental_heat_controller.tick(
            solar_power_w=solar_power_w,
            household_load_w=household_load_w,
            dt_s=10.0,
        )
        logger.info(
            "Supplemental heat: %s (surplus=%.1f kW, daily=%.2f h)",
            result["log_message"],
            result["surplus_kw"],
            result["daily_runtime_h"],
        )
```

In `lifespan()` startup:

```python
# Initialize supplemental heat controller
config = SupplementalHeatConfig()
_supplemental_heat_controller = SupplementalHeatController(
    config=config,
    influxdb_write_api=_influxdb_write_api,
)
logger.info("Supplemental heat controller initialized")
```

### Option 2: Standalone Task

If you prefer separate task scheduling:

```python
async def supplemental_heat_loop(settings: HEMSSettings) -> None:
    """Dedicated loop for supplemental heat control."""
    config = SupplementalHeatConfig()
    controller = SupplementalHeatController(
        config=config,
        influxdb_write_api=_influxdb_write_api,
    )
    
    while True:
        try:
            solar_power_w = await _fetch_solar_power()
            household_load_w = await _fetch_household_load()
            
            result = await controller.tick(
                solar_power_w=solar_power_w,
                household_load_w=household_load_w,
                dt_s=30.0,  # Run every 30 seconds
            )
            logger.debug("Supplemental heat: %s", result["log_message"])
        except Exception as e:
            logger.error("Error in supplemental heat loop: %s", e)
        
        await asyncio.sleep(30)

# In lifespan():
_supplemental_heat_task = asyncio.create_task(supplemental_heat_loop(settings))
```

## Sensor Data Source

The controller needs two sensor inputs:

1. **Solar Generation**: `sensor.solar_current_power` (watts)
2. **Household Load**: `sensor.household_power` (watts)

These should be available from:
- **Solar**: Inverter API (e.g., Fronius, SMA)
- **Household Load**: Smart meter or sum of sub-meters

Example queries from orchestrator:

```python
async def _fetch_solar_power() -> float:
    """Fetch solar power from HA."""
    state = await ha_client.get_state("sensor.solar_current_power")
    return float(state.get("state", 0))

async def _fetch_household_load() -> float:
    """Fetch household power consumption."""
    state = await ha_client.get_state("sensor.household_power")
    return float(state.get("state", 0))
```

## API Endpoints

### Get Controller Status

```python
@router.get("/api/v1/hems/supplemental-heat/status")
async def get_supplemental_heat_status():
    if _supplemental_heat_controller:
        return _supplemental_heat_controller.get_status()
    return {"error": "Controller not initialized"}
```

Example response:

```json
{
  "state": "on",
  "is_on": true,
  "runtime_s": 3600,
  "daily_runtime_s": 3600,
  "daily_runtime_h": 1.0,
  "daily_remaining_h": 3.0,
  "surplus_on_time_min": 45.5,
  "config": {
    "min_surplus_kw": 3.0,
    "off_threshold_kw": 1.5,
    "min_duration_min": 15.0,
    "max_daily_hours": 4.0,
    "entity_names": ["switch.ir_heater_1", "switch.ir_heater_2"]
  }
}
```

## InfluxDB Metrics

The controller logs to InfluxDB bucket `hems` with the following fields:

- `surplus_kw`: Current PV surplus (float)
- `is_on`: Heater power state (boolean)
- `daily_runtime_h`: Daily runtime in hours (float)
- `surplus_on_time_min`: Time accumulating surplus (float)
- `session_runtime_s`: Current session runtime in seconds (float)

Tag: `state` (off, charging, on, cooldown)

Query example:

```
from(bucket: "hems")
  |> range(start: -1h)
  |> filter(fn: (r) => r["_measurement"] == "supplemental_heat_controller")
  |> filter(fn: (r) => r["state"] == "on")
```

## State Machine

```
    ┌─────────┐
    │   OFF   │◄─────────────────────┐
    └────┬────┘                      │
         │                           │
  Surplus >                          │
  3.0kW?                             │
         │                           │
         v                           │
    ┌─────────┐                      │
    │ CHARGING│                      │
    └────┬────┘                      │
         │                           │
  Duration >                         │
  15 min?                            │
         │                           │
         v                           │
    ┌─────────┐                      │
    │   ON    │◄────────┐            │
    └────┬────┘         │            │
         │              │            │
  Surplus <    Daily max │            │
  1.5kW?      exceeded?  │            │
         │                           │
         v                           │
    ┌─────────┐                      │
    │ COOLDOWN│──────────────────────┘
    └─────────┘
          │
       (wait for
        reset)
          │
          └──► OFF
```

## Error Handling

The controller handles the following gracefully:

1. **HA Connection Errors**: Logs warning, continues state machine
2. **Missing Sensors**: Treats as 0 surplus, stays OFF
3. **Daily Reset**: Automatically resets at midnight UTC
4. **InfluxDB Write Errors**: Non-blocking, continues operation

## Testing

Run unit tests:

```bash
cd claude/services/hems
python3 test_supplemental_heat_simple.py
```

All state transitions and daily limit enforcement are covered.

## Troubleshooting

### Heaters Not Turning On

1. Check HA entity_ids exist: `switch.ir_heater_1` in HA
2. Verify sufficient surplus: `logger.debug` will show current surplus_kw
3. Verify min_duration is accumulated: Watch `surplus_on_time_min` in logs
4. Check daily limit not exceeded: `daily_limit_exceeded` in status

### Heaters Turning Off Unexpectedly

1. Check solar power availability
2. Verify off_threshold setting (default 1.5 kW)
3. Check daily limit: `daily_remaining_h` should be > 0
4. Look for HA service call failures in logs

### High Daily Runtime

Adjust `max_daily_hours` in config or monitor via API `/api/v1/hems/supplemental-heat/status`.

## Future Enhancements

1. **Priority Queue**: Coordinate with battery charging, EV charging
2. **Weather Forecast**: Predict surplus drops, smarter activation
3. **ML Optimization**: Learn best times to heat (e.g., before price spikes)
4. **Multi-Zone Heating**: Different heater activation strategies per zone
5. **Economic Tracking**: Calculate savings vs grid price
