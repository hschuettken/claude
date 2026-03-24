"""
Migration script to seed ContentPillar nodes in the KG.

Usage:
    python migrations/seed_content_pillars.py

This script:
1. Initializes Neo4j connection using config
2. Creates ContentPillar nodes for all 6 pillars
3. Logs success/failure for each pillar
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import settings
from app.knowledge_graph import Neo4jSingleton, MarketingKGSchema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Run the migration."""
    logger.info("🚀 Starting ContentPillar seeding...")

    # Initialize Neo4j
    neo4j = await Neo4jSingleton.initialize(
        settings.neo4j_url,
        settings.neo4j_user,
        settings.neo4j_password,
    )

    if not neo4j.connected:
        logger.error("❌ Failed to connect to Neo4j. Aborting.")
        return False

    # Initialize schema
    logger.info("Initializing KG schema...")
    await MarketingKGSchema.initialize(neo4j)

    # Seed pillars
    logger.info("Seeding ContentPillar nodes...")
    success = await MarketingKGSchema.seed_pillars(neo4j)

    # Verify
    if success:
        node_counts = await MarketingKGQuery.get_node_counts()
        pillar_count = node_counts.get("ContentPillar", 0)
        logger.info(f"✅ Successfully seeded {pillar_count} ContentPillar nodes")
        return True
    else:
        logger.error("❌ Failed to seed ContentPillar nodes")
        return False


if __name__ == "__main__":
    from app.knowledge_graph import MarketingKGQuery

    success = asyncio.run(main())
    sys.exit(0 if success else 1)
