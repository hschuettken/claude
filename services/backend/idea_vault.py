"""
Idea Vault Service — Quick capture with voice, OCR, and auto-classification.

Features:
  - Quick text capture with floating widget (keyboard shortcut `q`)
  - Voice-to-text transcription (WebRTC/Web Speech API → backend)
  - Screenshot OCR (client-side Canvas → POST → Tesseract/LLM)
  - Auto-classification by pillar (idea/task/decision/routine/insight)
  - Save-for-later cards with metadata

This service bridges frontend capture UI with backend processing.
"""

import json
import logging
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class CaptureType(str, Enum):
    """Capture type classification."""
    IDEA = "idea"
    TASK = "task"
    DECISION = "decision"
    ROUTINE = "routine"
    INSIGHT = "insight"


class PillarTag(str, Enum):
    """Content pillar for auto-classification."""
    PERSONAL = "personal"
    PROFESSIONAL = "professional"
    CREATIVE = "creative"
    LEARNING = "learning"
    HEALTH = "health"
    FINANCE = "finance"
    RELATIONSHIP = "relationship"
    LIFESTYLE = "lifestyle"


class CaptureRequest(BaseModel):
    """User-initiated capture request."""
    text: str = Field(..., description="Main capture text")
    title: Optional[str] = Field(None, description="Optional title")
    source: str = Field(default="web", description="Source: web/mobile/voice/screenshot")
    voice_transcript: Optional[str] = Field(None, description="Transcribed voice text")
    screenshot_ocr: Optional[str] = Field(None, description="Extracted OCR text from screenshot")
    current_url: Optional[str] = Field(None, description="Current page URL for context")
    current_project_id: Optional[str] = Field(None, description="Current project UUID")
    current_goal_id: Optional[str] = Field(None, description="Current goal UUID")
    metadata: Optional[dict] = Field(default_factory=dict, description="Additional metadata")


class CaptureResponse(BaseModel):
    """Response after capture submission."""
    capture_id: str = Field(..., description="Unique capture ID")
    detected_type: CaptureType = Field(..., description="Auto-detected capture type")
    detected_pillars: list[PillarTag] = Field(..., description="Auto-detected pillars")
    status: str = Field(default="processing", description="Processing status")
    timestamp: str = Field(..., description="Capture timestamp (ISO 8601)")
    confidence: float = Field(..., description="Classification confidence (0.0-1.0)")


class IdeaCard(BaseModel):
    """A saved idea card with metadata."""
    card_id: str = Field(..., description="Unique card ID")
    title: str = Field(..., description="Card title")
    content: str = Field(..., description="Card content")
    capture_type: CaptureType = Field(..., description="Capture type")
    pillars: list[PillarTag] = Field(..., description="Assigned pillars")
    created_at: str = Field(..., description="Creation timestamp (ISO 8601)")
    updated_at: str = Field(..., description="Last update timestamp (ISO 8601)")
    saved: bool = Field(default=False, description="Whether saved to vault")
    source: str = Field(default="web", description="Source: web/voice/screenshot")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    tags: list[str] = Field(default_factory=list, description="User-assigned tags")


class IdeaVaultStats(BaseModel):
    """Statistics for the idea vault."""
    total_captures: int = Field(..., description="Total captures")
    saved_cards: int = Field(..., description="Saved idea cards")
    by_type: dict[str, int] = Field(..., description="Count by capture type")
    by_pillar: dict[str, int] = Field(..., description="Count by pillar")
    this_week: int = Field(..., description="Captures this week")


# ============================================================================
# Type Detection Logic
# ============================================================================

CAPTURE_TYPE_KEYWORDS = {
    CaptureType.TASK: ["do", "implement", "complete", "finish", "need to", "build", "fix", "create", "make"],
    CaptureType.DECISION: ["should", "which", "choice", "decide", "choose", "best", "option"],
    CaptureType.ROUTINE: ["daily", "recurring", "schedule", "habit", "every", "morning", "evening", "weekly"],
    CaptureType.INSIGHT: ["realize", "understand", "insight", "learned", "discovered", "pattern", "note that"],
}

