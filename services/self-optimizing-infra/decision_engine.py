"""Phase 1 — Decision Engine: rule evaluation + auto-approve framework.

Rules are stored in PostgreSQL (soi_decision_rules) and evaluated every
`decision_loop_interval_seconds` against the L2 infra snapshot.

Risk levels and auto-approve policy:
  low    → auto-approved and executed immediately via ops-bridge
  medium → auto-approved but held for MEDIUM_HOLD_SECONDS before execution
            (human can reject within that window)
  high   → always requires human approval via POST /api/v1/decisions/{id}/approve
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx

from . import db
from .config import settings
from .models import Decision, DecisionCreate, DecisionRule, DecisionRuleCreate

logger = logging.getLogger(__name__)

MEDIUM_HOLD_SECONDS = 600  # 10-minute window for human cancellation

# ─────────────────────────────────────────────────────────────────────────────
# Default rules seeded on first start
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "service_offline_restart",
        "description": "Restart a homelab service that has gone offline (L0 heartbeat missing).",
        "condition_type": "heartbeat_missing",
        "condition_params": {"timeout_seconds": 300},
        "action_type": "restart_service",
        "action_params": {},
        "risk_level": "low",
        "auto_approve": True,
        "cooldown_minutes": 15,
    },
    {
        "name": "node_high_cpu_alert",
        "description": "Alert when a Proxmox/Bootstrap node sustains >85% CPU.",
        "condition_type": "cpu_high",
        "condition_params": {"threshold_pct": 85},
        "action_type": "alert_telegram",
        "action_params": {"message_template": "Node {target} CPU at {value:.1f}%"},
        "risk_level": "low",
        "auto_approve": True,
        "cooldown_minutes": 30,
    },
    {
        "name": "node_high_memory_alert",
        "description": "Alert when a node memory exceeds 90%.",
        "condition_type": "mem_high",
        "condition_params": {"threshold_pct": 90},
        "action_type": "alert_telegram",
        "action_params": {"message_template": "Node {target} memory at {value:.1f}%"},
        "risk_level": "low",
        "auto_approve": True,
        "cooldown_minutes": 30,
    },
    {
        "name": "node_offline_investigate",
        "description": "Create remediation task when an infra node goes offline.",
        "condition_type": "node_down",
        "condition_params": {},
        "action_type": "create_task",
        "action_params": {"task_type": "infra_remediation", "priority": 5},
        "risk_level": "medium",
        "auto_approve": True,
        "cooldown_minutes": 20,
    },
    {
        "name": "k3s_node_notready_reboot",
        "description": "Propose reboot for a K3s node stuck in NotReady state.",
        "condition_type": "node_down",
        "condition_params": {"source": "k3s"},
        "action_type": "reboot_node",
        "action_params": {},
        "risk_level": "high",
        "auto_approve": False,
        "cooldown_minutes": 60,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Rule CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def seed_default_rules() -> None:
    """Insert default rules if the table is empty."""
    count = await db.fetchval("SELECT COUNT(*) FROM soi_decision_rules")
    if count and int(count) > 0:
        return
    for r in DEFAULT_RULES:
        try:
            await db.execute(
                """
                INSERT INTO soi_decision_rules
                    (name, description, condition_type, condition_params,
                     action_type, action_params, risk_level, auto_approve,
                     cooldown_minutes)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                ON CONFLICT (name) DO NOTHING
                """,
                r["name"], r["description"], r["condition_type"],
                json.dumps(r["condition_params"]),
                r["action_type"], json.dumps(r["action_params"]),
                r["risk_level"], r["auto_approve"], r["cooldown_minutes"],
            )
        except Exception as exc:
            logger.warning("seed_rule_failed name=%s error=%s", r["name"], exc)
    logger.info("soi default_rules_seeded count=%d", len(DEFAULT_RULES))


async def create_rule(data: DecisionRuleCreate) -> Optional[DecisionRule]:
    row = await db.fetchrow(
        """
        INSERT INTO soi_decision_rules
            (name, description, condition_type, condition_params,
             action_type, action_params, risk_level, auto_approve,
             enabled, cooldown_minutes)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
        RETURNING *
        """,
        data.name, data.description, data.condition_type,
        json.dumps(data.condition_params),
        data.action_type, json.dumps(data.action_params),
        data.risk_level, data.auto_approve, data.enabled, data.cooldown_minutes,
    )
    return _row_to_rule(row) if row else None


async def list_rules(enabled_only: bool = False) -> list[DecisionRule]:
    q = "SELECT * FROM soi_decision_rules"
    if enabled_only:
        q += " WHERE enabled = true"
    q += " ORDER BY created_at"
    rows = await db.fetch(q)
    return [_row_to_rule(r) for r in rows]


async def get_rule(rule_id: uuid.UUID) -> Optional[DecisionRule]:
    row = await db.fetchrow("SELECT * FROM soi_decision_rules WHERE id=$1", rule_id)
    return _row_to_rule(row) if row else None


async def toggle_rule(rule_id: uuid.UUID, enabled: bool) -> Optional[DecisionRule]:
    row = await db.fetchrow(
        "UPDATE soi_decision_rules SET enabled=$1 WHERE id=$2 RETURNING *",
        enabled, rule_id,
    )
    return _row_to_rule(row) if row else None


def _row_to_rule(row: Any) -> DecisionRule:
    return DecisionRule(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        condition_type=row["condition_type"],
        condition_params=row["condition_params"] if isinstance(row["condition_params"], dict)
                         else json.loads(row["condition_params"] or "{}"),
        action_type=row["action_type"],
        action_params=row["action_params"] if isinstance(row["action_params"], dict)
                      else json.loads(row["action_params"] or "{}"),
        risk_level=row["risk_level"],
        auto_approve=row["auto_approve"],
        enabled=row["enabled"],
        cooldown_minutes=row["cooldown_minutes"],
        created_at=row["created_at"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Decision CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def create_decision(data: DecisionCreate) -> Optional[Decision]:
    row = await db.fetchrow(
        """
        INSERT INTO soi_decisions
            (rule_id, rule_name, trigger_data, action_type, action_params,
             risk_level, auto_approved)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING *
        """,
        data.rule_id, data.rule_name,
        json.dumps(data.trigger_data),
        data.action_type, json.dumps(data.action_params),
        data.risk_level, data.auto_approved,
    )
    return _row_to_decision(row) if row else None


async def list_decisions(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Decision]:
    if status:
        rows = await db.fetch(
            "SELECT * FROM soi_decisions WHERE status=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            status, limit, offset,
        )
    else:
        rows = await db.fetch(
            "SELECT * FROM soi_decisions ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
    return [_row_to_decision(r) for r in rows]


async def get_decision(decision_id: uuid.UUID) -> Optional[Decision]:
    row = await db.fetchrow("SELECT * FROM soi_decisions WHERE id=$1", decision_id)
    return _row_to_decision(row) if row else None


async def approve_decision(decision_id: uuid.UUID, approved_by: str) -> Optional[Decision]:
    row = await db.fetchrow(
        """
        UPDATE soi_decisions
        SET status='approved', approved_by=$1, approved_at=NOW()
        WHERE id=$2 AND status='pending'
        RETURNING *
        """,
        approved_by, decision_id,
    )
    return _row_to_decision(row) if row else None


async def reject_decision(
    decision_id: uuid.UUID, rejected_by: str, reason: str = ""
) -> Optional[Decision]:
    row = await db.fetchrow(
        """
        UPDATE soi_decisions
        SET status='rejected', approved_by=$1, result=$2, approved_at=NOW()
        WHERE id=$3 AND status IN ('pending', 'approved')
        RETURNING *
        """,
        rejected_by, f"rejected: {reason}", decision_id,
    )
    return _row_to_decision(row) if row else None


async def _mark_executing(decision_id: uuid.UUID) -> None:
    await db.execute(
        "UPDATE soi_decisions SET status='executing', executed_at=NOW() WHERE id=$1",
        decision_id,
    )


async def _mark_done(decision_id: uuid.UUID, result: str) -> None:
    await db.execute(
        "UPDATE soi_decisions SET status='done', result=$1 WHERE id=$2",
        result, decision_id,
    )


async def _mark_failed(decision_id: uuid.UUID, error: str) -> None:
    await db.execute(
        "UPDATE soi_decisions SET status='failed', result=$1 WHERE id=$2",
        error, decision_id,
    )


def _row_to_decision(row: Any) -> Decision:
    return Decision(
        id=row["id"],
        rule_id=row["rule_id"],
        rule_name=row["rule_name"],
        trigger_data=row["trigger_data"] if isinstance(row["trigger_data"], dict)
                     else json.loads(row["trigger_data"] or "{}"),
        action_type=row["action_type"],
        action_params=row["action_params"] if isinstance(row["action_params"], dict)
                      else json.loads(row["action_params"] or "{}"),
        risk_level=row["risk_level"],
        status=row["status"],
        auto_approved=row["auto_approved"],
        approved_by=row["approved_by"],
        result=row["result"],
        created_at=row["created_at"],
        approved_at=row["approved_at"],
        executed_at=row["executed_at"],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Rule evaluation
# ─────────────────────────────────────────────────────────────────────────────

async def _is_cooling_down(rule: DecisionRule) -> bool:
    """Return True if the rule fired recently and is in its cooldown window."""
    row = await db.fetchrow(
        """
        SELECT created_at FROM soi_decisions
        WHERE rule_id=$1 AND created_at > NOW() - INTERVAL '1 minute' * $2
        ORDER BY created_at DESC LIMIT 1
        """,
        rule.id, rule.cooldown_minutes,
    )
    return row is not None


def _evaluate_condition(rule: DecisionRule, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of trigger-data dicts (one per matching target, empty if no match)."""
    ctype = rule.condition_type
    cparams = rule.condition_params
    triggers: list[dict[str, Any]] = []

    if ctype == "heartbeat_missing":
        for svc in snapshot.get("offline_services", []):
            triggers.append({"service": svc, "reason": "heartbeat_missing"})
        for svc in snapshot.get("stale_services", []):
            if svc not in snapshot.get("offline_services", []):
                triggers.append({"service": svc, "reason": "stale_heartbeat"})

    elif ctype == "cpu_high":
        threshold = float(cparams.get("threshold_pct", 85))
        for node in snapshot.get("high_cpu_nodes", []):
            if node["cpu_percent"] >= threshold:
                triggers.append({
                    "node": node["name"],
                    "cpu_percent": node["cpu_percent"],
                })

    elif ctype == "mem_high":
        threshold = float(cparams.get("threshold_pct", 90))
        for node in snapshot.get("high_mem_nodes", []):
            if node["mem_percent"] >= threshold:
                triggers.append({
                    "node": node["name"],
                    "mem_percent": node["mem_percent"],
                })

    elif ctype == "node_down":
        required_source = cparams.get("source")
        for node_name in snapshot.get("offline_nodes", []):
            # source filter is best-effort (embedded in the name prefix)
            if required_source and not node_name.startswith(required_source):
                continue
            triggers.append({"node": node_name, "reason": "node_down"})

    return triggers


