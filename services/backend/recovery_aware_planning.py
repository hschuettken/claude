"""Recovery-Aware Planning for SynthesisOS

Task #810: Implements recovery-aware planning that:
- Reads HRV/sleep/load signals from intervals.icu wellness data
- Automatically suggests lighter tasks when HRV is low
- Downgrades workout intensity when sleep is poor or training load is high
- Protects recovery blocks (rest days, light activity days)

Signals considered:
- HRV (Heart Rate Variability): low HRV (<50 ms) = fatigue, needs recovery
- Sleep Quality: <6.5 hours or sleep_score <70 = insufficient recovery
- Training Load: chronic high load (7-day moving avg) = needs lighter schedule
- Resting HR: elevated resting HR (+10 bpm vs baseline) = stressed/fatigued

Recovery recommendations:
- HRV <50: suggest LIGHTWEIGHT tasks only, avoid intense training
- Sleep <6.5h: suggest REST day (minimal schedule), no workouts
- Training Load High: suggest FOCUS tasks only (no multi-tasking), lighter physical activity
- Resting HR elevated: suggest RECOVERY focus (sleep, nutrition, light movement)
"""

from datetime import datetime, date, timedelta, timezone
from typing import Optional, List
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, Field


class RecoveryLevel(str, Enum):
    """Recovery state based on wellness signals."""
    OPTIMAL = "optimal"        # Low stress, good sleep, high HRV
    GOOD = "good"              # Normal conditions
    FATIGUED = "fatigued"      # Low HRV or poor sleep
    DEPLETED = "depleted"      # Multiple signals indicate severe fatigue


class TaskIntensity(str, Enum):
    """Task intensity for scheduling recommendations."""
    HEAVYWEIGHT = "heavyweight"  # Heavy cognitive load, intense training
    STANDARD = "standard"        # Normal tasks, standard intensity
    LIGHTWEIGHT = "lightweight"  # Light cognitive load, easy movement
    REST = "rest"               # Recovery focus only


@dataclass
class WellnessSignals:
    """Current wellness state from intervals.icu."""
    date: date
    hrv_rmssd: Optional[float] = None  # Heart rate variability (ms)
    resting_hr: Optional[int] = None
    sleep_hours: Optional[float] = None
    sleep_score: Optional[int] = None
    training_readiness: Optional[str] = None  # "low", "balanced", "high"
    stress_avg: Optional[int] = None
    body_battery: Optional[int] = None  # Garmin's battery metric (0-100)
    
    # Baseline for comparison (establish from historical avg)
    baseline_resting_hr: Optional[int] = None
    

@dataclass
class TrainingLoadMetrics:
    """Training load from past 7 days."""
    acute_load: float  # Last 7 days
    chronic_load: float  # Last 28 days
    training_stress_balance: float  # Positive = rested, negative = fatigued
    moving_avg_7d: float  # 7-day moving average


class RecoveryAssessmentResponse(BaseModel):
    """Assessment of current recovery state and recommendations."""
    recovery_level: RecoveryLevel
    wellness_signals: dict  # Current HRV, sleep, HR, etc.
    signal_interpretation: dict = Field(
        default_factory=dict,
        description="Human-readable interpretation of each signal"
    )
    
    # Scheduling recommendations
    recommended_intensity: TaskIntensity
    task_recommendations: List[dict] = Field(
        default_factory=list,
        description="Suggested task types and intensity levels"
    )
    
    # Workout recommendations
    workout_recommendations: dict = Field(
        default_factory=dict,
        description="Suggested workout type, duration, intensity"
    )
    
    # Recovery actions
    recovery_priorities: List[str] = Field(
        default_factory=list,
        description="What to prioritize for recovery"
    )
    
    summary: str
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)


class RecoveryAwareSchedulingRequest(BaseModel):
    """Request to adjust schedule based on recovery state."""
    user_id: str
    target_date: date
    include_workout_suggestions: bool = True
    include_task_suggestions: bool = True
    protection_window: int = Field(default=2, ge=0, le=7, description="Days to look ahead for recovery blocks")


class ScheduleAdjustmentResponse(BaseModel):
    """Adjusted schedule respecting recovery state."""
    date: date
    original_schedule: List[dict]
    adjusted_schedule: List[dict]
    removed_tasks: List[dict] = Field(
        default_factory=list,
        description="Tasks removed/deferred due to recovery needs"
    )
    deferred_until: Optional[date] = None
    reasoning: str
    recovery_protected: bool


