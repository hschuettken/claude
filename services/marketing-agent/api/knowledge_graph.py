"""Knowledge Graph REST API endpoints for marketing agent."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from app.knowledge_graph import Neo4jSingleton, MarketingKGQuery

logger = logging.getLogger(__name__)

router = APIRouter(tags=["knowledge_graph"])


@router.get("/marketing/kg/status")
async def kg_status():
    """Get Knowledge Graph connection status and node counts."""
    neo4j = Neo4jSingleton()
    query = MarketingKGQuery(neo4j)

    return {
        "neo4j_connected": neo4j.connected,
        "connection_error": neo4j.connection_error,
        "node_counts": await query.get_node_counts() if neo4j.connected else {},
    }


@router.get("/marketing/kg/pillars")
async def kg_pillars():
    """Get statistics for all 6 content pillars."""
    neo4j = Neo4jSingleton()
    if not neo4j.connected:
        return {
            "status": "unavailable",
            "message": "Knowledge Graph not connected",
            "pillars": {},
        }

    query = MarketingKGQuery(neo4j)
    stats = await query.get_all_pillars_stats()

    return {
        "status": "ok",
        "pillars": stats,
    }


@router.get("/marketing/kg/posts")
async def kg_posts(topic_keywords: Optional[str] = None):
    """
    Get published posts matching topic keywords.

    Query params:
    - topic_keywords: Comma-separated keywords to search for
    """
    neo4j = Neo4jSingleton()
    if not neo4j.connected:
        return {
            "status": "unavailable",
            "message": "Knowledge Graph not connected",
            "posts": [],
        }

    if not topic_keywords:
        return {
            "status": "error",
            "message": "topic_keywords parameter required",
            "posts": [],
        }

    keywords = [kw.strip() for kw in topic_keywords.split(",")]
    query = MarketingKGQuery(neo4j)
    posts = await query.get_published_posts_on_topic(keywords)

    return {
        "status": "ok",
        "keywords": keywords,
        "posts": posts,
    }


@router.get("/marketing/kg/cluster/{topic_id}")
async def kg_cluster(topic_id: str):
    """
    Get the full KG cluster for a topic.

    Returns:
    - Topic node
    - Connected signals (CONTRIBUTES_TO)
    - Generated posts (GENERATED)
    """
    neo4j = Neo4jSingleton()
    if not neo4j.connected:
        return {
            "status": "unavailable",
            "message": "Knowledge Graph not connected",
            "cluster": None,
        }

    query = MarketingKGQuery(neo4j)
    cluster = await query.get_topic_cluster(topic_id)

    if not cluster:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Topic {topic_id} not found in Knowledge Graph",
        )

    return {
        "status": "ok",
        "topic_id": topic_id,
        "cluster": cluster,
    }


@router.get("/marketing/kg/related-posts/{topic_title}")
async def kg_related_posts(topic_title: str):
    """
    Get published posts similar to a topic by keyword matching.

    This is a simplified query endpoint that uses the topic title as keyword.
    """
    neo4j = Neo4jSingleton()
    if not neo4j.connected:
        return {
            "status": "unavailable",
            "message": "Knowledge Graph not connected",
            "posts": [],
        }

    query = MarketingKGQuery(neo4j)
    # Split topic title into keywords
    keywords = [word for word in topic_title.split() if len(word) > 3]
    posts = await query.get_published_posts_on_topic(keywords)

    return {
        "status": "ok",
        "topic_title": topic_title,
        "keywords": keywords,
        "posts": posts,
    }
