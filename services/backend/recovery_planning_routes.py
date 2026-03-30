"""API Routes for Recovery-Aware Planning (Task #810)

Endpoints for:
- Retrieving wellness signals from intervals.icu
- Assessing recovery state
- Getting recovery-aware task recommendations
- Adjusting schedule based on recovery signals
- Protecting recovery blocks
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import date, timedelta
from typing import Optional, List
from pydantic import BaseModel, Field

from recovery_aware_planning import (
    RecoveryLevel,
    TaskIntensity,
    RecoveryAssessmentResponse,
    ScheduleAdjustmentResponse,
    WellnessSignals,
    TrainingLoadMetrics,
    analyze_wellness_signals,
    interpret_wellness_signal,
    get_task_recommendations,
    get_workout_recommendations,
    get_recovery_priorities,
    adjust_schedule_for_recovery,
    identify_recovery_blocks,
)

router = APIRouter(prefix="/api/v1/recovery", tags=["recovery-planning"])


# ============================================================================
# Request/Response Models
# ============================================================================

class WellnessSignalsRequest(BaseModel):
    """Request to assess wellness signals."""
    user_id: str
    date: Optional[date] = None  # Defaults to today
    include_historical: bool = False  # Look at past 7 days


class TaskForScheduling(BaseModel):
    """A task in the schedule."""
    id: str
    title: str
    type: str  # deep_work, meetings, admin_work, training, etc.
    duration: int = Field(..., description="Duration in minutes")
    priority: str = Field(default="normal", description="critical, high, normal, low")
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None


class RecoveryProtectionRequest(BaseModel):
    """Request to identify and protect recovery blocks."""
    user_id: str
    days_to_analyze: int = Field(default=14, ge=7, le=30)
    protection_window: int = Field(default=2, ge=0, le=7, description="Days to protect around fatigued periods")


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.post("/assess", response_model=RecoveryAssessmentResponse)
async def assess_recovery(
    request: WellnessSignalsRequest,
) -> RecoveryAssessmentResponse:
    """
    POST /api/v1/recovery/assess
    
    Assess current recovery state based on wellness signals from intervals.icu.
    
    Returns:
    - Recovery level (OPTIMAL, GOOD, FATIGUED, DEPLETED)
    - Interpretation of each signal
    - Task recommendations
    - Workout suggestions
    - Recovery priorities
    
    Task #810: Recovery-aware planning
    """
    target_date = request.date or date.today()
    
    # TODO: In a real implementation, fetch wellness data from intervals.icu
    # For now, using mock data for demonstration
    signals = WellnessSignals(
        date=target_date,
        hrv_rmssd=45.5,  # Low HRV
        resting_hr=68,
        sleep_hours=6.2,  # Below 6.5
        sleep_score=65,
        stress_avg=45,
        body_battery=35,  # Low battery
        baseline_resting_hr=58,
    )
    
    # Analyze recovery level
    recovery_level = analyze_wellness_signals(signals, baseline_resting_hr=58)
    
    # Build signal interpretations
    signal_interpretation = {
        "hrv_rmssd": interpret_wellness_signal("hrv_rmssd", signals.hrv_rmssd),
        "sleep_hours": interpret_wellness_signal("sleep_hours", signals.sleep_hours),
        "sleep_score": interpret_wellness_signal("sleep_score", signals.sleep_score),
        "body_battery": interpret_wellness_signal("body_battery", signals.body_battery),
    }
    
    # Get recommendations
    task_recommendations = get_task_recommendations(recovery_level)
    workout_recommendations = get_workout_recommendations(recovery_level)
    recovery_priorities = get_recovery_priorities(recovery_level, signals)
    
    # Generate summary
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


@router.post("/adjust-schedule", response_model=ScheduleAdjustmentResponse)
async def adjust_schedule(
    user_id: str = Query(..., description="User ID"),
    recovery_level: RecoveryLevel = Query(..., description="Current recovery level"),
    tasks: List[TaskForScheduling] = Query(..., description="Current schedule tasks"),
    target_date: Optional[date] = None,
) -> ScheduleAdjustmentResponse:
    """
    POST /api/v1/recovery/adjust-schedule
    
    Adjust schedule based on recovery state.
    
    When recovery is low (FATIGUED or DEPLETED):
    - Remove non-essential deep work
    - Reduce meeting durations
    - Protect rest/recovery time
    - Suggest task deferral
    
    Task #810: Recovery-aware planning
    """
    target_date = target_date or date.today()
    
    # Adjust schedule
    adjusted_schedule, removed_tasks = adjust_schedule_for_recovery(
        [t.model_dump() for t in tasks],
        recovery_level,
    )
    
    # Generate reasoning
    if recovery_level == RecoveryLevel.DEPLETED:
        reasoning = "SEVERE FATIGUE: Schedule significantly reduced. Focus on rest only."
    elif recovery_level == RecoveryLevel.FATIGUED:
        reasoning = "Low recovery: Removed heavy tasks, kept critical items. Suggest deferral to next week."
    elif recovery_level == RecoveryLevel.GOOD:
        reasoning = "Normal recovery: Standard schedule maintained."
    else:
        reasoning = "Optimal recovery: Full schedule available."
    
    # Calculate deferral date (2-3 days out)
    deferred_until = target_date + timedelta(days=3) if removed_tasks else None
    
    return ScheduleAdjustmentResponse(
        date=target_date,
        original_schedule=[t.model_dump() for t in tasks],
        adjusted_schedule=adjusted_schedule,
        removed_tasks=removed_tasks,
        deferred_until=deferred_until,
        reasoning=reasoning,
        recovery_protected=recovery_level in [RecoveryLevel.FATIGUED, RecoveryLevel.DEPLETED],
    )


@router.post("/recovery-blocks", response_model=dict)
async def identify_recovery_periods(
    request: RecoveryProtectionRequest,
) -> dict:
    """
    POST /api/v1/recovery/recovery-blocks
    
    Identify recovery blocks where user needs protected rest time.
    
    A recovery block is identified when:
    - Multiple days show FATIGUED or DEPLETED status
    - HRV remains low across several consecutive days
    - Sleep debt accumulates
    
    Returns protected time blocks that should have minimal scheduling.
    
    Task #810: Recovery-aware planning
    """
    # TODO: In real implementation, analyze historical wellness data
    # For now, returning mock recovery blocks
    
    mock_history = [
        (date.today() - timedelta(days=3), RecoveryLevel.GOOD),
        (date.today() - timedelta(days=2), RecoveryLevel.FATIGUED),
        (date.today() - timedelta(days=1), RecoveryLevel.FATIGUED),
        (date.today(), RecoveryLevel.DEPLETED),
    ]
    
    blocks = identify_recovery_blocks(mock_history, protection_days=request.protection_window)
    
    return {
        "user_id": request.user_id,
        "analysis_period": {
            "start": (date.today() - timedelta(days=request.days_to_analyze)).isoformat(),
            "end": date.today().isoformat(),
        },
        "recovery_blocks": [
            {
                "start": b["start"].isoformat(),
                "end": b["end"].isoformat(),
                "duration_days": (b["end"] - b["start"]).days + 1,
                "levels": [l.value for l in b["levels"]],
                "protection_recommendation": "Light schedule, prioritize sleep and recovery",
            }
            for b in blocks
        ],
        "summary": f"Identified {len(blocks)} recovery block(s) requiring protected scheduling.",
    }


@router.get("/recommendations")
async def get_recovery_recommendations(
    recovery_level: RecoveryLevel = Query(...),
    include_tasks: bool = Query(default=True),
    include_workouts: bool = Query(default=True),
) -> dict:
    """
    GET /api/v1/recovery/recommendations
    
    Get recovery recommendations for a given recovery level.
    
    Query params:
    - recovery_level: OPTIMAL, GOOD, FATIGUED, or DEPLETED
    - include_tasks: Include task recommendations
    - include_workouts: Include workout suggestions
    
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


