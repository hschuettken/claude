"""Publish endpoints for Ghost CMS integration."""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ghost_client import get_ghost_client, GhostAdminClient
from database import get_db
from models import Draft, BlogPost, PerformanceSnapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/marketing/publish", tags=["publish"])


class PublishRequest(BaseModel):
    """Request model for publishing a draft."""
    tags: Optional[list[str]] = Field(default_factory=list, description="Tags for the Ghost post")
    featured_image: Optional[str] = None
    custom_excerpt: Optional[str] = None


class ScheduleRequest(BaseModel):
    """Request model for scheduling a draft."""
    publish_at: str = Field(..., description="ISO 8601 timestamp for scheduled publish")
    tags: Optional[list[str]] = Field(default_factory=list)
    featured_image: Optional[str] = None
    custom_excerpt: Optional[str] = None


class PublishResponse(BaseModel):
    """Response model for publish action."""
    success: bool
    draft_id: int
    ghost_post_id: str
    ghost_url: str
    slug: str
    status: str


@router.post("/{draft_id}", response_model=PublishResponse, status_code=200)
async def publish_draft(
    draft_id: int,
    req: PublishRequest,
    db: Session = Depends(get_db),
):
    """
    Publish an approved draft to Ghost CMS.
    
    - Validates draft status is 'approved'
    - Creates post in Ghost with status='published'
    - Stores ghost_post_id in BlogPost record
    - Updates draft status to 'published'
    - Returns Ghost post details
    """
    # Get draft from DB
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    # Validate status
    if draft.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Draft must be 'approved' to publish. Current status: {draft.status}"
        )
    
    # Create Ghost post
    ghost_client = get_ghost_client()
    try:
        # Convert title to slug if not provided
        slug = (draft.title or "untitled").lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        
        logger.info(f"Publishing draft {draft_id} to Ghost with slug: {slug}")
        
        ghost_post = await ghost_client.create_post(
            title=draft.title,
            html=draft.content,
            status="published",
            tags=req.tags,
            feature_image=req.featured_image,
            custom_excerpt=req.custom_excerpt or (draft.seo_meta.get("description") if draft.seo_meta else None),
        )
        
        ghost_post_id = ghost_post.get("id")
        if not ghost_post_id:
            raise ValueError("Ghost API did not return post ID")
        
        # Store in BlogPost table
        blog_post = BlogPost(
            draft_id=draft_id,
            ghost_post_id=ghost_post_id,
            published_at=datetime.utcnow(),
            slug=ghost_post.get("slug", slug),
            tags=",".join(req.tags) if req.tags else None,
        )
        db.add(blog_post)
        
        # Update draft status
        draft.status = "published"
        db.commit()
        db.refresh(draft)
        db.refresh(blog_post)
        
        # Construct Ghost URL
        from config import settings
        ghost_url = f"{settings.ghost_url}/{ghost_post.get('slug', slug)}"
        
        logger.info(f"Successfully published draft {draft_id} to Ghost: {ghost_url}")
        
        # Publish post.published NATS event (graceful — don't let this fail the request)
        try:
            from app.events.publishers import publish_post_published
            await publish_post_published(
                post_id=str(blog_post.id),
                title=draft.title or "",
                url=ghost_url,
                published_at=blog_post.published_at or datetime.utcnow(),
                draft_id=str(draft_id),
            )
        except Exception as e:
            logger.warning(f"Failed to publish post.published NATS event: {e}")
        
        return PublishResponse(
            success=True,
            draft_id=draft_id,
            ghost_post_id=ghost_post_id,
            ghost_url=ghost_url,
            slug=ghost_post.get("slug", slug),
            status="published",
        )
        
    except Exception as e:
        logger.error(f"Failed to publish draft {draft_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish to Ghost: {str(e)}"
        )
    finally:
        await ghost_client.close()


