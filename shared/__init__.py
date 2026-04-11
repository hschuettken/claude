"""Shared library for homelab automation services."""

from shared.config import Settings
from shared.energy_events import (
    EVChargingCompleted,
    EVChargingStarted,
    EVDrainBudgetExhausted,
    EVDrainRefillComplete,
    EVDrainStarted,
    EVModeChanged,
    EVPlanUpdated,
    EVSurplusAvailable,
    PVAnomalyDetected,
    PVDriftDetected,
    PVForecastAccuracyResult,
    PVForecastUpdated,
    PVModelRetrained,
    SolarDaylightWindow,
)
from shared.influx_client import InfluxClient
from shared.log import get_logger
from shared.nats_client import NatsPublisher

__all__ = [
    "Settings",
    "get_logger",
    "InfluxClient",
    "NatsPublisher",
    # PV events
    "PVForecastUpdated",
    "PVModelRetrained",
    "PVAnomalyDetected",
    "PVDriftDetected",
    "SolarDaylightWindow",
    "PVForecastAccuracyResult",
    # EV events
    "EVPlanUpdated",
    "EVChargingStarted",
    "EVChargingCompleted",
    "EVModeChanged",
    "EVSurplusAvailable",
    "EVDrainStarted",
    "EVDrainBudgetExhausted",
    "EVDrainRefillComplete",
]
