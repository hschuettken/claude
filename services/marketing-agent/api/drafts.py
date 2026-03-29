"""Marketing drafts and Ghost publishing API."""
import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from sqlalchemy import select
from pydantic import BaseModel

from models import Draft, DraftStatus, Platform, BlogPost
from ghost_client import GhostAdminAPIClient
from kg_query import get_kg_query
from kg_ingest import get_kg_ingest
from events import publish_draft_created, publish_post_published, publish_performance_updated
from app.knowledge_graph.hooks import KGHooks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/drafts", tags=["drafts"])


class DraftCreate(BaseModel):
    """Create draft request."""
    title: str
    content: str
    summary: Optional[str] = None
    topic_id: Optional[int] = None
    signal_id: Optional[int] = None
    platform: Platform = Platform.blog
    tags: List[str] = []
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None


class DraftUpdate(BaseModel):
    """Update draft request."""
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    status: Optional[DraftStatus] = None
    topic_id: Optional[int] = None
    tags: Optional[List[str]] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None


class DraftResponse(BaseModel):
    """Draft response."""
    id: int
    title: str
    content: str
    summary: Optional[str]
    status: str
    platform: str
    ghost_post_id: Optional[str]
    ghost_url: Optional[str]
    tags: List[str]
    topic_id: Optional[int]
    signal_id: Optional[int]
    created_at: str
    updated_at: str
    published_at: Optional[str]
    
    class Config:
        from_attributes = True


class KGContext(BaseModel):
    """Knowledge Graph context for draft generation."""
    published_posts: List[Dict[str, Any]] = []
    active_projects: List[Dict[str, Any]] = []
    pillar_stats: Dict[str, Any] = {}


class DraftWithKGContext(DraftResponse):
    """Draft response with Knowledge Graph context."""
    kg_context: Optional[KGContext] = None


@router.post("", response_model=DraftWithKGContext)
async def create_draft(
    draft: DraftCreate,
    db: AsyncSession = Depends(get_db),
) -> DraftWithKGContext:
    """Create a new marketing draft with KG context enrichment.
    
    If Knowledge Graph is available, injects context about:
    - Previously published posts on related topics
    - Active projects/tasks related to the topic
    - Content statistics for this pillar
    """
    new_draft = Draft(
        title=draft.title,
        content=draft.content,
        summary=draft.summary,
        topic_id=draft.topic_id,
        signal_id=draft.signal_id,
        platform=draft.platform,
        tags=draft.tags,
        seo_title=draft.seo_title,
        seo_description=draft.seo_description,
        status=DraftStatus.draft,
    )
    
    db.add(new_draft)
    await db.flush()
    
    # Ingest draft to KG
    kg_ingest = get_kg_ingest()
    pillar_id = 1  # Default to first pillar if not specified
    await kg_ingest.ingest_draft_as_post(
        draft_id=new_draft.id,
        title=new_draft.title,
        format=new_draft.platform.value,
        topic_id=new_draft.topic_id,
        pillar_id=pillar_id,
        word_count=len(new_draft.content.split()),
        status=new_draft.status.value,
    )
    
    # Publish NATS event: draft.created
    await publish_draft_created(
        draft_id=new_draft.id,
        title=new_draft.title,
        tags=new_draft.tags,
        source_signal=str(new_draft.signal_id) if new_draft.signal_id else None,
    )
    
    # Enrich with KG context if available
    kg_context = None
    kg_query = get_kg_query()
    if kg_query.is_available():
        # Extract keywords from title and tags
        keywords = draft.tags + [draft.title]
        
        # Query KG for related context
        published_posts = await kg_query.get_published_posts_on_topic(keywords)
        active_projects = await kg_query.get_active_projects(keywords)
        pillar_stats = await kg_query.get_pillar_statistics(pillar_id)
        
        kg_context = KGContext(
            published_posts=published_posts,
            active_projects=active_projects,
            pillar_stats=pillar_stats,
        )
        
        logger.info(
            f"Draft {new_draft.id} enriched with KG context: "
            f"{len(published_posts)} posts, {len(active_projects)} projects"
        )
    
    response = DraftWithKGContext.model_validate(new_draft)
    response.kg_context = kg_context
    
    logger.info(f"Draft created: {new_draft.id} ({draft.title})")
    return response


@router.get("", response_model=List[DraftResponse])
async def list_drafts(
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[str] = None,
) -> List[DraftResponse]:
    """
    List marketing drafts, optionally filtered by status.
    
    Query params:
      - status_filter: Filter by status (draft, review, approved, published, etc.)
    """
    query = select(Draft).order_by(Draft.created_at.desc())
    
    if status_filter:
        query = query.where(Draft.status == status_filter)
    
    result = await db.execute(query)
    drafts = result.scalars().all()
    
    return [DraftResponse.model_validate(d) for d in drafts]


@router.get("/{draft_id}", response_model=DraftWithKGContext)
async def get_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
    include_kg: bool = True,
) -> DraftWithKGContext:
    """Get a single draft by ID.
    
    Query params:
      - include_kg: Include Knowledge Graph context (default: true)
    """
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    # Enrich with KG context if requested
    kg_context = None
    if include_kg:
        kg_query = get_kg_query()
        if kg_query.is_available():
            keywords = draft.tags + [draft.title]
            pillar_id = 1  # Default
            
            published_posts = await kg_query.get_published_posts_on_topic(keywords)
            active_projects = await kg_query.get_active_projects(keywords)
            pillar_stats = await kg_query.get_pillar_statistics(pillar_id)
            
            kg_context = KGContext(
                published_posts=published_posts,
                active_projects=active_projects,
                pillar_stats=pillar_stats,
            )
    
    response = DraftWithKGContext.model_validate(draft)
    response.kg_context = kg_context
    return response


