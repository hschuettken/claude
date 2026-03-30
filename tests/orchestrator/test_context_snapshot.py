"""Tests for cross-domain context snapshot endpoint (#809)."""

from __future__ import annotations

import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

# Import the models and service
from api.context_snapshot import (
    CrossDomainContextSnapshot,
    CalendarEvent,
    WeatherCondition,
    WeatherForecast,
    EnergySnapshot,
    TrainingLoad,
    MealPlan,
    PendingTask,
)


class TestContextSnapshotModels:
    """Test Pydantic models for context snapshot."""
    
    def test_calendar_event_valid(self):
        """Test CalendarEvent model validation."""
        event = CalendarEvent(
            title="Meeting",
            start="2025-03-31T10:00:00+02:00",
            end="2025-03-31T11:00:00+02:00",
            calendar="family"
        )
        assert event.title == "Meeting"
        assert event.calendar == "family"
        assert event.all_day is False
    
    def test_calendar_event_all_day(self):
        """Test all-day calendar event."""
        event = CalendarEvent(
            title="Birthday",
            start="2025-03-31",
            end="2025-04-01",
            all_day=True,
            calendar="orchestrator"
        )
        assert event.all_day is True
    
    def test_weather_condition(self):
        """Test WeatherCondition model."""
        weather = WeatherCondition(
            temperature=22.5,
            humidity=65,
            condition="Partly cloudy",
            wind_speed=10,
            wind_bearing=180
        )
        assert weather.temperature == 22.5
        assert weather.humidity == 65
    
    def test_weather_forecast(self):
        """Test WeatherForecast model."""
        forecast = WeatherForecast(
            date="2025-03-31",
            condition="Rainy",
            temp_min=15,
            temp_max=20,
            precipitation_chance=80
        )
        assert forecast.date == "2025-03-31"
        assert forecast.precipitation_chance == 80
    
    def test_energy_snapshot(self):
        """Test EnergySnapshot model."""
        energy = EnergySnapshot(
            pv_production_w=3500,
            grid_power_w=-1200,  # Exporting
            battery_charge_percent=78,
            house_consumption_w=1500,
            ev_charging_w=2300,
            pv_forecast_today_kwh=42.5,
            pv_forecast_tomorrow_kwh=38.2
        )
        assert energy.pv_production_w == 3500
        assert energy.grid_power_w == -1200  # Negative = exporting
        assert energy.battery_charge_percent == 78
    
    def test_training_load(self):
        """Test TrainingLoad model."""
        training = TrainingLoad(
            load_index=65,
            recovery_score=72,
            readiness="high",
            last_update="2025-03-31T08:00:00+02:00"
        )
        assert training.load_index == 65
        assert training.readiness == "high"
    
    def test_meal_plan(self):
        """Test MealPlan model."""
        meal = MealPlan(
            breakfast="Oatmeal with berries",
            lunch="Grilled chicken with vegetables",
            dinner="Fish and rice",
            notes="High protein for recovery"
        )
        assert meal.breakfast == "Oatmeal with berries"
        assert meal.notes == "High protein for recovery"
    
    def test_pending_task(self):
        """Test PendingTask model."""
        task = PendingTask(
            title="Finish sprint planning",
            due_date="2025-04-01",
            priority="high",
            tags=["work", "sprint"],
            energy_level="high"
        )
        assert task.priority == "high"
        assert "sprint" in task.tags
    
    def test_task_default_priority(self):
        """Test PendingTask with default priority."""
        task = PendingTask(title="Review code")
        assert task.priority == "medium"
    
    def test_cross_domain_snapshot_minimal(self):
        """Test CrossDomainContextSnapshot with minimal data."""
        snapshot = CrossDomainContextSnapshot(
            timestamp="2025-03-31T10:00:00+02:00",
            timezone="Europe/Berlin",
            today_date="2025-03-31",
        )
        assert snapshot.timestamp == "2025-03-31T10:00:00+02:00"
        assert snapshot.timezone == "Europe/Berlin"
        assert snapshot.calendar_events == []
        assert snapshot.pending_tasks == []
        assert snapshot.weather_current is None
    
    def test_cross_domain_snapshot_full(self):
        """Test CrossDomainContextSnapshot with full data."""
        snapshot = CrossDomainContextSnapshot(
            timestamp="2025-03-31T10:00:00+02:00",
            timezone="Europe/Berlin",
            today_date="2025-03-31",
            calendar_events=[
                CalendarEvent(
                    title="Standup",
                    start="2025-03-31T09:00:00+02:00",
                    end="2025-03-31T09:30:00+02:00",
                    calendar="family"
                )
            ],
            household_availability="home",
            weather_current=WeatherCondition(temperature=20, humidity=60),
            weather_forecast_today=WeatherForecast(date="2025-03-31", temp_max=22),
            weather_forecast_tomorrow=WeatherForecast(date="2025-04-01", temp_max=21),
            energy=EnergySnapshot(pv_production_w=3000, battery_charge_percent=80),
            training_load=TrainingLoad(load_index=50, recovery_score=75),
            meal_plan=MealPlan(breakfast="Coffee"),
            pending_tasks=[
                PendingTask(title="Write tests", priority="medium")
            ],
            data_available={
                "calendar": True,
                "weather": True,
                "energy": True,
                "training": True,
                "meals": True,
                "tasks": True,
            }
        )
        assert len(snapshot.calendar_events) == 1
        assert len(snapshot.pending_tasks) == 1
        assert snapshot.weather_current is not None
        assert snapshot.data_available["calendar"] is True
    
    def test_context_snapshot_partial_data(self):
        """Test context snapshot with only some data available."""
        snapshot = CrossDomainContextSnapshot(
            timestamp="2025-03-31T10:00:00+02:00",
            timezone="Europe/Berlin",
            today_date="2025-03-31",
            weather_current=WeatherCondition(temperature=20),
            # Other fields are optional and default to None/empty
            data_available={
                "weather": True,
                "calendar": False,
                "energy": False,
                "training": False,
                "meals": False,
                "tasks": False,
            }
        )
        assert snapshot.weather_current is not None
        assert snapshot.training_load is None
        assert snapshot.data_available["weather"] is True
        assert snapshot.data_available["calendar"] is False


