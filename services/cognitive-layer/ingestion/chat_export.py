"""Ingest ChatGPT / Claude export JSON → KG nodes + edges.

ChatGPT export format: list of conversations, each with messages.
Claude export format: list of conversations with uuid + messages[].

Creates:
  - One `chat` node per conversation
  - One `thought` node per user message that contains a question or decision
  - DISCUSSED_IN edges from thought → chat
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .. import knowledge_graph as kg
from ..models import EdgeCreate, IngestResult, NodeCreate

logger = logging.getLogger(__name__)

# Heuristic: user messages longer than this and ending with ? are thoughts
_MIN_LEN = 30


async def ingest_chat_export(export_path: str, source_tag: str = "chat_export") -> IngestResult:
    """Parse a ChatGPT or Claude JSON export and create KG nodes.

    Args:
        export_path: Path to the downloaded export JSON file.
        source_tag:  Source label written to kg_nodes.source.
    """
    result = IngestResult(source=source_tag, nodes_created=0, edges_created=0)
    try:
        data = json.loads(Path(export_path).read_text())
    except Exception as exc:
        result.errors.append(f"Failed to read {export_path}: {exc}")
        return result

    conversations = data if isinstance(data, list) else data.get("conversations", [])
    for conv in conversations:
        conv_id = str(conv.get("id") or conv.get("uuid") or "")
        title = conv.get("title") or conv.get("name") or "Untitled conversation"
        created = conv.get("create_time") or conv.get("created_at") or ""

        chat_node = await kg.create_node(NodeCreate(
            node_type="chat",
            label=title,
            properties={"created": created, "id": conv_id},
            source=source_tag,
            source_id=conv_id,
        ))
        if chat_node:
            result.nodes_created += 1

        # Extract significant user turns
        messages = _extract_messages(conv)
        for msg in messages:
            if msg["role"] != "user":
                continue
            text = msg.get("content", "")
            if len(text) < _MIN_LEN:
                continue
            thought_node = await kg.create_node(NodeCreate(
                node_type="thought",
                label=_truncate(text, 120),
                properties={"full_text": text, "conv_id": conv_id},
                source=source_tag,
                source_id=f"{conv_id}:{msg.get('id', '')}",
            ))
            if thought_node and chat_node:
                result.nodes_created += 1
                edge = await kg.create_edge(EdgeCreate(
                    source_id=thought_node.id,
                    target_id=chat_node.id,
                    relation_type="DISCUSSED_IN",
                ))
                if edge:
                    result.edges_created += 1

    logger.info(
        "chat_export_ingested source=%s nodes=%d edges=%d errors=%d",
        source_tag, result.nodes_created, result.edges_created, len(result.errors),
    )
    return result


def _extract_messages(conv: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise ChatGPT mapping-tree or Claude flat list into [{role, content, id}]."""
    # Claude export: flat messages list
    if "messages" in conv and isinstance(conv["messages"], list):
        return conv["messages"]
    # ChatGPT export: mapping tree
    mapping = conv.get("mapping", {})
    ordered: list[dict[str, Any]] = []
    for node in mapping.values():
        msg = node.get("message")
        if not msg:
            continue
        role = msg.get("author", {}).get("role", "unknown")
        parts = msg.get("content", {}).get("parts", [])
        text = " ".join(str(p) for p in parts if isinstance(p, str))
        ordered.append({"role": role, "content": text, "id": msg.get("id", "")})
    return ordered


def _truncate(s: str, n: int) -> str:
    return s[:n] + "…" if len(s) > n else s