# ============================================================================
# RECOVERY SIGNAL ANALYSIS
# ============================================================================

def analyze_wellness_signals(signals: WellnessSignals, baseline_resting_hr: int = 60) -> RecoveryLevel:
    """
    Analyze wellness signals and determine recovery level.
    
    Returns RecoveryLevel based on:
    - HRV <50 ms: FATIGUED (needs recovery)
    - Sleep <6.5h OR sleep_score <70: FATIGUED
    - Resting HR >baseline+10: elevated stress
    - Multiple signals: DEPLETED
    """
    fatigue_flags = []
    
    # HRV Analysis: <50 is low, 30 is very low
    if signals.hrv_rmssd is not None:
        if signals.hrv_rmssd < 30:
            fatigue_flags.append("hrv_critical")  # Very fatigued
        elif signals.hrv_rmssd < 50:
            fatigue_flags.append("hrv_low")  # Fatigued
    
    # Sleep Analysis
    if signals.sleep_hours is not None and signals.sleep_hours < 6.5:
        fatigue_flags.append("sleep_insufficient")
    
    if signals.sleep_score is not None and signals.sleep_score < 70:
        fatigue_flags.append("sleep_quality_poor")
    
    # Resting Heart Rate Analysis
    baseline_rhr = signals.baseline_resting_hr or baseline_resting_hr
    if signals.resting_hr is not None and signals.resting_hr > baseline_rhr + 10:
        fatigue_flags.append("hr_elevated")
    
    # Body Battery (Garmin) Analysis: <20 is critical
    if signals.body_battery is not None:
        if signals.body_battery < 20:
            fatigue_flags.append("battery_critical")
        elif signals.body_battery < 40:
            fatigue_flags.append("battery_low")
    
    # Determine recovery level
    if len(fatigue_flags) >= 3 or "hrv_critical" in fatigue_flags or "battery_critical" in fatigue_flags:
        return RecoveryLevel.DEPLETED
    elif len(fatigue_flags) >= 1:
        return RecoveryLevel.FATIGUED
    elif signals.hrv_rmssd is not None and signals.hrv_rmssd > 70:
        return RecoveryLevel.OPTIMAL
    else:
        return RecoveryLevel.GOOD


def interpret_wellness_signal(signal_name: str, value: Optional[float], context: Optional[str] = None) -> str:
    """Generate human-readable interpretation of a wellness signal."""
    if value is None:
        return "No data available"
    
    if signal_name == "hrv_rmssd":
        if value > 70:
            return f"Excellent HRV ({value:.0f} ms) — well recovered, ready for training"
        elif value > 50:
            return f"Good HRV ({value:.0f} ms) — normal recovery state"
        elif value > 30:
            return f"Low HRV ({value:.0f} ms) — fatigued, suggest lighter activity"
        else:
            return f"Very low HRV ({value:.0f} ms) — severe fatigue, prioritize rest"
    
    elif signal_name == "sleep_hours":
        if value >= 8:
            return f"{value:.1f}h sleep — excellent recovery"
        elif value >= 7:
            return f"{value:.1f}h sleep — good recovery"
        elif value >= 6.5:
            return f"{value:.1f}h sleep — adequate but monitor"
        else:
            return f"{value:.1f}h sleep — insufficient recovery, need more sleep"
    
    elif signal_name == "sleep_score":
        if value >= 80:
            return f"Sleep quality {value} — excellent"
        elif value >= 70:
            return f"Sleep quality {value} — good"
        elif value >= 60:
            return f"Sleep quality {value} — fair, may need earlier bedtime"
        else:
            return f"Sleep quality {value} — poor, address sleep environment"
    
    elif signal_name == "resting_hr":
        return f"Resting HR {value:.0f} bpm — compare to your baseline"
    
    elif signal_name == "body_battery":
        if value >= 80:
            return f"Body battery {value:.0f} — fully charged, ready for hard work"
        elif value >= 50:
            return f"Body battery {value:.0f} — healthy, normal capacity"
        elif value >= 20:
            return f"Body battery {value:.0f} — low, avoid intense activity"
        else:
            return f"Body battery {value:.0f} — critical, rest strongly recommended"
    
    return f"{signal_name}: {value}"


# ============================================================================
# TASK & WORKOUT RECOMMENDATIONS
# ============================================================================

