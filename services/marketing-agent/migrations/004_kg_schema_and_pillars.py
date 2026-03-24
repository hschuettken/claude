#!/usr/bin/env python3
"""
Neo4j Knowledge Graph Schema Initialization & ContentPillar Seed Data.

Runs after main service starts. Creates node labels, constraints, and seeds
the 6 ContentPillar nodes that organize marketing content.

Usage:
    python migrations/004_kg_schema_and_pillars.py
    
Environment:
    NEO4J_URL — bolt connection (default: bolt://192.168.0.340:7687)
    NEO4J_USER — username (default: neo4j)
    NEO4J_PASSWORD — password (required)
"""
import os
import sys
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def initialize_kg_schema():
    """Create KG schema, constraints, and seed ContentPillar nodes."""
    neo4j_url = os.getenv("NEO4J_URL", "bolt://192.168.0.340:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "")
    
    if not neo4j_password:
        logger.error("NEO4J_PASSWORD not set, cannot initialize KG schema")
        return False
    
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.error("neo4j driver not installed. Install: pip install neo4j")
        return False
    
    try:
        driver = GraphDatabase.driver(
            neo4j_url,
            auth=(neo4j_user, neo4j_password),
            connection_timeout=10,
        )
        
        with driver.session() as session:
            # Create constraints for Signal node label
            logger.info("Creating Signal node constraint...")
            try:
                session.run("""
                    CREATE CONSTRAINT signal_id_unique IF NOT EXISTS
                    FOR (s:Signal) REQUIRE s.id IS UNIQUE
                """)
                logger.info("✓ Signal constraint created")
            except Exception as e:
                logger.warning(f"Signal constraint already exists or error: {e}")
            
            # Create constraints for Topic node label
            logger.info("Creating Topic node constraint...")
            try:
                session.run("""
                    CREATE CONSTRAINT topic_id_unique IF NOT EXISTS
                    FOR (t:Topic) REQUIRE t.id IS UNIQUE
                """)
                logger.info("✓ Topic constraint created")
            except Exception as e:
                logger.warning(f"Topic constraint already exists or error: {e}")
            
            # Create constraints for Post node label
            logger.info("Creating Post node constraint...")
            try:
                session.run("""
                    CREATE CONSTRAINT post_id_unique IF NOT EXISTS
                    FOR (p:Post) REQUIRE p.id IS UNIQUE
                """)
                logger.info("✓ Post constraint created")
            except Exception as e:
                logger.warning(f"Post constraint already exists or error: {e}")
            
            # Create constraints for ContentPillar node label
            logger.info("Creating ContentPillar node constraint...")
            try:
                session.run("""
                    CREATE CONSTRAINT pillar_id_unique IF NOT EXISTS
                    FOR (cp:ContentPillar) REQUIRE cp.id IS UNIQUE
                """)
                logger.info("✓ ContentPillar constraint created")
            except Exception as e:
                logger.warning(f"ContentPillar constraint already exists or error: {e}")
            
            # Seed ContentPillar nodes (6 pillars)
            pillars = [
                {
                    "id": 1,
                    "name": "SAP deep technical",
                    "weight": 0.45,
                    "description": "Deep technical content on SAP products, data models, APIs"
                },
                {
                    "id": 2,
                    "name": "SAP roadmap & features",
                    "weight": 0.20,
                    "description": "SAP product roadmap, new features, releases"
                },
                {
                    "id": 3,
                    "name": "Architecture & decisions",
                    "weight": 0.15,
                    "description": "System architecture, design decisions, technical choices"
                },
                {
                    "id": 4,
                    "name": "AI in the enterprise",
                    "weight": 0.10,
                    "description": "AI applications, LLMs, enterprise automation"
                },
                {
                    "id": 5,
                    "name": "Builder / lab / infrastructure",
                    "weight": 0.07,
                    "description": "Homelab, infrastructure, builder tools, automation"
                },
                {
                    "id": 6,
                    "name": "Personal builder lifestyle",
                    "weight": 0.03,
                    "description": "Personal journey, learning, lifestyle, philosophy"
                },
            ]
            
            for pillar in pillars:
                logger.info(f"Seeding ContentPillar {pillar['id']}: {pillar['name']}...")
                session.run("""
                    MERGE (cp:ContentPillar {id: $id})
                    SET cp.name = $name,
                        cp.weight = $weight,
                        cp.description = $description,
                        cp.created_at = datetime(),
                        cp.updated_at = datetime()
                    RETURN cp.id
                """, **pillar)
                logger.info(f"✓ ContentPillar {pillar['id']} seeded")
            
            # Verify
            result = session.run("MATCH (cp:ContentPillar) RETURN count(cp) as count")
            record = result.single()
            count = record["count"] if record else 0
            logger.info(f"✓ Total ContentPillar nodes in KG: {count}")
            
            return count == 6
    
    except Exception as e:
        logger.error(f"Failed to initialize KG schema: {e}", exc_info=True)
        return False
    
    finally:
        driver.close()


if __name__ == "__main__":
    success = initialize_kg_schema()
    sys.exit(0 if success else 1)
