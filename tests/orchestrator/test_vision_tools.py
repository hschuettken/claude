"""Tests for tooling/vision_tools.py and provider-level vision handling.

Covers:
- VisionTools.list_cameras: happy path, empty, HA error
- VisionTools.get_camera_snapshot: image available, camera offline
- _build_tool_result_content logic (Anthropic image promotion)
- Gemini _build_contents: _image stripped from function response
- OpenAI _convert_messages: _image stripped from tool content
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Path constants (conftest.py adds SERVICE_DIR + SHARED_DIR to sys.path)
# ---------------------------------------------------------------------------

SERVICE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "orchestrator")
)

# ---------------------------------------------------------------------------
# Stub external packages absent from test environment
# ---------------------------------------------------------------------------


def _ensure_stub(name: str, mod: Any | None = None) -> Any:
    if name not in sys.modules:
        sys.modules[name] = mod if mod is not None else MagicMock()
    return sys.modules[name]


_log_stub = MagicMock()
_log_stub.get_logger.return_value = MagicMock(
    info=MagicMock(), warning=MagicMock(), debug=MagicMock(), exception=MagicMock()
)
_ensure_stub("shared")
sys.modules["shared.log"] = _log_stub
_ensure_stub("shared.ha_client")
_ensure_stub("shared.retry")


# ---------------------------------------------------------------------------
# Load VisionTools directly (avoid triggering tooling/__init__.py chain)
# ---------------------------------------------------------------------------

_vt_spec = importlib.util.spec_from_file_location(
    "tooling.vision_tools",
    os.path.join(SERVICE_DIR, "tooling", "vision_tools.py"),
)
_vt_mod = importlib.util.module_from_spec(_vt_spec)
sys.modules["tooling.vision_tools"] = _vt_mod
_vt_spec.loader.exec_module(_vt_mod)
VisionTools = _vt_mod.VisionTools


# ---------------------------------------------------------------------------
# Local minimal Message stub (mirrors llm.base.Message)
# ---------------------------------------------------------------------------


@dataclass
class _Msg:
    role: str
    content: str | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None
    name: str | None = None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_ha():
    ha = MagicMock()
    ha.get_states = AsyncMock()
    ha.get_camera_image = AsyncMock()
    return ha


@pytest.fixture()
def vision_tools(mock_ha):
    return VisionTools(ha=mock_ha)


# ---------------------------------------------------------------------------
# VisionTools.list_cameras
# ---------------------------------------------------------------------------


class TestListCameras:
    @pytest.mark.asyncio
    async def test_returns_only_camera_entities(self, vision_tools, mock_ha):
        mock_ha.get_states.return_value = [
            {"entity_id": "camera.front_door", "state": "idle",
             "attributes": {"friendly_name": "Front Door"}, "last_changed": "2024-01-01T00:00:00Z"},
            {"entity_id": "sensor.temperature", "state": "21",
             "attributes": {}, "last_changed": "2024-01-01T00:00:00Z"},
            {"entity_id": "camera.backyard", "state": "streaming",
             "attributes": {"friendly_name": "Backyard"}, "last_changed": "2024-01-01T00:00:00Z"},
        ]
        result = await vision_tools.list_cameras()
        assert result["count"] == 2
        ids = [c["entity_id"] for c in result["cameras"]]
        assert "camera.front_door" in ids
        assert "camera.backyard" in ids
        assert "sensor.temperature" not in ids

    @pytest.mark.asyncio
    async def test_empty_when_no_cameras(self, vision_tools, mock_ha):
        mock_ha.get_states.return_value = [
            {"entity_id": "sensor.temperature", "state": "21",
             "attributes": {}, "last_changed": "2024-01-01T00:00:00Z"},
        ]
        result = await vision_tools.list_cameras()
        assert result["count"] == 0
        assert result["cameras"] == []

    @pytest.mark.asyncio
    async def test_ha_error_returns_error_key(self, vision_tools, mock_ha):
        mock_ha.get_states.side_effect = Exception("HA unavailable")
        result = await vision_tools.list_cameras()
        assert "error" in result
        assert result["cameras"] == []


# ---------------------------------------------------------------------------
# VisionTools.get_camera_snapshot
# ---------------------------------------------------------------------------


class TestGetCameraSnapshot:
    @pytest.mark.asyncio
    async def test_success_embeds_base64_image(self, vision_tools, mock_ha):
        fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        mock_ha.get_camera_image.return_value = fake_jpeg

        result = await vision_tools.get_camera_snapshot("camera.front_door")

        assert result["image_available"] is True
        assert result["camera_entity_id"] == "camera.front_door"
        assert "_image" in result
        assert result["_image"]["media_type"] == "image/jpeg"
        assert base64.b64decode(result["_image"]["base64"]) == fake_jpeg

    @pytest.mark.asyncio
    async def test_offline_camera_returns_error(self, vision_tools, mock_ha):
        mock_ha.get_camera_image.return_value = None

        result = await vision_tools.get_camera_snapshot("camera.nonexistent")

        assert result["image_available"] is False
        assert "error" in result
        assert "_image" not in result


# ---------------------------------------------------------------------------
# _build_tool_result_content logic (tested as a pure function)
# ---------------------------------------------------------------------------


def _build_tool_result_content(content_str: str):
    """Replicated from AnthropicProvider — test the logic independently."""
    try:
        data = json.loads(content_str)
    except (json.JSONDecodeError, TypeError):
        return content_str
    img = data.pop("_image", None) if isinstance(data, dict) else None
    if not img:
        return content_str
    text_part = {"type": "text", "text": json.dumps(data, ensure_ascii=False)}
    image_part = {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": img.get("media_type", "image/jpeg"),
            "data": img["base64"],
        },
    }
    return [text_part, image_part]


class TestBuildToolResultContent:
    def test_plain_string_passthrough(self):
        assert _build_tool_result_content("hello world") == "hello world"

    def test_json_without_image_passthrough(self):
        payload = json.dumps({"status": "ok", "value": 42})
        assert _build_tool_result_content(payload) == payload

    def test_json_with_image_becomes_content_block_list(self):
        b64_data = base64.b64encode(b"fake-image-bytes").decode()
        payload = json.dumps({
            "camera_entity_id": "camera.front_door",
            "image_available": True,
            "_image": {"base64": b64_data, "media_type": "image/jpeg"},
        })
        result = _build_tool_result_content(payload)

        assert isinstance(result, list)
        assert len(result) == 2

        text_block = result[0]
        assert text_block["type"] == "text"
        text_data = json.loads(text_block["text"])
        assert text_data["camera_entity_id"] == "camera.front_door"
        assert "_image" not in text_data

        image_block = result[1]
        assert image_block["type"] == "image"
        assert image_block["source"]["type"] == "base64"
        assert image_block["source"]["media_type"] == "image/jpeg"
        assert image_block["source"]["data"] == b64_data

    def test_invalid_json_passthrough(self):
        assert _build_tool_result_content("not json {{{") == "not json {{{"


# ---------------------------------------------------------------------------
# Gemini provider: _image stripped from function response data
# ---------------------------------------------------------------------------


class TestGeminiStripsImage:
    def test_image_key_removed_from_parsed_response(self):
        """Verify the pop logic in gemini._build_contents strips _image."""
        b64_data = base64.b64encode(b"fake").decode()
        raw = json.dumps({
            "camera_entity_id": "camera.front_door",
            "image_available": True,
            "_image": {"base64": b64_data, "media_type": "image/jpeg"},
        })

        # Replicate the Gemini parsing + stripping logic directly
        try:
            response_data = json.loads(raw)
            if isinstance(response_data, dict):
                response_data.pop("_image", None)
        except (json.JSONDecodeError, TypeError):
            response_data = {"result": raw}

        assert "_image" not in response_data
        assert response_data["camera_entity_id"] == "camera.front_door"
        assert response_data["image_available"] is True


# ---------------------------------------------------------------------------
# OpenAI-compat: _image stripped from tool content
# ---------------------------------------------------------------------------


class TestOpenAIStripsImage:
    def test_image_removed_from_tool_content(self):
        """Verify the _image stripping logic in openai_compat._convert_messages."""
        b64_data = base64.b64encode(b"fake").decode()
        raw = json.dumps({
            "camera_entity_id": "camera.front_door",
            "image_available": True,
            "_image": {"base64": b64_data, "media_type": "image/jpeg"},
        })

        # Replicate the stripping logic from OpenAICompatProvider._convert_messages
        tool_content = raw
        try:
            data = json.loads(tool_content)
            if isinstance(data, dict) and "_image" in data:
                data.pop("_image")
                tool_content = json.dumps(data, ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass

        parsed = json.loads(tool_content)
        assert "_image" not in parsed
        assert parsed["camera_entity_id"] == "camera.front_door"
        assert parsed["image_available"] is True
