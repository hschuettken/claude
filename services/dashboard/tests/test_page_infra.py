"""Tests for the infra dashboard page and related config.

Runs without a real browser or external services.
nicegui is not available in the test environment — tests that need it are skipped.
"""
from __future__ import annotations

import importlib
import os
import sys
import types

# Make shared/ importable (dashboard config inherits from shared.config.Settings)
# shared is a package at /repos/claude/shared/, so we add the repo root
_repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Make dashboard/ importable
_dashboard_path = os.path.join(os.path.dirname(__file__), "..")
if _dashboard_path not in sys.path:
    sys.path.insert(0, os.path.normpath(_dashboard_path))

_NICEGUI_AVAILABLE = importlib.util.find_spec("nicegui") is not None


# ─────────────────────────────────────────────────────────────────────────────
# DashboardSettings — infra URL default (parsed from source to avoid module clash)
# ─────────────────────────────────────────────────────────────────────────────

def _read_config_source() -> str:
    config_path = os.path.join(_dashboard_path, "config.py")
    with open(config_path) as f:
        return f.read()


def test_dashboard_config_has_soi_url():
    src = _read_config_source()
    assert "self_optimizing_infra_url" in src
    assert "8242" in src


def test_soi_url_default_is_docker_hostname():
    src = _read_config_source()
    assert "self-optimizing-infra" in src  # Docker service name in URL


# ─────────────────────────────────────────────────────────────────────────────
# NAV_ITEMS — /infra registered (parse layout.py as text to avoid nicegui dep)
# ─────────────────────────────────────────────────────────────────────────────

def _read_layout_nav_items() -> list[tuple[str, str, str]]:
    """Parse NAV_ITEMS from layout.py without importing nicegui."""
    layout_path = os.path.join(_dashboard_path, "layout.py")
    with open(layout_path) as f:
        src = f.read()
    # Extract the NAV_ITEMS list literal as text
    start = src.find("NAV_ITEMS = [")
    end = src.find("]", start) + 1
    block = src[start:end]
    items = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith('("'):
            parts = [p.strip().strip('"').strip("'") for p in line.strip(",").strip("()").split(",")]
            if len(parts) >= 3:
                items.append((parts[0].strip('"\''), parts[1].strip('"\''), parts[2].strip('"\')')))
    return items


def test_nav_items_include_infra():
    items = _read_layout_nav_items()
    paths = [item[0] for item in items]
    assert "/infra" in paths


def test_nav_items_infra_has_label():
    items = _read_layout_nav_items()
    infra_item = next((item for item in items if item[0] == "/infra"), None)
    assert infra_item is not None
    assert infra_item[2] == "Infra"


def test_nav_items_chat_still_present():
    items = _read_layout_nav_items()
    paths = [item[0] for item in items]
    assert "/chat" in paths


# ─────────────────────────────────────────────────────────────────────────────
# page_infra.py — source-level checks without executing nicegui
# ─────────────────────────────────────────────────────────────────────────────

def _read_page_infra_source() -> str:
    path = os.path.join(_dashboard_path, "page_infra.py")
    with open(path) as f:
        return f.read()


def test_page_infra_defines_setup():
    src = _read_page_infra_source()
    assert "def setup(" in src


def test_page_infra_registers_infra_route():
    src = _read_page_infra_source()
    assert '"/infra"' in src


def test_page_infra_has_decision_sections():
    src = _read_page_infra_source()
    assert "render_decisions" in src
    assert "render_proposals" in src
    assert "render_chaos" in src
    assert "render_monitors" in src


def test_page_infra_approve_reject_actions():
    src = _read_page_infra_source()
    assert "_approve_decision" in src
    assert "_reject_decision" in src
    assert "_approve_proposal" in src
    assert "_reject_proposal" in src
    assert "_implement_proposal" in src


def test_page_infra_uses_soi_url_from_settings():
    src = _read_page_infra_source()
    assert "settings.self_optimizing_infra_url" in src


# ─────────────────────────────────────────────────────────────────────────────
# main.py — page_infra is registered
# ─────────────────────────────────────────────────────────────────────────────

def test_main_imports_page_infra():
    main_path = os.path.join(_dashboard_path, "main.py")
    with open(main_path) as f:
        src = f.read()
    assert "import page_infra" in src
    assert "page_infra.setup(" in src
