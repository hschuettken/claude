"""
Backend Service — Core microservice for handling business logic.

Provides REST API with health checks, service status, and modular route structure.
Runs on port 8000.

Endpoints:
  GET  /health    — health check
  GET  /          — service info
  GET  /docs      — OpenAPI documentation
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from idea_vault import (
    IdeaVaultService,
    CaptureRequest,
    CaptureResponse,
    IdeaCard,
    CaptureType,
    PillarTag,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app with documentation
app = FastAPI(
    title="Backend Service",
    description="Core microservice for business logic and API routing",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ============================================================================
# Models
# ============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service health status")
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    timestamp: str = Field(..., description="Response timestamp (ISO 8601)")
    uptime_seconds: float | None = Field(None, description="Seconds since startup")


class ServiceInfo(BaseModel):
    """Service information response."""
    service: str = Field(..., description="Service name")
    version: str = Field(..., description="Service version")
    status: str = Field(..., description="Current status")
    environment: str = Field(..., description="Environment (dev/staging/prod)")
    endpoints: dict[str, str] = Field(..., description="Available endpoints")


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str = Field(..., description="Error message")
    status_code: int = Field(..., description="HTTP status code")
    timestamp: str = Field(..., description="Error timestamp (ISO 8601)")


# ============================================================================
# Global state
# ============================================================================

startup_time: datetime = None


# ============================================================================
# Lifecycle events
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Initialize service on startup."""
    global startup_time
    startup_time = datetime.utcnow()
    logger.info("Backend Service starting up...")
    logger.info(f"Environment: {os.getenv('ENVIRONMENT', 'development')}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Backend Service shutting down...")


# ============================================================================
# Health & Info endpoints
# ============================================================================

