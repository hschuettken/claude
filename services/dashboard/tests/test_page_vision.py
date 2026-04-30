"""Tests for the Vision dashboard page and registration."""

from __future__ import annotations

import os
import sys

_repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

_dashboard_path = os.path.join(os.path.dirname(__file__), "..")
if _dashboard_path not in sys.path:
    sys.path.insert(0, os.path.normpath(_dashboard_path))


def _read(path: str) -> str:
    with open(os.path.join(_dashboard_path, path)) as f:
        return f.read()


def _read_layout_nav_items() -> list[tuple[str, str, str]]:
    src = _read("layout.py")
    start = src.find("NAV_ITEMS = [")
    end = src.find("]", start) + 1
    block = src[start:end]
    items = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith('("'):
            parts = [
                p.strip().strip('"').strip("'")
                for p in line.strip(",").strip("()").split(",")
            ]
            if len(parts) >= 3:
                items.append((parts[0], parts[1], parts[2]))
    return items


def test_nav_items_include_vision():
    paths = [item[0] for item in _read_layout_nav_items()]
    assert "/vision" in paths


def test_nav_items_vision_has_label_and_icon():
    item = next(i for i in _read_layout_nav_items() if i[0] == "/vision")
    assert item[1] == "visibility"
    assert item[2] == "Vision"


def test_page_vision_defines_setup():
    src = _read("page_vision.py")
    assert "def setup(" in src


def test_page_vision_registers_route():
    src = _read("page_vision.py")
    assert '"/vision"' in src


def test_page_vision_calls_orchestrator_vision_endpoint():
    src = _read("page_vision.py")
    assert "settings.orchestrator_url" in src
    assert "settings.orchestrator_api_key" in src
    assert "/api/v1/vision" in src


def test_page_vision_renders_north_star_and_areas():
    src = _read("page_vision.py")
    assert "north_star" in src
    assert "areas_total" in src
    assert "services_online" in src
    assert "Implementation Areas" in src


def test_main_imports_page_vision():
    src = _read("main.py")
    assert "import page_vision" in src
    assert "page_vision.setup(" in src


def test_main_oracle_manifest_includes_vision_route():
    src = _read("main.py")
    assert '"/vision"' in src
    assert "Home Brain vision" in src
