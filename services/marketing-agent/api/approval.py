"""
Approval workflow API for marketing drafts.

Manages draft status transitions through review→approval→publication pipeline.
Includes Discord notifications, Orbit task creation, and status history tracking.
"""
import os
import logging
from datetime import datetime
from typing import Optional
from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends, HTTPException, status as http_status

from models import MarketingDraft, StatusHistory, ApprovalQueue
from database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(tags=["approval"])

# Discord webhook for notifications (optional)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")


async def _notify_discord(message: str):
    """Send notification to Discord."""
    if not DISCORD_WEBHOOK_URL:
        logger.debug("Discord webhook not configured, skipping notification")
        return
    
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                DISCORD_WEBHOOK_URL,
                json={"content": message},
                timeout=aiohttp.ClientTimeout(total=5),
            )
        logger.debug(f"Discord notification sent: {message[:50]}...")
    except Exception as e:
        logger.warning(f"Failed to send Discord notification: {e}")


async def _create_orbit_task(draft_id: int, title: str, db: AsyncSession):
    """Create a corresponding Orbit task for review."""
    try:
        # This would integrate with the Orbit service
        # For now, just log it
        logger.info(f"Would create Orbit task for draft {draft_id}: {title}")
        # TODO: Implement actual Orbit API call
    except Exception as e:
        logger.warning(f"Failed to create Orbit task: {e}")


async def _record_status_change(
    draft_id: int,
    from_status: Optional[str],
    to_status: str,
    changed_by: str,
    feedback: Optional[str],
    db: AsyncSession,
):
    """Record status transition in history."""
    history = StatusHistory(
        draft_id=draft_id,
        from_status=from_status,
        to_status=to_status,
        changed_by=changed_by,
        feedback=feedback,
        created_at=datetime.utcnow(),
    )
    db.add(history)
    await db.flush()


