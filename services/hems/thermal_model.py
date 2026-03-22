"""Physics-based 1R1C thermal model per room."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("hems.thermal_model")

DEFAULT_U_EFF = 50.0       # W/K — effective heat loss coefficient
DEFAULT_CAPACITY = 300.0   # Wh/K — thermal capacity of the room


@dataclass
class PhysicsModelParams:
    u_eff: float = DEFAULT_U_EFF          # W/K
    thermal_capacity: float = DEFAULT_CAPACITY  # Wh/K
    fitted_at: Optional[str] = None       # ISO-8601 timestamp
    room_id: Optional[str] = None


class PhysicsModel:
    """Simple 1R1C (resistance-capacitance) thermal model for a single room.

    State equation (discrete, dt in minutes):
        delta_T = (P_heat - U_eff * (T_room - T_outdoor)) / (thermal_capacity * 3600 / dt) * dt
    where P_heat ≈ U_eff * (T_flow - T_room)  (simplified radiator model)
    """

    def __init__(self, room_id: str, params: Optional[PhysicsModelParams] = None):
        self.room_id = room_id
        self.params = params or PhysicsModelParams(room_id=room_id)

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict_temp_delta(
        self,
        flow_temp: float,
        outdoor_temp: float,
        current_temp: float,
        dt_minutes: float = 15.0,
    ) -> float:
        """Return predicted temperature change (°C) over dt_minutes.

        Args:
            flow_temp: Radiator/floor heating flow temperature (°C)
            outdoor_temp: Outdoor air temperature (°C)
            current_temp: Current room temperature (°C)
            dt_minutes: Time step in minutes (default 15)

        Returns:
            Predicted delta T in °C
        """
        u = self.params.u_eff               # W/K
        c = self.params.thermal_capacity    # Wh/K
        dt_h = dt_minutes / 60.0           # hours

        # Heat input from radiator (simplified — proportional to supply/room delta)
        p_heat = u * max(flow_temp - current_temp, 0.0)  # W

        # Net heat loss to outside
        p_loss = u * (current_temp - outdoor_temp)       # W

        # Net power into room
        p_net = p_heat - p_loss  # W  (= W * 1)

        # Temperature change: P_net [W] * dt [h] / C [Wh/K]
        delta_t = (p_net * dt_h) / c
        return delta_t

    # ------------------------------------------------------------------
    # Parameter fitting
    # ------------------------------------------------------------------

    def fit_parameters(self, training_data: list[dict]) -> PhysicsModelParams:
        """Fit U_eff and thermal_capacity from training data.

        training_data: list of dicts with keys:
            flow_temp, outdoor_temp, room_temp_before, room_temp_after, dt_minutes

        Falls back to defaults if data is empty or fitting fails.
        """
        if not training_data or len(training_data) < 5:
            logger.info(
                "room=%s: insufficient training data (%d rows) — using defaults",
                self.room_id,
                len(training_data) if training_data else 0,
            )
            self.params = PhysicsModelParams(
                u_eff=DEFAULT_U_EFF,
                thermal_capacity=DEFAULT_CAPACITY,
                fitted_at=datetime.now(timezone.utc).isoformat(),
                room_id=self.room_id,
            )
            return self.params

        try:
            from scipy.optimize import minimize  # type: ignore
            import numpy as np  # type: ignore

            flows = np.array([d["flow_temp"] for d in training_data], dtype=float)
            outdoors = np.array([d["outdoor_temp"] for d in training_data], dtype=float)
            t_before = np.array([d["room_temp_before"] for d in training_data], dtype=float)
            t_after = np.array([d["room_temp_after"] for d in training_data], dtype=float)
            dts = np.array([d.get("dt_minutes", 15.0) for d in training_data], dtype=float)
            observed_delta = t_after - t_before

            def residuals(x):
                u, c = x
                if c <= 0 or u <= 0:
                    return 1e9
                p_heat = u * np.maximum(flows - t_before, 0.0)
                p_loss = u * (t_before - outdoors)
                p_net = p_heat - p_loss
                dt_h = dts / 60.0
                predicted = (p_net * dt_h) / c
                return float(np.sum((predicted - observed_delta) ** 2))

            result = minimize(
                residuals,
                x0=[DEFAULT_U_EFF, DEFAULT_CAPACITY],
                bounds=[(1.0, 500.0), (10.0, 5000.0)],
                method="L-BFGS-B",
            )

            if result.success:
                u_fitted, c_fitted = result.x
                logger.info(
                    "room=%s: fitted U_eff=%.2f W/K, capacity=%.2f Wh/K (n=%d)",
                    self.room_id, u_fitted, c_fitted, len(training_data),
                )
            else:
                logger.warning("room=%s: fitting did not converge — using defaults", self.room_id)
                u_fitted, c_fitted = DEFAULT_U_EFF, DEFAULT_CAPACITY

        except ImportError:
            logger.warning("scipy not available — using default thermal parameters")
            u_fitted, c_fitted = DEFAULT_U_EFF, DEFAULT_CAPACITY
        except Exception as exc:
            logger.warning("room=%s: fitting error (%s) — using defaults", self.room_id, exc)
            u_fitted, c_fitted = DEFAULT_U_EFF, DEFAULT_CAPACITY

        self.params = PhysicsModelParams(
            u_eff=float(u_fitted),
            thermal_capacity=float(c_fitted),
            fitted_at=datetime.now(timezone.utc).isoformat(),
            room_id=self.room_id,
        )
        return self.params

    # ------------------------------------------------------------------
    # Persistence helpers (JSON ↔ hems_config)
    # ------------------------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self.params))

    @classmethod
    def from_json(cls, room_id: str, raw: str) -> "PhysicsModel":
        data = json.loads(raw)
        params = PhysicsModelParams(**data)
        model = cls(room_id=room_id, params=params)
        return model
