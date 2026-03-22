"""Signal to topic clustering engine."""

import logging
from typing import Dict, List, Set, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

logger = logging.getLogger(__name__)


class TopicCluster:
    """A cluster of related signals forming a candidate topic."""

    def __init__(self, signal_ids: List[int], title: str, summary: str, pillar_id: int):
        self.signal_ids = signal_ids
        self.title = title
        self.summary = summary
        self.pillar_id = pillar_id


def extract_keywords(text: str) -> Set[str]:
    """Extract keywords from text."""
    if not text:
        return set()
    return set(text.lower().split())


def compute_keyword_overlap(text1: str, text2: str) -> float:
    """
    Compute keyword overlap between two texts (simple Jaccard similarity).
    
    Returns 0.0 to 1.0
    """
    keywords1 = extract_keywords(text1)
    keywords2 = extract_keywords(text2)
    
    if not keywords1 or not keywords2:
        return 0.0
    
    intersection = len(keywords1 & keywords2)
    union = len(keywords1 | keywords2)
    
    return intersection / union if union > 0 else 0.0


def compute_tfidf_similarity(texts: List[str]) -> np.ndarray:
    """
    Compute TF-IDF cosine similarity matrix.
    
    Returns similarity matrix (n x n).
    """
    if len(texts) < 2:
        return np.array([[1.0]])
    
    vectorizer = TfidfVectorizer(max_features=100, stop_words="english")
    try:
        tfidf_matrix = vectorizer.fit_transform(texts)
        similarity = cosine_similarity(tfidf_matrix)
        return similarity
    except Exception:
        # Fallback if vectorizer fails (e.g., all texts are empty)
        return np.zeros((len(texts), len(texts)))


async def cluster_signals_into_topics(
    signals: List[Dict],
    pillar_id: int = 1,
    min_similarity: float = 0.3,
    max_signals_per_topic: int = 10,
    min_cluster_size: int = 3,
) -> List[TopicCluster]:
    """
    Cluster signals into candidate topics.
    
    Strategy:
    1. Filter signals by pillar_id (if provided)
    2. Compute similarity matrix (TF-IDF cosine)
    3. Greedy clustering: link signals with similarity > threshold
    4. Only keep clusters with 3+ signals (configurable)
    5. Cap each cluster at max_signals_per_topic
    6. Return TopicCluster objects
    
    Params:
    - signals: list of signal dicts with id, title, snippet, relevance_score, created_at, pillar_id
    - pillar_id: filter to specific pillar (0 = no filter)
    - min_similarity: cosine similarity threshold for grouping
    - max_signals_per_topic: max signals per cluster
    - min_cluster_size: minimum signals to form a topic (default 3)
    
    Returns:
    - List of TopicCluster objects with 3+ signals
    """
    from datetime import datetime, timedelta
    
    # Filter by pillar if specified
    if pillar_id > 0:
        signals = [s for s in signals if s.get("pillar_id") == pillar_id]
    
    if not signals:
        return []
    
    # Filter to signals from last 7 days (topic window)
    cutoff_date = datetime.utcnow() - timedelta(days=7)
    signals_recent = [
        s for s in signals
        if s.get("created_at") is None or s.get("created_at") >= cutoff_date
    ]
    
    if len(signals_recent) < min_cluster_size:
        return []
    
    # Sort by relevance (highest first) for greedy clustering
    signals_sorted = sorted(signals_recent, key=lambda s: s.get("relevance_score", 0), reverse=True)
    
    # Compute TF-IDF similarity
    texts = [s.get("title", "") + " " + s.get("snippet", "") for s in signals_sorted]
    similarity_matrix = compute_tfidf_similarity(texts)
    
    # Greedy clustering: start with highest-relevance signals
    clustered = set()
    clusters: List[TopicCluster] = []
    
    for i in range(len(signals_sorted)):
        if i in clustered:
            continue
        
        # Start a new cluster with signal i
        cluster_signal_ids = [signals_sorted[i]["id"]]
        clustered.add(i)
        
        # Add similar signals
        for j in range(i + 1, len(signals_sorted)):
            if j in clustered:
                continue
            
            if similarity_matrix[i][j] > min_similarity and len(cluster_signal_ids) < max_signals_per_topic:
                cluster_signal_ids.append(signals_sorted[j]["id"])
                clustered.add(j)
        
        # Only keep clusters with min_cluster_size or more
        if len(cluster_signal_ids) < min_cluster_size:
            logger.debug(f"Skipping cluster with {len(cluster_signal_ids)} signals (min: {min_cluster_size})")
            continue
        
        # Create topic title from highest-relevance signals
        topic_title = signals_sorted[i].get("title", f"Topic {pillar_id}")
        
        # Use snippet or title for summary
        topic_summary = signals_sorted[i].get("snippet", "")
        
        # Create cluster
        cluster = TopicCluster(
            signal_ids=cluster_signal_ids,
            title=topic_title,
            summary=topic_summary,
            pillar_id=pillar_id or signals_sorted[i].get("pillar_id", 1),
        )
        clusters.append(cluster)
        logger.info(f"Created cluster: {topic_title} with {len(cluster_signal_ids)} signals")
    
    return clusters
