"""Topic service — orchestrates clustering + scoring."""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy.orm import Session

from app.topics.clustering import cluster_signals_into_topics
from app.topics.scoring import TopicCandidate, TopicScore, score_topic, ScoringContext
from models import Signal, Topic

logger = logging.getLogger(__name__)


class TopicService:
    """Service for clustering signals and scoring topics."""

    def __init__(self, db: Session):
        self.db = db

    async def refresh_topics(self, days: int = 7, min_score: float = 0.4) -> List[Topic]:
        """
        Refresh topics from unprocessed signals.

        1. Get all signals from last N days
        2. Filter unprocessed (not yet in a topic)
        3. Cluster into candidate topics (3+ signals per cluster)
        4. Score each topic
        5. Store topics with score > min_score
        6. Auto-draft topics with score > 0.8 (if no draft in last 14d)
        7. Return created topics

        Params:
        - days: lookback period
        - min_score: minimum score to store as candidate
        """
        from models import Draft
        
        # Get recent signals
        cutoff = datetime.utcnow() - timedelta(days=days)
        recent_signals = (
            self.db.query(Signal)
            .filter(Signal.created_at >= cutoff)
            .filter(Signal.status != "archived")
            .all()
        )

        if not recent_signals:
            logger.info(f"No signals found from last {days} days")
            return []

        logger.info(f"Found {len(recent_signals)} recent signals, clustering...")

        # Convert to dicts for clustering
        signal_dicts = [
            {
                "id": s.id,
                "title": s.title,
                "snippet": s.snippet or "",
                "source": s.source,
                "source_domain": s.source_domain,
                "relevance_score": s.relevance_score,
                "created_at": s.created_at,
                "pillar_id": s.pillar_id or 1,  # Use signal pillar if available
            }
            for s in recent_signals
        ]

        # Cluster by pillar (1-6)
        created_topics = []
        context = self._build_scoring_context()
        
        # Cluster for each pillar separately
        for pillar_id in range(1, 7):
            clusters = await cluster_signals_into_topics(signal_dicts, pillar_id=pillar_id, min_cluster_size=3)
            logger.info(f"Created {len(clusters)} clusters for pillar {pillar_id}")

            # Score each cluster and store
            for cluster in clusters:
                # Get signals for this cluster
                cluster_signals = [s for s in signal_dicts if s["id"] in cluster.signal_ids]

                # Create topic candidate
                topic_candidate = TopicCandidate(
                    title=cluster.title,
                    summary=cluster.summary,
                    pillar_id=cluster.pillar_id,
                    signal_ids=cluster.signal_ids,
                    created_at=datetime.utcnow(),
                )

                # Score topic
                topic_score = score_topic(topic_candidate, context, cluster_signals)

                if topic_score.total >= min_score:
                    # Check if topic already exists (by name)
                    existing_topic = self.db.query(Topic).filter(Topic.name == cluster.title).first()
                    if existing_topic:
                        logger.debug(f"Topic already exists: {cluster.title}")
                        continue

                    # Store in database
                    db_topic = Topic(
                        name=cluster.title,
                        pillar=f"pillar_{cluster.pillar_id}",
                        audience_segment="technical",
                        created_at=datetime.utcnow(),
                    )
                    
                    # Store extended fields if schema supports
                    if hasattr(db_topic, "score"):
                        db_topic.score = topic_score.total
                        db_topic.score_breakdown = topic_score.breakdown
                        db_topic.signal_ids = cluster.signal_ids
                        db_topic.pillar_id = cluster.pillar_id
                        db_topic.status = "candidate"

                    self.db.add(db_topic)
                    self.db.flush()  # Get the ID
                    created_topics.append(db_topic)
                    
                    # Auto-draft trigger: score > 0.8 AND no draft in last 14 days
                    if topic_score.total > 0.8:
                        cutoff_14d = datetime.utcnow() - timedelta(days=14)
                        recent_draft = (
                            self.db.query(Draft)
                            .filter(Draft.topic_id == db_topic.id)
                            .filter(Draft.created_at >= cutoff_14d)
                            .first()
                        )
                        
                        if not recent_draft:
                            logger.info(f"Auto-triggering draft for high-score topic: {cluster.title} (score: {topic_score.total})")
                            # TODO: Integrate with draft writer to auto-generate
                            # For now, just log the intent

        if created_topics:
            self.db.commit()
            logger.info(f"Stored {len(created_topics)} new topics")

        return created_topics

    def get_topics(
        self,
        status: Optional[str] = None,
        pillar_id: Optional[int] = None,
        min_score: Optional[float] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[Topic], int]:
        """
        Get topics with optional filtering.

        Returns (topics, total_count).
        """
        query = self.db.query(Topic)

        if status:
            query = query.filter(Topic.status == status)
        if pillar_id:
            query = query.filter(Topic.pillar_id == pillar_id)
        if min_score is not None:
            query = query.filter(Topic.score >= min_score)

        total = query.count()
        topics = query.order_by(Topic.score.desc()).offset(offset).limit(limit).all()

        return topics, total

    def get_top_topics(self, limit: int = 5) -> List[Topic]:
        """
        Get top N topics by score.

        Used for weekly content proposal.
        """
        return (
            self.db.query(Topic)
            .filter(Topic.status == "candidate")
            .order_by(Topic.score.desc())
            .limit(limit)
            .all()
        )

    def update_topic_status(self, topic_id: int, status: str) -> Optional[Topic]:
        """Update topic status."""
        topic = self.db.query(Topic).filter(Topic.id == topic_id).first()
        if topic:
            topic.status = status
            topic.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(topic)
        return topic

    def _build_scoring_context(self) -> ScoringContext:
        """Build scoring context from database."""
        # Load voice rules
        from models import VoiceRule
        voice_rules_db = self.db.query(VoiceRule).all()
        voice_rules = {vr.rule_type: vr.content for vr in voice_rules_db}

        # Load performance history
        from models import PerformanceSnapshot
        perf_history = self.db.query(PerformanceSnapshot).all()
        performance_history = [
            {
                "post_id": p.post_id,
                "platform": p.platform,
                "engagement_rate": p.engagement_rate,
                "pillar_id": 1,  # TODO: link to actual pillar
            }
            for p in perf_history
        ]

        return ScoringContext(
            audience_segments=["technical", "enterprise", "developers"],
            voice_rules=voice_rules,
            published_posts=[],  # TODO: load from blog_posts
            performance_history=performance_history,
        )
