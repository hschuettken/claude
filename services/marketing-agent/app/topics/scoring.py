"""Topic scoring engine — 6-factor weighted formula."""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pydantic import BaseModel


class TopicScore(BaseModel):
    """Scored topic with breakdown."""

    total: float  # 0.0 - 1.0
    breakdown: Dict[str, float]


class TopicCandidate(BaseModel):
    """Candidate topic for scoring."""

    title: str
    summary: str
    pillar_id: int
    signal_ids: List[int]
    created_at: datetime


class ScoringContext(BaseModel):
    """Context for scoring calculations."""

    audience_segments: List[str]
    voice_rules: Dict[str, str]
    published_posts: List[Dict] = []
    performance_history: List[Dict] = []


def compute_audience_fit(topic: TopicCandidate, audience_segments: List[str]) -> float:
    """
    Compute audience fit (25% weight).
    
    SAP technical topics score highest for primary audience.
    Pillar 1 (SAP/Datasphere) = 45% of content plan → 1.0 fit
    Pillar 2-3 (Trading/EV) = 30% → 0.8
    Pillar 4-6 (Other) = 25% → 0.5
    """
    pillar_weights = {
        1: 1.0,  # SAP/Datasphere
        2: 0.8,  # Trading
        3: 0.8,  # EV/PV
        4: 0.5,  # Other
        5: 0.5,
        6: 0.5,
    }
    return pillar_weights.get(topic.pillar_id, 0.5)


def compute_timeliness(signals: List[Dict], cutoff_days: int = 30) -> float:
    """
    Compute timeliness (20% weight).
    
    Signals from last 7 days: 1.0
    Signals from last 30 days: 0.6
    Older signals: 0.2
    SAP release notes bump: +0.3 (capped at 1.0)
    """
    if not signals:
        return 0.2

    now = datetime.utcnow()
    total_score = 0.0
    
    for signal in signals:
        created_at = signal.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        
        days_old = (now - created_at).days
        
        if days_old <= 7:
            score = 1.0
        elif days_old <= 30:
            score = 0.6
        else:
            score = 0.2
        
        # SAP release note bonus
        source = signal.get("source", "").lower()
        if "sap" in source or "release" in source:
            score = min(score + 0.3, 1.0)
        
        total_score += score
    
    return min(total_score / len(signals), 1.0)


def compute_authenticity(topic: TopicCandidate, voice_rules: Dict[str, str], known_domains: Optional[List[str]] = None) -> float:
    """
    Compute authenticity (20% weight).
    
    Topic matches Henning's known domains (SAP, Datasphere, trading, EV): +0.4
    Topic matches active projects: +0.3
    Generic topic with no personal angle: 0.1
    """
    if known_domains is None:
        known_domains = ["SAP", "Datasphere", "trading", "EV", "PV", "orchestrator"]
    
    title_lower = topic.title.lower()
    
    # Check for known domain matches
    domain_match = any(domain.lower() in title_lower for domain in known_domains)
    if domain_match:
        return 0.7  # 0.4 base + 0.3 for active projects
    
    # Check if topic is generic (very low authenticity)
    generic_keywords = ["AI", "transforming", "future", "innovation", "technology"]
    if all(kw.lower() in title_lower for kw in generic_keywords[:2]):
        return 0.1
    
    # Default: neutral authenticity
    return 0.4


def compute_uniqueness(topic: TopicCandidate, published_posts: List[Dict]) -> float:
    """
    Compute uniqueness (15% weight).
    
    No published posts on this topic: 1.0
    Related post in last 90 days: 0.3
    Covered in last 30 days: 0.0 (suppress)
    """
    if not published_posts:
        return 1.0
    
    now = datetime.utcnow()
    
    for post in published_posts:
        published_at = post.get("published_at")
        if isinstance(published_at, str):
            published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        
        days_ago = (now - published_at).days
        post_title = post.get("title", "").lower()
        topic_title = topic.title.lower()
        
        # Simple string overlap check
        if topic_title in post_title or post_title in topic_title:
            if days_ago <= 30:
                return 0.0  # Suppress recent duplicates
            elif days_ago <= 90:
                return 0.3  # Lower score for related recent posts
    
    return 1.0


def compute_evidence_strength(signals: List[Dict]) -> float:
    """
    Compute evidence strength (10% weight).
    
    Number of high-quality signals: count * 0.1, capped at 1.0
    High authority sources: +0.2
    """
    if not signals:
        return 0.0
    
    base_score = min(len(signals) * 0.1, 1.0)
    
    # Check for high-authority sources
    authority_sources = ["sap.com", "github.com", "academic", "official"]
    high_authority_count = sum(
        1 for signal in signals
        if any(auth in signal.get("source", "").lower() for auth in authority_sources)
    )
    
    authority_bonus = min(high_authority_count * 0.05, 0.2)
    return min(base_score + authority_bonus, 1.0)


def predict_performance(topic: TopicCandidate, performance_history: List[Dict]) -> float:
    """
    Compute performance prediction (10% weight).
    
    Average score of similar past posts: start with 0.5 as default
    Pillar performance bonus: pillar 1 posts avg engagement bonus
    """
    # Default fallback: neutral prediction
    default_score = 0.5
    
    if not performance_history:
        # Pillar 1 (SAP) gets slight bonus
        if topic.pillar_id == 1:
            return min(default_score + 0.2, 1.0)
        return default_score
    
    # Calculate average engagement from similar pillar posts
    similar_posts = [p for p in performance_history if p.get("pillar_id") == topic.pillar_id]
    
    if not similar_posts:
        return default_score
    
    avg_engagement = sum(p.get("engagement_rate", 0) for p in similar_posts) / len(similar_posts)
    # Normalize engagement rate (0-1) as score
    return min(avg_engagement, 1.0)


def score_topic(topic: TopicCandidate, context: ScoringContext, signals: Optional[List[Dict]] = None) -> TopicScore:
    """
    Score a topic using 6-factor weighted formula.
    
    Returns TopicScore with total (0.0-1.0) and breakdown dict.
    """
    # Compute all dimensions
    audience_fit = compute_audience_fit(topic, context.audience_segments)
    timeliness = compute_timeliness(signals or [])
    authenticity = compute_authenticity(topic, context.voice_rules)
    uniqueness = compute_uniqueness(topic, context.published_posts)
    evidence = compute_evidence_strength(signals or [])
    performance = predict_performance(topic, context.performance_history)
    
    # Weighted formula
    total = (
        0.25 * audience_fit +
        0.20 * timeliness +
        0.20 * authenticity +
        0.15 * uniqueness +
        0.10 * evidence +
        0.10 * performance
    )
    
    return TopicScore(
        total=round(total, 3),
        breakdown={
            "audience_fit": round(audience_fit, 3),
            "timeliness": round(timeliness, 3),
            "authenticity": round(authenticity, 3),
            "uniqueness": round(uniqueness, 3),
            "evidence": round(evidence, 3),
            "performance": round(performance, 3),
        }
    )
