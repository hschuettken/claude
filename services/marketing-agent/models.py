"""
SQLAlchemy models for Marketing Agent — full 12-table schema.
All tables in the 'marketing' PostgreSQL schema.

Schema tables:
- signals, topics, storylines, drafts, blog_posts, linkedin_posts
- visual_concepts, performance_snapshots, idea_notes, voice_rules
- content_pillars, audience_segments
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
        Index("idx_signals_url_hash", "url_hash"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    url = Column(String(1024))
    snippet = Column(Text)  # Content snippet from search result
    source_domain = Column(String(255))  # e.g., sap.com, linkedin.com
    source = Column(String(100), nullable=False)  # scout, manual, research, etc.
    relevance_score = Column(Float, default=0.0)  # 0.0-1.0
    pillar_id = Column(Integer, ForeignKey("marketing.content_pillars.id"))  # 1-6
    status = Column(SQLEnum(SignalStatus), default=SignalStatus.new)  # new, read, used, archived
    kg_node_id = Column(String(100))  # Reference to knowledge graph node
    url_hash = Column(String(64), unique=True)  # sha256(url) for deduplication
    search_profile_id = Column(String(100))  # Profile that detected this signal
    raw_json = Column(JSON)  # Full SearXNG result JSON
    detected_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    pillar = relationship("ContentPillar", back_populates="signals")
    drafts = relationship("Draft", back_populates="signal")


class Topic(Base):
    """Content topics and topic categorization."""
    __tablename__ = "topics"
    __table_args__ = (
        Index("idx_topics_pillar", "pillar_id"),
        Index("idx_topics_audience", "audience_segment_id"),
        Index("idx_topics_status", "status"),
        Index("idx_topics_created_at", "created_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    kg_id = Column(Integer)  # KG topic ID for cross-system linking
    pillar_id = Column(Integer, ForeignKey("marketing.content_pillars.id"))
    score = Column(Float, default=0.0)  # Topic relevance/viability score (0.0-1.0)
    summary = Column(Text)  # Topic summary/context for draft writer
    status = Column(String(50), default="candidate")  # candidate, selected, drafted, published, archived
    audience_segment_id = Column(Integer, ForeignKey("marketing.audience_segments.id"))
    storyline_id = Column(Integer, ForeignKey("marketing.storylines.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    pillar = relationship("ContentPillar", back_populates="topics")
    audience_segment = relationship("AudienceSegment", back_populates="topics")
    storyline = relationship("Storyline", back_populates="topics")
    drafts = relationship("Draft", back_populates="topic")


class Storyline(Base):
    """12-week content arcs and narrative structures."""
    __tablename__ = "storylines"
    __table_args__ = (
        Index("idx_storylines_start_date", "start_date"),
        Index("idx_storylines_pillar_id", "pillar_id"),
        Index("idx_storylines_status", "status"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    pillar_id = Column(Integer, ForeignKey("marketing.content_pillars.id"))
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    status = Column(String(50), default="planned")  # planned, in-progress, completed, archived
    color = Column(String(7))  # Hex color for UI
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    pillar = relationship("ContentPillar", back_populates="storylines")
    topics = relationship("Topic", back_populates="storyline")


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
    performance_snapshots = relationship("PerformanceSnapshot", back_populates="blog_post")


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


class VisualConcept(Base):
    """Visual prompt generations for images, diagrams, and brand assets."""
    __tablename__ = "visual_concepts"
    __table_args__ = (
        Index("idx_visual_concepts_draft_id", "draft_id"),
        Index("idx_visual_concepts_created_at", "created_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    draft_id = Column(Integer, ForeignKey("marketing.drafts.id"))
    prompt = Column(Text, nullable=False)  # Image generation prompt
    style_preset = Column(String(100))  # isometric, architecture, data-flow, etc.
    generated_url = Column(String(1024))  # URL to generated image
    created_at = Column(DateTime, default=datetime.utcnow)


class PerformanceSnapshot(Base):
    """Analytics snapshots from Plausible or Ghost."""
    __tablename__ = "performance_snapshots"
    __table_args__ = (
        Index("idx_perf_post_id", "blog_post_id"),
        Index("idx_perf_platform", "platform"),
        Index("idx_perf_recorded_at", "recorded_at"),
        Index("idx_perf_platform_recorded", "platform", "recorded_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    blog_post_id = Column(Integer, ForeignKey("marketing.blog_posts.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # plausible, ghost, linkedin
    views = Column(Integer, default=0)
    engagement_rate = Column(Float)  # 0.0-1.0
    click_rate = Column(Float)
    read_time_avg = Column(Float)  # Average reading time in seconds
    recorded_at = Column(DateTime, default=datetime.utcnow)
    extra_data = Column(JSON, default={})  # Raw analytics data
    
    # Relationships
    blog_post = relationship("BlogPost", back_populates="performance_snapshots")


class IdeaNote(Base):
    """Quick-capture ideas for future content."""
    __tablename__ = "idea_notes"
    __table_args__ = (
        Index("idx_idea_notes_status", "status"),
        Index("idx_idea_notes_pillar_id", "pillar_id"),
        Index("idx_idea_notes_created_at", "created_at"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text)
    pillar_id = Column(Integer, ForeignKey("marketing.content_pillars.id"))
    audience_segment_id = Column(Integer, ForeignKey("marketing.audience_segments.id"))
    status = Column(String(50), default="draft")  # draft, candidate, used, archived
    source = Column(String(100))  # memora, meeting, research, inspiration, etc.
    source_link = Column(String(1024))  # Link to source (meeting recording, article, etc.)
    tags = Column(ARRAY(String), default=[])
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    context = Column(String(255))  # Where/how the rule applies
    priority = Column(Integer, default=0)  # Higher priority rules checked first
    created_at = Column(DateTime, default=datetime.utcnow)


class ContentPillar(Base):
    """Content strategy pillars aligned with KG ContentPillar nodes (1-6)."""
    __tablename__ = "content_pillars"
    __table_args__ = (
        Index("idx_content_pillars_name", "name"),
        Index("idx_content_pillars_kg_id", "kg_id"),
        {"schema": "marketing"}
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
    
    # Relationships
    signals = relationship("Signal", back_populates="pillar")
    topics = relationship("Topic", back_populates="pillar")
    storylines = relationship("Storyline", back_populates="pillar")


class AudienceSegment(Base):
    """Target audience segments for content strategy."""
    __tablename__ = "audience_segments"
    __table_args__ = (
        Index("idx_audience_segments_name", "name"),
        Index("idx_audience_segments_kg_id", "kg_id"),
        {"schema": "marketing"}
    )
    
    id = Column(Integer, primary_key=True)
    kg_id = Column(Integer, unique=True)  # KG audience segment ID
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    size_estimate = Column(Integer)  # Estimated audience size
    engagement_profile = Column(JSON)  # Preferences, channels, interests
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    topics = relationship("Topic", back_populates="audience_segment")


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
