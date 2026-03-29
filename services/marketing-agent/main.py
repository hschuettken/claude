"""
Marketing Agent Service — FastAPI backend for content drafting and Ghost CMS integration.

Provides:
- Marketing signals/opportunities API
- Content draft management
- Ghost CMS publishing pipeline
- Content pillar and voice rule management
- Knowledge Graph enrichment (Neo4j)
- Analytics integration (future)
- NATS JetStream event publishing
- Scout Engine (SearXNG-based signal detection)

Environment variables:
  - MARKETING_DB_URL: PostgreSQL connection string
  - GHOST_ADMIN_API_KEY: Ghost API key (format: id:secret_hex)
  - GHOST_URL: Ghost base URL (default: https://layer8.schuettken.net)
  - NEO4J_URL: Neo4j connection URL (default: bolt://192.168.0.84:7687)
  - NEO4J_USER: Neo4j username (default: neo4j)
  - NEO4J_PASSWORD: Neo4j password (default: neo4j)
  - MARKETING_PORT: API port (default: 8210)
  - NATS_URL: NATS JetStream URL (optional, e.g. nats://localhost:4222)
  - NATS_USER: NATS username (optional)
  - NATS_PASSWORD: NATS password (optional)
  - SEARXNG_URL: SearXNG base URL (default: http://192.168.0.84:8080)
  - SCOUT_ENABLED: Enable Scout scheduler (default: true)
"""
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, status
from fastapi.responses import JSONResponse

