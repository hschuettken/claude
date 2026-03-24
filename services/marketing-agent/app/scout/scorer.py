"""Relevance scoring for search results."""

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# SAP-related keywords
SAP_KEYWORDS = {
    "sap",
    "datasphere",
    "analytics",
    "businessobjects",
    "btp",
    "bpc",
    "businessdata",
    "data",
    "cloud",
}

# Pillar-specific keywords
PILLAR_KEYWORDS = {
    1: {
        "datasphere",
        "sap datasphere",
        "data integration",
        "data warehouse",
        "analytics",
    },
    2: {
        "release",
        "update",
        "roadmap",
        "new features",
        "q1",
        "q2",
        "q3",
        "q4",
    },
    3: {
        "thought leadership",
        "insights",
        "strategy",
        "trend",
        "executive",
    },
    4: {
        "ai",
        "llm",
        "artificial intelligence",
        "machine learning",
        "generative",
    },
    5: {
        "community",
        "discussion",
        "forum",
        "expert",
        "question",
    },
    6: {
        "compliance",
        "governance",
        "security",
        "privacy",
        "gdpr",
    },
}

# High-authority domains
HIGH_AUTH_DOMAINS = {
    "sap.com",
    "community.sap.com",
    "blogs.sap.com",
}

# Medium-authority domains
MED_AUTH_DOMAINS = {
    "linkedin.com",
    "gartner.com",
    "forrester.com",
    "medium.com",
    "github.com",
}


def extract_recency_boost(snippet: str) -> float:
    """
    Extract recency boost from snippet text.

    Looks for date patterns to determine if content is recent.
    Returns 0.3 for this week, 0.1 for this month, 0.0 otherwise.
    """
    now = datetime.utcnow()
    this_week = now - timedelta(days=7)
    this_month = now - timedelta(days=30)

    # Simple heuristic: look for year 2025, 2026 or month references
    text_lower = snippet.lower()

    if "2025" in text_lower or "2026" in text_lower or "january" in text_lower:
        # Assume recent
        return 0.15  # Conservative boost for current year mentions
    if "today" in text_lower or "this week" in text_lower or "latest" in text_lower:
        return 0.3
    if "this month" in text_lower or "recent" in text_lower:
        return 0.1

    return 0.0


def count_keyword_matches(text: str, keywords: set[str]) -> int:
    """Count how many keywords appear in text (case-insensitive)."""
    text_lower = text.lower()
    count = 0
    for keyword in keywords:
        if keyword in text_lower:
            count += 1
    return count


def score_signal(title: str, snippet: str, url: str, pillar_id: int) -> float:
    """
    Score a search result for relevance (0.0-1.0).

    Factors:
    - Keyword relevance (SAP + pillar keywords)
    - Source authority (domain)
    - Recency (from snippet/title)
    """
    score = 0.0

    # Combine title and snippet for keyword analysis
    combined_text = f"{title} {snippet}"

    # Keyword relevance: base SAP keywords
    sap_keywords_found = count_keyword_matches(combined_text, SAP_KEYWORDS)
    if sap_keywords_found > 0:
        score += min(sap_keywords_found * 0.08, 0.25)

    # Pillar-specific keywords
    pillar_keywords = PILLAR_KEYWORDS.get(pillar_id, set())
    pillar_keywords_found = count_keyword_matches(combined_text, pillar_keywords)
    if pillar_keywords_found > 0:
        score += min(pillar_keywords_found * 0.1, 0.35)

    # Source authority
    url_lower = url.lower()
    if any(domain in url_lower for domain in HIGH_AUTH_DOMAINS):
        score += 0.25
    elif any(domain in url_lower for domain in MED_AUTH_DOMAINS):
        score += 0.15

    # Recency boost
    recency = extract_recency_boost(combined_text)
    score += recency

    # Normalize to 0.0-1.0
    score = min(max(score, 0.0), 1.0)

    logger.debug(
        f"Signal score for '{title[:50]}...': {score:.2f} "
        f"(SAP keywords: {sap_keywords_found}, pillar keywords: {pillar_keywords_found})"
    )

    return score
