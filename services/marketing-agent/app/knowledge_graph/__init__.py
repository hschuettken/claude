"""Knowledge Graph integration for marketing agent."""

from app.knowledge_graph.neo4j_singleton import Neo4jSingleton, get_neo4j
from app.knowledge_graph.schema import MarketingKGSchema
from app.knowledge_graph.ingestion import MarketingKGIngestion
from app.knowledge_graph.query import MarketingKGQuery
from app.knowledge_graph.init import initialize_kg, get_kg_status, sync_initialize_kg, get_cached_kg_status

__all__ = [
    "Neo4jSingleton",
    "get_neo4j",
    "MarketingKGSchema",
    "MarketingKGIngestion",
    "MarketingKGQuery",
    "initialize_kg",
    "get_kg_status",
    "sync_initialize_kg",
    "get_cached_kg_status",
]
