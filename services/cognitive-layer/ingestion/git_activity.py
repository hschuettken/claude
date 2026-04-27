"""Ingest GitHub activity → KG nodes.

Polls the GitHub REST API for commits across all repos owned by GITHUB_OWNER,
maps each commit to a `git_commit` node, and links it to a `concept` node
representing the repository.

Creates:
  - `concept` node per repository (label = repo name)
  - `git_commit` node per commit
  - PART_OF edge: commit → repo
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from ..config import settings
from .. import knowledge_graph as kg
from ..models import EdgeCreate, IngestResult, NodeCreate

logger = logging.getLogger(__name__)

_GH_API = "https://api.github.com"
_DEFAULT_REPOS = ["claude", "nb9os", "memora"]


async def ingest_git_activity(
    repos: Optional[list[str]] = None,
    since_days: int = 7,
) -> IngestResult:
    """Poll GitHub commits for the last `since_days` days and create KG nodes."""
    result = IngestResult(source="git", nodes_created=0, edges_created=0)
    if not settings.github_token:
        result.errors.append("GITHUB_TOKEN not configured — skipping git ingestion")
        return result

    repos = repos or _DEFAULT_REPOS
    since = _iso_ago(since_days)
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        for repo in repos:
            repo_node = await _ensure_repo_node(repo, result)
            if repo_node is None:
                continue
            try:
                resp = await client.get(
                    f"{_GH_API}/repos/{settings.github_owner}/{repo}/commits",
                    params={"since": since, "per_page": 100},
                )
                if resp.status_code == 404:
                    logger.debug("git_repo_not_found repo=%s", repo)
                    continue
                resp.raise_for_status()
                commits = resp.json()
            except Exception as exc:
                result.errors.append(f"GitHub API error for {repo}: {exc}")
                continue

            for commit_data in commits:
                sha = commit_data.get("sha", "")[:12]
                info = commit_data.get("commit", {})
                message = info.get("message", "").split("\n")[0][:200]
                author = info.get("author", {}).get("name", "unknown")
                date_str = info.get("author", {}).get("date", "")

                node = await kg.create_node(NodeCreate(
                    node_type="git_commit",
                    label=f"{sha}: {message}",
                    properties={
                        "sha": sha,
                        "author": author,
                        "date": date_str,
                        "repo": repo,
                        "full_message": info.get("message", ""),
                    },
                    source="git",
                    source_id=sha,
                ))
                if node:
                    result.nodes_created += 1
                    edge = await kg.create_edge(EdgeCreate(
                        source_id=node.id,
                        target_id=repo_node.id,
                        relation_type="PART_OF",
                    ))
                    if edge:
                        result.edges_created += 1

    logger.info(
        "git_activity_ingested repos=%d nodes=%d edges=%d errors=%d",
        len(repos), result.nodes_created, result.edges_created, len(result.errors),
    )
    return result


async def _ensure_repo_node(repo: str, result: IngestResult):
    node = await kg.create_node(NodeCreate(
        node_type="concept",
        label=f"repo:{repo}",
        properties={"repo": repo, "owner": settings.github_owner},
        source="git",
        source_id=f"repo:{repo}",
    ))
    if node:
        result.nodes_created += 1
    return node


def _iso_ago(days: int) -> str:
    from datetime import timedelta
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
