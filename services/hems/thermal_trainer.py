"""ThermalNNTrainer — InfluxDB-to-DataLoader training pipeline (#1028 #1029 #1030).

Fetches 28-feature tensors from InfluxDB, trains ThermalPINN.
Schedules: 6h incremental fine-tune, weekly full retrain (Sunday 02:00).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import torch
import numpy as np

from .thermal_nn import ThermalPINN, physics_informed_loss, FEATURE_NAMES

logger = logging.getLogger(__name__)


class ThermalNNTrainer:
    """Manages training lifecycle for ThermalPINN (#1028).

    Incremental: fine-tune on last 6h of data every 6 hours.
    Full retrain: all available data, Sunday 02:00.
    """

    def __init__(
        self,
        model: Optional[ThermalPINN] = None,
        influx_url: str = "http://192.168.0.66:8086",
        influx_token: str = "",
        influx_org: str = "nb9",
        device: str = "cpu",
    ):
        self.model = model or ThermalPINN()
        self.model.to(device)
        self.device = device
        self.influx_url = influx_url
        self.influx_token = influx_token
        self.influx_org = influx_org
        self._last_full_train: Optional[datetime] = None
        self._last_incremental: Optional[datetime] = None

    async def fetch_features(self, hours: int = 168) -> Optional[np.ndarray]:
        """Fetch 28-feature tensors from InfluxDB thermal_training measurement (#1026).

        Returns array of shape (n_samples, 28) or None on failure.
        """
        try:
            import httpx

            flux_query = f"""
from(bucket: "hems")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r._measurement == "thermal_training")
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
"""
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    f"{self.influx_url}/api/v2/query",
                    headers={
                        "Authorization": f"Token {self.influx_token}",
                        "Content-Type": "application/vnd.flux",
                        "Accept": "application/csv",
                    },
                    params={"org": self.influx_org},
                    content=flux_query,
                )
                if r.status_code != 200:
                    logger.warning("InfluxDB query failed: %s", r.status_code)
                    return None

                # Parse CSV response
                lines = r.text.strip().split("\n")
                if len(lines) < 2:
                    return None

                headers = lines[0].split(",")
                rows = []
                for line in lines[1:]:
                    if line.startswith("#") or not line.strip():
                        continue
                    vals = line.split(",")
                    row = {}
                    for h, v in zip(headers, vals):
                        h = h.strip()
                        if h in FEATURE_NAMES:
                            try:
                                row[h] = float(v)
                            except ValueError:
                                row[h] = 0.0
                    rows.append(row)

                if not rows:
                    return None

                # Build feature matrix
                matrix = np.array(
                    [[row.get(f, 0.0) for f in FEATURE_NAMES] for row in rows],
                    dtype=np.float32,
                )
                return matrix
        except Exception as e:
            logger.error("Feature fetch failed: %s", e)
            return None

    def _make_sequences(
        self,
        features: np.ndarray,
        seq_len: int = 24,
        target_col: int = 5,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Build (X, y_delta, room_ids) tensors from feature matrix."""
        X_list, y_list, room_list = [], [], []

        for i in range(seq_len, len(features) - 1):
            seq = features[i - seq_len : i]  # (seq_len, 28)
            current_temp = seq[-1, target_col]
            next_temp = features[i + 1, target_col]
            delta = next_temp - current_temp

            X_list.append(seq)
            y_list.append(delta)
            room_list.append(0)  # room 0 for now; multi-room: cycle through rooms

        if not X_list:
            raise ValueError("Not enough data for sequences")

        X = torch.from_numpy(np.stack(X_list))
        y = torch.tensor(y_list, dtype=torch.float32)
        rooms = torch.tensor(room_list, dtype=torch.long)
        return X, y, rooms

    async def incremental_train(self, epochs: int = 5, lr: float = 1e-4):
        """Fine-tune on last 6 hours of data (#1029)."""
        logger.info("Incremental thermal model training starting")
        features = await self.fetch_features(hours=6)
        if features is None or len(features) < 30:
            logger.warning("Not enough data for incremental training")
            return
        await self._train(features, epochs=epochs, lr=lr, label="incremental")
        self._last_incremental = datetime.now(timezone.utc)

    async def full_retrain(self, epochs: int = 50, lr: float = 1e-3):
        """Full retrain on all data (#1030)."""
        logger.info("Full thermal model retrain starting")
        features = await self.fetch_features(hours=24 * 90)  # 90 days
        if features is None or len(features) < 100:
            logger.warning("Not enough data for full retrain")
            return
        await self._train(features, epochs=epochs, lr=lr, label="full")
        self._last_full_train = datetime.now(timezone.utc)

    async def _train(self, features: np.ndarray, epochs: int, lr: float, label: str):
        """Core training loop."""
        try:
            X, y, rooms = self._make_sequences(features)
        except ValueError as e:
            logger.warning("Training skipped: %s", e)
            return

        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        self.model.train()
        loss = torch.tensor(0.0)

        for epoch in range(epochs):
            optimizer.zero_grad()
            pred, residual = self.model(X.to(self.device), rooms.to(self.device))
            loss = physics_informed_loss(pred, y.to(self.device), residual)
            loss.backward()
            optimizer.step()

            if epoch % 10 == 0:
                logger.info(
                    "[%s] epoch %d/%d, loss=%.4f", label, epoch, epochs, loss.item()
                )

        self.model.eval()
        logger.info("[%s] training complete, final loss=%.4f", label, loss.item())

    async def run_schedule(self):
        """Run training schedule: 6h incremental + Sunday 02:00 full retrain (#1029 #1030)."""
        logger.info("Thermal trainer scheduler starting")
        while True:
            now = datetime.now(timezone.utc)

            # Sunday 02:00 full retrain
            if now.weekday() == 6 and now.hour == 2:
                if (
                    self._last_full_train is None
                    or (now - self._last_full_train).days >= 7
                ):
                    await self.full_retrain()

            # 6h incremental
            if (
                self._last_incremental is None
                or (now - self._last_incremental).total_seconds() >= 6 * 3600
            ):
                await self.incremental_train()

            await asyncio.sleep(3600)  # Check every hour
