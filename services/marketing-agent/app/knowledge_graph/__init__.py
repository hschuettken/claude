"""Knowledge Graph integration for marketing agent."""

from app.knowledge_graph.neo4j_singleton import Neo4jSingleton, get_neo4j
from app.knowledge_graph.schema import MarketingKGSchema
from app.knowledge_graph.ingestion import MarketingKGIngestion
from app.knowledge_graph.query import MarketingKGQuery

__all__ = [
    "Neo4jSingleton",
    "get_neo4j",
    "MarketingKGSchema",
    "MarketingKGIngestion",
    "MarketingKGQuery",
]
