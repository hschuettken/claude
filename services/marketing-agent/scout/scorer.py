"""Relevance scoring for Scout Engine signals."""

import logging
from datetime import datetime, timedelta
from typing import Optional
from .searxng_client import SearchResult

logger = logging.getLogger(__name__)


# Keyword sets for pillar matching and boost
SAP_KEYWORDS = {
    "sap", "datasphere", "btp", "hana", "analyticscloud", "businessobjects",
    "successfactors", "ariba", "concur", "fieldglass", "hybris"
}

PILLAR_KEYWORDS = {
    1: {  # SAP Datasphere & Data
        "datasphere", "data", "modeling", "etl", "integration", "warehouse",
        "datalake", "semantics", "analytics", "metadata", "lineage"
    },
    2: {  # Release Notes & Updates
        "release", "update", "version", "roadmap", "new features", "announcement",
        "q1", "q2", "q3", "q4", "2025"
    },
    3: {  # Community & Thought Leadership
        "community", "thought leader", "expert", "best practice", "case study",
        "webinar", "conference", "summit", "opinion", "perspective"
    },
    4: {  # AI & Enterprise
        "ai", "llm", "machine learning", "automation", "intelligence", "copilot",
        "genai", "generative", "neural", "deep learning"
    },
    5: {  # Integration & Architecture
        "integration", "api", "ecosystem", "architecture", "microservices",
        "cloud", "hybrid", "middleware", "connector"
    },
    6: {  # Customer & Industry
        "customer", "industry", "vertical", "use case", "success", "roi",
        "enterprise", "sme", "adoption", "transformation"
    }
}

HIGH_AUTH_DOMAINS = {
    "sap.com", "community.sap.com", "blogs.sap.com", "news.sap.com",
    "help.sap.com"
}

MED_AUTH_DOMAINS = {
    "linkedin.com", "gartner.com", "forrester.com", "linkedin.com",
    "medium.com", "dev.to", "github.com", "youtube.com", "aws.amazon.com",
    "cloud.google.com", "azure.microsoft.com"
}


def _normalize_text(text: str) -> str:
    """Lowercase and strip punctuation for keyword matching."""
    return text.lower().strip()


def _count_keywords(text: str, keywords: set) -> int:
    """Count keyword occurrences in text (case-insensitive, substring match)."""
    normalized = _normalize_text(text)
    count = 0
    for kw in keywords:
        # Simple substring matching (could use regex for word boundaries)
        count += normalized.count(kw)
    return count


def _parse_publish_date(date_str: Optional[str]) -> Optional[datetime]:
    """
    Try to parse a publish date from various formats.
    
    Returns None if unparseable.
    """
    if not date_str:
        return None
    
    try:
        # ISO format: 2025-03-23T...
        if "T" in date_str:
            return datetime.fromisoformat(date_str.split("T")[0])
        
        # Other common formats can be added here
        return None
    except Exception:
        return None


def _get_recency_boost(published: Optional[str]) -> float:
    """
    Return recency boost (0.0-0.3) based on publish date.
    
    - This week: 0.3
    - This month: 0.2
    - This year: 0.1
    - Older or unknown: 0.0
    """
    pub_date = _parse_publish_date(published)
    if not pub_date:
        return 0.0
    
    now = datetime.utcnow()
    age = now - pub_date
    
    if age < timedelta(days=7):
        return 0.3
    elif age < timedelta(days=30):
        return 0.2
    elif age < timedelta(days=365):
        return 0.1
    else:
        return 0.0


def score_signal(
    result: SearchResult,
    pillar_id: int = 1,
    base_score: float = 0.5
) -> float:
    """
    Score a search result for relevance (0.0-1.0).
    
    Scoring factors:
    - SAP keyword presence: up to 0.2
    - Pillar-specific keywords: up to 0.25
    - Source authority: up to 0.2
    - Recency: up to 0.3
    
    Args:
        result: SearchResult from SearXNG
        pillar_id: Target pillar (1-6) for keyword matching
        base_score: Starting score (default 0.5)
    
    Returns:
        Score 0.0-1.0 (clamped)
    """
    score = base_score
    
    # Combine title and snippet for keyword analysis
    content = f"{result.title} {result.content}".lower()
    
    # SAP keyword boost
    sap_kw_count = _count_keywords(content, SAP_KEYWORDS)
    score += min(sap_kw_count * 0.05, 0.2)  # up to 0.2
    
    # Pillar-specific keyword boost
    pillar_keywords = PILLAR_KEYWORDS.get(pillar_id, set())
    pillar_kw_count = _count_keywords(content, pillar_keywords)
    score += min(pillar_kw_count * 0.05, 0.25)  # up to 0.25
    
    # Domain authority boost
    url_lower = result.url.lower()
    if any(domain in url_lower for domain in HIGH_AUTH_DOMAINS):
        score += 0.2
    elif any(domain in url_lower for domain in MED_AUTH_DOMAINS):
        score += 0.1
    
    # Recency boost
    recency = _get_recency_boost(result.published)
    score += recency
    
    # Clamp to 0.0-1.0
    return max(0.0, min(1.0, score))
