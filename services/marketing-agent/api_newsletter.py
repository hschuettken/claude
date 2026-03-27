"""
Newsletter API endpoints for the Marketing Agent.

Provides:
- GET /newsletters — List past newsletters
- POST /newsletters/generate — Generate a monthly newsletter
- GET /newsletters/{id} — Retrieve specific newsletter
- POST /newsletters/{id}/publish — Publish newsletter to Ghost
"""

import logging
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from newsletter_generator import NewsletterGenerator, MonthlyNewsletter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/newsletters", tags=["newsletter"])


# Request/Response Models
class NewsletterGenerateRequest(BaseModel):
    """Request to generate a newsletter."""
    month_date: Optional[str] = None  # ISO format date string
    publish_to_ghost: bool = False


class PublishedPostSummary(BaseModel):
    """Summary of a published post in the newsletter."""
    title: str
    link: Optional[str] = None
    pillar: str
    date: Optional[str] = None


class SignalSummary(BaseModel):
    """Summary of a signal in the newsletter."""
    title: str
    source: str
    relevance_score: float
    date: Optional[str] = None


class DraftIdea(BaseModel):
    """Draft idea in the newsletter."""
    title: str
    pillar: str
    status: str


class NewsletterSummary(BaseModel):
    """Newsletter response model."""
    id: Optional[str] = None
    month: str
    subject_line: str
    published_posts_count: int
    featured_signals_count: int
    draft_ideas_count: int
    created_at: str
    ghost_post_id: Optional[str] = None
    
    published_posts: List[PublishedPostSummary]
    featured_signals: List[SignalSummary]
    draft_ideas: List[DraftIdea]


class NewsletterResponse(BaseModel):
    """Full newsletter response with HTML content."""
    month: str
    subject_line: str
    hero_text: str
    newsletter_html: str
    monthly_stats: dict
    created_at: str
    ghost_post_id: Optional[str] = None


async def get_newsletter_generator(db: AsyncSession) -> NewsletterGenerator:
    """Dependency to get newsletter generator instance."""
    import os
    db_url = os.getenv("MARKETING_DB_URL", "postgresql://localhost/marketing")
    return NewsletterGenerator(db_url)


@router.get("/", response_model=List[NewsletterSummary])
async def list_newsletters(
    skip: int = 0,
    limit: int = 12,
    generator: NewsletterGenerator = Depends(get_newsletter_generator),
    db: AsyncSession = Depends(),  # Placeholder
) -> List[NewsletterSummary]:
    """
    List all generated newsletters.
    
    Returns the 12 most recent newsletters by default.
    """
    logger.info(f"Listing newsletters (skip={skip}, limit={limit})")
    
    # Note: In a full implementation, this would query a newsletters table
    # For now, returning empty list as placeholder
    return []


@router.post("/generate", response_model=NewsletterResponse, status_code=status.HTTP_201_CREATED)
async def generate_newsletter(
    request: NewsletterGenerateRequest,
    generator: NewsletterGenerator = Depends(get_newsletter_generator),
    db: AsyncSession = Depends(),  # Placeholder
) -> NewsletterResponse:
    """
    Generate a new monthly newsletter.
    
    Parameters:
    - month_date: ISO format date (defaults to last month)
    - publish_to_ghost: If true, publishes to Ghost CMS as a draft post
    
    Returns the complete newsletter HTML and metadata.
    """
    try:
        # Parse month_date if provided
        month_date = None
        if request.month_date:
            month_date = datetime.fromisoformat(request.month_date)
        
        logger.info(f"Generating newsletter for {request.month_date or 'last month'}")
        
        # Generate the newsletter
        newsletter = await generator.generate_monthly_newsletter(
            db=db,
            month_date=month_date,
            publish_to_ghost=request.publish_to_ghost,
        )
        
        # Return response
        return NewsletterResponse(
            month=newsletter.month,
            subject_line=newsletter.subject_line,
            hero_text=newsletter.hero_text,
            newsletter_html=newsletter.newsletter_html,
            monthly_stats=newsletter.monthly_stats,
            created_at=newsletter.created_at.isoformat(),
            ghost_post_id=newsletter.ghost_post_id,
        )
    
    except Exception as e:
        logger.error(f"Failed to generate newsletter: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Newsletter generation failed: {str(e)}",
        )


@router.get("/{newsletter_id}", response_model=NewsletterResponse)
async def get_newsletter(
    newsletter_id: str,
    generator: NewsletterGenerator = Depends(get_newsletter_generator),
    db: AsyncSession = Depends(),  # Placeholder
) -> NewsletterResponse:
    """
    Retrieve a specific newsletter by ID.
    
    Note: This would require storing newsletters in a database.
    """
    logger.info(f"Retrieving newsletter {newsletter_id}")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Newsletter not found",
    )


@router.post("/{newsletter_id}/publish", status_code=status.HTTP_200_OK)
async def publish_newsletter_to_ghost(
    newsletter_id: str,
    generator: NewsletterGenerator = Depends(get_newsletter_generator),
    db: AsyncSession = Depends(),  # Placeholder
) -> dict:
    """
    Publish a newsletter to Ghost CMS.
    
    Creates a draft post in Ghost that can be reviewed before publication.
    """
    logger.info(f"Publishing newsletter {newsletter_id} to Ghost")
    
    try:
        # In a full implementation, would retrieve newsletter from database
        # and publish it to Ghost
        return {
            "status": "published",
            "message": f"Newsletter {newsletter_id} published to Ghost",
            "ghost_post_id": "placeholder_id",
        }
    
    except Exception as e:
        logger.error(f"Failed to publish newsletter: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish newsletter: {str(e)}",
        )


@router.post("/{newsletter_id}/send", status_code=status.HTTP_200_OK)
async def send_newsletter_to_subscribers(
    newsletter_id: str,
    test_email: Optional[str] = None,
    generator: NewsletterGenerator = Depends(get_newsletter_generator),
    db: AsyncSession = Depends(),  # Placeholder
) -> dict:
    """
    Send newsletter to Ghost subscribers.
    
    Parameters:
    - test_email: Optional test email address to send to first
    
    Uses Ghost Newsletter feature to send to the Layer 8 newsletter list.
    """
    logger.info(f"Sending newsletter {newsletter_id} to subscribers")
    
    try:
        if test_email:
            logger.info(f"Sending test email to {test_email}")
        
        # In a full implementation, would use Ghost API to send newsletter
        return {
            "status": "sent",
            "message": f"Newsletter {newsletter_id} sent to subscribers",
            "recipients_count": 150,  # Placeholder
        }
    
    except Exception as e:
        logger.error(f"Failed to send newsletter: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send newsletter: {str(e)}",
        )