def get_task_recommendations(recovery_level: RecoveryLevel) -> List[dict]:
    """
    Get task recommendations based on recovery level.
    
    OPTIMAL: All task types available
    GOOD: Normal scheduling
    FATIGUED: Lightweight tasks only, avoid deep cognitive work
    DEPLETED: Rest focus only, minimal schedule
    """
    recommendations = {
        RecoveryLevel.OPTIMAL: [
            {
                "type": "deep_work",
                "description": "Complex problem-solving, creative work",
                "estimated_hours": 4,
                "priority": "high",
            },
            {
                "type": "meetings",
                "description": "Collaborative sessions, presentations",
                "estimated_hours": 2,
                "priority": "normal",
            },
            {
                "type": "admin_work",
                "description": "Email, planning, routine tasks",
                "estimated_hours": 1,
                "priority": "low",
            },
        ],
        RecoveryLevel.GOOD: [
            {
                "type": "deep_work",
                "description": "Focused work with breaks",
                "estimated_hours": 3,
                "priority": "high",
            },
            {
                "type": "meetings",
                "description": "Standard meetings and collaboration",
                "estimated_hours": 2,
                "priority": "normal",
            },
            {
                "type": "admin_work",
                "description": "Administrative work",
                "estimated_hours": 1.5,
                "priority": "low",
            },
        ],
        RecoveryLevel.FATIGUED: [
            {
                "type": "shallow_work",
                "description": "Light tasks, routine items only",
                "estimated_hours": 2,
                "priority": "high",
                "reason": "Low energy — avoid deep cognitive work",
            },
            {
                "type": "admin_work",
                "description": "Administrative tasks, email",
                "estimated_hours": 1,
                "priority": "normal",
            },
            {
                "type": "rest_recovery",
                "description": "Naps, walks, stretching, meditation",
                "estimated_hours": 1,
                "priority": "critical",
                "reason": "Prioritize recovery",
            },
        ],
        RecoveryLevel.DEPLETED: [
            {
                "type": "rest_recovery",
                "description": "Sleep, light movement, hydration",
                "estimated_hours": 6,
                "priority": "critical",
                "reason": "Severe fatigue — rest is essential",
            },
            {
                "type": "admin_work",
                "description": "Minimal urgent tasks only",
                "estimated_hours": 0.5,
                "priority": "critical",
                "reason": "Only if absolutely necessary",
            },
        ],
    }
    
    return recommendations.get(recovery_level, [])


def get_workout_recommendations(recovery_level: RecoveryLevel, training_load: Optional[TrainingLoadMetrics] = None) -> dict:
    """
    Get workout recommendations based on recovery level and training load.
    
    OPTIMAL: Can do intense training
    GOOD: Normal training schedule
    FATIGUED: Light activity only
    DEPLETED: Complete rest or gentle movement only
    """
    recommendations = {
        RecoveryLevel.OPTIMAL: {
            "suggested_activity": "Threshold/VO2 work, strength training",
            "duration_minutes": 60,
            "intensity": "high",
            "zone": "Z4-Z5 (threshold, VO2max)",
            "notes": "Good recovery state. Opportunity for quality training.",
        },
        RecoveryLevel.GOOD: {
            "suggested_activity": "Steady state, tempo, or general strength",
            "duration_minutes": 45,
            "intensity": "moderate",
            "zone": "Z2-Z3 (endurance, tempo)",
            "notes": "Normal training. Maintain current schedule.",
        },
        RecoveryLevel.FATIGUED: {
            "suggested_activity": "Easy ride/run or walk, mobility work",
            "duration_minutes": 30,
            "intensity": "light",
            "zone": "Z1-Z2 (recovery, easy)",
            "notes": "Fatigued state. Active recovery only, no intensity.",
        },
        RecoveryLevel.DEPLETED: {
            "suggested_activity": "REST DAY or gentle stretching/walks",
            "duration_minutes": 0,
            "intensity": "none",
            "zone": "Rest",
            "notes": "Critical fatigue. No training today. Focus on sleep and nutrition.",
        },
    }
    
    return recommendations.get(recovery_level, {})