class TestContextAggregationLogic:
    """Test context aggregation helper functions."""
    
    def test_context_snapshot_json_serializable(self):
        """Test that context snapshot can be serialized to JSON."""
        import json
        
        snapshot = CrossDomainContextSnapshot(
            timestamp="2025-03-31T10:00:00+02:00",
            timezone="Europe/Berlin",
            today_date="2025-03-31",
            calendar_events=[
                CalendarEvent(
                    title="Meeting",
                    start="2025-03-31T10:00:00+02:00",
                    end="2025-03-31T11:00:00+02:00",
                    calendar="family"
                )
            ],
            energy=EnergySnapshot(pv_production_w=3000),
        )
        
        # Should serialize to JSON without errors
        json_str = json.dumps(snapshot.model_dump())
        assert "Meeting" in json_str
        assert "2025-03-31" in json_str
    
    def test_context_models_iso_timestamps(self):
        """Test that all timestamps are ISO 8601 compatible."""
        from zoneinfo import ZoneInfo
        
        tz = ZoneInfo("Europe/Berlin")
        now = datetime.now(tz).isoformat()
        
        snapshot = CrossDomainContextSnapshot(
            timestamp=now,
            timezone="Europe/Berlin",
            today_date=now.split("T")[0],  # YYYY-MM-DD portion
        )
        
        # Verify timestamp format
        assert "T" in snapshot.timestamp
        assert "+" in snapshot.timestamp or "Z" in snapshot.timestamp


class TestDataAvailabilityTracking:
    """Test data_available quality indicators."""
    
    def test_data_available_all_present(self):
        """Test when all data sources are available."""
        snapshot = CrossDomainContextSnapshot(
            timestamp="2025-03-31T10:00:00+02:00",
            timezone="Europe/Berlin",
            today_date="2025-03-31",
            calendar_events=[CalendarEvent(
                title="Test", start="2025-03-31", end="2025-03-31", calendar="family"
            )],
            weather_current=WeatherCondition(temperature=20),
            energy=EnergySnapshot(pv_production_w=1000),
            training_load=TrainingLoad(load_index=50),
            meal_plan=MealPlan(breakfast="Toast"),
            pending_tasks=[PendingTask(title="Task")],
            data_available={
                "calendar": True,
                "weather": True,
                "energy": True,
                "training": True,
                "meals": True,
                "tasks": True,
            }
        )
        
        all_available = all(snapshot.data_available.values())
        assert all_available is True
    
    def test_data_available_partial(self):
        """Test when only some data sources are available."""
        snapshot = CrossDomainContextSnapshot(
            timestamp="2025-03-31T10:00:00+02:00",
            timezone="Europe/Berlin",
            today_date="2025-03-31",
            energy=EnergySnapshot(pv_production_w=1000),
            data_available={
                "calendar": False,
                "weather": False,
                "energy": True,
                "training": False,
                "meals": False,
                "tasks": False,
            }
        )
        
        available_count = sum(1 for v in snapshot.data_available.values() if v)
        assert available_count == 1
        assert snapshot.data_available["energy"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
