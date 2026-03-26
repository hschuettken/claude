"""SearXNG client for Scout Engine signal detection."""

import logging
import httpx
import asyncio
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
    
    def __init__(self, base_url: str = "http://192.168.0.84:8080", timeout: float = 5.0):
        """
        Initialize SearXNG client.
        
        Args:
            base_url: SearXNG base URL (default: internal LXC)
            timeout: HTTP request timeout in seconds (default: 5.0, matches health_check)
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
        Execute a search query against SearXNG with retry logic and error handling.
        
        Args:
            query: Search query string
            engines: List of engines to use (default: all)
            max_results: Max results to return (default: 10)
            language: Language code (default: en)
        
        Returns:
            List of SearchResult objects (empty list on failure after retries)
        """
        url = f"{self.base_url}/search"
        max_retries = 3
        base_backoff = 0.5  # seconds
        
        params = {
            "q": query,
            "format": "json",
            "pageno": 1,
            "count": max_results,
            "language": language,
        }
        
        if engines:
            params["engines"] = ",".join(engines)
        
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    
                    # Parse JSON with explicit error handling
                    try:
                        data = response.json()
                    except ValueError as json_err:
                        logger.error(
                            f"SearXNG malformed JSON (attempt {attempt + 1}/{max_retries}): "
                            f"query='{query}', status={response.status_code}, error={json_err}"
                        )
                        # Server is up but broke response — don't retry
                        return []
                    
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
                            logger.warning(f"Failed to parse result: {type(e).__name__}: {e}")
                            continue
                    
                    logger.debug(f"SearXNG returned {len(results)} results for '{query}'")
                    return results
            
            except httpx.ConnectError as e:
                logger.error(
                    f"SearXNG connection refused (attempt {attempt + 1}/{max_retries}): "
                    f"query='{query}', base_url={self.base_url}, error={e}"
                )
                # Transient — retry with backoff
                if attempt < max_retries - 1:
                    backoff_secs = base_backoff * (2 ** attempt)
                    await asyncio.sleep(backoff_secs)
            
            except httpx.TimeoutException as e:
                logger.error(
                    f"SearXNG timeout (attempt {attempt + 1}/{max_retries}): "
                    f"query='{query}', timeout={self.timeout}s, error={e}"
                )
                # Transient — retry with backoff
                if attempt < max_retries - 1:
                    backoff_secs = base_backoff * (2 ** attempt)
                    await asyncio.sleep(backoff_secs)
            
            except httpx.HTTPStatusError as e:
                logger.error(
                    f"SearXNG HTTP error (attempt {attempt + 1}/{max_retries}): "
                    f"query='{query}', status={e.response.status_code}, error={e}"
                )
                # Non-transient (4xx/5xx) — don't retry
                return []
            
            except Exception as e:
                logger.error(
                    f"SearXNG search failed (attempt {attempt + 1}/{max_retries}): "
                    f"query='{query}', error_type={type(e).__name__}, error={e}"
                )
                # Unknown error — retry with backoff
                if attempt < max_retries - 1:
                    backoff_secs = base_backoff * (2 ** attempt)
                    await asyncio.sleep(backoff_secs)
        
        # All retries exhausted
        logger.error(f"SearXNG search exhausted {max_retries} attempts: query='{query}'")
        return []
    
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