@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns service status and uptime information. Used by container orchestrators
    and monitoring systems to verify service availability.
    
    Returns:
        HealthResponse with status and uptime
    """
    uptime = None
    if startup_time:
        uptime = (datetime.utcnow() - startup_time).total_seconds()
    
    return HealthResponse(
        status="healthy",
        service="backend-service",
        version="1.0.0",
        timestamp=datetime.utcnow().isoformat() + "Z",
        uptime_seconds=uptime,
    )


@app.get("/", response_model=ServiceInfo, tags=["info"])
async def root() -> ServiceInfo:
    """
    Service information endpoint.
    
    Provides metadata about the backend service, environment, and available endpoints.
    
    Returns:
        ServiceInfo with service details and endpoint references
    """
    return ServiceInfo(
        service="backend-service",
        version="1.0.0",
        status="running",
        environment=os.getenv("ENVIRONMENT", "development"),
        endpoints={
            "info": "/",
            "health": "/health",
            "docs": "/docs",
            "redoc": "/redoc",
            "openapi": "/openapi.json",
        },
    )


# ============================================================================
# Idea Vault Routes
# ============================================================================

# In-memory storage (TODO: migrate to database)
_captures: dict[str, dict[str, Any]] = {}
_idea_cards: dict[str, IdeaCard] = {}


@app.post("/api/v1/capture", response_model=CaptureResponse, status_code=202, tags=["idea-vault"])
async def create_capture(request: CaptureRequest) -> CaptureResponse:
    """
    Create a new capture (idea, task, decision, routine, or insight).
    
    Quick capture endpoint. Accepts text, voice transcription, or OCR text,
    auto-detects type and pillars, and returns immediately (202 Accepted).
    
    Args:
        request: CaptureRequest with capture details
        
    Returns:
        CaptureResponse with detected_type and detected_pillars
        
    Example:
        ```bash
        curl -X POST http://localhost:8000/api/v1/capture \
          -H "Content-Type: application/json" \
          -d '{
            "text": "Build async capture system for ideas",
            "source": "web",
            "current_url": "/dashboard"
          }'
        ```
    """
    # Generate capture ID
    capture_id = f"cap-{uuid.uuid4().hex[:8]}"
    
    # Combine all text sources
    combined_text = " ".join([
        request.text or "",
        request.voice_transcript or "",
        request.screenshot_ocr or "",
    ]).strip()
    
    # Create response with classification
    response = IdeaVaultService.create_capture_response(capture_id, combined_text)
    
    # Store capture for later retrieval
    _captures[capture_id] = {
        "request": request.dict(),
        "response": response.dict(),
        "stored_at": datetime.utcnow().isoformat() + "Z",
    }
    
    logger.info(
        f"Capture {capture_id} created: type={response.detected_type}, "
        f"pillars={response.detected_pillars}, confidence={response.confidence:.2f}"
    )
    
    return response


@app.get("/api/v1/capture/{capture_id}", tags=["idea-vault"])
async def get_capture(capture_id: str) -> dict[str, Any]:
    """
    Retrieve capture details by ID.
    
    Args:
        capture_id: Capture ID (e.g., cap-abc123de)
        
    Returns:
        Capture request and response data
    """
    if capture_id not in _captures:
        return JSONResponse(
            status_code=404,
            content={"error": f"Capture {capture_id} not found"},
        )
    
    return _captures[capture_id]


@app.post("/api/v1/capture/{capture_id}/save", response_model=IdeaCard, tags=["idea-vault"])
async def save_capture_as_card(
    capture_id: str,
    title: str = None,
    tags: list[str] = None,
) -> IdeaCard:
    """
    Save a capture as an idea card to the vault.
    
    Converts a processed capture into a persistent idea card with
    optional title and user-assigned tags.
    
    Args:
        capture_id: Capture ID to save
        title: Optional override title
        tags: Optional user-assigned tags
        
    Returns:
        Created IdeaCard
    """
    if capture_id not in _captures:
        return JSONResponse(
            status_code=404,
            content={"error": f"Capture {capture_id} not found"},
        )
    
    capture_data = _captures[capture_id]
    request_data = capture_data["request"]
    response_data = capture_data["response"]
    
    # Create card
    card_id = f"card-{uuid.uuid4().hex[:8]}"
    card = IdeaVaultService.create_idea_card(
        card_id=card_id,
        title=title or request_data.get("title") or "Untitled",
        content=request_data.get("text", ""),
        capture_type=CaptureType(response_data["detected_type"]),
        pillars=[PillarTag(p) for p in response_data["detected_pillars"]],
        source=request_data.get("source", "web"),
        metadata={
            "capture_id": capture_id,
            "original_url": request_data.get("current_url"),
            "original_project_id": request_data.get("current_project_id"),
        },
    )
    
    # Add user tags
    if tags:
        card.tags = tags
    
    # Mark as saved
    card.saved = True
    
    # Store card
    _idea_cards[card_id] = card
    
    logger.info(f"Capture {capture_id} saved as card {card_id}")
    
    return card


@app.get("/api/v1/cards", tags=["idea-vault"])
async def list_idea_cards(
    capture_type: str = None,
    pillar: str = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    List all idea cards with optional filtering.
    
    Args:
        capture_type: Filter by capture type (idea/task/decision/routine/insight)
        pillar: Filter by pillar (personal/professional/creative/etc)
        limit: Max number of cards to return
        
    Returns:
        List of IdeaCard objects
    """
    cards = list(_idea_cards.values())
    
    # Filter by type
    if capture_type:
        cards = [c for c in cards if c.capture_type == capture_type]
    
    # Filter by pillar
    if pillar:
        cards = [c for c in cards if pillar in [p.value for p in c.pillars]]
    
    # Sort by creation date (newest first)
    cards.sort(key=lambda c: c.created_at, reverse=True)
    
    return {
        "total": len(cards),
        "cards": cards[:limit],
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/api/v1/cards/{card_id}", response_model=IdeaCard, tags=["idea-vault"])
async def get_idea_card(card_id: str) -> IdeaCard:
    """
    Retrieve a specific idea card.
    
    Args:
        card_id: Card ID (e.g., card-abc123de)
        
    Returns:
        IdeaCard details
    """
    if card_id not in _idea_cards:
        return JSONResponse(
            status_code=404,
            content={"error": f"Card {card_id} not found"},
        )
    
    return _idea_cards[card_id]


@app.post("/api/v1/cards/{card_id}/tag", tags=["idea-vault"])
async def add_tags_to_card(card_id: str, tags: list[str]) -> IdeaCard:
    """
    Add tags to an idea card.
    
    Args:
        card_id: Card ID
        tags: Tags to add
        
    Returns:
        Updated IdeaCard
    """
    if card_id not in _idea_cards:
        return JSONResponse(
            status_code=404,
            content={"error": f"Card {card_id} not found"},
        )
    
    card = _idea_cards[card_id]
    card.tags.extend(tags)
    card.tags = list(set(card.tags))  # Remove duplicates
    card.updated_at = datetime.utcnow().isoformat() + "Z"
    
    return card


@app.get("/api/v1/stats", tags=["idea-vault"])
async def get_vault_stats() -> dict[str, Any]:
    """
    Get idea vault statistics.
    
    Returns:
        Stats including total captures, cards by type/pillar, this week count
    """
    from datetime import timedelta
    
    cards = list(_idea_cards.values())
    
    # Count by type
    by_type = {}
    for card in cards:
        type_name = card.capture_type.value
        by_type[type_name] = by_type.get(type_name, 0) + 1
    
    # Count by pillar
    by_pillar = {}
    for card in cards:
        for pillar in card.pillars:
            pillar_name = pillar.value
            by_pillar[pillar_name] = by_pillar.get(pillar_name, 0) + 1
    
    # Count this week (past 7 days)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    this_week = sum(
        1 for card in cards
        if datetime.fromisoformat(card.created_at.replace("Z", "+00:00")) > week_ago
    )
    
    return {
        "total_captures": len(_captures),
        "saved_cards": len(cards),
        "by_type": by_type,
        "by_pillar": by_pillar,
        "this_week": this_week,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


# ============================================================================
# Example routes (to be expanded with business logic)
# ============================================================================

@app.get("/status", tags=["status"])
async def status() -> dict[str, Any]:
    """
    Extended status endpoint.
    
    Provides detailed service status for monitoring and debugging.
    
    Returns:
        Status dictionary with service metrics
    """
    uptime = None
    if startup_time:
        uptime = (datetime.utcnow() - startup_time).total_seconds()
    
    return {
        "service": "backend-service",
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "uptime_seconds": uptime,
        "python_version": os.sys.version.split()[0],
    }


# ============================================================================
# Recovery-Aware Planning Routes (Task #810)
# ============================================================================

@app.post("/api/v1/recovery/assess", response_model=RecoveryAssessmentResponse, tags=["recovery-planning"])
async def assess_recovery(
    user_id: str = None,
    date_str: str = None,
) -> RecoveryAssessmentResponse:
    """
    POST /api/v1/recovery/assess
    
    Assess current recovery state based on wellness signals from intervals.icu.
    
    Returns recovery level and recommendations.
    Task #810: Recovery-aware planning
    """
    from datetime import date as date_type
    
    target_date = date_type.fromisoformat(date_str) if date_str else date_type.today()
    
    # Create mock wellness signals for demonstration
    signals = WellnessSignals(
        date=target_date,
        hrv_rmssd=45.5,
        resting_hr=68,
        sleep_hours=6.2,
        sleep_score=65,
        stress_avg=45,
        body_battery=35,
        baseline_resting_hr=58,
    )
    
    recovery_level = analyze_wellness_signals(signals, baseline_resting_hr=58)
    
    signal_interpretation = {
        "hrv_rmssd": interpret_wellness_signal("hrv_rmssd", signals.hrv_rmssd),
        "sleep_hours": interpret_wellness_signal("sleep_hours", signals.sleep_hours),
        "sleep_score": interpret_wellness_signal("sleep_score", signals.sleep_score),
        "body_battery": interpret_wellness_signal("body_battery", signals.body_battery),
    }
    
    task_recommendations = get_task_recommendations(recovery_level)
    workout_recommendations = get_workout_recommendations(recovery_level)
    recovery_priorities = get_recovery_priorities(recovery_level, signals)
    
    summary = f"Recovery state: {recovery_level.value}. "
    if recovery_level == RecoveryLevel.DEPLETED:
        summary += "Critical fatigue detected. Strongly recommend rest day and prioritize sleep."
    elif recovery_level == RecoveryLevel.FATIGUED:
        summary += "Fatigued state. Suggest light tasks only and active recovery instead of training."
    elif recovery_level == RecoveryLevel.GOOD:
        summary += "Normal recovery. Standard scheduling recommended."
    else:
        summary += "Excellent recovery state. Can handle demanding work and training."
    
    return RecoveryAssessmentResponse(
        recovery_level=recovery_level,
        wellness_signals={
            "date": target_date.isoformat(),
            "hrv_rmssd": signals.hrv_rmssd,
            "resting_hr": signals.resting_hr,
            "sleep_hours": signals.sleep_hours,
            "sleep_score": signals.sleep_score,
            "body_battery": signals.body_battery,
            "stress_avg": signals.stress_avg,
        },
        signal_interpretation=signal_interpretation,
        recommended_intensity=TaskIntensity.LIGHTWEIGHT if recovery_level == RecoveryLevel.FATIGUED else (
            TaskIntensity.REST if recovery_level == RecoveryLevel.DEPLETED else TaskIntensity.STANDARD
        ),
        task_recommendations=task_recommendations,
        workout_recommendations=workout_recommendations,
        recovery_priorities=recovery_priorities,
        summary=summary,
        confidence=0.75,
    )


@app.get("/api/v1/recovery/interpret-signal", tags=["recovery-planning"])
async def interpret_signal(
    signal_name: str,
    value: float,
) -> dict:
    """
    GET /api/v1/recovery/interpret-signal
    
    Get human-readable interpretation of a wellness signal.
    
    Examples:
    - /api/v1/recovery/interpret-signal?signal_name=hrv_rmssd&value=45
    - /api/v1/recovery/interpret-signal?signal_name=sleep_hours&value=6.2
    
    Task #810: Recovery-aware planning
    """
    interpretation = interpret_wellness_signal(signal_name, value)
    
    return {
        "signal": signal_name,
        "value": value,
        "interpretation": interpretation,
    }


@app.get("/api/v1/recovery/recommendations", tags=["recovery-planning"])
async def get_recommendations(
    recovery_level: RecoveryLevel,
    include_tasks: bool = True,
    include_workouts: bool = True,
) -> dict:
    """
    GET /api/v1/recovery/recommendations
    
    Get recovery recommendations for a given recovery level.
    
    Task #810: Recovery-aware planning
    """
    result = {}
    
    if include_tasks:
        result["task_recommendations"] = get_task_recommendations(recovery_level)
    
    if include_workouts:
        result["workout_recommendations"] = get_workout_recommendations(recovery_level)
    
    return {
        "recovery_level": recovery_level.value,
        "recommendations": result,
        "summary": f"Recommendations for {recovery_level.value} recovery state",
    }


# ============================================================================
# Error handlers
# ============================================================================

@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content=ErrorResponse(
            error="Endpoint not found",
            status_code=404,
            timestamp=datetime.utcnow().isoformat() + "Z",
        ).dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle general exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            status_code=500,
            timestamp=datetime.utcnow().isoformat() + "Z",
        ).dict(),
    )


# ============================================================================
# Main entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    environment = os.getenv("ENVIRONMENT", "development")

    logger.info(f"Starting Backend Service on {host}:{port} ({environment})")
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
