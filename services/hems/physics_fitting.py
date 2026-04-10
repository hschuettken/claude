"""Physics parameter fitting and NN/physics confidence blending (#1031 #1032).

Bootstrap weeks 0-4: use scipy to fit thermal model parameters from data.
After sufficient NN training, blend predictions by confidence.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def fit_thermal_parameters(
    temps: np.ndarray,
    outside_temps: np.ndarray,
    heat_inputs: np.ndarray,
    dt_hours: float = 1.0,
) -> dict:
    """Fit thermal_capacity (C) and heat_loss_coeff (UA) via linear regression (#1031).

    Uses simple thermal model: C * dT/dt = Q_heat - UA * (T_room - T_out)
    Reformulated as linear regression: dT = a * Q_heat + b * (T_room - T_out)
    where a = dt/C, b = -UA*dt/C

    Args:
        temps: (N,) room temperatures in °C
        outside_temps: (N,) outdoor temperatures in °C
        heat_inputs: (N,) heat input in kW
        dt_hours: time step in hours (default 1.0)

    Returns:
        dict with thermal_capacity_kwh_per_K, heat_loss_coeff_kW_per_K, r_squared,
        samples, or error key on failure.
    """
    try:
        from numpy.linalg import lstsq

        if len(temps) < 10:
            return {"error": "insufficient_data", "samples": len(temps)}

        dT = np.diff(temps)
        T_avg = (temps[:-1] + temps[1:]) / 2
        T_delta = T_avg - outside_temps[: len(dT)]
        Q = heat_inputs[: len(dT)]

        # Stack: [Q, -delta_T] → target: dT
        A = np.column_stack([Q, -T_delta])

        # Linear regression: dT ≈ a*Q - b*delta_T
        coeffs, _residuals, _rank, _sv = lstsq(A, dT, rcond=None)
        a, b = coeffs

        C = dt_hours / max(a, 1e-6)
        UA = b * C / max(dt_hours, 1e-6)

        dT_pred = A @ coeffs
        ss_res = np.sum((dT - dT_pred) ** 2)
        ss_tot = np.sum((dT - dT.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0

        logger.info("Fitted: C=%.2f kWh/K, UA=%.3f kW/K, R²=%.3f", C, UA, r2)
        return {
            "thermal_capacity_kwh_per_K": round(C, 3),
            "heat_loss_coeff_kW_per_K": round(UA, 4),
            "r_squared": round(r2, 4),
            "samples": len(dT),
        }
    except Exception as e:
        logger.error("Physics fitting failed: %s", e)
        return {"error": str(e)}


class ConfidenceBlender:
    """Blend NN and physics predictions by confidence (#1032).

    Bootstrap weeks 0-4: pure physics (NN has no data yet).
    After week 4: blend proportionally to NN training data count.
    Week 8+: prefer NN if its validation loss < physics RMSE.
    """

    def __init__(self, nn_sample_threshold: int = 500):
        self.nn_sample_threshold = nn_sample_threshold
        self._nn_samples_seen: int = 0
        self._nn_val_loss: Optional[float] = None
        self._physics_rmse: Optional[float] = None

    def update_nn_stats(self, samples_seen: int, val_loss: float) -> None:
        self._nn_samples_seen = samples_seen
        self._nn_val_loss = val_loss

    def update_physics_stats(self, rmse: float) -> None:
        self._physics_rmse = rmse

    def blend(self, nn_pred: float, physics_pred: float) -> tuple[float, float]:
        """Returns (blended_prediction, nn_weight)."""
        if self._nn_samples_seen < self.nn_sample_threshold:
            # Bootstrap: pure physics
            nn_weight = 0.0
        elif self._nn_val_loss is not None and self._physics_rmse is not None:
            # Quality-based blend: higher nn_weight when physics RMSE is worse
            total = self._nn_val_loss + self._physics_rmse
            if total > 0:
                nn_weight = self._physics_rmse / total
            else:
                nn_weight = 0.5
        else:
            # Gradual ramp up to 0.25 weight as samples accumulate
            nn_weight = min(1.0, self._nn_samples_seen / (self.nn_sample_threshold * 4))

        blended = nn_weight * nn_pred + (1 - nn_weight) * physics_pred
        return blended, nn_weight

    def get_status(self) -> dict:
        _, nn_w = self.blend(0.0, 0.0)
        return {
            "nn_samples_seen": self._nn_samples_seen,
            "nn_weight": round(nn_w, 3),
            "physics_weight": round(1 - nn_w, 3),
            "mode": "physics" if nn_w < 0.1 else "blended" if nn_w < 0.9 else "nn",
        }
