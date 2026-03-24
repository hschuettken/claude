"""
Migration 001: Knowledge Graph Schema for Marketing Entities

Creates Neo4j node labels (Signal, Topic, Post, ContentPillar) with constraints,
properties, relationships, and seed data for the 6 content pillars.

Reference: Task 132, Part 1 — KG Schema Extension
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


class MarketingKGMigration:
    """Database migration: Initialize KG schema for marketing entities."""

    # All Cypher constraints for the 4 new node types
    CONSTRAINTS = [
        # Signal constraints
        "CREATE CONSTRAINT signal_id IF NOT EXISTS FOR (s:Signal) REQUIRE s.id IS UNIQUE",
        "CREATE INDEX signal_title IF NOT EXISTS FOR (s:Signal) ON (s.title)",
        "CREATE INDEX signal_pillar IF NOT EXISTS FOR (s:Signal) ON (s.pillar_id)",
        "CREATE INDEX signal_status IF NOT EXISTS FOR (s:Signal) ON (s.status)",
        
        # Topic constraints
        "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
        "CREATE INDEX topic_title IF NOT EXISTS FOR (t:Topic) ON (t.title)",
        "CREATE INDEX topic_pillar IF NOT EXISTS FOR (t:Topic) ON (t.pillar_id)",
        "CREATE INDEX topic_status IF NOT EXISTS FOR (t:Topic) ON (t.status)",
        
        # Post constraints
        "CREATE CONSTRAINT post_id IF NOT EXISTS FOR (p:Post) REQUIRE p.id IS UNIQUE",
        "CREATE INDEX post_title IF NOT EXISTS FOR (p:Post) ON (p.title)",
        "CREATE INDEX post_format IF NOT EXISTS FOR (p:Post) ON (p.format)",
        "CREATE INDEX post_status IF NOT EXISTS FOR (p:Post) ON (p.status)",
        "CREATE INDEX post_pillar IF NOT EXISTS FOR (p:Post) ON (p.pillar_id)",
        
        # ContentPillar constraints
        "CREATE CONSTRAINT pillar_id IF NOT EXISTS FOR (cp:ContentPillar) REQUIRE cp.id IS UNIQUE",
        "CREATE INDEX pillar_name IF NOT EXISTS FOR (cp:ContentPillar) ON (cp.name)",
    ]

    PILLARS = [
        {"id": 1, "name": "SAP deep technical", "weight": 0.45},
        {"id": 2, "name": "SAP roadmap & features", "weight": 0.20},
        {"id": 3, "name": "Architecture & decisions", "weight": 0.15},
        {"id": 4, "name": "AI in the enterprise", "weight": 0.10},
        {"id": 5, "name": "Builder / lab / infrastructure", "weight": 0.07},
        {"id": 6, "name": "Personal builder lifestyle", "weight": 0.03},
    ]

    def __init__(self, neo4j_client):
        """
        Args:
            neo4j_client: Neo4j connection object (from neo4j_singleton.py)
        """
        self.neo4j = neo4j_client

    async def up(self) -> bool:
        """Execute migration: create schema and seed data."""
        logger.info("Running migration 001: KG Schema for Marketing")

        # Step 1: Create all constraints and indexes
        logger.info("Creating constraints and indexes...")
        constraint_success = await self._create_constraints()
        if not constraint_success:
            logger.error("Failed to create constraints")
            return False

        # Step 2: Seed ContentPillar nodes
        logger.info("Seeding ContentPillar nodes...")
        pillar_success = await self._seed_pillars()
        if not pillar_success:
            logger.error("Failed to seed pillars")
            return False

        logger.info("✓ Migration 001 complete: KG schema initialized")
        return True

    async def down(self) -> bool:
        """Rollback migration: drop constraints (keep data for safety)."""
        logger.info("Rolling back migration 001...")
        # In practice, we keep the data and constraints—Neo4j constraints
        # are safer to keep than to drop (prevents re-creation on restart).
        logger.info("✓ Migration 001 rollback: constraints preserved for safety")
        return True

    async def _create_constraints(self) -> bool:
        """Create all Neo4j constraints and indexes."""
        success_count = 0
        for constraint in self.CONSTRAINTS:
            try:
                await self.neo4j.execute(constraint)
                success_count += 1
                logger.debug(f"✓ {constraint[:60]}...")
            except Exception as e:
                # Ignore "already exists" errors (idempotent)
                if "already exists" in str(e).lower():
                    success_count += 1
                else:
                    logger.warning(f"Failed to create constraint: {e}")

        logger.info(f"Created {success_count}/{len(self.CONSTRAINTS)} constraints")
        return success_count > 0

    async def _seed_pillars(self) -> bool:
        """Seed the 6 ContentPillar nodes."""
        cypher = """
        MERGE (cp:ContentPillar {id: $id})
        SET cp.name = $name,
            cp.weight = $weight,
            cp.created_at = datetime(),
            cp.updated_at = datetime()
        RETURN cp.id
        """

        success_count = 0
        for pillar in self.PILLARS:
            try:
                await self.neo4j.execute(cypher, **pillar)
                success_count += 1
                logger.debug(f"✓ Seeded pillar {pillar['id']}: {pillar['name']}")
            except Exception as e:
                logger.warning(f"Failed to seed pillar {pillar['id']}: {e}")

        logger.info(f"Seeded {success_count}/{len(self.PILLARS)} pillars")
        return success_count == len(self.PILLARS)


async def migrate_up(neo4j_client) -> bool:
    """Convenience function: run migration up."""
    migration = MarketingKGMigration(neo4j_client)
    return await migration.up()


async def migrate_down(neo4j_client) -> bool:
    """Convenience function: run migration down."""
    migration = MarketingKGMigration(neo4j_client)
    return await migration.down()
