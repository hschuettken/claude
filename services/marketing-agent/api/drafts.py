"""Marketing drafts and Ghost publishing API."""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from ..models import Draft, DraftStatus, Platform, BlogPost
from ..ghost_client import GhostAdminAPIClient

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


@router.post("", response_model=DraftResponse)
async def create_draft(
    draft: DraftCreate,
    db: AsyncSession,
) -> DraftResponse:
    """Create a new marketing draft."""
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
    
    logger.info(f"Draft created: {new_draft.id} ({draft.title})")
    return DraftResponse.model_validate(new_draft)


@router.get("", response_model=List[DraftResponse])
async def list_drafts(
    db: AsyncSession,
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


@router.get("/{draft_id}", response_model=DraftResponse)
async def get_draft(
    draft_id: int,
    db: AsyncSession,
) -> DraftResponse:
    """Get a single draft by ID."""
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    return DraftResponse.model_validate(draft)


@router.put("/{draft_id}", response_model=DraftResponse)
async def update_draft(
    draft_id: int,
    update: DraftUpdate,
    db: AsyncSession,
) -> DraftResponse:
    """Update a draft."""
    query = select(Draft).where(Draft.id == draft_id)
    result = await db.execute(query)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id} not found")
    
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(draft, key, value)
    
    draft.updated_at = datetime.now(timezone.utc)
    await db.flush()
    
    logger.info(f"Draft updated: {draft_id}")
    return DraftResponse.model_validate(draft)


@router.delete("/{draft_id}")
async def delete_draft(
    draft_id: int,
    db: AsyncSession,
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


@router.post("/{draft_id}/publish", response_model=Dict[str, Any])
async def publish_draft(
    draft_id: int,
    db: AsyncSession,
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
