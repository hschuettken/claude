"""Opportunity radar — Phase 3 automated data source fetchers.

Fetches opportunities from external sources (job search, ETFs, travel)
without requiring API keys. Falls back gracefully on any HTTP error.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LifeNav-Radar/1.0)"}
_TIMEOUT = 12


# ─────────────────────────────────────────────────────────────────────────────
# Job opportunities — DuckDuckGo HTML search (no API key)
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_job_opportunities(keywords: list[str], max_results: int = 5) -> list[dict[str, Any]]:
    """Search DuckDuckGo for job postings and return structured opportunities."""
    if not keywords:
        return []
    query = " ".join(k for k in keywords[:4]) + " remote job opening"
    results: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers=_HEADERS,
            )
            text = resp.text
            # DuckDuckGo HTML: <a class="result__a" href="...">title</a>
            # followed by <a class="result__snippet">snippet</a>
            link_re = re.compile(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S
            )
            snippet_re = re.compile(r'class="result__snippet"[^>]*>(.*?)</a>', re.S)
            titles_urls = link_re.findall(text)
            snippets = [re.sub(r"<[^>]+>", "", s) for s in snippet_re.findall(text)]
            expires_at = datetime.now(timezone.utc) + timedelta(days=7)
            for i, (url, raw_title) in enumerate(titles_urls[:max_results]):
                title = re.sub(r"<[^>]+>", "", raw_title).strip()
                if not title:
                    continue
                snippet = snippets[i].strip() if i < len(snippets) else ""
                results.append({
                    "title": title[:255],
                    "description": snippet[:500],
                    "category": "job",
                    "url": url if url.startswith("http") else None,
                    "relevance_score": 0.65,
                    "source": "web_search",
                    "expires_at": expires_at,
                })
    except Exception:
        pass
    return results


# ─────────────────────────────────────────────────────────────────────────────
# ETF/investment opportunities — Yahoo Finance (public, no auth)
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_ETF_SYMBOLS = ["VTI", "VOO", "QQQ", "VIG", "VXUS", "BND"]


async def fetch_etf_opportunities(
    symbols: list[str] | None = None,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Fetch ETF/stock quotes from Yahoo Finance and surface notable movers."""
    watch = symbols or _DEFAULT_ETF_SYMBOLS
    results: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://query1.finance.yahoo.com/v8/finance/quote",
                params={"symbols": ",".join(watch)},
                headers=_HEADERS,
            )
            resp.raise_for_status()
            quotes = resp.json().get("quoteResponse", {}).get("result", [])
    except Exception:
        return []

    # Sort by absolute day-change % to surface notable movers first
    def _change(q: dict[str, Any]) -> float:
        return abs(q.get("regularMarketChangePercent") or 0.0)

    for q in sorted(quotes, key=_change, reverse=True)[:max_results]:
        symbol: str = q.get("symbol", "")
        name: str = q.get("longName") or q.get("shortName") or symbol
        price: float = q.get("regularMarketPrice") or 0.0
        day_pct: float = q.get("regularMarketChangePercent") or 0.0
        pe: float | None = q.get("trailingPE")
        desc_parts = [f"${price:.2f} ({day_pct:+.2f}% today)"]
        if pe:
            desc_parts.append(f"P/E {pe:.1f}")
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        relevance = min(1.0, 0.5 + abs(day_pct) / 15)
        results.append({
            "title": f"{name} ({symbol})",
            "description": ", ".join(desc_parts),
            "category": "investment",
            "url": f"https://finance.yahoo.com/quote/{symbol}",
            "relevance_score": relevance,
            "source": "yahoo_finance",
            "expires_at": expires_at,
        })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Travel deal opportunities — RSS feed parser
# ─────────────────────────────────────────────────────────────────────────────

# Public RSS feeds with no login required
_TRAVEL_RSS_FEEDS = [
    "https://www.secretflying.com/feed/",
    "https://holidaypirates.com/rss/de/",
]


async def fetch_travel_opportunities(max_results: int = 5) -> list[dict[str, Any]]:
    """Parse travel deal RSS feeds and return structured opportunities."""
    results: list[dict[str, Any]] = []
    expires_at = datetime.now(timezone.utc) + timedelta(days=3)

    for feed_url in _TRAVEL_RSS_FEEDS:
        if len(results) >= max_results:
            break
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(feed_url, headers=_HEADERS)
                resp.raise_for_status()
            root = ET.fromstring(resp.text)
            ns: dict[str, str] = {}
            channel = root.find("channel")
            if channel is None:
                continue
            for item in channel.findall("item"):
                if len(results) >= max_results:
                    break
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                if title_el is None or title_el.text is None:
                    continue
                title = title_el.text.strip()
                link = (link_el.text or "").strip() if link_el is not None else None
                raw_desc = (desc_el.text or "") if desc_el is not None else ""
                desc = re.sub(r"<[^>]+>", "", raw_desc).strip()[:300]
                results.append({
                    "title": title[:255],
                    "description": desc,
                    "category": "travel",
                    "url": link or None,
                    "relevance_score": 0.7,
                    "source": "rss_feed",
                    "expires_at": expires_at,
                })
        except Exception:
            continue

    return results[:max_results]
