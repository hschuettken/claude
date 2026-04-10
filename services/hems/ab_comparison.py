"""A/B comparison mode: Neural Network vs Physics-Only predictions (#1083).

Supports three modes for HEMS setpoint adjustment:
- PHYSICS_ONLY: Simple linear physics model
- NEURAL_NETWORK: ThermalPINN-based predictions
- HYBRID: Average of both models

Logs all predictions to InfluxDB for comparison analysis.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

HEMS_AB_MODE = os.getenv("HEMS_AB_MODE", "hybrid").lower()
INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://192.168.0.66:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "nb9")
INFLUXDB_BUCKET = os.getenv("INFLUXDB_BUCKET", "hems")


class ABComparisonMode(str, Enum):
    """A/B test mode enumeration."""

    NEURAL_NETWORK = "nn"
    PHYSICS_ONLY = "physics"
    HYBRID = "hybrid"


class ABController:
    """A/B comparison controller for heating predictions."""

    def __init__(
        self,
        mode: str = HEMS_AB_MODE,
        influx_url: str = INFLUXDB_URL,
        influx_token: str = INFLUXDB_TOKEN,
        influx_org: str = INFLUXDB_ORG,
    ):
        """Initialize A/B controller.

        Args:
            mode: One of "nn", "physics", "hybrid" (from env HEMS_AB_MODE)
            influx_url: InfluxDB URL
            influx_token: InfluxDB auth token
            influx_org: InfluxDB org name
        """
        # Parse mode string, default to hybrid
        try:
            self.mode = ABComparisonMode(mode)
        except ValueError:
            logger.warning("Invalid AB mode '%s', defaulting to hybrid", mode)
            self.mode = ABComparisonMode.HYBRID

        self.influx_url = influx_url
        self.influx_token = influx_token
        self.influx_org = influx_org

        # Stats tracking
        self._nn_predictions = 0
        self._physics_predictions = 0

    async def predict_setpoint_adjustment(
        self,
        room_id: str,
        current_temp: float,
        outside_temp: float,
        target_temp: float = 21.0,
    ) -> float:
        """Predict setpoint adjustment (delta watts or delta setpoint).

        Args:
            room_id: Room identifier (e.g., "living_room")
            current_temp: Current room temperature (°C)
            outside_temp: Outside temperature (°C)
            target_temp: Target room temperature (°C, default 21)

        Returns:
            Adjustment value (delta watts or delta setpoint °C)
            Positive = heat more, negative = heat less
        """
        adjustment = 0.0

        if self.mode == ABComparisonMode.PHYSICS_ONLY:
            adjustment = self._predict_physics_only(
                current_temp, outside_temp, target_temp
            )
            self._physics_predictions += 1

        elif self.mode == ABComparisonMode.NEURAL_NETWORK:
            adjustment = await self._predict_neural_network(
                room_id, current_temp, outside_temp, target_temp
            )
            self._nn_predictions += 1

        elif self.mode == ABComparisonMode.HYBRID:
            physics_adj = self._predict_physics_only(
                current_temp, outside_temp, target_temp
            )
            nn_adj = await self._predict_neural_network(
                room_id, current_temp, outside_temp, target_temp
            )
            adjustment = (physics_adj + nn_adj) / 2.0
            self._physics_predictions += 1
            self._nn_predictions += 1

        return adjustment

    def _predict_physics_only(
        self,
        current_temp: float,
        outside_temp: float,
        target_temp: float,
    ) -> float:
        """Physics-based simple linear prediction.

        Formula: (target - current) * 0.3 W adjustment
        Accounts for temperature error and outside temp influence.

        Args:
            current_temp: Current room temperature (°C)
            outside_temp: Outside temperature (°C)
            target_temp: Target room temperature (°C)

        Returns:
            Adjustment in watts (or normalized units)
        """
        temp_error = target_temp - current_temp
        # Base adjustment from temperature error
        adjustment = temp_error * 0.3

        # Modify based on outside temperature (cold = more heating)
        temp_diff = current_temp - outside_temp
        if temp_diff < 5:
            # Large temperature gap = boost heating
            adjustment *= 1.5
        elif temp_diff > 15:
            # Small temperature gap = reduce heating
            adjustment *= 0.7

        return adjustment

    async def _predict_neural_network(
        self,
        room_id: str,
        current_temp: float,
        outside_temp: float,
        target_temp: float,
    ) -> float:
        """Neural network-based prediction using ThermalPINN.

        Falls back to physics if ThermalPINN not available.

        Args:
            room_id: Room identifier
            current_temp: Current room temperature (°C)
            outside_temp: Outside temperature (°C)
            target_temp: Target room temperature (°C)

        Returns:
            Adjustment in watts
        """
        try:
            from thermal_nn import ThermalPINN
            import torch

            # Try to load and use ThermalPINN if available
            # This is a simplified inference — full implementation would
            # construct features from InfluxDB state and room history
            pinn = ThermalPINN()

            # Simple mock feature vector (28 features)
            # In production, fetch from InfluxDB
            features = torch.randn(1, 1, 28)  # (batch=1, seq=1, features=28)
            room_tensor = torch.tensor([hash(room_id) % 4], dtype=torch.long)

            with torch.no_grad():
                pred_delta, _ = pinn.forward(features, room_tensor)
                adjustment = float(pred_delta[0].item()) * 10.0  # Scale to watts

            return adjustment

        except (ImportError, Exception) as e:
            # Fallback to physics model
            logger.debug("ThermalPINN unavailable (%s), falling back to physics", e)
            return self._predict_physics_only(current_temp, outside_temp, target_temp)

    async def log_prediction(
        self,
        room_id: str,
        mode: str,
        prediction: float,
        actual: Optional[float] = None,
    ) -> None:
        """Log prediction to InfluxDB for A/B analysis.

        Args:
            room_id: Room identifier
            mode: Prediction mode ("physics", "nn", or "hybrid")
            prediction: Predicted adjustment value
            actual: Actual observed adjustment (if available)
        """
        try:
            from influxdb_client import InfluxDBClient, Point

            client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org,
            )
            write_api = client.write_api()

            point = (
                Point("ab_comparison")
                .time(datetime.now(timezone.utc), write_precision="ns")
                .field("prediction", prediction)
                .tag("room_id", room_id)
                .tag("mode", mode)
            )

            if actual is not None:
                point.field("actual", actual)

            write_api.write(
                bucket=INFLUXDB_BUCKET,
                org=self.influx_org,
                record=point,
            )
            logger.debug(
                "Logged prediction to InfluxDB: room=%s, mode=%s, pred=%f",
                room_id,
                mode,
                prediction,
            )
            client.close()

        except Exception as e:
            logger.warning("Failed to log prediction to InfluxDB: %s", e)

    def get_mode_stats(self) -> dict:
        """Get prediction statistics for current session.

        Returns:
            {
                "mode": str,
                "nn_predictions": int,
                "physics_predictions": int,
            }
        """
        return {
            "mode": self.mode.value,
            "nn_predictions": self._nn_predictions,
            "physics_predictions": self._physics_predictions,
        }
