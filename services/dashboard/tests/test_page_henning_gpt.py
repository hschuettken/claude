"""Tests for the HenningGPT dashboard page and related config.

Runs without a real browser or external services.
nicegui is not available in the test environment — tests that need it are skipped.
"""
from __future__ import annotations

import importlib
import os
import sys

# Make shared/ importable (dashboard config inherits from shared.config.Settings)
_repo_root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Make dashboard/ importable
_dashboard_path = os.path.join(os.path.dirname(__file__), "..")
if _dashboard_path not in sys.path:
    sys.path.insert(0, os.path.normpath(_dashboard_path))


# ─────────────────────────────────────────────────────────────────────────────
# NAV_ITEMS — /henning-gpt registered
# ─────────────────────────────────────────────────────────────────────────────

def _read_layout_nav_items() -> list[tuple[str, str, str]]:
    """Parse NAV_ITEMS from layout.py without importing nicegui."""
    layout_path = os.path.join(_dashboard_path, "layout.py")
    with open(layout_path) as f:
        src = f.read()
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


def test_nav_items_include_henning_gpt():
    items = _read_layout_nav_items()
    paths = [item[0] for item in items]
    assert "/henning-gpt" in paths


def test_nav_items_henning_gpt_has_label():
    items = _read_layout_nav_items()
    item = next((i for i in items if i[0] == "/henning-gpt"), None)
    assert item is not None
    assert "Henning" in item[2] or "henning" in item[2].lower()


def test_nav_items_chat_still_present():
    items = _read_layout_nav_items()
    paths = [item[0] for item in items]
    assert "/chat" in paths


# ─────────────────────────────────────────────────────────────────────────────
# page_henning_gpt.py — source-level checks
# ─────────────────────────────────────────────────────────────────────────────

def _read_page_source() -> str:
    path = os.path.join(_dashboard_path, "page_henning_gpt.py")
    with open(path) as f:
        return f.read()


def test_page_defines_setup():
    src = _read_page_source()
    assert "def setup(" in src


def test_page_registers_henning_gpt_route():
    src = _read_page_source()
    assert '"/henning-gpt"' in src


def test_page_has_all_four_phases():
    src = _read_page_source()
    # Phase 1 — decision memory
    assert "render_decisions" in src
    # Phase 2 — preference graph
    assert "render_preferences" in src
    # Phase 3 — accuracy + pending
    assert "render_accuracy" in src
    assert "render_pending" in src
    # Phase 4 — delegation
    assert "render_delegation" in src


def test_page_has_feedback_actions():
    src = _read_page_source()
    assert "_submit_feedback" in src
    assert "thumb_up" in src
    assert "thumb_down" in src


def test_page_has_delegation_sandbox():
    src = _read_page_source()
    assert "_score_delegation_demo" in src
    assert "henninggpt/delegate" in src


def test_page_uses_orchestrator_url():
    src = _read_page_source()
    assert "settings.orchestrator_url" in src


def test_page_uses_orchestrator_api_key():
    src = _read_page_source()
    assert "settings.orchestrator_api_key" in src


def test_page_calls_search_endpoint():
    src = _read_page_source()
    assert "henninggpt/decisions/search" in src


def test_page_calls_preferences_endpoint():
    src = _read_page_source()
    assert "henninggpt/preferences" in src


def test_page_calls_accuracy_endpoint():
    src = _read_page_source()
    assert "henninggpt/accuracy" in src


def test_page_calls_policy_endpoint():
    src = _read_page_source()
    assert "henninggpt/delegate/policy" in src


# ─────────────────────────────────────────────────────────────────────────────
# main.py — page_henning_gpt is registered
# ─────────────────────────────────────────────────────────────────────────────

def test_main_imports_page_henning_gpt():
    main_path = os.path.join(_dashboard_path, "main.py")
    with open(main_path) as f:
        src = f.read()
    assert "import page_henning_gpt" in src
    assert "page_henning_gpt.setup(" in src


def test_main_oracle_manifest_includes_henning_gpt_route():
    main_path = os.path.join(_dashboard_path, "main.py")
    with open(main_path) as f:
        src = f.read()
    assert "/henning-gpt" in src