PILLAR_KEYWORDS = {
    PillarTag.PERSONAL: ["personal", "self", "life", "growth", "myself", "private"],
    PillarTag.PROFESSIONAL: ["work", "job", "career", "project", "team", "professional", "business"],
    PillarTag.CREATIVE: ["create", "design", "art", "music", "write", "creative", "build"],
    PillarTag.LEARNING: ["learn", "study", "course", "book", "skill", "knowledge", "training"],
    PillarTag.HEALTH: ["health", "fitness", "exercise", "diet", "sleep", "wellness", "medical"],
    PillarTag.FINANCE: ["money", "budget", "invest", "finance", "savings", "spend", "cost"],
    PillarTag.RELATIONSHIP: ["friend", "family", "partner", "love", "social", "relationship", "people"],
    PillarTag.LIFESTYLE: ["travel", "lifestyle", "hobby", "enjoy", "fun", "experience", "adventure"],
}


class IdeaVaultService:
    """Service for capturing, classifying, and managing ideas."""

    @staticmethod
    def detect_capture_type(text: str) -> tuple[CaptureType, float]:
        """
        Detect capture type using keyword heuristics.
        
        Args:
            text: Capture text to classify
            
        Returns:
            (detected_type, confidence)
        """
        text_lower = text.lower()
        scores = {cap_type: 0 for cap_type in CaptureType}

        # Keyword scoring
        for cap_type, keywords in CAPTURE_TYPE_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    scores[cap_type] += 1

        # Normalize scores to confidence
        max_score = max(scores.values()) if scores.values() else 0
        if max_score == 0:
            # Default to IDEA if no keywords match
            return CaptureType.IDEA, 0.5

        best_type = max(scores, key=scores.get)
        confidence = min(max_score / 3.0, 1.0)  # Normalize to 0-1 range
        return best_type, confidence

    @staticmethod
    def detect_pillars(text: str) -> list[PillarTag]:
        """
        Detect pillars from capture text.
        
        Args:
            text: Capture text to classify
            
        Returns:
            List of detected pillars
        """
        text_lower = text.lower()
        detected = []

        for pillar, keywords in PILLAR_KEYWORDS.items():
            for keyword in keywords:
                if keyword in text_lower:
                    detected.append(pillar)
                    break  # Only add once per pillar

        # Return unique pillars, default to PERSONAL if none detected
        return list(set(detected)) if detected else [PillarTag.PERSONAL]

    @classmethod
    def create_capture_response(
        cls,
        capture_id: str,
        text: str,
    ) -> CaptureResponse:
        """
        Create a capture response with auto-detected type and pillars.
        
        Args:
            capture_id: Unique ID for this capture
            text: Capture text
            
        Returns:
            CaptureResponse with classification
        """
        detected_type, confidence = cls.detect_capture_type(text)
        pillars = cls.detect_pillars(text)

        return CaptureResponse(
            capture_id=capture_id,
            detected_type=detected_type,
            detected_pillars=pillars,
            status="processing",
            timestamp=datetime.utcnow().isoformat() + "Z",
            confidence=confidence,
        )

    @staticmethod
    def create_idea_card(
        card_id: str,
        title: str,
        content: str,
        capture_type: CaptureType,
        pillars: list[PillarTag],
        source: str = "web",
        metadata: Optional[dict] = None,
    ) -> IdeaCard:
        """
        Create an idea card.
        
        Args:
            card_id: Unique card ID
            title: Card title
            content: Card content
            capture_type: Type of capture
            pillars: List of pillars
            source: Source of capture
            metadata: Optional metadata
            
        Returns:
            IdeaCard instance
        """
        now = datetime.utcnow().isoformat() + "Z"
        return IdeaCard(
            card_id=card_id,
            title=title or "Untitled",
            content=content,
            capture_type=capture_type,
            pillars=pillars,
            created_at=now,
            updated_at=now,
            source=source,
            metadata=metadata or {},
        )


# ============================================================================
# Export for use in main.py
# ============================================================================

__all__ = [
    "IdeaVaultService",
    "CaptureRequest",
    "CaptureResponse",
    "IdeaCard",
    "IdeaVaultStats",
    "CaptureType",
    "PillarTag",
]
