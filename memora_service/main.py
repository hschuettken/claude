"""
Memora Transcription Service — Standalone microservice for audio transcription.

Provides real-time audio transcription using faster-whisper.
Runs on port 8071.

Endpoints:
  POST /transcribe — async file upload transcription
  GET  /health    — health check
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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Memora Transcription Service",
    description="Real-time audio transcription using faster-whisper",
    version="1.0.0",
)

# Global transcriber instance
transcriber: Optional[TranscriberService] = None

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


@app.on_event("startup")
async def startup_event():
    """Initialize transcriber on startup."""
    global transcriber
    try:
        logger.info("Initializing Memora Transcription Service...")
        model_name = os.getenv("WHISPER_MODEL", "base")
        device = os.getenv("WHISPER_DEVICE", "auto")
        compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "default")

        logger.info(f"Loading whisper model: {model_name} (device={device}, compute_type={compute_type})")
        transcriber = TranscriberService(
            model_name=model_name,
            device=device,
            compute_type=compute_type,
        )
        logger.info("Memora Transcription Service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize transcriber: {e}", exc_info=True)
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    global transcriber
    if transcriber:
        logger.info("Shutting down Memora Transcription Service")
        transcriber = None


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns service status and whether model is loaded.
    """
    return HealthResponse(
        status="healthy" if transcriber else "initializing",
        service="memora-transcription",
        version="1.0.0",
        model_loaded=transcriber is not None,
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

    logger.info(f"Starting Memora Transcription Service on {host}:{port}")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