async def evaluate_rules(snapshot: dict[str, Any]) -> list[Decision]:
    """Evaluate all enabled rules against the current infra snapshot.

    Returns newly-created Decision objects (auto-approved where applicable).
    """
    rules = await list_rules(enabled_only=True)
    created: list[Decision] = []

    for rule in rules:
        try:
            if await _is_cooling_down(rule):
                continue
            triggers = _evaluate_condition(rule, snapshot)
            if not triggers:
                continue

            for trigger_data in triggers:
                action_params = dict(rule.action_params)
                # Inject target into action_params for restart / alert
                if "service" in trigger_data:
                    action_params.setdefault("service_name", trigger_data["service"])
                if "node" in trigger_data:
                    action_params.setdefault("node_name", trigger_data["node"])

                auto = rule.auto_approve and rule.risk_level in ("low", "medium")
                dc = DecisionCreate(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    trigger_data=trigger_data,
                    action_type=rule.action_type,
                    action_params=action_params,
                    risk_level=rule.risk_level,
                    auto_approved=auto,
                )
                decision = await create_decision(dc)
                if decision is None:
                    continue

                if auto:
                    if rule.risk_level == "low":
                        await approve_decision(decision.id, "system")
                        asyncio.create_task(_execute_decision(decision))
                    else:
                        # Medium risk: approve but hold before execution
                        await approve_decision(decision.id, "system")
                        asyncio.create_task(_delayed_execute(decision, MEDIUM_HOLD_SECONDS))

                created.append(decision)
                logger.info(
                    "soi decision_created rule=%s action=%s risk=%s auto=%s target=%s",
                    rule.name, rule.action_type, rule.risk_level, auto,
                    trigger_data,
                )
        except Exception as exc:
            logger.warning("soi rule_eval_error rule=%s error=%s", rule.name, exc)

    return created


