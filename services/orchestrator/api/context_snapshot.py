"""Cross-domain context snapshot endpoint for Day Shaper and recommendations.

Aggregates calendar, weather, energy, training load, meal plans, and pending tasks
into a unified context structure for decision-making systems.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from shared.ha_client import HomeAssistantClient
from shared.log import get_logger
from config import OrchestratorSettings

logger = get_logger("api.context_snapshot")

router = APIRouter(prefix="/api/v1/context", tags=["context"])

# Global state — wired by configure() at startup
_tool_executor: Any = None
_settings: Any = None


def configure(tool_executor: Any, settings: Any) -> None:
    """Wire up shared components for context snapshot."""
    global _tool_executor, _settings
    _tool_executor = tool_executor
    _settings = settings


# ============================================================================
# Pydantic Models for Cross-Domain Context
# ============================================================================

class CalendarEvent(BaseModel):
    """A calendar event (family or orchestrator)."""
    title: str
    start: str  # ISO 8601
    end: str  # ISO 8601
    all_day: bool = False
    description: Optional[str] = None
    calendar: str = Field(..., description="'family' or 'orchestrator'")


class WeatherCondition(BaseModel):
    """Current weather snapshot."""
    temperature: Optional[float] = None
    humidity: Optional[int] = None
    condition: Optional[str] = None
    wind_speed: Optional[float] = None
    wind_bearing: Optional[int] = None
    pressure: Optional[float] = None


class WeatherForecast(BaseModel):
    """Weather forecast for a day."""
    date: str  # YYYY-MM-DD
    condition: Optional[str] = None
    temp_min: Optional[float] = None
    temp_max: Optional[float] = None
    precipitation_chance: Optional[int] = None


class EnergySnapshot(BaseModel):
    """Current energy state and forecast."""
    pv_production_w: Optional[float] = None  # Current PV production (watts)
    grid_power_w: Optional[float] = None  # Current grid power (positive=import)
    battery_charge_percent: Optional[float] = None
    house_consumption_w: Optional[float] = None
    ev_charging_w: Optional[float] = None
    pv_forecast_today_kwh: Optional[float] = None  # Today's PV forecast
    pv_forecast_tomorrow_kwh: Optional[float] = None


class TrainingLoad(BaseModel):
    """Fitness/training load metrics."""
    load_index: Optional[float] = None  # 0-100 scale
    recovery_score: Optional[float] = None  # 0-100 scale
    readiness: Optional[str] = None  # 'low', 'moderate', 'high'
    last_update: Optional[str] = None  # ISO 8601


class MealPlan(BaseModel):
    """Meal plan for the day."""
    breakfast: Optional[str] = None
    lunch: Optional[str] = None
    dinner: Optional[str] = None
    notes: Optional[str] = None


class PendingTask(BaseModel):
    """A task or action item pending."""
    title: str
    due_date: Optional[str] = None  # ISO 8601 or YYYY-MM-DD
    priority: str = Field(default="medium", description="'low', 'medium', 'high', 'urgent'")
    tags: list[str] = Field(default_factory=list)
    energy_level: Optional[str] = None  # 'low', 'medium', 'high'


class CrossDomainContextSnapshot(BaseModel):
    """Unified context snapshot for Day Shaper and recommendations."""
    timestamp: str = Field(..., description="ISO 8601 timestamp when snapshot was generated")
    timezone: str = Field(..., description="Timezone used for all times")
    
    # Today's context
    today_date: str = Field(..., description="YYYY-MM-DD")
    
    # Calendar
    calendar_events: list[CalendarEvent] = Field(
        default_factory=list,
        description="Today's calendar events from family and orchestrator calendars"
    )
    household_availability: str = Field(
        default="unknown",
        description="'home', 'away', 'partial', 'unknown' — summary of family availability"
    )
    
    # Weather
    weather_current: Optional[WeatherCondition] = None
    weather_forecast_today: Optional[WeatherForecast] = None
    weather_forecast_tomorrow: Optional[WeatherForecast] = None
    
    # Energy
    energy: Optional[EnergySnapshot] = None
    
    # Health & training
    training_load: Optional[TrainingLoad] = None
    
    # Meal plan
    meal_plan: Optional[MealPlan] = None
    
    # Pending tasks
    pending_tasks: list[PendingTask] = Field(
        default_factory=list,
        description="Tasks due today or overdue"
    )
    
    # Quality indicators
    data_available: dict[str, bool] = Field(
        default_factory=dict,
        description="Which data sources were successfully retrieved"
    )


# ============================================================================
# Context Aggregation Logic
# ============================================================================

async def _get_calendar_events(tz: ZoneInfo) -> tuple[list[CalendarEvent], str]:
    """Fetch today's calendar events from both calendars.
    
    Returns:
        (events_list, availability_summary)
    """
    today = datetime.now(tz).date()
    events = []
    availability = "unknown"
    
    try:
        if not _tool_executor:
            return events, availability
        
        # Fetch family calendar
        try:
            result = await _tool_executor.execute("get_calendar_events", {
                "calendar": "family",
                "days_ahead": 1,
            })
            import json
            fam_data = json.loads(result) if isinstance(result, str) else result
            
            # Check availability from family calendar
            avail_result = await _tool_executor.execute("check_household_availability", {
                "days_ahead": 1,
            })
            avail_data = json.loads(avail_result) if isinstance(avail_result, str) else avail_result
            availability = avail_data.get("availability_today", "unknown")
            
            # Parse family events
            if isinstance(fam_data, dict) and "events" in fam_data:
                for evt in fam_data["events"]:
                    try:
                        events.append(CalendarEvent(
                            title=evt.get("summary", "Untitled"),
                            start=evt.get("start", ""),
                            end=evt.get("end", ""),
                            all_day=evt.get("all_day", False),
                            description=evt.get("description"),
                            calendar="family"
                        ))
                    except Exception as e:
                        logger.debug(f"Failed to parse family calendar event: {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch family calendar: {e}")
        
        # Fetch orchestrator calendar
        try:
            result = await _tool_executor.execute("get_calendar_events", {
                "calendar": "orchestrator",
                "days_ahead": 1,
            })
            orch_data = json.loads(result) if isinstance(result, str) else result
            
            if isinstance(orch_data, dict) and "events" in orch_data:
                for evt in orch_data["events"]:
                    try:
                        events.append(CalendarEvent(
                            title=evt.get("summary", "Untitled"),
                            start=evt.get("start", ""),
                            end=evt.get("end", ""),
                            all_day=evt.get("all_day", False),
                            description=evt.get("description"),
                            calendar="orchestrator"
                        ))
                    except Exception as e:
                        logger.debug(f"Failed to parse orchestrator calendar event: {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch orchestrator calendar: {e}")
    
    except Exception as e:
        logger.error(f"Error fetching calendar events: {e}")
    
    return events, availability


async def _get_weather() -> tuple[Optional[WeatherCondition], Optional[WeatherForecast], Optional[WeatherForecast]]:
    """Fetch current weather and forecasts."""
    current = None
    forecast_today = None
    forecast_tomorrow = None
    
    try:
        if not _settings or not _tool_executor:
            return current, forecast_today, forecast_tomorrow
        
        # Get current weather via HA
        try:
            settings = OrchestratorSettings()
            ha = HomeAssistantClient(settings.ha_url, settings.ha_token)
            
            # Try entities in priority order
            entity_id = None
            for entity in ["weather.forecast_home_2", "weather.home", "weather.openweathermap", "weather.forecast_home"]:
                try:
                    state = await ha.get_state(entity)
                    if state.get("state") != "unavailable":
                        entity_id = entity
                        break
                except Exception:
                    continue
            
            if entity_id:
                state = await ha.get_state(entity_id)
                attrs = state.get("attributes", {})
                
                current = WeatherCondition(
                    temperature=attrs.get("temperature"),
                    humidity=attrs.get("humidity"),
                    condition=state.get("state"),
                    wind_speed=attrs.get("wind_speed"),
                    wind_bearing=attrs.get("wind_bearing"),
                    pressure=attrs.get("pressure"),
                )
                
                # Parse forecast
                forecast_list = attrs.get("forecast", [])
                tz = ZoneInfo(_settings.timezone) if _settings else ZoneInfo("Europe/Berlin")
                today = datetime.now(tz).date()
                tomorrow = today + timedelta(days=1)
                
                for f in forecast_list:
                    try:
                        f_date_str = f.get("datetime", "").split("T")[0]
                        if f_date_str == today.isoformat():
                            forecast_today = WeatherForecast(
                                date=f_date_str,
                                condition=f.get("condition"),
                                temp_min=f.get("templow"),
                                temp_max=f.get("temperature"),
                                precipitation_chance=f.get("precipitation_probability"),
                            )
                        elif f_date_str == tomorrow.isoformat():
                            forecast_tomorrow = WeatherForecast(
                                date=f_date_str,
                                condition=f.get("condition"),
                                temp_min=f.get("templow"),
                                temp_max=f.get("temperature"),
                                precipitation_chance=f.get("precipitation_probability"),
                            )
                    except Exception as e:
                        logger.debug(f"Failed to parse forecast entry: {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch weather from HA: {e}")
    
    except Exception as e:
        logger.error(f"Error fetching weather: {e}")
    
    return current, forecast_today, forecast_tomorrow


async def _get_energy() -> Optional[EnergySnapshot]:
    """Fetch current energy state and forecast."""
    try:
        if not _tool_executor:
            return None
        
        result = await _tool_executor.execute("get_home_energy_summary", {})
        import json
        data = json.loads(result) if isinstance(result, str) else result
        
        if isinstance(data, dict):
            return EnergySnapshot(
                pv_production_w=data.get("pv_production_w"),
                grid_power_w=data.get("grid_power_w"),
                battery_charge_percent=data.get("battery_percent"),
                house_consumption_w=data.get("house_consumption_w"),
                ev_charging_w=data.get("ev_charging_w"),
                pv_forecast_today_kwh=data.get("pv_forecast_today_kwh"),
                pv_forecast_tomorrow_kwh=data.get("pv_forecast_tomorrow_kwh"),
            )
    except Exception as e:
        logger.warning(f"Failed to fetch energy data: {e}")
    
    return None


async def _get_training_load() -> Optional[TrainingLoad]:
    """Fetch training/recovery metrics from Oura or health data."""
    try:
        if not _tool_executor:
            return None
        
        # Try to get recovery data via memory/health tool
        # For now, return placeholder if available
        # Future: integrate with Oura API or health tools
        return None
    
    except Exception as e:
        logger.warning(f"Failed to fetch training load: {e}")
    
    return None


async def _get_meal_plan() -> Optional[MealPlan]:
    """Fetch meal plan for today.
    
    Future: integrate with meal planning app or calendar entries.
    """
    try:
        # Placeholder for future meal plan integration
        # Could parse calendar events tagged with meals
        # Or fetch from meal planning database
        return None
    
    except Exception as e:
        logger.warning(f"Failed to fetch meal plan: {e}")
    
    return None


async def _get_pending_tasks() -> list[PendingTask]:
    """Fetch pending tasks due today or overdue."""
    tasks = []
    
    try:
        if not _tool_executor:
            return tasks
        
        # Fetch tasks from Orbit (due today or overdue)
        try:
            result = await _tool_executor.execute("orbit_list_tasks", {
                "status": "backlog",  # or "ready"
                "limit": 10,
            })
            import json
            data = json.loads(result) if isinstance(result, str) else result
            
            if isinstance(data, dict) and "tasks" in data:
                for task in data["tasks"]:
                    try:
                        tasks.append(PendingTask(
                            title=task.get("title", "Untitled"),
                            due_date=task.get("due_date"),
                            priority=task.get("priority", "medium"),
                            tags=task.get("tags", []),
                            energy_level=task.get("energy_level"),
                        ))
                    except Exception as e:
                        logger.debug(f"Failed to parse task: {e}")
        except Exception as e:
            logger.debug(f"Failed to fetch tasks from Orbit: {e}")
    
    except Exception as e:
        logger.error(f"Error fetching pending tasks: {e}")
    
    return tasks


# ============================================================================
# REST Endpoint
# ============================================================================

@router.get("/snapshot", response_model=CrossDomainContextSnapshot)
async def get_context_snapshot() -> CrossDomainContextSnapshot:
    """Get unified cross-domain context snapshot.
    
    Aggregates calendar, weather, energy, training load, meal plans, and tasks
    into a single context for Day Shaper and recommendation systems.
    
    Returns:
        CrossDomainContextSnapshot with all available data and quality indicators.
    """
    tz = ZoneInfo(_settings.timezone) if _settings else ZoneInfo("Europe/Berlin")
    now = datetime.now(tz)
    
    logger.info("Building context snapshot", timestamp=now.isoformat())
    
    # Fetch all data in parallel
    import asyncio
    
    try:
        (
            calendar_events,
            availability,
            (weather_current, weather_today, weather_tomorrow),
            energy,
            training,
            meals,
            tasks,
        ) = await asyncio.gather(
            _get_calendar_events(tz),
            _get_weather(),  # Returns tuple
            _get_energy(),
            _get_training_load(),
            _get_meal_plan(),
            _get_pending_tasks(),
            return_exceptions=True,
        )
        
        # Handle exceptions from gather
        if isinstance(calendar_events, Exception):
            logger.warning(f"Calendar fetch failed: {calendar_events}")
            calendar_events, availability = [], "unknown"
        if isinstance(weather_current, Exception):
            logger.warning(f"Weather fetch failed: {weather_current}")
            weather_current, weather_today, weather_tomorrow = None, None, None
        if isinstance(energy, Exception):
            logger.warning(f"Energy fetch failed: {energy}")
            energy = None
        if isinstance(training, Exception):
            logger.warning(f"Training fetch failed: {training}")
            training = None
        if isinstance(meals, Exception):
            logger.warning(f"Meal plan fetch failed: {meals}")
            meals = None
        if isinstance(tasks, Exception):
            logger.warning(f"Tasks fetch failed: {tasks}")
            tasks = []
        
        # Build snapshot
        snapshot = CrossDomainContextSnapshot(
            timestamp=now.isoformat(),
            timezone=_settings.timezone if _settings else "Europe/Berlin",
            today_date=now.date().isoformat(),
            
            calendar_events=calendar_events if isinstance(calendar_events, list) else [],
            household_availability=availability if isinstance(availability, str) else "unknown",
            
            weather_current=weather_current,
            weather_forecast_today=weather_today,
            weather_forecast_tomorrow=weather_tomorrow,
            
            energy=energy,
            training_load=training,
            meal_plan=meals,
            pending_tasks=tasks if isinstance(tasks, list) else [],
            
            data_available={
                "calendar": True,  # Always return structure, filled if available
                "weather": weather_current is not None,
                "energy": energy is not None,
                "training": training is not None,
                "meals": meals is not None,
                "tasks": len(tasks) > 0 if isinstance(tasks, list) else False,
            }
        )
        
        logger.info(
            "Context snapshot built successfully",
            timestamp=snapshot.timestamp,
            calendar_events=len(snapshot.calendar_events),
            pending_tasks=len(snapshot.pending_tasks),
        )
        
        return snapshot
    
    except Exception as e:
        logger.error(f"Failed to build context snapshot: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to build context snapshot: {str(e)}"
        )
