"""Knowledge Graph CRUD — flat PostgreSQL (no graph DB).

Nodes model concepts/events/tasks; edges represent typed relationships.
All relationships are stored as FK references — no Neo4j, no Cypher.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import db
from .models import Edge, EdgeCreate, GraphNeighbours, Node, NodeCreate, NodeUpdate

# Optional NATS publisher — set by main.py after NATS connects.
# When present, `cognitive.node.created` is published on every new/upserted node.
_nats_publisher: Any = None


def set_nats(publisher: Any) -> None:
    global _nats_publisher
    _nats_publisher = publisher


# ─────────────────────────────────────────────────────────────────────────────
# Node operations
# ─────────────────────────────────────────────────────────────────────────────

async def create_node(data: NodeCreate) -> Optional[Node]:
    row = await db.fetchrow(
        """
        INSERT INTO kg_nodes (node_type, label, properties, source, source_id)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (source, source_id)
            WHERE source IS NOT NULL AND source_id IS NOT NULL
        DO UPDATE SET
            label      = EXCLUDED.label,
            properties = kg_nodes.properties || EXCLUDED.properties,
            updated_at = NOW()
        RETURNING *
        """,
        data.node_type,
        data.label,
        data.properties,
        data.source,
        data.source_id,
    )
    node = _row_to_node(row) if row else None
    if node is not None and _nats_publisher is not None:
        try:
            await _nats_publisher.publish(
                "cognitive.node.created",
                {"id": str(node.id), "type": node.node_type, "label": node.label},
            )
        except Exception:
            pass  # NATS publish failure must never break KG writes
    return node


async def get_node(node_id: uuid.UUID) -> Optional[Node]:
    row = await db.fetchrow("SELECT * FROM kg_nodes WHERE id = $1", node_id)
    return _row_to_node(row) if row else None


async def update_node(node_id: uuid.UUID, data: NodeUpdate) -> Optional[Node]:
    sets = []
    args: list[Any] = []
    idx = 1
    if data.label is not None:
        sets.append(f"label = ${idx}")
        args.append(data.label)
        idx += 1
    if data.properties is not None:
        sets.append(f"properties = properties || ${idx}")
        args.append(data.properties)
        idx += 1
    if not sets:
        return await get_node(node_id)
    sets.append("updated_at = NOW()")
    args.append(node_id)
    row = await db.fetchrow(
        f"UPDATE kg_nodes SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
        *args,
    )
    return _row_to_node(row) if row else None


async def delete_node(node_id: uuid.UUID) -> bool:
    result = await db.fetchval("DELETE FROM kg_nodes WHERE id = $1 RETURNING id", node_id)
    return result is not None


async def list_nodes(
    node_type: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Node]:
    conditions = []
    args: list[Any] = []
    idx = 1
    if node_type:
        conditions.append(f"node_type = ${idx}")
        args.append(node_type)
        idx += 1
    if source:
        conditions.append(f"source = ${idx}")
        args.append(source)
        idx += 1
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    args += [limit, offset]
    rows = await db.fetch(
        f"SELECT * FROM kg_nodes {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
        *args,
    )
    return [_row_to_node(r) for r in rows]


async def search_nodes(query: str, limit: int = 20) -> list[Node]:
    """Full-text label search (ILIKE fallback — no vector required)."""
    rows = await db.fetch(
        "SELECT * FROM kg_nodes WHERE label ILIKE $1 OR properties::text ILIKE $1 "
        "ORDER BY created_at DESC LIMIT $2",
        f"%{query}%",
        limit,
    )
    return [_row_to_node(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# Edge operations
# ─────────────────────────────────────────────────────────────────────────────

async def create_edge(data: EdgeCreate) -> Optional[Edge]:
    row = await db.fetchrow(
        """
        INSERT INTO kg_edges (source_id, target_id, relation_type, weight, properties)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT DO NOTHING
        RETURNING *
        """,
        data.source_id,
        data.target_id,
        data.relation_type,
        data.weight,
        data.properties,
    )
    # If ON CONFLICT hit, fetch the existing edge
    if row is None:
        row = await db.fetchrow(
            "SELECT * FROM kg_edges WHERE source_id=$1 AND target_id=$2 AND relation_type=$3",
            data.source_id,
            data.target_id,
            data.relation_type,
        )
    return _row_to_edge(row) if row else None


async def get_edge(edge_id: uuid.UUID) -> Optional[Edge]:
    row = await db.fetchrow("SELECT * FROM kg_edges WHERE id = $1", edge_id)
    return _row_to_edge(row) if row else None


async def delete_edge(edge_id: uuid.UUID) -> bool:
    result = await db.fetchval("DELETE FROM kg_edges WHERE id = $1 RETURNING id", edge_id)
    return result is not None


async def get_neighbours(node_id: uuid.UUID, max_depth: int = 1) -> GraphNeighbours:
    """Return the node + all directly adjacent edges and neighbour nodes (depth=1)."""
    node = await get_node(node_id)
    if node is None:
        return GraphNeighbours(node=None, edges=[], neighbours=[])  # type: ignore[arg-type]

    edge_rows = await db.fetch(
        "SELECT * FROM kg_edges WHERE source_id = $1 OR target_id = $1",
        node_id,
    )
    edges = [_row_to_edge(r) for r in edge_rows]

    neighbour_ids = set()
    for e in edges:
        if e.source_id != node_id:
            neighbour_ids.add(e.source_id)
        if e.target_id != node_id:
            neighbour_ids.add(e.target_id)

    neighbours: list[Node] = []
    for nid in neighbour_ids:
        n = await get_node(nid)
        if n:
            neighbours.append(n)

    return GraphNeighbours(node=node, edges=edges, neighbours=neighbours)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _row_to_node(row: Any) -> Node:
    return Node(
        id=row["id"],
        node_type=row["node_type"],
        label=row["label"],
        properties=dict(row["properties"]) if row["properties"] else {},
        source=row["source"],
        source_id=row["source_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_edge(row: Any) -> Edge:
    return Edge(
        id=row["id"],
        source_id=row["source_id"],
        target_id=row["target_id"],
        relation_type=row["relation_type"],
        weight=float(row["weight"]),
        properties=dict(row["properties"]) if row["properties"] else {},
        created_at=row["created_at"],
    )