@router.post("/drafts/{draft_id}/review")
async def submit_for_review(
    draft_id: int,
    changed_by: str = "system",
    feedback: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Submit draft for review (draft → review)."""
    # Fetch draft
    stmt = select(MarketingDraft).where(MarketingDraft.id == draft_id)
    result = await db.execute(stmt)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if draft.status != "draft":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Can only submit draft status drafts for review, current status: {draft.status}",
        )
    
    # Update draft status
    draft.status = "review"
    draft.updated_at = datetime.utcnow()
    
    # Record status change
    await _record_status_change(
        draft_id=draft_id,
        from_status="draft",
        to_status="review",
        changed_by=changed_by,
        feedback=feedback,
        db=db,
    )
    
    # Create approval queue entry
    queue_entry = ApprovalQueue(
        draft_id=draft_id,
        queued_at=datetime.utcnow(),
        assigned_to="henning",
        orbit_task_id=None,  # TODO: Create Orbit task and store ID
    )
    db.add(queue_entry)
    
    # Create Orbit task
    await _create_orbit_task(
        draft_id=draft_id,
        title=f"Draft pending review: {draft.title}",
        db=db,
    )
    
    # Notify Discord
    await _notify_discord(
        f"📝 Draft pending review: **{draft.title}**\n"
        f"Author: {draft.author or 'Unknown'}\n"
        f"Ready for review: <{os.getenv('NB9OS_URL', 'http://localhost:8080')}/marketing/drafts/{draft_id}>"
    )
    
    await db.commit()
    
    return {
        "id": draft.id,
        "status": draft.status,
        "title": draft.title,
        "message": "Draft submitted for review",
    }


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: int,
    changed_by: str = "henning",
    feedback: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Approve a draft (review → approved)."""
    # Fetch draft
    stmt = select(MarketingDraft).where(MarketingDraft.id == draft_id)
    result = await db.execute(stmt)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if draft.status != "review":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Can only approve drafts in review status, current: {draft.status}",
        )
    
    # Update draft status
    draft.status = "approved"
    draft.updated_at = datetime.utcnow()
    draft.rejection_feedback = None  # Clear any prior rejection feedback
    
    # Record status change
    await _record_status_change(
        draft_id=draft_id,
        from_status="review",
        to_status="approved",
        changed_by=changed_by,
        feedback=feedback,
        db=db,
    )
    
    # Remove from approval queue
    stmt = (
        select(ApprovalQueue)
        .where(ApprovalQueue.draft_id == draft_id)
    )
    result = await db.execute(stmt)
    queue_entry = result.scalar_one_or_none()
    if queue_entry:
        await db.delete(queue_entry)
    
    # Notify Discord
    await _notify_discord(
        f"✅ Draft approved: **{draft.title}**\n"
        f"Approved by: {changed_by}\n"
        f"Status: Ready to schedule or publish"
    )
    
    await db.commit()
    
    return {
        "id": draft.id,
        "status": draft.status,
        "title": draft.title,
        "message": "Draft approved and ready for publication",
    }


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(
    draft_id: int,
    feedback: str,
    changed_by: str = "henning",
    db: AsyncSession = Depends(get_db),
):
    """Reject draft with feedback (review → draft)."""
    if not feedback:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Feedback is required when rejecting a draft",
        )
    
    # Fetch draft
    stmt = select(MarketingDraft).where(MarketingDraft.id == draft_id)
    result = await db.execute(stmt)
    draft = result.scalar_one_or_none()
    
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    if draft.status != "review":
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Can only reject drafts in review status, current: {draft.status}",
        )
    
    # Update draft status
    draft.status = "draft"
    draft.rejection_feedback = feedback
    draft.updated_at = datetime.utcnow()
    
    # Record status change
    await _record_status_change(
        draft_id=draft_id,
        from_status="review",
        to_status="draft",
        changed_by=changed_by,
        feedback=feedback,
        db=db,
    )
    
    # Remove from approval queue
    stmt = (
        select(ApprovalQueue)
        .where(ApprovalQueue.draft_id == draft_id)
    )
    result = await db.execute(stmt)
    queue_entry = result.scalar_one_or_none()
    if queue_entry:
        await db.delete(queue_entry)
    
    # Notify Discord
    await _notify_discord(
        f"❌ Draft rejected: **{draft.title}**\n"
        f"Feedback: {feedback}\n"
        f"Returned to draft for editing"
    )
    
    await db.commit()
    
    return {
        "id": draft.id,
        "status": draft.status,
        "title": draft.title,
        "feedback": feedback,
        "message": "Draft returned to draft status with feedback",
    }


@router.get("/approval-queue")
async def get_approval_queue(
    db: AsyncSession = Depends(get_db),
):
    """Get all drafts pending review."""
    stmt = (
        select(ApprovalQueue, MarketingDraft)
        .join(MarketingDraft)
        .order_by(ApprovalQueue.queued_at.desc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    
    items = [
        {
            "draft_id": row.ApprovalQueue.draft_id,
            "title": row.MarketingDraft.title,
            "queued_at": row.ApprovalQueue.queued_at.isoformat(),
            "assigned_to": row.ApprovalQueue.assigned_to,
            "orbit_task_id": row.ApprovalQueue.orbit_task_id,
        }
        for row in rows
    ]
    
    return {
        "count": len(items),
        "queue": items,
    }


@router.get("/drafts/{draft_id}/history")
async def get_draft_status_history(
    draft_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get status change history for a draft."""
    stmt = (
        select(StatusHistory)
        .where(StatusHistory.draft_id == draft_id)
        .order_by(StatusHistory.created_at.desc())
    )
    result = await db.execute(stmt)
    history = result.scalars().all()
    
    return {
        "draft_id": draft_id,
        "history": [
            {
                "id": h.id,
                "from_status": h.from_status,
                "to_status": h.to_status,
                "changed_by": h.changed_by,
                "feedback": h.feedback,
                "created_at": h.created_at.isoformat(),
            }
            for h in history
        ],
    }
