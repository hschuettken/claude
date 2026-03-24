"""SearXNG client for Scout Engine signal detection."""

import logging
import httpx
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    """A single search result from SearXNG."""
    title: str
    url: str
    content: str  # snippet
    engine: str
    score: Optional[float] = None
    published: Optional[str] = None


class SearXNGClient:
    """
    SearXNG client for fetching search results.
    
    Handles:
    - Query execution against SearXNG API
    - Result parsing
    - Health checks
    - Timeout/error handling with graceful degradation
    """
    
    def __init__(self, base_url: str = "http://192.168.0.84:8080", timeout: float = 30.0):
        """
        Initialize SearXNG client.
        
        Args:
            base_url: SearXNG base URL (default: internal LXC)
            timeout: HTTP request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
    
    async def search(
        self,
        query: str,
        engines: Optional[List[str]] = None,
        max_results: int = 10,
        language: str = "en",
    ) -> List[SearchResult]:
        """
        Execute a search query against SearXNG.
        
        Args:
            query: Search query string
            engines: List of engines to use (default: all)
            max_results: Max results to return (default: 10)
            language: Language code (default: en)
        
        Returns:
            List of SearchResult objects
        
        Raises:
            httpx.RequestError: Network or timeout error (caller should handle)
        """
        url = f"{self.base_url}/search"
        
        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
            "count": max_results,
            "language": language,
        }
        
        if engines:
            params["engines"] = ",".join(engines)
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                
                data = response.json()
                results = []
                
                for result in data.get("results", [])[:max_results]:
                    try:
                        sr = SearchResult(
                            title=result.get("title", ""),
                            url=result.get("url", ""),
                            content=result.get("content", ""),
                            engine=result.get("engine", "unknown"),
                            score=result.get("score"),
                            published=result.get("publishedDate"),
                        )
                        results.append(sr)
                    except Exception as e:
                        logger.warning(f"Failed to parse result: {e}")
                        continue
                
                logger.debug(f"SearXNG returned {len(results)} results for '{query}'")
                return results
        
        except httpx.TimeoutException:
            logger.error(f"SearXNG timeout for query '{query}'")
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"SearXNG HTTP error {e.status_code}: {e.response.text[:200]}")
            raise
        except Exception as e:
            logger.error(f"SearXNG request failed: {e}")
            raise
    
    async def health_check(self) -> bool:
        """
        Check if SearXNG is alive and responsive.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/", follow_redirects=True)
                is_healthy = response.status_code == 200
                
                if is_healthy:
                    logger.debug(f"SearXNG health check: OK ({self.base_url})")
                else:
                    logger.warning(f"SearXNG health check: HTTP {response.status_code}")
                
                return is_healthy
        except Exception as e:
            logger.warning(f"SearXNG health check failed: {e}")
            return False
