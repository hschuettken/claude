"""Decision Journal — structured "why" records for EV planning + control.

Every plan generation and every meaningful control-loop decision writes
one record. Records flow to (a) NATS for real-time consumers (dashboard,
ProactiveEngine) and (b) Influx ``analytics`` bucket for audit + analysis.

Best-effort: failures are logged but never propagate. The service must
keep running even if Influx or NATS is down.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.nats_client import NatsPublisher

logger = get_logger("decision_journal")


# Allowed values — kept as frozensets so callers can validate cheaply.
DECISION_KINDS = frozenset(
    {
        "plan_generated",
        "mode_selected",
        "target_power_set",
        "battery_drain_decided",
        "override_applied",
        "presence_reactor_triggered",
    }
)

OUTCOME_CLASSES = frozenset(
    {
        "charge",
        "hold",
        "drain_battery",
        "error",
    }
)


class DecisionJournal:
    """Best-effort writer for ev_decisions Influx measurement + NATS subject.

    Construct once per service. Pass through to planner + control loop.
    Never raises.
    """

    def __init__(
        self,
        influx_admin: InfluxClient,
        nats: NatsPublisher | None,
        service: str,
        bucket: str = "analytics",
        vehicle: str = "audi_a6_etron",
    ) -> None:
        self._influx = influx_admin
        self._nats = nats
        self._service = service
        self._bucket = bucket
        self._vehicle = vehicle

    @staticmethod
    def new_trace_id() -> str:
        """Generate a short trace_id linking a plan to resulting control decisions."""
        return uuid.uuid4().hex[:12]

    async def write(
        self,
        decision_kind: str,
        outcome: str,
        reason: str,
        *,
        outcome_class: str = "charge",
        trace_id: str | None = None,
        current_soc_pct: float | None = None,
        target_soc_pct: float | None = None,
        energy_needed_kwh: float | None = None,
        pv_available_w: int | None = None,
        home_battery_soc_pct: int | None = None,
        target_power_w: int | None = None,
        urgency: str | None = None,
        mode: str | None = None,
        inputs: dict[str, Any] | None = None,
        alternatives: list[dict[str, Any]] | None = None,
    ) -> None:
        """Best-effort write. Never raises."""
        if decision_kind not in DECISION_KINDS:
            logger.warning("invalid_decision_kind", kind=decision_kind)
            return
        if outcome_class not in OUTCOME_CLASSES:
            logger.warning("invalid_outcome_class", outcome_class=outcome_class)
            return

        ts = datetime.now(timezone.utc)
        tid = trace_id or self.new_trace_id()

        # Build fields dict — only include non-None values to keep Influx tidy.
        fields: dict[str, Any] = {
            "outcome": outcome,
            "reason": reason,
            "trace_id": tid,
        }
        if current_soc_pct is not None:
            fields["current_soc_pct"] = float(current_soc_pct)
        if target_soc_pct is not None:
            fields["target_soc_pct"] = float(target_soc_pct)
        if energy_needed_kwh is not None:
            fields["energy_needed_kwh"] = float(energy_needed_kwh)
        if pv_available_w is not None:
            fields["pv_available_w"] = int(pv_available_w)
        if home_battery_soc_pct is not None:
            fields["home_battery_soc_pct"] = int(home_battery_soc_pct)
        if target_power_w is not None:
            fields["target_power_w"] = int(target_power_w)
        if urgency is not None:
            fields["urgency"] = urgency
        if mode is not None:
            fields["mode"] = mode
        if inputs is not None:
            fields["inputs_json"] = json.dumps(inputs, default=str)
        if alternatives is not None:
            fields["alternatives_json"] = json.dumps(alternatives, default=str)

        tags = {
            "service": self._service,
            "decision_kind": decision_kind,
            "outcome_class": outcome_class,
            "vehicle": self._vehicle,
        }

        # 1. Write to Influx — best effort
        try:
            self._influx.write_point(
                bucket=self._bucket,
                measurement="ev_decisions",
                fields=fields,
                tags=tags,
                timestamp=ts,
            )
        except Exception:
            logger.warning(
                "journal_influx_write_failed", kind=decision_kind, exc_info=True
            )

        # 2. Publish to NATS — best effort
        if self._nats is not None and getattr(self._nats, "connected", False):
            try:
                payload = {
                    "timestamp": ts.isoformat(),
                    **tags,
                    **fields,
                }
                subject = (
                    "energy.ev.decision.plan"
                    if decision_kind == "plan_generated"
                    else "energy.ev.decision.control"
                )
                await self._nats.publish(subject, payload)
            except Exception:
                logger.warning(
                    "journal_nats_publish_failed", kind=decision_kind, exc_info=True
                )
