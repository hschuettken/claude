"""
SQLAlchemy models for Marketing Agent — full 8-table schema.
All tables in the 'marketing' PostgreSQL schema.
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Float, Boolean, 
    ForeignKey, ARRAY, JSON, Enum as SQLEnum, Index, UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


class DraftStatus(str, enum.Enum):
    """Draft lifecycle states."""
    draft = "draft"
    review = "review"
    approved = "approved"
    scheduled = "scheduled"
    published = "published"
    archived = "archived"


class RuleType(str, enum.Enum):
    """Voice rule types."""
    never_say = "never_say"
    always_say = "always_say"


class Platform(str, enum.Enum):
    """Publishing platforms."""
    blog = "blog"
    linkedin = "linkedin"
    twitter = "twitter"
    email = "email"


class SignalStatus(str, enum.Enum):
    """Signal lifecycle states."""
    new = "new"
    read = "read"
    used = "used"
    archived = "archived"


class Signal(Base):
    """Marketing signals/opportunities detected by Scout or manual input."""
    __tablename__ = "signals"
    __table_args__ = (
        Index("idx_signals_created_at", "created_at"),
        Index("idx_signals_relevance", "relevance_score"),
        Index("idx_signals_kg_node", "kg_node_id"),
        Index("idx_signals_status", "status"),
        Index("idx_signals_pillar", "pillar_id"),
<<<<<<< HEAD
        Index("idx_signals_url_hash", "url_hash"),
        {"schema": "marketing"}
=======
>>>>>>> origin/main
    )
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    url = Column(String(1024))
    snippet = Column(Text)  # Content snippet from search result
    source_domain = Column(String(255))  # e.g., sap.com, linkedin.com
    source = Column(String(100), nullable=False)  # scout, manual, research, etc.
    relevance_score = Column(Float, default=0.0)  # 0.0-1.0
<<<<<<< HEAD
    pillar_id = Column(Integer, ForeignKey("marketing.content_pillars.id"))  # 1-6
    status = Column(SQLEnum(SignalStatus), default=SignalStatus.new)  # new, read, used, archived
=======
    pillar_id = Column(Integer)  # Content pillar (1-6), for KG categorization
    status = Column(String(50), default="new")  # new, read, used, archived
    detected_at = Column(DateTime, default=datetime.utcnow)  # When signal was detected
>>>>>>> origin/main
    kg_node_id = Column(String(100))  # Reference to knowledge graph node
    url_hash = Column(String(64), unique=True)  # sha256(url) for deduplication
    search_profile_id = Column(String(100))  # Profile that detected this signal
    raw_json = Column(JSON)  # Full SearXNG result JSON
    detected_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    drafts = relationship("Draft", back_populates="signal")


class Topic(Base):
    """Content topics and topic categorization."""
    __tablename__ = "topics"
    __table_args__ = (
<<<<<<< HEAD
        Index("idx_topics_pillar", "pillar"),
        Index("idx_topics_audience", "audience_segment"),
        {"schema": "marketing"}
=======
        Index("idx_topics_pillar_id", "pillar_id"),
        Index("idx_topics_status", "status"),
        Index("idx_topics_created_at", "created_at"),
>>>>>>> origin/main
    )
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    pillar = Column(String(100))  # Legacy: human-readable pillar name
    pillar_id = Column(Integer)  # KG pillar ID (1-6)
    score = Column(Float, default=0.0)  # Topic relevance/viability score (0.0-1.0)
    summary = Column(Text)  # Topic summary/context for draft writer
    status = Column(String(50), default="candidate")  # candidate, selected, drafted, published, archived
    audience_segment = Column(String(100))  # e.g., "Enterprise", "SMB", "Developers"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    drafts = relationship("Draft", back_populates="topic")


class Draft(Base):
    """Marketing content drafts before publishing."""
    __tablename__ = "drafts"
    __table_args__ = (
        Index("idx_drafts_status", "status"),
        Index("idx_drafts_created_at", "created_at"),
        Index("idx_drafts_topic_id", "topic_id"),
        Index("idx_drafts_status_created", "status", "created_at"),
        UniqueConstraint("ghost_post_id", name="uq_drafts_ghost_post_id"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(String(500))
    
    # Relationships
    topic_id = Column(Integer, ForeignKey("marketing.topics.id"))
    signal_id = Column(Integer, ForeignKey("marketing.signals.id"))
    
    # Platform & publishing
    platform = Column(SQLEnum(Platform), default=Platform.blog)
    status = Column(SQLEnum(DraftStatus), default=DraftStatus.draft)
    ghost_post_id = Column(String(255))  # Set after publishing to Ghost
    ghost_url = Column(String(1024))
    
    # Approval workflow
    rejection_feedback = Column(Text)  # Feedback when rejected during review
    
    # Metadata
    tags = Column(ARRAY(String), default=[])
    seo_title = Column(String(255))
    seo_description = Column(String(160))
    extra_metadata = Column(JSON, default={})
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime)
    
    # Relationships
    topic = relationship("Topic", back_populates="drafts")
    signal = relationship("Signal", back_populates="drafts")
    blog_posts = relationship("BlogPost", back_populates="draft")
    linkedin_posts = relationship("LinkedInPost", back_populates="draft")
    status_history = relationship("StatusHistory", back_populates="draft", cascade="all, delete-orphan")
    approval_queue = relationship("ApprovalQueue", back_populates="draft", uselist=False, cascade="all, delete-orphan")


class BlogPost(Base):
    """Published Ghost blog posts with metadata."""
    __tablename__ = "blog_posts"
    __table_args__ = (
        Index("idx_blog_posts_draft_id", "draft_id"),
        Index("idx_blog_posts_published_at", "published_at"),
        Index("idx_blog_posts_ghost_post_id", "ghost_post_id"),
        UniqueConstraint("draft_id", name="uq_blog_posts_draft_id"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    draft_id = Column(Integer, ForeignKey("marketing.drafts.id"), nullable=False)
    ghost_post_id = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True)
    tags = Column(ARRAY(String), default=[])
    published_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    draft = relationship("Draft", back_populates="blog_posts")


class LinkedInPost(Base):
    """LinkedIn-specific posts generated from drafts."""
    __tablename__ = "linkedin_posts"
    __table_args__ = (
        Index("idx_linkedin_posts_draft_id", "draft_id"),
        Index("idx_linkedin_posts_posted_at", "posted_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    draft_id = Column(Integer, ForeignKey("marketing.drafts.id"), nullable=False)
    content = Column(Text, nullable=False)
    hook = Column(String(500))  # LinkedIn hook/opening line
    posted_at = Column(DateTime)
    linkedin_post_id = Column(String(255))  # LinkedIn post ID
    
    # Relationships
    draft = relationship("Draft", back_populates="linkedin_posts")


class VoiceRule(Base):
    """Brand voice guidelines and restrictions."""
    __tablename__ = "voice_rules"
    __table_args__ = (
        Index("idx_voice_rules_type", "rule_type"),
        Index("idx_voice_rules_created_at", "created_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    rule_type = Column(SQLEnum(RuleType), nullable=False)  # never_say, always_say
    content = Column(String(500), nullable=False)  # The actual rule text
    created_at = Column(DateTime, default=datetime.utcnow)


class ContentPillar(Base):
    """Content strategy pillars aligned with KG ContentPillar nodes (1-6)."""
    __tablename__ = "content_pillars"
    __table_args__ = (
        Index("idx_content_pillars_name", "name"),
<<<<<<< HEAD
        {"schema": "marketing"}
=======
        Index("idx_content_pillars_kg_id", "kg_id"),
>>>>>>> origin/main
    )
    
    id = Column(Integer, primary_key=True)
    kg_id = Column(Integer, unique=True)  # KG pillar ID (1-6) for KG sync
    name = Column(String(255), nullable=False, unique=True)
    weight = Column(Float, default=0.0)  # Pillar weight in distribution (sums to 1.0)
    description = Column(Text)
    color = Column(String(7))  # Hex color for UI
    target_audience = Column(String(255))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PerformanceSnapshot(Base):
    """Analytics snapshots from Plausible or Ghost."""
    __tablename__ = "performance_snapshots"
    __table_args__ = (
        Index("idx_perf_post_id", "post_id"),
        Index("idx_perf_platform", "platform"),
        Index("idx_perf_recorded_at", "recorded_at"),
        Index("idx_perf_platform_recorded", "platform", "recorded_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("marketing.blog_posts.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # plausible, ghost, linkedin
    views = Column(Integer, default=0)
    engagement_rate = Column(Float)  # 0.0-1.0
    recorded_at = Column(DateTime, default=datetime.utcnow)
    extra_data = Column(JSON, default={})  # Raw analytics data


class StatusHistory(Base):
    """Approval workflow — status transition history for drafts."""
    __tablename__ = "status_history"
    __table_args__ = (
        Index("idx_status_history_draft_id", "draft_id"),
        Index("idx_status_history_created_at", "created_at"),
        Index("idx_status_history_to_status", "to_status"),
        Index("idx_status_history_draft_created", "draft_id", "created_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    draft_id = Column(Integer, ForeignKey("marketing.drafts.id"), nullable=False)
    from_status = Column(String(50))  # NULL for initial status
    to_status = Column(String(50), nullable=False)
    changed_by = Column(String(255))  # User who made the transition
    feedback = Column(Text)  # Rejection feedback or notes
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    draft = relationship("Draft", back_populates="status_history")


class ApprovalQueue(Base):
    """Approval workflow — pending drafts awaiting review."""
    __tablename__ = "approval_queue"
    __table_args__ = (
        Index("idx_approval_queue_queued_at", "queued_at"),
        Index("idx_approval_queue_assigned_to", "assigned_to"),
        Index("idx_approval_queue_orbit_task_id", "orbit_task_id"),
        UniqueConstraint("draft_id", name="uq_approval_queue_draft_id"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    draft_id = Column(Integer, ForeignKey("marketing.drafts.id"), nullable=False)
    queued_at = Column(DateTime, default=datetime.utcnow)
    assigned_to = Column(String(255))  # Who it's assigned to (e.g., "henning")
    orbit_task_id = Column(String(255))  # Link to Orbit task
    discord_notified_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    draft = relationship("Draft", back_populates="approval_queue")
