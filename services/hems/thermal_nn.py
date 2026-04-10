"""Physics-Informed Neural Network (PINN) for thermal modeling (#1025 #1026 #1027).

Architecture: PyTorch LSTM with room embeddings.
28 input features from InfluxDB.
Physics-informed loss: energy balance residual.

Features (28 total):
  Weather (5): outside_temp, solar_irradiance, wind_speed, humidity, cloud_cover
  House state (8): room_temp_x4, flow_temp, return_temp, boiler_on, dhw_on
  Energy (5): pv_power, grid_import, grid_export, heat_meter, ev_charging
  Time (4): hour_sin, hour_cos, day_sin, day_cos
  Derived (6): delta_temp_inside_outside, thermal_mass_indicator,
               solar_gain_estimate, occupancy_proxy, setpoint_delta,
               prev_hour_avg_temp
"""

from __future__ import annotations

import logging

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    # Weather
    "outside_temp",
    "solar_irradiance",
    "wind_speed",
    "humidity",
    "cloud_cover",
    # House state
    "room_temp_0",
    "room_temp_1",
    "room_temp_2",
    "room_temp_3",
    "flow_temp",
    "return_temp",
    "boiler_on",
    "dhw_on",
    # Energy
    "pv_power",
    "grid_import",
    "grid_export",
    "heat_meter",
    "ev_charging",
    # Time encoding
    "hour_sin",
    "hour_cos",
    "day_sin",
    "day_cos",
    # Derived
    "delta_temp_in_out",
    "thermal_mass_indicator",
    "solar_gain_estimate",
    "occupancy_proxy",
    "setpoint_delta",
    "prev_hour_avg_temp",
]
N_FEATURES = len(FEATURE_NAMES)  # 28
N_ROOMS = 4


class ThermalPINN(nn.Module):
    """Physics-Informed LSTM for room temperature prediction.

    Predicts next-hour room temperatures given current state.
    Physics loss enforces energy balance: dT/dt = (Q_heat - Q_loss) / C_thermal
    """

    def __init__(
        self,
        n_features: int = N_FEATURES,
        n_rooms: int = N_ROOMS,
        hidden_size: int = 64,
        n_layers: int = 2,
        room_embed_dim: int = 8,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.n_rooms = n_rooms
        self.hidden_size = hidden_size

        # Room embedding
        self.room_embed = nn.Embedding(n_rooms, room_embed_dim)

        # LSTM backbone
        lstm_input = n_features + room_embed_dim
        self.lstm = nn.LSTM(
            input_size=lstm_input,
            hidden_size=hidden_size,
            num_layers=n_layers,
            dropout=dropout if n_layers > 1 else 0.0,
            batch_first=True,
        )

        # Output head: predict temperature delta (dT for next hour)
        self.head = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

        # Physics parameters (learnable)
        self.log_thermal_capacity = nn.Parameter(torch.tensor(2.0))  # log(C) kWh/°C
        self.log_heat_loss_coeff = nn.Parameter(torch.tensor(0.5))  # log(UA) kW/°C

    def forward(
        self,
        x: torch.Tensor,  # (batch, seq_len, n_features)
        room_id: torch.Tensor,  # (batch,) room indices
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass. Returns (pred_delta_T, physics_residual)."""
        batch, seq_len, _ = x.shape

        # Room embedding
        embed = self.room_embed(room_id)  # (batch, embed_dim)
        embed_expanded = embed.unsqueeze(1).expand(
            -1, seq_len, -1
        )  # (batch, seq, embed)

        # Concatenate features + room embedding
        x_in = torch.cat([x, embed_expanded], dim=-1)  # (batch, seq, feats+embed)

        # LSTM
        out, _ = self.lstm(x_in)  # (batch, seq, hidden)
        last_out = out[:, -1, :]  # (batch, hidden)

        # Predict delta T
        pred_delta = self.head(last_out).squeeze(-1)  # (batch,)

        # Physics residual: dT = (Q_heat - UA * (T_room - T_outside)) / C
        C = torch.exp(self.log_thermal_capacity)
        UA = torch.exp(self.log_heat_loss_coeff)
        T_room = x[:, -1, 5]  # room_temp_0 at last timestep
        T_out = x[:, -1, 0]  # outside_temp at last timestep
        Q_heat = x[:, -1, 13] * 0.001  # heat_meter W → kW approx

        physics_dT = (Q_heat - UA * (T_room - T_out)) / C
        residual = pred_delta - physics_dT  # should be near 0

        return pred_delta, residual

    @property
    def thermal_capacity_kwh_per_K(self) -> float:
        return float(torch.exp(self.log_thermal_capacity).item())

    @property
    def heat_loss_coeff_kW_per_K(self) -> float:
        return float(torch.exp(self.log_heat_loss_coeff).item())


def physics_informed_loss(
    pred_delta: torch.Tensor,
    true_delta: torch.Tensor,
    physics_residual: torch.Tensor,
    lambda_physics: float = 0.1,
) -> torch.Tensor:
    """Combined MSE + physics residual loss (#1027)."""
    mse_loss = nn.functional.mse_loss(pred_delta, true_delta)
    physics_loss = (physics_residual**2).mean()
    return mse_loss + lambda_physics * physics_loss
