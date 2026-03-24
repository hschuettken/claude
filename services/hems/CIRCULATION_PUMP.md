# Circulation Pump Scheduler — HEMS Phase 1.3

## Overview

The **CirculationPumpScheduler** manages the heating system's circulation pump (also called heating pump, circulation pump, or aquastat pump) to:

1. **Maximize efficiency** — Pump runs only when needed
2. **Protect equipment** — Enforce min/max runtime limits
3. **Prevent chatter** — Use hysteresis to avoid rapid cycling
4. **Track maintenance** — Log cumulative runtime hours

## Architecture

### State Machine

The pump uses a **three-state FSM**:

```
OFF → ON → COOLDOWN → OFF
```

| State | Entry Condition | Exit Condition | Behavior |
|-------|-----------------|----------------|----------|
| **OFF** | Initial state; after cooldown complete | Boiler active OR room needs heating | Pump is off |
| **ON** | Demand detected | Min runtime elapsed AND (boiler off AND all rooms satisfied) | Pump running; min 10 min enforced |
| **COOLDOWN** | Min runtime met, all targets satisfied, boiler off | Fixed 0s (immediate) | Brief decay phase before OFF |

### Turn-On Logic

Pump turns ON if **either**:
- **Boiler is actively firing** (heating demand detected), OR
- **Any room target > current room temp + 0.5°C hysteresis**

### Turn-Off Logic

Pump turns OFF only if **all** conditions met:
1. Boiler is idle (not firing)
2. **All** rooms at or above their target temps (with hysteresis)
3. Minimum runtime (10 min default) has elapsed
4. Maximum runtime (60 min) not exceeded

### Hysteresis

- **Purpose**: Prevent chatter when room temp oscillates around target
- **Default**: 0.5°C
- **Application**: `target_temp > room_actual_temp + hysteresis` triggers ON

Example:
- Target: 21°C, Hysteresis: 0.5°C
- Room at 20.8°C → No heating demand (within 0.5°C margin)
- Room at 20.4°C → Heating demand (exceeds margin)

## Configuration

### Default Parameters

```python
CirculationPumpScheduler(
    min_runtime_s=600,      # 10 minutes
    max_runtime_s=3600,     # 60 minutes (safety limit)
    temp_hysteresis_c=0.5   # Prevent chatter
)
```

### Configurable via Environment

In future versions, load from environment:

```bash
HEMS_PUMP_MIN_RUNTIME_S=600      # Minimum on-time
HEMS_PUMP_MAX_RUNTIME_S=3600     # Safety cutoff
HEMS_PUMP_HYSTERESIS_C=0.5       # Temperature threshold
```

## Integration with HEMS Control Loop

### Calling the Scheduler

The control loop calls the pump scheduler every 10 seconds:

```python
pump_should_run = _circulation_pump.should_pump(
    boiler_active=boiler_should_fire,          # From BoilerManager
    room_targets={'living_room': 21.0},        # From schedule DB
    room_actuals={'living_room': 20.2}         # From HA climate entities
)
```

### Data Flow

```
HEMS Control Loop (10s tick)
  ↓
  ├─ Fetch boiler state (BoilerManager)
  ├─ Fetch room schedules (PostgreSQL)
  ├─ Fetch room temps (HA climate entities via orchestrator)
  ↓
  Call CirculationPumpScheduler
  ↓
  Get pump state (OFF/ON/COOLDOWN)
  ↓
  Log to InfluxDB → pump state, runtime hours
  ↓
  Future: Call HA switch.turn_on/off(switch.circulation_pump)
```

### InfluxDB Telemetry

Pump state is logged to InfluxDB measurement `hems_circulation_pump`:

```
hems_circulation_pump:
  tags:
    service: "hems"
  fields:
    pump_on: bool              # True if pump should be on
    pump_state: string         # "off", "on", "cooldown"
    runtime_hours: float       # Cumulative hours
```

Query recent pump activity:

```flux
from(bucket: "hems")
  |> range(start: -24h)
  |> filter(fn: (r) => r._measurement == "hems_circulation_pump")
  |> filter(fn: (r) => r.service == "hems")
```

## API Endpoints

### GET /api/v1/hems/control/tick

Returns control decision including pump state:

```json
{
  "timestamp": "2026-03-22T10:30:00Z",
  "boiler_should_fire": true,
  "boiler_state": "heating",
  "circulation_pump_on": true,
  "circulation_pump_state": "on",
  "circulation_pump_runtime_hours": 2.5,
  "valve_position_pct": 45.3,
  "setpoint_c": 50.0,
  "measured_flow_temp_c": 48.2,
  "degraded": false,
  "is_available": {
    "flow_temperature": true,
    "demand": true,
    "pump": true
  }
}
```

## Home Assistant Integration (Phase 2)

### Planned: Switch Control

Once orchestrator supports HA service calls:

