"""
Knowledge Graph initialization module.

Called at marketing-agent startup to:
1. Initialize Neo4j connection
2. Create schema constraints if not exist
3. Seed ContentPillar nodes
4. Verify connectivity and report status

This is idempotent—safe to call multiple times.
"""

import asyncio
import logging
import os
from typing import Optional

from app.knowledge_graph.neo4j_singleton import Neo4jSingleton
from app.knowledge_graph.schema import MarketingKGSchema
from app.knowledge_graph.query import MarketingKGQuery

logger = logging.getLogger(__name__)


async def initialize_kg() -> dict:
    """
    Initialize the Knowledge Graph subsystem.

    Returns:
        Dictionary with initialization status:
        {
            "success": bool,
            "connected": bool,
            "constraints_created": int,
            "pillars_seeded": int,
            "error": str (if any)
        }
    """
    status = {
        "success": False,
        "connected": False,
        "constraints_created": 0,
        "pillars_seeded": 0,
        "error": None,
    }

    try:
        # Step 1: Get Neo4j connection config from environment
        neo4j_url = os.environ.get("NEO4J_URL", "bolt://192.168.0.84:7687")
        neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
        neo4j_password = os.environ.get("NEO4J_PASSWORD", "neo4j")

        logger.info(f"Initializing KG: connecting to {neo4j_url}")

        # Step 2: Initialize Neo4j singleton
        neo4j = await Neo4jSingleton.initialize(neo4j_url, neo4j_user, neo4j_password)

        if not neo4j.connected:
            status["error"] = neo4j.connection_error or "Unknown connection error"
            logger.warning(f"KG initialization: Neo4j connection failed — {status['error']}")
            logger.warning(
                "Graceful degradation enabled: marketing-agent will continue without KG features"
            )
            return status

        status["connected"] = True
        logger.info("✓ Neo4j connection established")

        # Step 3: Initialize schema (create constraints and indexes)
        logger.info("Creating schema constraints...")
        schema_success = await MarketingKGSchema.initialize(neo4j)
        if schema_success:
            status["constraints_created"] = len(MarketingKGSchema.ALL_CONSTRAINTS)
            logger.info(f"✓ Created {status['constraints_created']} schema constraints")
        else:
            logger.warning("Failed to create all schema constraints")

        # Step 4: Seed ContentPillar nodes
        logger.info("Seeding ContentPillar nodes...")
        pillars_success = await MarketingKGSchema.seed_pillars(neo4j)
        if pillars_success:
            status["pillars_seeded"] = 6
            logger.info("✓ Seeded 6 ContentPillar nodes")
        else:
            logger.warning("Failed to seed all ContentPillar nodes")

        # Step 5: Verify with a simple query
        logger.info("Verifying KG connectivity with test query...")
        counts = await MarketingKGQuery(neo4j).get_node_counts()
        if counts:
            logger.info(f"✓ Node counts: {counts}")
        else:
            logger.warning("Could not retrieve node counts (query returned empty)")

        status["success"] = schema_success and pillars_success
        if status["success"]:
            logger.info("✓ KG initialization complete — ready for ingestion")
        else:
            logger.warning(
                "KG initialization partially succeeded — some operations failed. "
                "Check logs for details."
            )

    except Exception as e:
        status["error"] = str(e)
        logger.error(f"KG initialization failed with exception: {e}", exc_info=True)

    return status


async def get_kg_status() -> dict:
    """
    Get the current KG status (connected, node counts, etc.).

    Returns:
        Dictionary with KG status information.
    """
    try:
        neo4j = Neo4jSingleton()
        if not neo4j.connected:
            return {
                "connected": False,
                "error": neo4j.connection_error,
            }

        query = MarketingKGQuery(neo4j)
        counts = await query.get_node_counts()
        pillars = await query.get_all_pillars_stats()

        return {
            "connected": True,
            "node_counts": counts,
            "pillars": pillars,
        }

    except Exception as e:
        logger.error(f"Error getting KG status: {e}")
        return {
            "connected": False,
            "error": str(e),
        }


# =============================================================================
# Synchronous wrappers (for use in sync contexts, e.g., startup hooks)
# =============================================================================

_kg_status = None


def sync_initialize_kg() -> dict:
    """Synchronous wrapper for initialize_kg()."""
    global _kg_status
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already in an async context (FastAPI startup)
            # Return placeholder; caller should use async version
            logger.warning("sync_initialize_kg() called from async context; use async version instead")
            return {"success": False, "error": "Called from async context"}
        else:
            # Run in existing loop
            _kg_status = loop.run_until_complete(initialize_kg())
            return _kg_status
    except RuntimeError:
        # No running loop, create temporary one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            _kg_status = loop.run_until_complete(initialize_kg())
            return _kg_status
        finally:
            loop.close()


def get_cached_kg_status() -> Optional[dict]:
    """Get the cached KG status from the last initialization."""
    return _kg_status
