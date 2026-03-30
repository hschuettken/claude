"""
Memora Transcription & Meeting Intelligence Service.

Provides:
  - Real-time audio transcription using faster-whisper (port 8071)
  - Meeting intelligence extraction: action items, decisions, risks, questions
  - Auto-extraction of insights from meeting transcripts
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from transcriber import TranscriberService, TranscriptionResult
from meeting_intelligence import (
    ActionItem,
    Decision,
    MeetingIntelligenceResult,
    MeetingIntelligenceService,
    OpenQuestion,
    Risk,
)
from semantic_search import (
    SemanticSearchService,
    SemanticSearchResponse,
    KeywordSearchResponse,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Memora Service",
    description="Transcription and meeting intelligence extraction",
    version="2.0.0",
)

# Global service instances
transcriber: Optional[TranscriberService] = None
meeting_intelligence: Optional[MeetingIntelligenceService] = None
semantic_search: Optional[SemanticSearchService] = None

# Request/Response models
class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    model_loaded: bool


class TranscribeResponse(BaseModel):
    """Transcription response."""
    success: bool
    text: str | None = None
    segments: list[dict] | None = None
    language: str | None = None
    duration_seconds: float | None = None
    error: str | None = None


class ExtractIntelligenceResponse(BaseModel):
    """Meeting intelligence extraction response."""
    success: bool
    result: MeetingIntelligenceResult | None = None
    error: str | None = None


class ExtractItemsResponse(BaseModel):
    """Action items extraction response."""
    success: bool
    items: list[ActionItem] | None = None
    count: int = 0
    error: str | None = None


class ExtractDecisionsResponse(BaseModel):
    """Decisions extraction response."""
    success: bool
    decisions: list[Decision] | None = None
    count: int = 0
    error: str | None = None


class ExtractQuestionsResponse(BaseModel):
    """Open questions extraction response."""
    success: bool
    questions: list[OpenQuestion] | None = None
    count: int = 0
    error: str | None = None


class ExtractRisksResponse(BaseModel):
    """Risks extraction response."""
    success: bool
    risks: list[Risk] | None = None
    count: int = 0
    error: str | None = None


@app.on_event("startup")
async def startup_event():
    """Initialize transcriber and meeting intelligence on startup."""
    global transcriber, meeting_intelligence
    try:
        logger.info("Initializing Memora Services...")
        model_name = os.getenv("WHISPER_MODEL", "base")
        device = os.getenv("WHISPER_DEVICE", "auto")
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "default")

        logger.info(f"Loading whisper model: {model_name} (device={device}, compute_type={compute_type})")
        transcriber = TranscriberService(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
        )
        logger.info("Transcription Service initialized successfully")
        
        # Initialize meeting intelligence service
        logger.info("Initializing Meeting Intelligence Service...")
        meeting_intelligence = MeetingIntelligenceService()
        logger.info("Meeting Intelligence Service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global transcriber, meeting_intelligence
    if transcriber or meeting_intelligence:
        logger.info("Shutting down Memora Services")
        transcriber = None
        meeting_intelligence = None


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns service status and whether models are loaded.
    """
    return HealthResponse(
        status="healthy" if transcriber and meeting_intelligence else "initializing",
        service="memora",
        version="2.0.0",
        model_loaded=transcriber is not None and meeting_intelligence is not None,
    )


@app.post("/transcribe", response_model=TranscribeResponse, tags=["transcription"])
async def transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = None,
) -> TranscribeResponse:
    """
    Transcribe audio file to text.
    
    Supports common audio formats: mp3, wav, flac, ogg, etc.
    
    Args:
        file: Audio file (multipart/form-data)
        language: Optional language code (e.g., 'en', 'de'). Auto-detected if omitted.
    
    Returns:
        TranscribeResponse with transcription text and metadata
    """
    if not transcriber:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transcriber not initialized",
        )

    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required",
        )

    try:
        # Read file into memory
        content = await file.read()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty",
            )

        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".audio") as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            # Transcribe in background to avoid blocking
            logger.info(f"Transcribing file: {file.filename} ({len(content)} bytes)")
            result: TranscriptionResult = await asyncio.to_thread(
                transcriber.transcribe,
                tmp_path,
                language,
            )

            logger.info(f"Transcription successful: {len(result.text)} chars, language={result.language}")
            return TranscribeResponse(
                success=True,
                text=result.text,
                segments=result.segments,
                language=result.language,
                duration_seconds=result.duration_seconds,
            )

        finally:
            # Clean up temp file
            try:
                os.unlink(tmp_path)
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {tmp_path}: {e}")

    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return TranscribeResponse(
            success=False,
            error=str(e),
        )


@app.post(
    "/extract_intelligence",
    response_model=ExtractIntelligenceResponse,
    tags=["meeting_intelligence"],
)
async def extract_intelligence(
    transcript: str,
    meeting_id: str = "default",
    language: str = "en",
    duration_seconds: Optional[float] = None,
) -> ExtractIntelligenceResponse:
    """
    Extract all intelligence from meeting transcript.
    
    Extracts action items, decisions, open questions, and risks.
    Stores as linked artifacts.
    
    Args:
        transcript: Meeting transcript text
        meeting_id: Unique meeting identifier
        language: Transcript language (default: en)
        duration_seconds: Meeting duration in seconds
    
    Returns:
        ExtractIntelligenceResponse with complete MeetingIntelligenceResult
    """
    if not meeting_intelligence:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meeting Intelligence Service not initialized",
        )

    if not transcript or len(transcript.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is required and must be at least 10 characters",
        )

    try:
        logger.info(f"Extracting intelligence from meeting {meeting_id}")
        result = meeting_intelligence.extract_all(
            transcript=transcript,
            meeting_id=meeting_id,
            language=language,
            duration_seconds=duration_seconds,
        )
        logger.info(f"Intelligence extraction complete for {meeting_id}")
        return ExtractIntelligenceResponse(success=True, result=result)
    except Exception as e:
        logger.error(f"Intelligence extraction failed: {e}", exc_info=True)
        return ExtractIntelligenceResponse(success=False, error=str(e))


