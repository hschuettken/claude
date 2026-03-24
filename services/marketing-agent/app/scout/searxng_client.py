"""SearXNG HTTP client for web search queries."""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class SearchResult:
    """Represents a single search result from SearXNG."""

    def __init__(
        self,
        title: str,
        url: str,
        snippet: str,
        engine: str,
        engine_score: float = 0.0,
    ):
        self.title = title
        self.url = url
        self.snippet = snippet
        self.engine = engine
        self.engine_score = engine_score  # 0.0-1.0 from SearXNG


class SearXNGClient:
    """HTTP client for SearXNG search engine."""

    def __init__(self, base_url: str = "http://192.168.0.84:8080"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search(
        self,
        query: str,
        engines: Optional[list[str]] = None,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """
        Search SearXNG for results.

        Args:
            query: Search query string
            engines: List of engines to use (e.g. ["google", "bing", "duckduckgo"])
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        if engines is None:
            engines = ["google"]

        try:
            params = {
                "q": query,
                "format": "json",
                "engines": ",".join(engines),
                "pageno": 1,
                "rss": "true",  # Try to get results
            }

            url = f"{self.base_url}/search"
            logger.debug(f"Searching SearXNG: {query} with engines {engines}")

            response = await self.client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            results = []

            # Parse results from SearXNG response
            for i, result in enumerate(data.get("results", [])):
                if i >= max_results:
                    break

                try:
                    search_result = SearchResult(
                        title=result.get("title", "").strip(),
                        url=result.get("url", "").strip(),
                        snippet=result.get("content", "").strip(),
                        engine=result.get("engine", "unknown"),
                        engine_score=0.5,  # SearXNG doesn't expose per-result scores
                    )
                    if search_result.title and search_result.url:
                        results.append(search_result)
                except (KeyError, ValueError) as e:
                    logger.debug(f"Error parsing SearXNG result: {e}")
                    continue

            logger.info(f"SearXNG search returned {len(results)} results for: {query}")
            return results

        except httpx.TimeoutException:
            logger.error(f"SearXNG timeout for query: {query}")
            return []
        except httpx.RequestError as e:
            logger.error(f"SearXNG request error: {e}")
            return []
        except ValueError as e:
            logger.error(f"SearXNG response parsing error: {e}")
            return []

    async def health_check(self) -> bool:
        """Check if SearXNG is healthy."""
        try:
            response = await self.client.get(f"{self.base_url}/status", timeout=5.0)
            is_healthy = response.status_code == 200
            logger.info(f"SearXNG health check: {'healthy' if is_healthy else 'unhealthy'}")
            return is_healthy
        except Exception as e:
            logger.warning(f"SearXNG health check failed: {e}")
            return False

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