@router.put("/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: int,
    update: DraftUpdate,
    db: AsyncSession = Depends(get_db),
) -> DraftResponse:
    """Update a draft."""
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    # Track old status for hook
    old_status = draft.status
    
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(draft, key, value)
    
    draft.updated_at = datetime.now(timezone.utc)
    await db.flush()
    
    logger.info(f"Draft updated: {draft_id}")
    
    # Auto-ingest to KG if status changed to 'approved' or 'published'
    if update.status and update.status in (DraftStatus.approved, DraftStatus.published):
        try:
            asyncio.create_task(
                KGHooks.on_draft_status_changed(
                    draft=draft,
                    old_status=str(old_status),
                    new_status=str(update.status)
                )
            )
        except Exception as e:
            logger.debug(f"KG hook scheduling failed (non-fatal): {e}")
    
    return DraftResponse.model_validate(draft)


@router.delete("/{draft_id}")
async def delete_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Delete a draft."""
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    await db.delete(draft)
    logger.info(f"Draft deleted: {draft_id}")
    
    return {"status": "ok", "deleted_id": draft_id}


@router.get("/kg/status")
async def kg_status() -> Dict[str, Any]:
    """Check Knowledge Graph connection status and node counts."""
    kg_query = get_kg_query()
    kg_ingest = get_kg_ingest()
    
    status = {
        "query_available": kg_query.is_available(),
        "ingest_available": kg_ingest.is_available(),
        "neo4j_url": kg_query.neo4j_url if kg_query.is_available() else None,
    }
    
    # Query node counts if available
    if kg_query.is_available():
        try:
            with kg_query._driver.session() as session:
                counts = {}
                for label in ["Signal", "Topic", "Post", "ContentPillar"]:
                    result = session.run(f"MATCH (n:{label}) RETURN count(n) as count")
                    record = result.single()
                    counts[label] = record["count"] if record else 0
                status["node_counts"] = counts
        except Exception as e:
            logger.warning(f"Failed to get node counts: {e}")
            status["node_counts"] = {}
    
    return status


@router.get("/kg/pillars")
async def kg_pillars() -> Dict[str, Any]:
    """Get content pillar statistics from Knowledge Graph."""
    kg_query = get_kg_query()
    
    if not kg_query.is_available():
        return {"error": "Knowledge Graph unavailable"}
    
    pillars = {}
    for pillar_id in range(1, 7):  # 6 pillars
        stats = await kg_query.get_pillar_statistics(pillar_id)
        pillars[f"pillar_{pillar_id}"] = stats
    
    return pillars


@router.get("/kg/cluster/{topic_id}")
async def kg_cluster(topic_id: str) -> Dict[str, Any]:
    """Get a topic's full Knowledge Graph cluster.
    
    Returns the topic node plus related signals and generated posts.
    """
    kg_query = get_kg_query()
    
    if not kg_query.is_available():
        return {"error": "Knowledge Graph unavailable"}
    
    cluster = await kg_query.get_topic_cluster(topic_id)
    return cluster


@router.post("/{draft_id}/publish", response_model=Dict[str, Any])
async def publish_draft(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Publish a draft to Ghost CMS.
    
    Creates a Ghost post, publishes it, and updates draft record.
    """
    # Fetch draft
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    if draft.status == DraftStatus.published:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Draft is already published",
        )
    
    try:
        async with GhostAdminAPIClient() as ghost:
            logger.info(f"Publishing draft {draft_id} to Ghost: {draft.title}")
            
            # Create and publish post
            post = await ghost.create_post(
                title=draft.title,
                html=draft.content,
                tags=draft.tags,
                status="draft",
                custom_excerpt=draft.summary,
            )
            
            ghost_post_id = post["id"]
            
            # Publish immediately
            published = await ghost.publish_post(ghost_post_id)
            ghost_url = published.get("url", "")
            
            # Update draft record
            draft.status = DraftStatus.published
            draft.ghost_post_id = ghost_post_id
            draft.ghost_url = ghost_url
            draft.published_at = datetime.now(timezone.utc)
            
            # Create blog_posts record
            blog_post = BlogPost(
                draft_id=draft.id,
                ghost_post_id=ghost_post_id,
                slug=published.get("slug"),
                tags=draft.tags,
            )
            db.add(blog_post)
            
            await db.flush()
            
            # Update KG with published status and URL
            kg_ingest = get_kg_ingest()
            if kg_ingest.is_available():
                pillar_id = 1  # Default
                await kg_ingest.ingest_draft_as_post(
                    draft_id=draft.id,
                    title=draft.title,
                    format=draft.platform.value,
                    topic_id=draft.topic_id,
                    pillar_id=pillar_id,
                    word_count=len(draft.content.split()),
                    status="published",
                )
                logger.info(f"Updated KG with published post: {draft.id}")
            
            # Publish NATS event: post.published
            await publish_post_published(
                draft_id=draft.id,
                ghost_id=ghost_post_id,
                ghost_url=ghost_url,
                title=draft.title,
            )
            
            logger.info(f"Draft published successfully: {ghost_url}")
            
            return {
                "status": "ok",
                "draft_id": draft_id,
                "ghost_post_id": ghost_post_id,
                "ghost_url": ghost_url,
                "slug": published.get("slug"),
                "published_at": draft.published_at.isoformat(),
            }
    
    except Exception as e:
        logger.error(f"Failed to publish draft {draft_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish to Ghost: {str(e)}",
        )
