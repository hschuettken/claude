"""Draft Studio API — split-pane draft editor with sources/KG context, rich text editor, and style checks.

Implements task #167: Draft Studio split-pane editor
- Left pane: sources/KG context/citations
- Center: rich text editor with draft CRUD
- Right pane: style checks, risk flags, visual prompt, CTA variants
- Governance: auto-flags client names and unsourced claims
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from sqlalchemy import select, desc
from pydantic import BaseModel, Field

from models import Draft, DraftStatus, Signal, Topic, Platform
from kg_query import get_kg_query
from app.drafts.governance import scan_risk_flags, format_risk_report, RiskFlag

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/draft-studio", tags=["draft-studio"])


# ============================================================================
# LEFT PANE: Sources, KG Context, Citations
# ============================================================================

class Citation(BaseModel):
    """Citation reference for sourcing claims."""
    id: Optional[int] = None
    title: str
    url: str
    source: str  # signal, topic, post, research, etc.
    relevance: float = Field(ge=0.0, le=1.0)  # 0.0-1.0 confidence
    snippet: Optional[str] = None
    added_at: Optional[str] = None
    
    class Config:
        from_attributes = True


class KGContextItem(BaseModel):
    """Knowledge Graph context item for draft reference."""
    type: str  # published_post, active_project, pillar_stat
    title: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = {}


class LeftPaneContext(BaseModel):
    """Left pane: sources, KG context, and citations."""
    signal_id: Optional[int] = None
    signal: Optional[Dict[str, Any]] = None  # Full signal object if linked
    topic_id: Optional[int] = None
    topic: Optional[Dict[str, Any]] = None  # Full topic object if linked
    kg_context: List[KGContextItem] = []  # Related posts, projects, stats
    citations: List[Citation] = []  # User-added citations
    pillar_id: Optional[int] = None


# ============================================================================
# CENTER PANE: Rich Text Editor CRUD
# ============================================================================

class DraftEditorData(BaseModel):
    """Center pane: draft text editor with content and metadata."""
    id: int
    title: str
    content: str  # HTML/markdown rich text
    summary: Optional[str] = None
    platform: str = "blog"
    tags: List[str] = []
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    status: str = "draft"
    word_count: int = 0
    last_saved_at: Optional[str] = None
    
    class Config:
        from_attributes = True


# ============================================================================
# RIGHT PANE: Style Checks, Risk Flags, Visual Prompt, CTA Variants
# ============================================================================

class StyleCheck(BaseModel):
    """Style check result."""
    rule: str
    severity: str  # info, warning, error
    match: str
    line_number: int
    suggestion: Optional[str] = None


class RiskFlagWithSuggestion(RiskFlag):
    """Risk flag with remediation suggestion."""
    remediation: Optional[str] = None


class CTAVariant(BaseModel):
    """Call-to-action variant for A/B testing."""
    id: str
    text: str
    color: str = "blue"
    style: str = "button"  # button, link, text
    position: str = "end"  # start, end, middle
    confidence: float = Field(ge=0.0, le=1.0)


class RightPaneChecks(BaseModel):
    """Right pane: style checks, risk flags, visual prompt, CTA variants."""
    style_checks: List[StyleCheck] = []
    risk_flags: List[RiskFlagWithSuggestion] = []
    readability_score: float = Field(ge=0.0, le=100.0)  # Flesch-Kincaid or similar
    estimated_reading_time: int = 0  # minutes
    visual_prompt: Optional[str] = None  # Suggested visual/hero image for post
    cta_variants: List[CTAVariant] = []  # Generated CTA variants
    governance_blocks: bool = False  # True if any critical governance risks
    governance_summary: str = ""


# ============================================================================
# Full Draft Studio State
# ============================================================================

class DraftStudioState(BaseModel):
    """Complete Draft Studio state: left + center + right panes."""
    draft_id: int
    left_pane: LeftPaneContext
    center_pane: DraftEditorData
    right_pane: RightPaneChecks
    created_at: str
    updated_at: str


# ============================================================================
# API Endpoints
# ============================================================================

async def _compute_readability_score(content: str) -> float:
    """Compute a simple readability score (0-100)."""
    # Very simplified: just check word count and sentence length
    words = content.split()
    if not words:
        return 50.0
    
    sentences = [s.strip() for s in content.split(".") if s.strip()]
    if not sentences:
        return 50.0
    
    avg_sentence_length = len(words) / len(sentences)
    # Score: 100 if avg_sentence_length is ~15 words, lower otherwise
    score = max(0, min(100, 100 - (abs(avg_sentence_length - 15) * 2)))
    return score


async def _generate_cta_variants(title: str, content: str) -> List[CTAVariant]:
    """Generate CTA variants based on content."""
    # Simple heuristic: generate a few generic CTAs
    base_ctas = [
        "Learn more",
        "Explore the full guide",
        "Get started now",
        "Read the complete story",
        "Discover more insights",
    ]
    
    variants = []
    for i, cta_text in enumerate(base_ctas[:3]):
        variants.append(CTAVariant(
            id=f"cta_{i}",
            text=cta_text,
            color="blue" if i == 0 else "gray",
            style="button" if i == 0 else "link",
            position="end",
            confidence=0.7 + (0.1 * i),  # 0.7, 0.8, 0.9
        ))
    
    return variants


async def _generate_visual_prompt(title: str, tags: List[str]) -> str:
    """Generate a visual prompt based on title and tags."""
    # Simple heuristic
    keywords = " ".join(tags[:2]) if tags else ""
    return f"Modern, professional hero image: {title}. Keywords: {keywords}"


@router.post("/open", response_model=DraftStudioState)
async def open_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> DraftStudioState:
    """
    Open a draft in Draft Studio.
    
    Returns the complete three-pane state:
    - Left: sources/KG context/citations
    - Center: rich text editor data
    - Right: style checks/risk flags/CTA variants
    """
    # Fetch draft
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    # ===== LEFT PANE: Sources/KG Context/Citations =====
    
    # Fetch linked signal and topic
    signal = None
    topic = None
    
    if draft.signal_id:
        signal_query = select(Signal).where(Signal.id == draft.signal_id)
        signal_result = await db.execute(signal_query)
        signal = signal_result.scalar_one_or_none()
    
    if draft.topic_id:
        topic_query = select(Topic).where(Topic.id == draft.topic_id)
        topic_result = await db.execute(topic_query)
        topic = topic_result.scalar_one_or_none()
    
    # Get KG context if available
    kg_context = []
    kg_query = get_kg_query()
    if kg_query.is_available():
        try:
            keywords = draft.tags + [draft.title]
            
            # Get published posts on topic
            published_posts = await kg_query.get_published_posts_on_topic(keywords)
            for post in published_posts:
                kg_context.append(KGContextItem(
                    type="published_post",
                    title=post.get("title", "Unknown"),
                    description=post.get("summary", ""),
                    metadata=post,
                ))
            
            # Get active projects
            active_projects = await kg_query.get_active_projects(keywords)
            for project in active_projects:
                kg_context.append(KGContextItem(
                    type="active_project",
                    title=project.get("name", "Unknown"),
                    description=project.get("description", ""),
                    metadata=project,
                ))
            
            # Get pillar stats
            pillar_id = 1  # Default
            pillar_stats = await kg_query.get_pillar_statistics(pillar_id)
            if pillar_stats:
                kg_context.append(KGContextItem(
                    type="pillar_stat",
                    title=f"Pillar {pillar_id} Statistics",
                    metadata=pillar_stats,
                ))
        except Exception as e:
            logger.warning(f"KG context fetch failed (non-fatal): {e}")
    
    # Create citations from signal/topic
    citations = []
    if signal:
        citations.append(Citation(
            id=signal.id,
            title=signal.title,
            url=signal.url or "",
            source="signal",
            relevance=signal.relevance_score or 0.5,
            snippet=signal.snippet,
            added_at=signal.created_at.isoformat() if signal.created_at else None,
        ))
    
    if topic:
        citations.append(Citation(
            id=topic.id,
            title=topic.name,
            url="",
            source="topic",
            relevance=topic.score or 0.5,
            snippet=topic.summary,
            added_at=topic.created_at.isoformat() if topic.created_at else None,
        ))
    
    left_pane = LeftPaneContext(
        signal_id=draft.signal_id,
        signal={"id": signal.id, "title": signal.title, "url": signal.url, "relevance": signal.relevance_score} if signal else None,
        topic_id=draft.topic_id,
        topic={"id": topic.id, "name": topic.name, "score": topic.score} if topic else None,
        kg_context=kg_context,
        citations=citations,
        pillar_id=1,  # Default
    )
    
    # ===== CENTER PANE: Editor Data =====
    word_count = len(draft.content.split()) if draft.content else 0
    center_pane = DraftEditorData(
        id=draft.id,
        title=draft.title,
        content=draft.content,
        summary=draft.summary,
        platform=draft.platform.value if draft.platform else "blog",
        tags=draft.tags or [],
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        status=draft.status.value if draft.status else "draft",
        word_count=word_count,
        last_saved_at=draft.updated_at.isoformat() if draft.updated_at else None,
    )
    
    # ===== RIGHT PANE: Style Checks/Risk Flags/CTAs =====
    
    # Governance scan
    risk_flags = await scan_risk_flags(draft.content)
    
    # Convert to right-pane format with remediation suggestions
    risk_flags_with_remediation = []
    for flag in risk_flags:
        remediation = None
        if flag.type == "client_reference":
            remediation = "Replace with generic company/client reference or remove specificity"
        elif flag.type == "unverified_metric":
            remediation = "Add citation or source for the metric claim"
        elif flag.type == "roadmap_claim":
            remediation = "Reframe as 'potential' or 'planned' rather than confirmed"
        elif flag.type == "confidentiality_risk":
            remediation = "Remove entirely — this is confidential information"
        elif flag.type == "unverified_feature":
            remediation = "Link to official documentation or product announcement"
        elif flag.type == "unsubstantiated_claim":
            remediation = "Add evidence, benchmark data, or soften claim language"
        elif flag.type == "style_allcaps":
            remediation = "Use emphasis (*text* or **text**) instead of ALL_CAPS"
        
        risk_flags_with_remediation.append(RiskFlagWithSuggestion(
            type=flag.type,
            match=flag.match,
            line_number=flag.line_number,
            action=flag.action,
            remediation=remediation,
        ))
    
    # Compute readability and CTA variants
    readability = await _compute_readability_score(draft.content)
    estimated_reading_time = max(1, word_count // 200)  # ~200 words per minute
    visual_prompt = await _generate_visual_prompt(draft.title, draft.tags or [])
    cta_variants = await _generate_cta_variants(draft.title, draft.content)
    
    # Check if governance blocks publishing
    blocking_flags = [f for f in risk_flags_with_remediation if f.action == "block"]
    governance_blocks = len(blocking_flags) > 0
    governance_summary = format_risk_report(risk_flags)
    
    right_pane = RightPaneChecks(
        style_checks=[],  # Can be extended with more style rules
        risk_flags=risk_flags_with_remediation,
        readability_score=readability,
        estimated_reading_time=estimated_reading_time,
        visual_prompt=visual_prompt,
        cta_variants=cta_variants,
        governance_blocks=governance_blocks,
        governance_summary=governance_summary,
    )
    
    # ===== Complete State =====
    state = DraftStudioState(
        draft_id=draft.id,
        left_pane=left_pane,
        center_pane=center_pane,
        right_pane=right_pane,
        created_at=draft.created_at.isoformat() if draft.created_at else "",
        updated_at=draft.updated_at.isoformat() if draft.updated_at else "",
    )
    
    logger.info(f"Draft {draft_id} opened in Draft Studio")
    return state


@router.put("/{draft_id}/center", response_model=DraftEditorData)
async def update_center_pane(
    draft_id: int,
    editor_data: DraftEditorData,
    db: AsyncSession = Depends(get_db),
) -> DraftEditorData:
    """
    Update center pane (rich text editor content).
    
    Auto-saves draft content, title, SEO metadata.
    """
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    # Update fields
    draft.title = editor_data.title
    draft.content = editor_data.content
    draft.summary = editor_data.summary
    draft.tags = editor_data.tags
    draft.seo_title = editor_data.seo_title
    draft.seo_description = editor_data.seo_description
    draft.updated_at = datetime.now(timezone.utc)
    
    await db.flush()
    
    # Recompute word count
    word_count = len(draft.content.split()) if draft.content else 0
    
    logger.info(f"Draft {draft_id} center pane updated ({word_count} words)")
    
    return DraftEditorData(
        id=draft.id,
        title=draft.title,
        content=draft.content,
        summary=draft.summary,
        platform=draft.platform.value if draft.platform else "blog",
        tags=draft.tags or [],
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        status=draft.status.value if draft.status else "draft",
        word_count=word_count,
        last_saved_at=draft.updated_at.isoformat(),
    )


@router.get("/{draft_id}/right", response_model=RightPaneChecks)
async def get_right_pane(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> RightPaneChecks:
    """
    Get/refresh right pane (style checks, risk flags, CTA variants).
    
    Re-scans governance and regenerates checks on demand.
    """
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    # Re-scan governance
    risk_flags = await scan_risk_flags(draft.content)
    risk_flags_with_remediation = []
    for flag in risk_flags:
        remediation = None
        if flag.type == "client_reference":
            remediation = "Replace with generic company/client reference or remove specificity"
        elif flag.type == "unverified_metric":
            remediation = "Add citation or source for the metric claim"
        elif flag.type == "roadmap_claim":
            remediation = "Reframe as 'potential' or 'planned' rather than confirmed"
        elif flag.type == "confidentiality_risk":
            remediation = "Remove entirely — this is confidential information"
        elif flag.type == "unverified_feature":
            remediation = "Link to official documentation or product announcement"
        elif flag.type == "unsubstantiated_claim":
            remediation = "Add evidence, benchmark data, or soften claim language"
        elif flag.type == "style_allcaps":
            remediation = "Use emphasis (*text* or **text**) instead of ALL_CAPS"
        
        risk_flags_with_remediation.append(RiskFlagWithSuggestion(
            type=flag.type,
            match=flag.match,
            line_number=flag.line_number,
            action=flag.action,
            remediation=remediation,
        ))
    
    # Readability and CTAs
    word_count = len(draft.content.split()) if draft.content else 0
    readability = await _compute_readability_score(draft.content)
    estimated_reading_time = max(1, word_count // 200)
    visual_prompt = await _generate_visual_prompt(draft.title, draft.tags or [])
    cta_variants = await _generate_cta_variants(draft.title, draft.content)
    
    # Governance
    blocking_flags = [f for f in risk_flags_with_remediation if f.action == "block"]
    governance_blocks = len(blocking_flags) > 0
    governance_summary = format_risk_report(risk_flags)
    
    return RightPaneChecks(
        style_checks=[],
        risk_flags=risk_flags_with_remediation,
        readability_score=readability,
        estimated_reading_time=estimated_reading_time,
        visual_prompt=visual_prompt,
        cta_variants=cta_variants,
        governance_blocks=governance_blocks,
        governance_summary=governance_summary,
    )


@router.post("/{draft_id}/citations", response_model=Citation)
async def add_citation(
    draft_id: int,
    citation: Citation,
    db: AsyncSession = Depends(get_db),
) -> Citation:
    """
    Add a citation to the left pane.
    
    Citations can be added from signals, topics, external URLs, or research.
    """
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    # Store citation in extra_metadata for now
    # (A dedicated table could be added later)
    if not draft.extra_metadata:
        draft.extra_metadata = {"citations": []}
    elif "citations" not in draft.extra_metadata:
        draft.extra_metadata["citations"] = []
    
    citation_data = citation.model_dump(exclude={"added_at"})
    citation_data["added_at"] = datetime.now(timezone.utc).isoformat()
    
    draft.extra_metadata["citations"].append(citation_data)
    draft.updated_at = datetime.now(timezone.utc)
    
    await db.flush()
    
    logger.info(f"Citation added to draft {draft_id}: {citation.title}")
    
    citation.added_at = datetime.now(timezone.utc).isoformat()
    return citation


@router.delete("/{draft_id}/citations/{citation_index}")
async def delete_citation(
    draft_id: int,
    citation_index: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Remove a citation from the left pane."""
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    if not draft.extra_metadata or "citations" not in draft.extra_metadata:
        raise HTTPException(status_code=404, detail="No citations found")
    
    citations = draft.extra_metadata["citations"]
    if citation_index < 0 or citation_index >= len(citations):
        raise HTTPException(status_code=404, detail=f"Citation index {citation_index} out of range")
    
    citations.pop(citation_index)
    draft.updated_at = datetime.now(timezone.utc)
    
    await db.flush()
    
    logger.info(f"Citation {citation_index} removed from draft {draft_id}")
    
    return {"status": "ok", "deleted_index": citation_index}