def get_recovery_priorities(recovery_level: RecoveryLevel, signals: WellnessSignals) -> List[str]:
    """
    Get recovery action priorities based on recovery level and signals.
    """
    priorities = []
    
    if recovery_level == RecoveryLevel.DEPLETED:
        priorities.extend([
            "SLEEP: Aim for 8-9 hours tonight, sleep in if possible",
            "HYDRATION: Drink water consistently throughout the day",
            "NUTRITION: Focus on protein and nutrient-dense foods",
            "NO TRAINING: Rest completely today",
            "STRESS: Minimize decisions, avoid deadline pressure",
        ])
    elif recovery_level == RecoveryLevel.FATIGUED:
        priorities.extend([
            "SLEEP: Prioritize early bedtime, aim for 8+ hours",
            "MOVEMENT: Light walking or stretching only",
            "NUTRITION: Increase calories slightly, focus on recovery foods",
            "MEETINGS: Defer non-urgent meetings if possible",
        ])
        
        # Signal-specific recommendations
        if signals.sleep_hours is not None and signals.sleep_hours < 6:
            priorities.insert(0, "CRITICAL SLEEP: You're significantly sleep deprived")
        if signals.hrv_rmssd is not None and signals.hrv_rmssd < 30:
            priorities.insert(0, "CRITICAL HRV: Severe fatigue, complete rest recommended")
    else:
        priorities.extend([
            "SLEEP: Maintain 7-8 hours nightly",
            "MOVEMENT: Regular activity, can include training",
            "NUTRITION: Balanced diet, adequate calories for activity level",
        ])
    
    return priorities


# ============================================================================
# SCHEDULE ADJUSTMENT LOGIC
# ============================================================================

def adjust_schedule_for_recovery(
    current_schedule: List[dict],
    recovery_level: RecoveryLevel,
) -> tuple[List[dict], List[dict]]:
    """
    Adjust task schedule based on recovery level.
    
    Args:
        current_schedule: List of scheduled tasks with 'duration', 'priority', 'type'
        recovery_level: Current recovery state
    
    Returns:
        (adjusted_schedule, removed_tasks)
    """
    adjusted = []
    removed = []
    
    if recovery_level == RecoveryLevel.OPTIMAL or recovery_level == RecoveryLevel.GOOD:
        # No adjustment needed
        return current_schedule, []
    
    for task in current_schedule:
        task_type = task.get("type", "unknown")
        priority = task.get("priority", "normal")
        duration = task.get("duration", 60)
        
        if recovery_level == RecoveryLevel.FATIGUED:
            # Remove non-essential tasks, keep lightweight/critical ones
            if task_type in ["deep_work", "high_intensity_training"]:
                removed.append(task)
            elif task_type in ["meetings"] and priority not in ["critical"]:
                removed.append(task)
            else:
                # Reduce duration if it's lengthy
                if duration > 90 and priority not in ["critical"]:
                    adjusted_task = task.copy()
                    adjusted_task["original_duration"] = duration
                    adjusted_task["adjusted_duration"] = min(duration // 2, 60)
                    adjusted_task["note"] = "Reduced due to fatigue"
                    adjusted.append(adjusted_task)
                else:
                    adjusted.append(task)
        
        elif recovery_level == RecoveryLevel.DEPLETED:
            # Remove almost everything except critical tasks
            if priority == "critical":
                adjusted.append(task)
            else:
                removed.append(task)
    
    return adjusted, removed


# ============================================================================
# PROTECTION OF RECOVERY BLOCKS
# ============================================================================

def identify_recovery_blocks(
    fatigue_history: List[tuple[date, RecoveryLevel]],
    protection_days: int = 2,
) -> List[dict]:
    """
    Identify and protect recovery blocks.
    
    A recovery block is a period when multiple days show low recovery signals.
    Protect these periods by keeping schedule light.
    """
    blocks = []
    current_block = None
    
    for d, level in sorted(fatigue_history):
        is_recovery_day = level in [RecoveryLevel.FATIGUED, RecoveryLevel.DEPLETED]
        
        if is_recovery_day:
            if current_block is None:
                current_block = {"start": d, "end": d, "levels": [level]}
            else:
                # Extend block if adjacent or within 2 days
                days_gap = (d - current_block["end"]).days
                if days_gap <= protection_days:
                    current_block["end"] = d
                    current_block["levels"].append(level)
                else:
                    blocks.append(current_block)
                    current_block = {"start": d, "end": d, "levels": [level]}
        else:
            if current_block is not None:
                blocks.append(current_block)
                current_block = None
    
    if current_block is not None:
        blocks.append(current_block)
    
    return blocks
