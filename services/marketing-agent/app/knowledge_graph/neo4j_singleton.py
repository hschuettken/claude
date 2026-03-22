"""Neo4j singleton connection with graceful degradation."""

import asyncio
import logging
from typing import Optional

from neo4j import AsyncDriver, AsyncSession, basic_auth
from typing import Union
ManagedAsyncSession = AsyncSession  # alias for compatibility

logger = logging.getLogger(__name__)


class Neo4jSingleton:
    """Thread-safe Neo4j connection singleton with health checks."""

    _instance: Optional["Neo4jSingleton"] = None
    _lock = asyncio.Lock()
    _driver: Optional[AsyncDriver] = None
    _connected: bool = False
    _connection_error: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def initialize(cls, neo4j_url: str, neo4j_user: str, neo4j_password: str) -> "Neo4jSingleton":
        """Initialize the singleton instance with Neo4j connection."""
        async with cls._lock:
            instance = cls()
            if instance._driver is None:
                try:
                    logger.info(f"Initializing Neo4j connection to {neo4j_url}...")
                    instance._driver = AsyncDriver(
                        neo4j_url,
                        auth=basic_auth(neo4j_user, neo4j_password),
                        encrypted=False,
                    )

                    # Test connection
                    async with instance._driver.session() as session:
                        result = await session.run("RETURN 1")
                        _ = await result.single()

                    instance._connected = True
                    instance._connection_error = None
                    logger.info("✓ Neo4j connection established successfully")
                except Exception as e:
                    instance._connected = False
                    instance._connection_error = str(e)
                    logger.warning(
                        f"⚠ Neo4j connection failed (graceful degradation enabled): {e}. "
                        "Marketing agent will continue without KG features."
                    )
                    # Don't raise—continue with graceful degradation
            return instance

    @property
    def connected(self) -> bool:
        """Check if Neo4j is currently connected."""
        return self._connected

    @property
    def connection_error(self) -> Optional[str]:
        """Get the last connection error message."""
        return self._connection_error

    async def get_session(self) -> Optional[ManagedAsyncSession]:
        """Get an async Neo4j session, or None if not connected."""
        if not self._connected or self._driver is None:
            return None
        return self._driver.session()

    async def close(self):
        """Close the Neo4j driver."""
        async with self._lock:
            if self._driver:
                await self._driver.close()
                self._driver = None
                self._connected = False
                logger.info("Neo4j connection closed")

    async def query(self, cypher: str, **params) -> list:
        """
        Execute a Cypher query and return results as list of dicts.
        Returns empty list if not connected.
        """
        if not self._connected or self._driver is None:
            logger.debug(f"KG unavailable; skipping query: {cypher[:50]}...")
            return []

        try:
            async with self._driver.session() as session:
                result = await session.run(cypher, parameters=params)
                records = await result.all()
                return [dict(record) for record in records]
        except Exception as e:
            logger.error(f"Cypher query error: {e}", exc_info=True)
            return []

    async def execute(self, cypher: str, **params) -> bool:
        """
        Execute a Cypher write operation (MERGE, CREATE, etc.).
        Returns True on success, False if not connected or on error.
        """
        if not self._connected or self._driver is None:
            logger.debug(f"KG unavailable; skipping write: {cypher[:50]}...")
            return False

        try:
            async with self._driver.session() as session:
                await session.run(cypher, parameters=params)
            return True
        except Exception as e:
            logger.error(f"Cypher write error: {e}", exc_info=True)
            return False


async def get_neo4j() -> Neo4jSingleton:
    """Get the Neo4j singleton instance."""
    return Neo4jSingleton()