# ─────────────────────────────────────────────────────────────────────────────
# Action execution
# ─────────────────────────────────────────────────────────────────────────────

async def _delayed_execute(decision: Decision, delay: float) -> None:
    await asyncio.sleep(delay)
    # Re-check status — human may have rejected during the hold window
    fresh = await get_decision(decision.id)
    if fresh and fresh.status == "approved":
        await _execute_decision(fresh)


async def _execute_decision(decision: Decision) -> None:
    await _mark_executing(decision.id)
    try:
        result = await _dispatch_action(decision.action_type, decision.action_params)
        await _mark_done(decision.id, result)
        logger.info("soi decision_done id=%s action=%s result=%s", decision.id, decision.action_type, result)
    except Exception as exc:
        await _mark_failed(decision.id, str(exc))
        logger.warning("soi decision_failed id=%s error=%s", decision.id, exc)


async def _dispatch_action(action_type: str, params: dict[str, Any]) -> str:
    if action_type == "restart_service":
        return await _restart_service(params.get("service_name", ""))
    elif action_type == "alert_telegram":
        return await _alert_telegram(params)
    elif action_type == "create_task":
        return await _create_infra_task(params)
    elif action_type == "reboot_node":
        return await _reboot_node(params.get("node_name", ""))
    else:
        return f"unknown_action:{action_type}"


