"""Signal to topic clustering engine."""

from typing import Dict, List, Set, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np


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
) -> List[TopicCluster]:
    """
    Cluster signals into candidate topics.
    
    Strategy:
    1. Filter signals by pillar_id (if provided)
    2. Compute similarity matrix (TF-IDF cosine)
    3. Greedy clustering: link signals with similarity > threshold
    4. Cap each cluster at max_signals_per_topic
    5. Return TopicCluster objects
    
    Params:
    - signals: list of signal dicts with id, title, summary (optional)
    - pillar_id: filter to specific pillar (0 = no filter)
    - min_similarity: cosine similarity threshold for grouping
    - max_signals_per_topic: max signals per cluster
    
    Returns:
    - List of TopicCluster objects
    """
    
    # Filter by pillar if specified
    if pillar_id > 0:
        signals = [s for s in signals if s.get("pillar_id") == pillar_id]
    
    if not signals:
        return []
    
    # Compute TF-IDF similarity
    texts = [s.get("title", "") + " " + s.get("summary", "") for s in signals]
    similarity_matrix = compute_tfidf_similarity(texts)
    
    # Greedy clustering
    clustered = set()
    clusters: List[TopicCluster] = []
    
    for i in range(len(signals)):
        if i in clustered:
            continue
        
        # Start a new cluster with signal i
        cluster_signal_ids = [signals[i]["id"]]
        clustered.add(i)
        
        # Add similar signals
        for j in range(len(signals)):
            if j in clustered or j == i:
                continue
            
            if similarity_matrix[i][j] > min_similarity and len(cluster_signal_ids) < max_signals_per_topic:
                cluster_signal_ids.append(signals[j]["id"])
                clustered.add(j)
        
        # Create topic title from signals
        titles = [signals[idx]["title"] for idx in [i] + [idx for idx, sig in enumerate(signals) if sig["id"] in cluster_signal_ids[1:]]]
        topic_title = titles[0] if titles else f"Topic from signal {signals[i]['id']}"
        
        # Use first signal's summary or combine
        topic_summary = signals[i].get("summary", "")
        
        # Create cluster
        cluster = TopicCluster(
            signal_ids=cluster_signal_ids,
            title=topic_title,
            summary=topic_summary,
            pillar_id=pillar_id or signals[i].get("pillar_id", 1),
        )
        clusters.append(cluster)
    
    return clusters