from models import Base
from database import get_db, _get_engine
from api import signals_router, topics_router, drafts_router, approval_router, kg_router, kg_status_router, publish_router, scout_router, storylines_router, draft_studio_router, performance_pulse_router
from kg_query import get_kg_query
from kg_ingest import get_kg_ingest
from events import MarketingNATSClient
from scout import ScoutScheduler, set_scheduler, get_scheduler
from nats_consumer import MarketingNATSConsumer

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _initialize_kg_schema():
    """Initialize Knowledge Graph schema and seed ContentPillar nodes (one-time)."""
    neo4j_password = os.getenv("NEO4J_PASSWORD", "")
    if not neo4j_password:
        logger.debug("NEO4J_PASSWORD not set, skipping KG schema initialization")
        return
    
    try:
        from neo4j import GraphDatabase
    except ImportError:
        logger.warning("neo4j driver not installed, skipping KG schema init")
        return
    
    neo4j_url = os.getenv("NEO4J_URL", "bolt://192.168.0.340:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    
    try:
        driver = GraphDatabase.driver(
            neo4j_url,
            auth=(neo4j_user, neo4j_password),
            connection_timeout=5,
        )
        
        with driver.session() as session:
            # Create constraints for node labels
            constraints = [
                ("Signal", "signal_id_unique", "s:Signal", "s.id"),
                ("Topic", "topic_id_unique", "t:Topic", "t.id"),
                ("Post", "post_id_unique", "p:Post", "p.id"),
                ("ContentPillar", "pillar_id_unique", "cp:ContentPillar", "cp.id"),
            ]
            
            for label, name, var, prop in constraints:
                try:
                    session.run(f"CREATE CONSTRAINT {name} IF NOT EXISTS FOR ({var}) REQUIRE {prop} IS UNIQUE")
                    logger.debug(f"✓ {label} constraint ready")
                except Exception as e:
                    logger.debug(f"{label} constraint: {e}")
            
            # Seed ContentPillar nodes (6 pillars)
            pillars = [
                (1, "SAP deep technical", 0.45),
                (2, "SAP roadmap & features", 0.20),
                (3, "Architecture & decisions", 0.15),
                (4, "AI in the enterprise", 0.10),
                (5, "Builder / lab / infrastructure", 0.07),
                (6, "Personal builder lifestyle", 0.03),
            ]
            
            for pillar_id, name, weight in pillars:
                session.run("""
                    MERGE (cp:ContentPillar {id: $id})
                    SET cp.name = $name,
                        cp.weight = $weight,
                        cp.created_at = datetime(),
                        cp.updated_at = datetime()
                """, id=pillar_id, name=name, weight=weight)
            
            result = session.run("MATCH (cp:ContentPillar) RETURN count(cp) as count")
            record = result.single()
            count = record["count"] if record else 0
            logger.info(f"✓ Knowledge Graph schema initialized ({count} pillars)")
    
    except Exception as e:
        logger.warning(f"Failed to initialize KG schema: {e}")
    
    finally:
        driver.close()


# Scout configuration
SEARXNG_URL = os.getenv("SEARXNG_URL", "http://192.168.0.84:8080")
SCOUT_ENABLED = os.getenv("SCOUT_ENABLED", "true").lower() == "true"

# Database engine is created lazily in database.py via _get_engine()
# to avoid psycopg2 import errors when MARKETING_DB_URL uses postgresql:// scheme


# Global service instances
scout_scheduler: ScoutScheduler = None
nats_consumer: MarketingNATSConsumer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    global scout_scheduler, nats_consumer
    
    logger.info("Starting Marketing Agent service...")
    
    # Startup: Create tables
    _engine, _ = _get_engine()
    async with _engine.begin() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS marketing")
        await conn.commit()
    
    # Create all tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    logger.info("Database tables created/verified")
    
    # Initialize Knowledge Graph connections
    logger.info("Initializing Knowledge Graph...")
    
    # Initialize KG schema and seed ContentPillar data (one-time setup)
    _initialize_kg_schema()
    
    kg_query = get_kg_query()
    kg_ingest = get_kg_ingest()
    
    if kg_query.is_available():
        logger.info("Knowledge Graph query layer ready")
    else:
        logger.warning("Knowledge Graph query layer unavailable (optional)")
    
    if kg_ingest.is_available():
        logger.info("Knowledge Graph ingestion layer ready")
    else:
        logger.warning("Knowledge Graph ingestion layer unavailable (optional)")
    
    # Initialize NATS JetStream connection for publishing
    nats_url = os.getenv("NATS_URL")
    if nats_url:
        connected = await MarketingNATSClient.connect(nats_url)
        if connected:
            logger.info("NATS JetStream initialized — event publishing enabled")
        else:
            logger.warning("NATS JetStream unavailable — event publishing disabled (optional)")
    else:
        logger.info("NATS_URL not configured — event publishing disabled (optional)")
    
    # Initialize NATS JetStream consumer for signal auto-drafting
    if nats_url:
        try:
            nats_user = os.getenv("NATS_USER")
            nats_password = os.getenv("NATS_PASSWORD")
            relevance_threshold = float(os.getenv("SIGNAL_RELEVANCE_THRESHOLD", "0.7"))
            
            _db_url = os.getenv("MARKETING_DB_URL", "postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab")
            if _db_url.startswith("postgresql://") or _db_url.startswith("postgres://"):
                _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)
            nats_consumer = MarketingNATSConsumer(
                db_url=_db_url,
                nats_url=nats_url,
                nats_user=nats_user,
                nats_password=nats_password,
                relevance_threshold=relevance_threshold,
            )
            
            if await nats_consumer.connect():
                await nats_consumer.start()
                logger.info(
                    f"✅ NATS consumer started (relevance threshold: {relevance_threshold})"
                )
            else:
                logger.warning("⚠️  NATS consumer failed to start (optional)")
                nats_consumer = None
        except Exception as e:
            logger.error(f"⚠️  NATS consumer initialization failed: {e}")
            nats_consumer = None
    else:
        logger.info("NATS_URL not configured — consumer disabled (optional)")
    
    # Initialize Scout Engine scheduler
    if SCOUT_ENABLED:
        try:
            _scout_db_url = os.getenv("MARKETING_DB_URL", "postgresql+asyncpg://homelab:homelab@192.168.0.80:5432/homelab")
            if _scout_db_url.startswith("postgresql://") or _scout_db_url.startswith("postgres://"):
                _scout_db_url = _scout_db_url.replace("postgresql://", "postgresql+asyncpg://", 1).replace("postgres://", "postgresql+asyncpg://", 1)
            scout_scheduler = ScoutScheduler(
                db_url=_scout_db_url,
                searxng_url=SEARXNG_URL,
            )
            await scout_scheduler.start()
            set_scheduler(scout_scheduler)  # Register in global instance
            logger.info("✅ Scout Engine scheduler initialized and started")
        except Exception as e:
            logger.error(f"⚠️  Scout Engine initialization failed: {e}")
            scout_scheduler = None
    else:
        logger.info("Scout Engine disabled (SCOUT_ENABLED=false)")
    
    yield
    
    # Shutdown: Stop NATS consumer
    if nats_consumer:
        await nats_consumer.stop()
        logger.info("NATS consumer stopped")
    
    # Shutdown: Stop Scout scheduler
    if scout_scheduler:
        await scout_scheduler.stop()
    
    # Shutdown: Close NATS publisher connection
    await MarketingNATSClient.close()
    
    # Shutdown: Close KG connections
    kg_query.close()
    kg_ingest.close()
    
    # Shutdown: Close database engine
    _engine, _ = _get_engine()
    await _engine.dispose()
    logger.info("Marketing Agent service stopped")


# Create FastAPI app
app = FastAPI(
    title="Marketing Agent",
    description="Content drafting, Ghost CMS publishing, and Scout Engine signal detection",
    version="0.1.0",
    lifespan=lifespan,
)

# Store scout scheduler in app state for endpoint access
app.scout_scheduler = None


# Health check
@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    consumer_status = "running" if nats_consumer and nats_consumer.is_running() else "stopped"
    
    return {
        "status": "ok",
        "service": "marketing-agent",
        "version": "0.1.0",
        "nats_consumer": consumer_status,
    }


# Include routers with API prefix
app.include_router(signals_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(topics_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(drafts_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(draft_studio_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(approval_router, prefix="/api/v1/marketing", dependencies=[Depends(get_db)])
app.include_router(publish_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(scout_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(storylines_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(performance_pulse_router, prefix="/api/v1", dependencies=[Depends(get_db)])
app.include_router(kg_router, prefix="/api/v1")
app.include_router(kg_status_router, prefix="/api/v1/knowledge-graph")


@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    """Handle validation errors."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc)},
    )


if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("MARKETING_PORT", 8210))
    
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
