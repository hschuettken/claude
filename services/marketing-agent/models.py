"""SQLAlchemy models for marketing schema."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    Index,
    ARRAY,
    JSON,
    Numeric,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class Signal(Base):
    """Marketing signals — external content/news/insights relevant to marketing."""

    __tablename__ = "signals"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    url_hash = Column(String(64), nullable=True, unique=True, index=True)  # SHA256 hash for dedup
    source = Column(String(128), nullable=False)  # Engine/source name
    source_domain = Column(String(255), nullable=True, index=True)  # Extracted domain
    snippet = Column(Text, nullable=True)  # Content preview
    relevance_score = Column(Float, nullable=False, default=0.0)
    pillar_id = Column(Integer, nullable=True, index=True)  # Content pillar (1-6)
    search_profile_id = Column(String(128), nullable=True, index=True)  # Which profile found it
    status = Column(String(32), nullable=False, default="new", index=True)  # new, read, used, archived
    raw_json = Column(Text, nullable=True)  # Full search result JSON
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    detected_at = Column(DateTime, nullable=True, index=True)  # When it was first detected
    kg_node_id = Column(String(128), nullable=True, index=True)


class Topic(Base):
    """Content topics/pillars for organizing marketing strategy."""

    __tablename__ = "topics"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    pillar = Column(String(255), nullable=False)  # e.g. 'Product', 'Leadership', 'Innovation'
    audience_segment = Column(String(255), nullable=False)  # e.g. 'Enterprise', 'SMB', 'Developers'
    
    # Topic Scoring Engine fields (Round 20)
    score = Column(Numeric(4, 3), nullable=True, default=0, index=True)  # 0.000 to 1.000
    score_breakdown = Column(JSON, nullable=True)  # {audience_fit, timeliness, authenticity, uniqueness, evidence, performance}
    signal_ids = Column(ARRAY(Integer), nullable=True, default=[])  # Source signal IDs
    pillar_id = Column(Integer, nullable=True, index=True)  # Pillar number 1-6
    status = Column(String(32), nullable=True, default="candidate", index=True)  # candidate, selected, drafted, published, archived
    
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    drafts = relationship("Draft", back_populates="topic")
    pillar_rel = relationship("ContentPillar", back_populates="topics")


class ContentPillar(Base):
    """Content pillars — top-level strategy buckets."""

    __tablename__ = "content_pillars"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    color = Column(String(7), nullable=True)  # Hex color code
    target_audience = Column(String(255), nullable=False)

    # Relationships
    topics = relationship("Topic", back_populates="pillar_rel")


class Draft(Base):
    """Content drafts — work-in-progress posts across platforms."""

    __tablename__ = "drafts"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    content = Column(Text, nullable=False)
    status = Column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )  # draft, review, approved, scheduled, published, rejected
    topic_id = Column(Integer, ForeignKey("marketing.topics.id"), nullable=True)
    platform = Column(String(64), nullable=False)  # blog, linkedin, twitter, etc.
    
    # Draft Writer fields (Round 20)
    format = Column(String(32), nullable=True, default="blog")  # blog, linkedin_teaser, linkedin_native
    outline = Column(JSON, nullable=True)  # Article outline structure
    sources = Column(JSON, nullable=True, default=[])  # Cited URLs and snippets
    seo_meta = Column(JSON, nullable=True)  # SEO title, description, keywords
    visual_prompt = Column(Text, nullable=True)  # Image generation prompt
    confidence_labels = Column(JSON, nullable=True, default={})  # Section confidence levels
    risk_flags = Column(JSON, nullable=True, default=[])  # Governance risk flags
    word_count = Column(Integer, nullable=True, default=0)
    
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    topic = relationship("Topic", back_populates="drafts")
    blog_post = relationship("BlogPost", uselist=False, back_populates="draft")
    linkedin_post = relationship("LinkedInPost", uselist=False, back_populates="draft")


class BlogPost(Base):
    """Blog posts — published via Ghost CMS."""

    __tablename__ = "blog_posts"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(Integer, ForeignKey("marketing.drafts.id"), nullable=False, unique=True)
    ghost_post_id = Column(String(64), nullable=False, unique=True, index=True)
    published_at = Column(DateTime, nullable=True)
    slug = Column(String(255), nullable=False, unique=True, index=True)
    tags = Column(String(512), nullable=True)  # Comma-separated or JSON-encoded

    # Relationships
    draft = relationship("Draft", back_populates="blog_post")


class LinkedInPost(Base):
    """LinkedIn posts — published to LinkedIn platform."""

    __tablename__ = "linkedin_posts"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    draft_id = Column(Integer, ForeignKey("marketing.drafts.id"), nullable=False, unique=True)
    content = Column(Text, nullable=False)
    hook = Column(String(512), nullable=True)  # Opening line to grab attention
    posted_at = Column(DateTime, nullable=True)

    # Relationships
    draft = relationship("Draft", back_populates="linkedin_post")


class VoiceRule(Base):
    """Voice & tone rules — guidelines for content generation."""

    __tablename__ = "voice_rules"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    rule_type = Column(String(32), nullable=False, index=True)  # never_say, always_say
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class PerformanceSnapshot(Base):
    """Performance snapshots — post engagement tracking."""

    __tablename__ = "performance_snapshots"
    __table_args__ = {"schema": "marketing"}

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, nullable=False, index=True)  # blog_post_id or linkedin_post_id
    platform = Column(String(64), nullable=False)  # blog, linkedin
    views = Column(Integer, nullable=False, default=0)
    engagement_rate = Column(Float, nullable=False, default=0.0)
    recorded_at = Column(DateTime, nullable=False, default=datetime.utcnow)
