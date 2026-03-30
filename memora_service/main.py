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
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel
import pathlib

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


class ClassifyContentResponse(BaseModel):
    """Content classification response."""
    success: bool
    classification: str | None = None  # idea, task, note, meeting
    confidence: float = 0.0
    reasoning: str | None = None
    error: str | None = None


@app.on_event("startup")
async def startup_event():
    """Initialize transcriber, meeting intelligence, and semantic search on startup."""
    global transcriber, meeting_intelligence, semantic_search
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
        
        # Initialize semantic search service
        logger.info("Initializing Semantic Search Service...")
        embedding_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        persist_dir = os.getenv("CHROMADB_PERSIST_DIR", None)
        semantic_search = SemanticSearchService(
            model_name=embedding_model,
            persist_directory=persist_dir,
        )
        logger.info("Semantic Search Service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global transcriber, meeting_intelligence, semantic_search
    if transcriber or meeting_intelligence or semantic_search:
        logger.info("Shutting down Memora Services")
        transcriber = None
        meeting_intelligence = None
        semantic_search = None


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


@app.post("/classify", response_model=ClassifyContentResponse, tags=["classification"])
async def classify_content(
    text: str,
    context: Optional[str] = None,
) -> ClassifyContentResponse:
    """
    Classify transcribed content into: idea, task, note, or meeting.
    
    Uses heuristics and keyword patterns to determine the best classification.
    
    Args:
        text: The transcribed text to classify
        context: Optional context about when/where the recording was made
    
    Returns:
        ClassifyContentResponse with classification type and confidence score
    """
    if not text or len(text.strip()) < 5:
        return ClassifyContentResponse(
            success=False,
            error="Text is required and must be at least 5 characters"
        )
    
    try:
        text_lower = text.lower()
        
        # Classification heuristics
        idea_indicators = [
            "what if", "could", "might be", "imagine", "brainstorm", "idea",
            "concept", "think about", "consider", "possible", "maybe",
            "thoughts", "wondering", "potentially", "theory", "hypothesis"
        ]
        
        task_indicators = [
            "need to", "must", "should", "have to", "todo", "action",
            "implement", "fix", "build", "create", "setup", "deploy",
            "release", "schedule", "deadline", "owner", "assigned",
            "ticket", "issue", "bug", "feature", "done", "complete",
            "finish", "resolve", "update", "review", "approve"
        ]
        
        meeting_indicators = [
            "decided", "agreed", "discussed", "meeting", "sync", "standup",
            "review", "retrospective", "planning", "sprint", "team",
            "participant", "attendee", "notes", "minute", "agenda",
            "action item", "decision", "risk", "next step", "follow up"
        ]
        
        note_indicators = [
            "remember", "note", "important", "key point", "highlight",
            "observation", "remark", "comment", "thought", "insight",
            "reminder", "don't forget", "keep in mind", "fyi"
        ]
        
        # Count indicator matches
        idea_count = sum(1 for ind in idea_indicators if ind in text_lower)
        task_count = sum(1 for ind in task_indicators if ind in text_lower)
        meeting_count = sum(1 for ind in meeting_indicators if ind in text_lower)
        note_count = sum(1 for ind in note_indicators if ind in text_lower)
        
        # Additional heuristics
        # If text contains multiple speakers or timestamps, likely a meeting
        if (":" in text and text.count(":") > 3) or "said" in text_lower or "speaker" in text_lower:
            meeting_count += 5
        
        # If text is very short, likely a note
        if len(text) < 100:
            note_count += 2
        
        # Determine dominant classification
        scores = {
            "idea": idea_count,
            "task": task_count,
            "meeting": meeting_count,
            "note": note_count,
        }
        
        best_classification = max(scores, key=scores.get)
        best_score = scores[best_classification]
        total_score = sum(scores.values())
        
        # Calculate confidence (0-1)
        if total_score > 0:
            confidence = best_score / (total_score + 1)
        else:
            # Default to "note" if no strong signals
            best_classification = "note"
            confidence = 0.5
        
        reasoning = (
            f"Detected {best_classification} with {best_score} indicator matches. "
            f"Pattern distribution: idea={scores['idea']}, task={scores['task']}, "
            f"meeting={scores['meeting']}, note={scores['note']}"
        )
        
        logger.info(f"Classified text as '{best_classification}' (confidence: {confidence:.2f})")
        
        return ClassifyContentResponse(
            success=True,
            classification=best_classification,
            confidence=min(confidence, 1.0),
            reasoning=reasoning,
        )
    
    except Exception as e:
        logger.error(f"Classification failed: {e}", exc_info=True)
        return ClassifyContentResponse(success=False, error=str(e))


@app.post("/search/semantic", response_model=SemanticSearchResponse, tags=["search"])
async def semantic_search_endpoint(
    query: str,
    source_type: Optional[str] = None,
    top_k: int = 5,
) -> SemanticSearchResponse:
    """
    Perform semantic search across pages and meeting transcripts.
    
    Uses sentence-transformer embeddings and ChromaDB for vector similarity search.
    
    Args:
        query: Search query string (e.g., "budget planning", "resource allocation")
        source_type: Optional filter - 'page' or 'transcript'. If None, search both.
        top_k: Number of results to return (default 5, max 20)
    
    Returns:
        SemanticSearchResponse with ranked results by semantic similarity (0-1 score)
    
    Example:
        POST /search/semantic?query=budget%20allocation&source_type=transcript&top_k=3
    """
    if not semantic_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic Search Service not initialized",
        )

    if not query or len(query.strip()) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query is required and must be at least 2 characters",
        )

    if source_type and source_type not in ["page", "transcript"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_type must be 'page' or 'transcript'",
        )

    top_k = max(1, min(top_k, 20))  # Clamp to [1, 20]

    try:
        logger.info(f"Semantic search: '{query}' (source_type={source_type}, top_k={top_k})")
        result = semantic_search.semantic_search(
            query=query,
            source_type=source_type,
            top_k=top_k,
        )
        logger.info(f"Semantic search returned {result.count} results")
        return result
    except Exception as e:
        logger.error(f"Semantic search failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Semantic search failed: {str(e)}",
        )