@router.post("/{draft_id}/schedule", response_model=PublishResponse, status_code=200)
async def schedule_draft(
    draft_id: int,
    req: ScheduleRequest,
    db: Session = Depends(get_db),
):
    """
    Schedule a draft for future publication to Ghost CMS.
    
    - Validates draft status is 'approved'
    - Parses publish_at timestamp (ISO 8601)
    - Creates post in Ghost with status='scheduled'
    - Stores ghost_post_id in BlogPost record
    - Updates draft status to 'scheduled'
    """
    # Get draft from DB
    draft = db.query(Draft).filter(Draft.id == draft_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    # Validate status
    if draft.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Draft must be 'approved' to schedule. Current status: {draft.status}"
        )
    
    # Parse publish_at timestamp
    try:
        publish_at_dt = datetime.fromisoformat(req.publish_at.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid ISO 8601 timestamp: {str(e)}"
        )
    
    # Create Ghost scheduled post
    ghost_client = get_ghost_client()
    try:
        slug = (draft.title or "untitled").lower().replace(" ", "-").replace("_", "-")
        slug = "".join(c for c in slug if c.isalnum() or c == "-")
        
        logger.info(f"Scheduling draft {draft_id} for {req.publish_at}")
        
        ghost_post = await ghost_client.create_post(
            title=draft.title,
            html=draft.content,
            status="scheduled",
            tags=req.tags,
            feature_image=req.featured_image,
            custom_excerpt=req.custom_excerpt or (draft.seo_meta.get("description") if draft.seo_meta else None),
        )
        
        ghost_post_id = ghost_post.get("id")
        if not ghost_post_id:
            raise ValueError("Ghost API did not return post ID")
        
        # Store in BlogPost table with scheduled status
        blog_post = BlogPost(
            draft_id=draft_id,
            ghost_post_id=ghost_post_id,
            published_at=publish_at_dt,  # Use scheduled time
            slug=ghost_post.get("slug", slug),
            tags=",".join(req.tags) if req.tags else None,
        )
        db.add(blog_post)
        
        # Update draft status
        draft.status = "scheduled"
        db.commit()
        db.refresh(draft)
        db.refresh(blog_post)
        
        # Construct Ghost URL
        from config import settings
        ghost_url = f"{settings.ghost_url}/{ghost_post.get('slug', slug)}"
        
        logger.info(f"Successfully scheduled draft {draft_id} for {req.publish_at}: {ghost_url}")
        
        return PublishResponse(
            success=True,
            draft_id=draft_id,
            ghost_post_id=ghost_post_id,
            ghost_url=ghost_url,
            slug=ghost_post.get("slug", slug),
            status="scheduled",
        )
        
    except Exception as e:
        logger.error(f"Failed to schedule draft {draft_id}: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to schedule on Ghost: {str(e)}"
        )
    finally:
        await ghost_client.close()


class PerformanceUpdateRequest(BaseModel):
    """Request model for recording post performance."""
    platform: str = Field(..., description="Platform: blog or linkedin")
    views: int = Field(default=0, ge=0)
    engagement_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class PerformanceUpdateResponse(BaseModel):
    """Response model for performance update."""
    snapshot_id: int
    post_id: int
    platform: str
    views: int
    engagement_rate: float
    recorded_at: str


@router.post("/{post_id}/performance", response_model=PerformanceUpdateResponse, status_code=201)
async def record_performance(
    post_id: int,
    req: PerformanceUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Record performance metrics for a published post.
    
    - Validates post exists
    - Stores PerformanceSnapshot
    - Publishes performance.updated NATS event
    """
    # Validate blog post exists
    blog_post = db.query(BlogPost).filter(BlogPost.id == post_id).first()
    if not blog_post:
        raise HTTPException(status_code=404, detail="Blog post not found")
    
    recorded_at = datetime.utcnow()
    
    # Store snapshot
    snapshot = PerformanceSnapshot(
        post_id=post_id,
        platform=req.platform,
        views=req.views,
        engagement_rate=req.engagement_rate,
        recorded_at=recorded_at,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    
    logger.info(f"Performance snapshot {snapshot.id} recorded for post {post_id}: views={req.views}, engagement={req.engagement_rate}")
    
    # Publish performance.updated NATS event (graceful)
    try:
        from app.events.publishers import publish_performance_updated
        await publish_performance_updated(
            post_id=str(post_id),
            platform=req.platform,
            views=req.views,
            engagement_rate=req.engagement_rate,
            recorded_at=recorded_at,
            snapshot_id=str(snapshot.id),
        )
    except Exception as e:
        logger.warning(f"Failed to publish performance.updated NATS event: {e}")
    
    return PerformanceUpdateResponse(
        snapshot_id=snapshot.id,
        post_id=post_id,
        platform=req.platform,
        views=req.views,
        engagement_rate=req.engagement_rate,
        recorded_at=recorded_at.isoformat(),
    )
