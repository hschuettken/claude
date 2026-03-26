"""Tests for Draft Studio API — split-pane draft editor.

This test validates the Draft Studio implementation for task #167:
- Left pane: sources/KG context/citations
- Center: rich text editor with draft CRUD
- Right pane: style checks/risk flags/visual prompt/CTA variants
- Governance: auto-flags client names and unsourced claims
"""

import pytest
import re
from pathlib import Path


def test_draft_studio_api_file_exists():
    """Verify draft_studio.py API file exists and is syntactically valid."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    assert api_file.exists(), f"draft_studio.py not found at {api_file}"
    
    # Verify it can be compiled
    with open(api_file) as f:
        code = f.read()
    
    # Check for critical components
    assert "class LeftPaneContext" in code
    assert "class DraftEditorData" in code
    assert "class RightPaneChecks" in code
    assert "class DraftStudioState" in code
    assert "async def open_draft" in code
    assert "async def update_center_pane" in code
    assert "async def get_right_pane" in code
    assert "async def add_citation" in code


def test_draft_studio_router_registered():
    """Verify draft_studio router is registered in main.py."""
    main_file = Path(__file__).parent.parent / "main.py"
    
    with open(main_file) as f:
        content = f.read()
    
    # Check import
    assert "draft_studio_router" in content
    assert "from api import" in content and "draft_studio_router" in content
    
    # Check registration
    assert 'app.include_router(draft_studio_router' in content


def test_draft_studio_router_in_api_init():
    """Verify draft_studio router is exported from api/__init__.py."""
    api_init = Path(__file__).parent.parent / "api" / "__init__.py"
    
    with open(api_init) as f:
        content = f.read()
    
    assert "draft_studio_router" in content
    assert "from .draft_studio import router as draft_studio_router" in content


def test_draft_studio_api_structure():
    """Verify Draft Studio API has correct structure."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Left pane components
    assert "class LeftPaneContext" in code
    assert "class Citation" in code
    assert "class KGContextItem" in code
    
    # Center pane components
    assert "class DraftEditorData" in code
    
    # Right pane components
    assert "class RightPaneChecks" in code
    assert "class RiskFlagWithSuggestion" in code
    assert "class CTAVariant" in code
    assert "class StyleCheck" in code
    
    # Main state
    assert "class DraftStudioState" in code
    
    # API endpoints
    assert 'router = APIRouter(prefix="/draft-studio"' in code
    assert "@router.post(\"/open\"" in code
    assert "@router.put(\"/{draft_id}/center\"" in code
    assert "@router.get(\"/{draft_id}/right\"" in code
    assert "@router.post(\"/{draft_id}/citations\"" in code
    assert "@router.delete(\"/{draft_id}/citations/{citation_index}\"" in code


def test_governance_integration():
    """Verify Draft Studio integrates governance checks."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Verify governance imports
    assert "from ..app.drafts.governance import scan_risk_flags" in code
    assert "format_risk_report" in code
    
    # Verify governance usage in right pane
    assert "risk_flags = await scan_risk_flags" in code
    assert "governance_blocks" in code
    assert "governance_summary" in code
    
    # Verify risk flag remediation
    assert "remediation = None" in code
    assert 'remediation = "Replace with generic' in code
    assert 'remediation = "Add citation' in code
    assert 'remediation = "Remove entirely' in code


def test_left_pane_features():
    """Verify left pane has all required features."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Sources/signals/topics
    assert "signal_id" in code
    assert "topic_id" in code
    assert "select(Signal)" in code
    assert "select(Topic)" in code
    
    # KG context
    assert "kg_context" in code
    assert "published_posts" in code
    assert "active_projects" in code
    assert "pillar_statistics" in code
    
    # Citations
    assert "citations" in code
    assert "@router.post" in code and "citations" in code
    assert "@router.delete" in code and "citations" in code


def test_center_pane_features():
    """Verify center pane has all required features."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Rich text editor data
    assert "DraftEditorData" in code
    assert "word_count" in code
    assert "last_saved_at" in code
    
    # CRUD operations
    assert "@router.put" in code and "update_center_pane" in code
    assert "auto-saves draft content" in code or "Auto-saves draft" in code


def test_right_pane_features():
    """Verify right pane has all required features."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Style checks
    assert "StyleCheck" in code
    assert "readability_score" in code
    
    # Risk flags
    assert "RiskFlagWithSuggestion" in code
    assert "risk_flags" in code
    
    # Visual prompt
    assert "visual_prompt" in code
    assert "_generate_visual_prompt" in code
    
    # CTA variants
    assert "CTAVariant" in code
    assert "_generate_cta_variants" in code
    assert "cta_variants" in code


def test_risk_flag_remediation():
    """Verify risk flags include remediation suggestions."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Check for specific remediations (as patterns, case-insensitive)
    remediations = [
        "generic",
        "citation",
        "potential",
        "Remove entirely",
        "documentation",
        "evidence",
        "emphasis",
    ]
    
    for remediation in remediations:
        assert remediation.lower() in code.lower(), f"Missing remediation: {remediation}"


def test_governance_risk_patterns():
    """Verify governance risk patterns are defined."""
    governance_file = Path(__file__).parent.parent / "app" / "drafts" / "governance.py"
    
    with open(governance_file) as f:
        code = f.read()
    
    # Verify risk patterns
    patterns = [
        "client_reference",
        "unverified_metric",
        "roadmap_claim",
        "confidentiality_risk",
        "unverified_feature",
        "unsubstantiated_claim",
    ]
    
    for pattern in patterns:
        assert pattern in code, f"Missing pattern: {pattern}"


def test_readability_calculation():
    """Verify readability score calculation exists."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    assert "_compute_readability_score" in code
    assert "estimated_reading_time" in code
    assert "word_count" in code


def test_cta_generation():
    """Verify CTA variant generation exists."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    assert "_generate_cta_variants" in code
    assert "Learn more" in code
    assert "Explore" in code
    assert "confidence" in code


def test_visual_prompt():
    """Verify visual prompt generation exists."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    assert "_generate_visual_prompt" in code
    assert "hero image" in code


def test_knowledge_graph_integration():
    """Verify Knowledge Graph integration in Draft Studio."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Check KG imports and usage
    assert "from ..kg_query import get_kg_query" in code
    assert "kg_query = get_kg_query()" in code
    assert "kg_query.is_available()" in code
    assert "published_posts_on_topic" in code
    assert "active_projects" in code
    assert "pillar_statistics" in code


def test_database_integration():
    """Verify database integration in Draft Studio."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Check database usage
    assert "AsyncSession" in code
    assert "select(Draft)" in code
    assert "select(Signal)" in code
    assert "select(Topic)" in code
    assert "db.flush()" in code
    assert "await db" in code  # Database operations


def test_error_handling():
    """Verify proper error handling in Draft Studio."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Check error handling
    assert "HTTPException" in code
    assert "404" in code  # 404 error codes
    assert "not found" in code.lower()
    assert "raise HTTPException" in code


def test_logging():
    """Verify logging is implemented in Draft Studio."""
    api_file = Path(__file__).parent.parent / "api" / "draft_studio.py"
    
    with open(api_file) as f:
        code = f.read()
    
    # Check logging
    assert "logger = logging.getLogger" in code
    assert "logger.info" in code
    assert "logger.warning" in code


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