@app.post("/search/keyword", response_model=KeywordSearchResponse, tags=["search"])
async def keyword_search_endpoint(
    query: str,
    source_type: Optional[str] = None,
    top_k: int = 5,
) -> KeywordSearchResponse:
    """
    Perform keyword-based search across pages and meeting transcripts.
    
    Uses simple substring/word matching to find relevant content.
    
    Args:
        query: Search query string (whitespace-separated words)
        source_type: Optional filter - 'page' or 'transcript'. If None, search both.
        top_k: Number of results to return (default 5, max 20)
    
    Returns:
        KeywordSearchResponse with ranked results by match count
    
    Example:
        POST /search/keyword?query=action%20items&source_type=transcript&top_k=5
    """
    if not semantic_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic Search Service not initialized",
        )

    if not query or len(query.strip()) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query is required and must be at least 2 characters",
        )

    if source_type and source_type not in ["page", "transcript"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_type must be 'page' or 'transcript'",
        )

    top_k = max(1, min(top_k, 20))  # Clamp to [1, 20]

    try:
        logger.info(f"Keyword search: '{query}' (source_type={source_type}, top_k={top_k})")
        result = semantic_search.keyword_search(
            query=query,
            source_type=source_type,
            top_k=top_k,
        )
        logger.info(f"Keyword search returned {result.count} results")
        return result
    except Exception as e:
        logger.error(f"Keyword search failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Keyword search failed: {str(e)}",
        )


