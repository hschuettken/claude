"""Plan-vs-actual reconciliation for ev-forecast (S2.5).

Run nightly to reconcile predicted demand vs actual driving + charging + PV
self-consumption + grid import. One row per day to `ev_plan_accuracy` in
`analytics` bucket.

Sources:
- Predicted demand/PV/grid: last `plan_generated` row of the day from `ev_decisions`
- Actual driving: Audi mileage delta × dynamic consumption rate
- Actual charging: amtron meter delta
- Actual grid import during day: integrated negative grid power
- Actual PV-for-EV: max(0, charging - grid_import)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

from shared.log import get_logger

if TYPE_CHECKING:
    from shared.influx_client import InfluxClient

logger = get_logger("ev_accuracy")


@dataclass
class AccuracyRow:
    target_date: date
    predicted_demand_kwh: float
    actual_demand_kwh: float
    predicted_pv_kwh: float
    actual_pv_kwh: float
    predicted_grid_kwh: float
    actual_grid_kwh: float

    @property
    def mae_kwh(self) -> float:
        return abs(self.predicted_demand_kwh - self.actual_demand_kwh)

    @property
    def bias_kwh(self) -> float:
        # positive = over-predicted demand
        return self.predicted_demand_kwh - self.actual_demand_kwh


async def compute_accuracy_for_date(
    target_date: date,
    influx_admin: "InfluxClient",
    influx_hass: "InfluxClient",
    *,
    consumption_kwh_per_100km: float = 22.0,
    analytics_bucket: str = "analytics",
    hass_bucket: str = "hass",
) -> AccuracyRow | None:
    """Compute reconciliation row for `target_date`. Returns None if no data."""
    start_iso = datetime.combine(
        target_date, time(0, 0), tzinfo=timezone.utc
    ).isoformat()
    end_iso = (
        datetime.combine(target_date, time(0, 0), tzinfo=timezone.utc)
        + timedelta(days=1)
    ).isoformat()

    predicted_demand = _query_predicted_demand(
        influx_admin, start_iso, end_iso, analytics_bucket
    )
    predicted_pv, predicted_grid = _query_predicted_pv_grid(
        influx_admin, start_iso, end_iso, analytics_bucket
    )

    mileage_delta_km = _query_mileage_delta(
        influx_hass, start_iso, end_iso, hass_bucket
    )
    actual_demand = (mileage_delta_km or 0.0) * consumption_kwh_per_100km / 100.0

    actual_charge_total = (
        _query_amtron_delta(influx_hass, start_iso, end_iso, hass_bucket) or 0.0
    )

    actual_grid = (
        _query_grid_import_during_day(influx_hass, start_iso, end_iso, hass_bucket)
        or 0.0
    )
    actual_pv = max(0.0, actual_charge_total - actual_grid)

    if predicted_demand is None and actual_demand == 0.0 and actual_charge_total == 0.0:
        return None

    return AccuracyRow(
        target_date=target_date,
        predicted_demand_kwh=predicted_demand or 0.0,
        actual_demand_kwh=actual_demand,
        predicted_pv_kwh=predicted_pv or 0.0,
        actual_pv_kwh=actual_pv,
        predicted_grid_kwh=predicted_grid or 0.0,
        actual_grid_kwh=actual_grid,
    )


def write_accuracy_row(
    row: AccuracyRow,
    influx_admin: "InfluxClient",
    bucket: str = "analytics",
) -> None:
    """Write one accuracy row to Influx, stamped at 20:00 UTC of target_date."""
    influx_admin.write_point(
        bucket=bucket,
        measurement="ev_plan_accuracy",
        fields={
            "predicted_demand_kwh": round(row.predicted_demand_kwh, 2),
            "actual_demand_kwh": round(row.actual_demand_kwh, 2),
            "predicted_pv_kwh": round(row.predicted_pv_kwh, 2),
            "actual_pv_kwh": round(row.actual_pv_kwh, 2),
            "predicted_grid_kwh": round(row.predicted_grid_kwh, 2),
            "actual_grid_kwh": round(row.actual_grid_kwh, 2),
            "mae_kwh": round(row.mae_kwh, 2),
            "bias_kwh": round(row.bias_kwh, 2),
        },
        tags={"vehicle": "audi_a6_etron"},
        timestamp=datetime.combine(row.target_date, time(20, 0), tzinfo=timezone.utc),
    )


# ----- Internal queries -----


def _query_predicted_demand(
    client: "InfluxClient", start: str, end: str, bucket: str
) -> float | None:
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r._measurement == "ev_decisions")
  |> filter(fn: (r) => r.decision_kind == "plan_generated")
  |> filter(fn: (r) => r._field == "energy_needed_kwh")
  |> last()
'''
    return _scalar_from_flux(client, flux)


def _query_predicted_pv_grid(
    client: "InfluxClient", start: str, end: str, bucket: str
) -> tuple[float | None, float | None]:
    """Read predicted PV/grid split from last plan's `inputs_json` (best-effort)."""
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r._measurement == "ev_decisions")
  |> filter(fn: (r) => r.decision_kind == "plan_generated")
  |> filter(fn: (r) => r._field == "inputs_json")
  |> last()
'''
    raw = _string_from_flux(client, flux)
    if not raw:
        return None, None
    try:
        data = json.loads(raw)
        sched = data.get("schedule") or []
        pv = sum(float(w.get("kwh", 0.0)) for w in sched if w.get("source") == "pv")
        grid = sum(float(w.get("kwh", 0.0)) for w in sched if w.get("source") == "grid")
        return pv, grid
    except (json.JSONDecodeError, AttributeError, TypeError):
        return None, None


def _query_mileage_delta(
    client: "InfluxClient", start: str, end: str, bucket: str
) -> float | None:
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r.entity_id == "audi_a6_avant_e_tron_mileage")
  |> filter(fn: (r) => r._field == "value")
  |> spread()
'''
    return _scalar_from_flux(client, flux)


def _query_amtron_delta(
    client: "InfluxClient", start: str, end: str, bucket: str
) -> float | None:
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r.entity_id == "amtron_meter_total_energy_kwh")
  |> filter(fn: (r) => r._field == "value")
  |> spread()
'''
    return _scalar_from_flux(client, flux)


def _query_grid_import_during_day(
    client: "InfluxClient", start: str, end: str, bucket: str
) -> float | None:
    """Approximate grid-imported-for-EV: integrate negative grid power over day.

    v1 simplification: assumes EV is the dominant overnight load. Refine in v2.
    """
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r.entity_id == "power_meter_active_power")
  |> filter(fn: (r) => r._field == "value")
  |> map(fn: (r) => ({{ r with _value: if r._value < 0.0 then -r._value else 0.0 }}))
  |> integral(unit: 1h)
  |> map(fn: (r) => ({{ r with _value: r._value / 1000.0 }}))
'''
    return _scalar_from_flux(client, flux)


def _scalar_from_flux(client: "InfluxClient", flux: str) -> float | None:
    """Run a Flux query and return the first numeric _value, or None."""
    try:
        tables = client.query_raw(flux)
    except Exception as exc:
        logger.warning("flux_query_failed", error=str(exc), flux=flux[:200])
        return None
    for table in tables:
        for record in table.records:
            v = record.get_value()
            if v is None:
                continue
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _string_from_flux(client: "InfluxClient", flux: str) -> str | None:
    try:
        tables = client.query_raw(flux)
    except Exception as exc:
        logger.warning("flux_query_failed", error=str(exc), flux=flux[:200])
        return None
    for table in tables:
        for record in table.records:
            v = record.get_value()
            if v is not None:
                return str(v)
    return None