async def _restart_service(service_name: str) -> str:
    """Call ops-bridge to restart a Docker Compose service."""
    if not service_name:
        return "no service_name provided"
    url = f"{settings.ops_bridge_url}/api/v1/services/{service_name}/restart"
    headers = {}
    if settings.ops_bridge_token:
        headers["Authorization"] = f"Bearer {settings.ops_bridge_token}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            return f"restarted:{service_name}:status={resp.status_code}"
    except Exception as exc:
        return f"restart_failed:{service_name}:{exc}"


async def _alert_telegram(params: dict[str, Any]) -> str:
    """Publish an alert to the orchestrator via NATS for Telegram forwarding.
    Fallback to a simple HTTP call if NATS is not available."""
    template = params.get("message_template", "Infrastructure alert: {target}")
    target = params.get("node_name") or params.get("service_name") or "unknown"
    value = params.get("cpu_percent") or params.get("mem_percent") or 0.0
    try:
        message = template.format(target=target, value=value)
    except Exception:
        message = template

    # Best-effort: try ops-bridge notification endpoint
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{settings.ops_bridge_url}/api/v1/notify",
                json={"message": message, "level": "warning"},
                headers={"Authorization": f"Bearer {settings.ops_bridge_token}"}
                if settings.ops_bridge_token else {},
            )
    except Exception:
        pass

    logger.info("soi alert_sent message=%s", message)
    return f"alert_sent:{message[:80]}"


async def _create_infra_task(params: dict[str, Any]) -> str:
    """POST a remediation task to the Agent Economy service."""
    task_type = params.get("task_type", "infra_remediation")
    priority = params.get("priority", 5)
    target = params.get("node_name") or params.get("service_name") or "unknown"
    body = {
        "title": f"Infra remediation: {target}",
        "description": f"Automated task triggered by decision engine. Target: {target}",
        "task_type": task_type,
        "priority": priority,
    }
    agent_economy_url = "http://agent-economy:8240"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{agent_economy_url}/api/v1/tasks", json=body)
            resp.raise_for_status()
            task_id = resp.json().get("id", "unknown")
            return f"task_created:{task_id}"
    except Exception as exc:
        return f"task_creation_failed:{exc}"


async def _reboot_node(node_name: str) -> str:
    """Request a node reboot via ops-bridge (high-risk — only executed after human approval)."""
    if not node_name:
        return "no node_name provided"
    url = f"{settings.ops_bridge_url}/api/v1/nodes/{node_name}/reboot"
    headers = {}
    if settings.ops_bridge_token:
        headers["Authorization"] = f"Bearer {settings.ops_bridge_token}"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
            return f"reboot_requested:{node_name}"
    except Exception as exc:
        return f"reboot_failed:{node_name}:{exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Execute pending approved decisions on startup recovery
# ─────────────────────────────────────────────────────────────────────────────

async def resume_approved_decisions() -> None:
    """Re-enqueue any 'approved' decisions that weren't executed before restart."""
    rows = await db.fetch(
        "SELECT * FROM soi_decisions WHERE status='approved' AND approved_at < NOW() - INTERVAL '5 minutes'"
    )
    for row in rows:
        decision = _row_to_decision(row)
        logger.info("soi resuming_decision id=%s action=%s", decision.id, decision.action_type)
        asyncio.create_task(_execute_decision(decision))