@app.post("/index/page", tags=["indexing"])
async def index_page(
    page_id: str,
    title: str,
    content: str,
    metadata: Optional[dict] = None,
) -> JSONResponse:
    """
    Add a page to the semantic search index.
    
    Args:
        page_id: Unique page identifier
        title: Page title
        content: Full page content
        metadata: Optional metadata dictionary
    
    Returns:
        Success/error response
    """
    if not semantic_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic Search Service not initialized",
        )

    if not page_id or not title or not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="page_id, title, and content are required",
        )

    try:
        logger.info(f"Indexing page {page_id}")
        semantic_search.add_page(
            page_id=page_id,
            title=title,
            content=content,
            metadata=metadata,
        )
        return JSONResponse(
            status_code=200,
            content={"success": True, "message": f"Indexed page {page_id}"},
        )
    except Exception as e:
        logger.error(f"Failed to index page: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index page: {str(e)}",
        )


@app.post("/index/transcript", tags=["indexing"])
async def index_transcript(
    meeting_id: str,
    transcript: str,
    language: str = "en",
    metadata: Optional[dict] = None,
) -> JSONResponse:
    """
    Add a meeting transcript to the semantic search index.
    
    Automatically segments the transcript and creates embeddings for each segment.
    
    Args:
        meeting_id: Unique meeting identifier
        transcript: Full transcript text
        language: Language code (default: 'en')
        metadata: Optional metadata dictionary
    
    Returns:
        Success response with segment count
    """
    if not semantic_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic Search Service not initialized",
        )

    if not meeting_id or not transcript:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="meeting_id and transcript are required",
        )

    if len(transcript.strip()) < 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcript must be at least 20 characters",
        )

    try:
        logger.info(f"Indexing transcript for meeting {meeting_id}")
        segment_count = semantic_search.add_transcript(
            meeting_id=meeting_id,
            transcript=transcript,
            language=language,
            metadata=metadata,
        )
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Indexed {segment_count} segments for meeting {meeting_id}",
                "segment_count": segment_count,
            },
        )
    except Exception as e:
        logger.error(f"Failed to index transcript: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to index transcript: {str(e)}",
        )


@app.get("/search/stats", tags=["search"])
async def search_stats() -> JSONResponse:
    """
    Get semantic search index statistics.
    
    Returns:
        Statistics about indexed pages, transcripts, and embedding model
    """
    if not semantic_search:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Semantic Search Service not initialized",
        )

    try:
        stats = semantic_search.get_stats()
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "stats": stats,
            },
        )
    except Exception as e:
        logger.error(f"Failed to get stats: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stats: {str(e)}",
        )


@app.get("/ui", response_class=HTMLResponse, tags=["ui"])
async def get_ui():
    """
    Serve Memora voice capture UI.
    
    Returns HTML frontend for browser-based voice recording,
    transcription, and classification.
    """
    frontend_path = pathlib.Path(__file__).parent / "frontend.html"
    if not frontend_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Frontend UI not found",
        )
    
    with open(frontend_path, "r") as f:
        return f.read()


@app.get("/", tags=["info"])
async def root():
    """Service info endpoint."""
    return {
        "service": "memora",
        "version": "3.0.0",
        "status": "running",
        "features": [
            "Audio transcription with faster-whisper",
            "Meeting intelligence extraction (action items, decisions, risks, questions)",
            "Semantic search across pages and transcripts (ChromaDB + sentence-transformers)",
            "Keyword-based search",
        ],
        "endpoints": {
            "ui": "/ui",
            "health": "/health",
            "transcribe": "/transcribe",
            "classify": "/classify",
            "extract_intelligence": "/extract_intelligence",
            "extract_action_items": "/extract_action_items",
            "extract_decisions": "/extract_decisions",
            "extract_questions": "/extract_questions",
            "extract_risks": "/extract_risks",
            "search_semantic": "/search/semantic",
            "search_keyword": "/search/keyword",
            "index_page": "/index/page",
            "index_transcript": "/index/transcript",
            "search_stats": "/search/stats",
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