@app.post(
    "/extract_action_items",
    response_model=ExtractItemsResponse,
    tags=["meeting_intelligence"],
)
async def extract_action_items(
    transcript: str,
    meeting_id: str = "default",
) -> ExtractItemsResponse:
    """
    Extract action items from meeting transcript.
    
    Looks for patterns like: "I will...", "We need to...", "Action item:"
    Identifies owner and due date when present.
    
    Args:
        transcript: Meeting transcript text
        meeting_id: Unique meeting identifier
    
    Returns:
        ExtractItemsResponse with list of ActionItem objects
    """
    if not meeting_intelligence:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meeting Intelligence Service not initialized",
        )

    if not transcript or len(transcript.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is required and must be at least 10 characters",
        )

    try:
        logger.info(f"Extracting action items from {meeting_id}")
        items = meeting_intelligence.extract_action_items(transcript)
        logger.info(f"Extracted {len(items)} action items")
        return ExtractItemsResponse(success=True, items=items, count=len(items))
    except Exception as e:
        logger.error(f"Action item extraction failed: {e}", exc_info=True)
        return ExtractItemsResponse(success=False, error=str(e))


@app.post(
    "/extract_decisions",
    response_model=ExtractDecisionsResponse,
    tags=["meeting_intelligence"],
)
async def extract_decisions(
    transcript: str,
    meeting_id: str = "default",
) -> ExtractDecisionsResponse:
    """
    Extract decisions from meeting transcript.
    
    Looks for patterns like: "We decided...", "We agreed...", "Decision:"
    Includes rationale when available.
    
    Args:
        transcript: Meeting transcript text
        meeting_id: Unique meeting identifier
    
    Returns:
        ExtractDecisionsResponse with list of Decision objects
    """
    if not meeting_intelligence:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meeting Intelligence Service not initialized",
        )

    if not transcript or len(transcript.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is required and must be at least 10 characters",
        )

    try:
        logger.info(f"Extracting decisions from {meeting_id}")
        decisions = meeting_intelligence.extract_decisions(transcript)
        logger.info(f"Extracted {len(decisions)} decisions")
        return ExtractDecisionsResponse(
            success=True, decisions=decisions, count=len(decisions)
        )
    except Exception as e:
        logger.error(f"Decision extraction failed: {e}", exc_info=True)
        return ExtractDecisionsResponse(success=False, error=str(e))


@app.post(
    "/extract_questions",
    response_model=ExtractQuestionsResponse,
    tags=["meeting_intelligence"],
)
async def extract_questions(
    transcript: str,
    meeting_id: str = "default",
) -> ExtractQuestionsResponse:
    """
    Extract open questions from meeting transcript.
    
    Looks for patterns like: "What...", "How...", "Question:", "We need to clarify..."
    
    Args:
        transcript: Meeting transcript text
        meeting_id: Unique meeting identifier
    
    Returns:
        ExtractQuestionsResponse with list of OpenQuestion objects
    """
    if not meeting_intelligence:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meeting Intelligence Service not initialized",
        )

    if not transcript or len(transcript.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is required and must be at least 10 characters",
        )

    try:
        logger.info(f"Extracting questions from {meeting_id}")
        questions = meeting_intelligence.extract_open_questions(transcript)
        logger.info(f"Extracted {len(questions)} open questions")
        return ExtractQuestionsResponse(
            success=True, questions=questions, count=len(questions)
        )
    except Exception as e:
        logger.error(f"Question extraction failed: {e}", exc_info=True)
        return ExtractQuestionsResponse(success=False, error=str(e))


@app.post(
    "/extract_risks",
    response_model=ExtractRisksResponse,
    tags=["meeting_intelligence"],
)
async def extract_risks(
    transcript: str,
    meeting_id: str = "default",
) -> ExtractRisksResponse:
    """
    Extract risks from meeting transcript.
    
    Looks for patterns like: "Risk:", "Concern:", "Could fail", "Blocker:", "Dependency on..."
    Assesses severity (low, medium, high, critical).
    
    Args:
        transcript: Meeting transcript text
        meeting_id: Unique meeting identifier
    
    Returns:
        ExtractRisksResponse with list of Risk objects
    """
    if not meeting_intelligence:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meeting Intelligence Service not initialized",
        )

    if not transcript or len(transcript.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript is required and must be at least 10 characters",
        )

    try:
        logger.info(f"Extracting risks from {meeting_id}")
        risks = meeting_intelligence.extract_risks(transcript)
        logger.info(f"Extracted {len(risks)} risks")
        return ExtractRisksResponse(success=True, risks=risks, count=len(risks))
    except Exception as e:
        logger.error(f"Risk extraction failed: {e}", exc_info=True)
        return ExtractRisksResponse(success=False, error=str(e))


@app.get("/", tags=["info"])
async def root():
    """Service info endpoint."""
    return {
        "service": "memora",
        "version": "2.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "transcribe": "/transcribe",
            "extract_intelligence": "/extract_intelligence",
            "extract_action_items": "/extract_action_items",
            "extract_decisions": "/extract_decisions",
            "extract_questions": "/extract_questions",
            "extract_risks": "/extract_risks",
            "docs": "/docs",
        },
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8071"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting Memora Service on {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