@router.get("/interpret-signal")
async def interpret_signal(
    signal_name: str = Query(..., description="hrv_rmssd, sleep_hours, sleep_score, body_battery, resting_hr"),
    value: float = Query(..., description="Signal value"),
) -> dict:
    """
    GET /api/v1/recovery/interpret-signal
    
    Get human-readable interpretation of a wellness signal.
    
    Examples:
    - GET /api/v1/recovery/interpret-signal?signal_name=hrv_rmssd&value=45
    - GET /api/v1/recovery/interpret-signal?signal_name=sleep_hours&value=6.2
    
    Task #810: Recovery-aware planning
    """
    interpretation = interpret_wellness_signal(signal_name, value)
    
    return {
        "signal": signal_name,
        "value": value,
        "interpretation": interpretation,
    }


# ============================================================================
# Future Endpoints (Phase 2)
# ============================================================================
# TODO #810: Add these endpoints in next phase
#
# @router.get("/trends")
# async def get_recovery_trends(
#     user_id: str,
#     days: int = 14,
# ) -> dict:
#     """Analyze recovery trends over time."""
#     pass
#
# @router.post("/sync-intervals")
# async def sync_wellness_from_intervals(user_id: str) -> dict:
#     """Sync latest wellness data from intervals.icu."""
#     pass
#
# @router.post("/auto-protect")
# async def enable_auto_protection(user_id: str) -> dict:
#     """Enable automatic schedule protection when fatigue detected."""
#     pass