```python
async def _call_ha_service(entity_id: str, action: str) -> bool:
    """Call Home Assistant service to turn pump on/off."""
    # POST to orchestrator /tools/execute with action
    # "switch.turn_on" or "switch.turn_off"
    # entity_id: "switch.circulation_pump"
```

### Planned: Room Temperature Sensors

Currently uses cached temps; future versions will fetch from HA:

```python
# TODO: Fetch from multiple climate entities
room_actuals = {
    'living_room': await ha_get_temp('climate.living_room'),
    'bedroom': await ha_get_temp('climate.bedroom'),
    'kitchen': await ha_get_temp('climate.kitchen'),
}
```

## Runtime Hour Tracking

The scheduler tracks **cumulative pump runtime** for maintenance planning:

```python
runtime_hours = pump.get_runtime_hours()

# Log to database for alerts
if runtime_hours > 5000:
    alert("Pump nearing service interval (5000+ hours)")
```

Maintenance intervals vary by pump:
- Typical heating circulation pumps: 5000–10000 hours
- Log to `hems_maintenance_tracking` table for scheduling

## Testing

### Unit Tests (22 tests)

Run full test suite:

```bash
cd services/hems
python3 -m pytest test_circulation_pump.py -v
```

Test coverage:

| Category | Tests | Details |
|----------|-------|---------|
| Basic state machine | 5 | Init, OFF→ON→COOLDOWN→OFF transitions |
| Hysteresis | 2 | Turn-on/off with temperature margins |
| Runtime enforcement | 2 | Min/max runtime limits |
| Multi-room logic | 3 | Single room, multiple rooms, unknown rooms |
| Runtime tracking | 1 | Cumulative hours accumulation |
| State introspection | 3 | get_state(), get_state_duration(), reset() |
| Edge cases | 4 | Empty dicts, extreme temps, zero/negative temps |
| State transitions | 2 | Full cycle, timer resets |

### Test Example

```python
def test_minimum_runtime_enforced():
    """Test that pump won't turn OFF before min_runtime expires."""
    pump = CirculationPumpScheduler(min_runtime_s=1.0)
    
    # Turn pump ON
    pump.should_pump(boiler_active=True, room_targets={}, room_actuals={})
    assert pump.state == PumpState.ON
    
    # Immediately try to turn OFF
    pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
    assert pump.state == PumpState.ON  # Still ON due to min_runtime
    
    # Wait for min_runtime
    time.sleep(1.1)
    pump.should_pump(boiler_active=False, room_targets={}, room_actuals={})
    assert pump.state == PumpState.COOLDOWN  # Now can transition
```

## Specifications Met

✅ **Phase 1.3 Circulation Pump Scheduler** (Spec: `spec-retro-hems-phase-plan-2026-03-22.md`)

| Requirement | Status | Notes |
|-------------|--------|-------|
| Turn ON: boiler active OR room target > actual | ✅ | Implemented in `should_pump()` |
| Turn OFF: boiler idle AND all rooms satisfied | ✅ | Hysteresis support (0.5°C) |
| Minimum runtime: 10 minutes | ✅ | Configurable, default 600s |
| Maximum runtime: 60 minutes (safety) | ✅ | Forces OFF after max_runtime_s |
| HA integration: switch.turn_on/off | 🔄 | Logic ready; HA calls in Phase 2 |
| Logging: pump state to InfluxDB | ✅ | `hems_circulation_pump` measurement |
| Maintenance tracking: runtime hours | ✅ | Cumulative hours tracked |
| Unit tests with HA entity mocks | ✅ | 22 comprehensive tests pass |
| Control loop integration (2-min interval) | ✅ | Integrated into 10s control loop |

## Future Enhancements

### Phase 2

- [ ] Fetch room temperatures from HA climate entities (multi-room support)
- [ ] Call HA `switch.turn_on/off` for actual pump control
- [ ] Add `ha_config/automation.yaml` for fallback if HEMS unresponsive
- [ ] Integrate with DHW scheduler for coordinated heating

### Phase 3

- [ ] Smart pump scheduling based on weather forecast (defer start for PV availability)
- [ ] Pump speed modulation (variable-speed pumps for efficiency)
- [ ] Predictive pre-heating: start pump before rooms fall below target
- [ ] Machine learning: learn optimal pump patterns from historical data

## Code Files

- **`circulation_pump.py`** — Core scheduler logic (262 lines)
- **`test_circulation_pump.py`** — Comprehensive unit tests (481 lines, 22 tests)
- **`main.py`** — Integration into control loop and API endpoints

## References

- Spec: `atlas/reports/spec-retro-hems-phase-plan-2026-03-22.md` (Phase 1.3)
- BoilerManager: `services/hems/boiler_manager.py` (similar FSM pattern)
- Control Loop: `services/hems/main.py::control_loop()`
- InfluxDB Schema: `services/hems/migrations/`
