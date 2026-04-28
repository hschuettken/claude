"""Tests for GET /api/v1/vision endpoint."""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock

SERVICE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "orchestrator")
)
SHARED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shared")
)
for d in (SERVICE_DIR, SHARED_DIR):
    if d not in sys.path:
        sys.path.insert(0, d)

# Stub heavy dependencies before importing api.routes
_log_stub = MagicMock()
_log_stub.get_logger.return_value = MagicMock(
    info=MagicMock(), warning=MagicMock(), debug=MagicMock(), exception=MagicMock()
)
sys.modules.setdefault("shared", MagicMock())
sys.modules.setdefault("shared.log", _log_stub)
sys.modules.setdefault("config", MagicMock())
sys.modules.setdefault("tools", MagicMock(TOOL_DEFINITIONS=[]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import routes
from api.models import VisionSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(service_states: dict | None = None) -> FastAPI:
    app = FastAPI()
    routes.configure(
        brain=None,
        tool_executor=None,
        activity=None,
        settings=None,
        service_states=service_states or {},
        start_time=0.0,
    )
    app.include_router(routes.router)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestVisionEndpoint:
    def test_returns_200(self):
        resp = TestClient(_make_app()).get("/api/v1/vision")
        assert resp.status_code == 200

    def test_response_shape(self):
        data = TestClient(_make_app()).get("/api/v1/vision").json()
        assert "north_star" in data
        assert "areas" in data
        assert "areas_total" in data
        assert "services_online" in data

    def test_north_star_non_empty(self):
        data = TestClient(_make_app()).get("/api/v1/vision").json()
        assert len(data["north_star"]) > 20

    def test_12_areas(self):
        data = TestClient(_make_app()).get("/api/v1/vision").json()
        assert data["areas_total"] == 12
        assert len(data["areas"]) == 12

    def test_area_ids_sequential(self):
        areas = TestClient(_make_app()).get("/api/v1/vision").json()["areas"]
        assert [a["id"] for a in areas] == list(range(1, 13))

    def test_areas_without_service_are_planned(self):
        areas = TestClient(_make_app()).get("/api/v1/vision").json()["areas"]
        for area in areas:
            if area["service"] is None:
                assert area["status"] == "planned"

    def test_online_service_reflected(self):
        states = {"cognitive-layer": {"status": "online"}}
        data = TestClient(_make_app(states)).get("/api/v1/vision").json()
        cognitive = next(a for a in data["areas"] if a["id"] == 1)
        assert cognitive["status"] == "online"
        assert data["services_online"] == 1

    def test_offline_service_reflected(self):
        states = {"digital-twin": {"status": "offline"}}
        areas = TestClient(_make_app(states)).get("/api/v1/vision").json()["areas"]
        twin = next(a for a in areas if a["id"] == 3)
        assert twin["status"] == "offline"

    def test_unknown_status_when_no_heartbeat(self):
        areas = TestClient(_make_app()).get("/api/v1/vision").json()["areas"]
        cognitive = next(a for a in areas if a["id"] == 1)
        assert cognitive["status"] == "unknown"

    def test_services_online_count(self):
        states = {
            "cognitive-layer": {"status": "online"},
            "agent-economy": {"status": "online"},
            "digital-twin": {"status": "offline"},
        }
        data = TestClient(_make_app(states)).get("/api/v1/vision").json()
        assert data["services_online"] == 2

    def test_pydantic_model_validates(self):
        data = TestClient(_make_app()).get("/api/v1/vision").json()
        summary = VisionSummary(**data)
        assert summary.areas_total == 12

    def test_area_12_is_autonomous_saturday(self):
        areas = TestClient(_make_app()).get("/api/v1/vision").json()["areas"]
        last = next(a for a in areas if a["id"] == 12)
        assert "Autonomous Saturday" in last["title"]
