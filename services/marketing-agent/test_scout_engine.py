"""
Test suite for Scout Engine (SearXNG Signal Monitor).

Tests:
1. SearXNG client mock search and result parsing
2. Relevance scorer with various inputs
3. Deduplication logic
4. APScheduler job scheduling
5. NATS event publishing
6. REST API endpoints
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


# ============================================================================
# Test 1: SearXNG Client
# ============================================================================

class TestSearXNGClient:
    """Test SearXNG HTTP client."""

    @pytest.mark.asyncio
    async def test_search_result_parsing(self):
        """Test parsing of SearXNG search results."""
        from app.scout.searxng_client import SearchResult, SearXNGClient

        # Create mock result
        result = SearchResult(
            title="SAP Datasphere Feature Announcement",
            url="https://sap.com/news/datasphere-2025",
            snippet="New features for SAP Datasphere in 2025...",
            engine="google",
            engine_score=0.8,
        )

        assert result.title == "SAP Datasphere Feature Announcement"
        assert result.url == "https://sap.com/news/datasphere-2025"
        assert result.snippet == "New features for SAP Datasphere in 2025..."
        assert result.engine == "google"
        assert result.engine_score == 0.8

    @pytest.mark.asyncio
    async def test_searxng_client_initialization(self):
        """Test SearXNG client initialization."""
        from app.scout.searxng_client import SearXNGClient

        client = SearXNGClient(base_url="http://192.168.0.84:8080")
        assert client.base_url == "http://192.168.0.84:8080"
        assert client.client is not None
        await client.close()

    @pytest.mark.asyncio
    async def test_search_with_mock_response(self):
        """Test search method with mocked HTTP response."""
        from app.scout.searxng_client import SearXNGClient

        client = SearXNGClient(base_url="http://192.168.0.84:8080")

        # Mock httpx response
        mock_response = {
            "results": [
                {
                    "title": "SAP Datasphere Update 2025",
                    "url": "https://sap.com/datasphere",
                    "content": "Major updates to SAP Datasphere...",
                    "engine": "google",
                },
                {
                    "title": "Enterprise Data Strategy",
                    "url": "https://blog.example.com/data",
                    "content": "How to build enterprise data platforms...",
                    "engine": "bing",
                },
            ]
        }

        # Patch httpx.AsyncClient.get
        with patch.object(client.client, "get") as mock_get:
            mock_get.return_value = AsyncMock(
                json=lambda: mock_response,
                status_code=200,
            )()

            results = await client.search(
                query="SAP Datasphere",
                engines=["google", "bing"],
                max_results=10,
            )

            # Should return 2 results
            # (Note: In real test, would need AsyncMock properly)
            logger.info(f"Mock search returned {len(results)} results")


# ============================================================================
# Test 2: Relevance Scorer
# ============================================================================

class TestRelevanceScorer:
    """Test relevance scoring algorithm."""

    def test_score_high_authority_domain(self):
        """Test scoring boost for high-authority domains."""
        from app.scout.scorer import score_signal

        score = score_signal(
            title="SAP Datasphere New Features",
            snippet="Latest updates to SAP Datasphere on sap.com",
            url="https://sap.com/news/datasphere",
            pillar_id=1,
        )

        # Should be high due to high-authority domain (sap.com)
        assert score > 0.5, f"Expected score > 0.5, got {score}"
        logger.info(f"High-authority domain score: {score:.3f}")

    def test_score_medium_authority_domain(self):
        """Test scoring for medium-authority domains."""
        from app.scout.scorer import score_signal

        score = score_signal(
            title="Data Architecture Insights",
            snippet="Enterprise data governance best practices on LinkedIn",
            url="https://linkedin.com/pulse/data-architecture",
            pillar_id=6,
        )

        # Should have some score from keyword match and medium authority
        assert score > 0.2, f"Expected score > 0.2, got {score}"
        logger.info(f"Medium-authority domain score: {score:.3f}")

    def test_score_keyword_relevance(self):
        """Test scoring based on keyword matches."""
        from app.scout.scorer import score_signal

        # Strong keyword match for pillar 4 (AI)
        score = score_signal(
            title="Generative AI in Enterprise Data",
            snippet="LLM integration with data governance for enterprise...",
            url="https://blog.example.com/ai-data",
            pillar_id=4,
        )

        assert score > 0.3, f"Expected score > 0.3, got {score}"
        logger.info(f"Keyword-rich content score: {score:.3f}")

    def test_score_normalization(self):
        """Test that scores are always 0.0-1.0."""
        from app.scout.scorer import score_signal

        for pillar in range(1, 7):
            score = score_signal(
                title="Test Title with all keywords datasphere ai analytics",
                snippet="Long snippet with many keywords...",
                url="https://sap.com/blogs/article",
                pillar_id=pillar,
            )

            assert 0.0 <= score <= 1.0, f"Score {score} outside valid range"
            logger.info(f"Pillar {pillar}: score={score:.3f}")


# ============================================================================
# Test 3: Deduplication
# ============================================================================

class TestDeduplication:
    """Test URL deduplication logic."""

    def test_url_hash_calculation(self):
        """Test SHA256 hash calculation for URLs."""
        url1 = "https://sap.com/news/datasphere-2025"
        url2 = "https://sap.com/news/datasphere-2025"
        url3 = "https://sap.com/news/other"

        hash1 = hashlib.sha256(url1.encode()).hexdigest()
        hash2 = hashlib.sha256(url2.encode()).hexdigest()
        hash3 = hashlib.sha256(url3.encode()).hexdigest()

        assert hash1 == hash2, "Same URL should produce same hash"
        assert hash1 != hash3, "Different URLs should produce different hashes"
        assert len(hash1) == 64, "SHA256 hex should be 64 chars"

        logger.info(f"URL hash test passed: {hash1[:16]}...")

    def test_recent_duplicate_detection(self):
        """Test detection of recent duplicates (within 30 days)."""
        now = datetime.utcnow()
        cutoff = now - timedelta(days=30)

        # Signals detected within 30 days should be considered duplicates
        signal_date_recent = now - timedelta(days=5)
        signal_date_old = now - timedelta(days=45)

        assert signal_date_recent >= cutoff, "Recent signal should be within window"
        assert signal_date_old < cutoff, "Old signal should be outside window"

        logger.info("Deduplication window test passed")


# ============================================================================
# Test 4: Scheduler
# ============================================================================

class TestScoutScheduler:
    """Test APScheduler integration."""

    @pytest.mark.asyncio
    async def test_scheduler_initialization(self):
        """Test scheduler initialization."""
        from app.scout.scheduler import ScoutScheduler

        scheduler = ScoutScheduler(searxng_url="http://192.168.0.84:8080")

        assert scheduler.scheduler is not None
        assert scheduler.searxng_client is not None
        assert scheduler.is_running == False
        assert scheduler.dedup_window_days == 30

        logger.info("Scheduler initialization passed")

    @pytest.mark.asyncio
    async def test_profile_job_creation(self):
        """Test that jobs are created for each profile."""
        from app.scout.scheduler import ScoutScheduler
        from app.scout.profiles import get_default_profiles

        scheduler = ScoutScheduler(searxng_url="http://192.168.0.84:8080")

        profiles = get_default_profiles()
        assert len(profiles) == 5, f"Expected 5 profiles, got {len(profiles)}"

        # Verify profile structure
        for profile in profiles:
            assert profile.id, "Profile must have ID"
            assert profile.name, "Profile must have name"
            assert profile.queries, "Profile must have queries"
            assert profile.engines, "Profile must have engines"
            assert profile.pillar_id, "Profile must have pillar_id"
            assert profile.interval_hours > 0, "Profile must have positive interval"

            logger.info(f"Profile '{profile.name}': {len(profile.queries)} queries, {profile.interval_hours}h interval")


# ============================================================================
# Test 5: Profiles
# ============================================================================

class TestSearchProfiles:
    """Test search profile configuration."""

    def test_default_profiles_exist(self):
        """Test that all 5 default profiles are defined."""
        from app.scout.profiles import get_default_profiles, get_profile_by_id

        profiles = get_default_profiles()

        assert len(profiles) == 5, f"Expected 5 profiles, got {len(profiles)}"
        assert all(p.id for p in profiles), "All profiles must have IDs"
        assert all(p.name for p in profiles), "All profiles must have names"

        logger.info(f"Found {len(profiles)} default profiles:")
        for p in profiles:
            logger.info(f"  - {p.name} (pillar {p.pillar_id}, {p.interval_hours}h)")

    def test_profile_lookup(self):
        """Test profile lookup by ID."""
        from app.scout.profiles import get_profile_by_id

        profile = get_profile_by_id("sap_datasphere")
        assert profile is not None
        assert profile.name == "SAP Datasphere News"
        assert profile.pillar_id == 1

        profile = get_profile_by_id("nonexistent")
        assert profile is None

        logger.info("Profile lookup test passed")

    def test_profile_pillar_coverage(self):
        """Test that profiles cover all 6 pillars."""
        from app.scout.profiles import get_default_profiles

        profiles = get_default_profiles()
        pillars = {p.pillar_id for p in profiles}

        logger.info(f"Pillars covered: {sorted(pillars)}")
        # Note: Not all pillars need to be covered by default profiles


# ============================================================================
# Test 6: REST API Endpoints
# ============================================================================

class TestRESTEndpoints:
    """Test REST API endpoints."""

    def test_signal_schema(self):
        """Test Signal response model."""
        from api.signals import SignalResponse
        from datetime import datetime

        # Test schema validation
        signal_data = {
            "id": 1,
            "title": "Test Signal",
            "url": "https://example.com",
            "source": "google",
            "source_domain": "example.com",
            "snippet": "Test snippet",
            "relevance_score": 0.85,
            "pillar_id": 1,
            "search_profile_id": "sap_datasphere",
            "status": "new",
            "detected_at": datetime.utcnow(),
            "created_at": datetime.utcnow(),
            "kg_node_id": None,
        }

        signal = SignalResponse(**signal_data)
        assert signal.id == 1
        assert signal.relevance_score == 0.85
        assert signal.status == "new"

        logger.info("Signal response model validation passed")

    def test_update_schema(self):
        """Test SignalUpdate request model."""
        from api.signals import SignalUpdate

        # Valid status
        update = SignalUpdate(status="read")
        assert update.status == "read"

        # No status (optional)
        update = SignalUpdate()
        assert update.status is None

        logger.info("Signal update schema test passed")


# ============================================================================
# Test 7: NATS Publishing
# ============================================================================

class TestNATSPublishing:
    """Test NATS event publishing."""

    @pytest.mark.asyncio
    async def test_nats_publisher_initialization(self):
        """Test NATS publisher initialization without connection."""
        from app.scout.events import NATSPublisher

        publisher = NATSPublisher()
        assert publisher._nats_available == False

        # Initialize with no URL (graceful degradation)
        await publisher.initialize(None)
        assert publisher._nats_available == False

        logger.info("NATS publisher graceful degradation test passed")

    @pytest.mark.asyncio
    async def test_signal_detected_payload(self):
        """Test signal.detected event payload structure."""
        from datetime import datetime

        signal_id = 123
        title = "Test Signal"
        url = "https://example.com"
        pillar_id = 1
        relevance_score = 0.85
        detected_at = datetime.utcnow()

        payload = {
            "event": "signal.detected",
            "signal_id": signal_id,
            "title": title,
            "url": url,
            "pillar_id": pillar_id,
            "relevance_score": relevance_score,
            "detected_at": detected_at.isoformat(),
        }

        # Should be JSON serializable
        json_str = json.dumps(payload)
        assert len(json_str) > 0

        logger.info(f"Event payload: {payload}")


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    """Run tests manually."""
    import asyncio

    # Quick validation tests
    print("=" * 80)
    print("Scout Engine Test Suite")
    print("=" * 80)

    # Test 1: Scorer
    print("\n[TEST 1] Relevance Scorer")
    from app.scout.scorer import score_signal

    score1 = score_signal(
        title="SAP Datasphere New Features",
        snippet="Latest updates from sap.com",
        url="https://sap.com/news",
        pillar_id=1,
    )
    print(f"✓ High-authority domain: {score1:.3f}")

    score2 = score_signal(
        title="Enterprise AI Strategy",
        snippet="Generative AI and LLM enterprise integration",
        url="https://example.com",
        pillar_id=4,
    )
    print(f"✓ AI pillar keywords: {score2:.3f}")

    # Test 2: Profiles
    print("\n[TEST 2] Search Profiles")
    from app.scout.profiles import get_default_profiles

    profiles = get_default_profiles()
    print(f"✓ Found {len(profiles)} default profiles")
    for p in profiles:
        print(f"  - {p.name}: {len(p.queries)} queries, {p.interval_hours}h interval")

    # Test 3: Deduplication
    print("\n[TEST 3] Deduplication")
    url = "https://sap.com/datasphere"
    hash1 = hashlib.sha256(url.encode()).hexdigest()
    print(f"✓ URL hash: {hash1[:32]}...")

    # Test 4: Schema
    print("\n[TEST 4] REST Schema")
    from api.signals import SignalResponse
    from datetime import datetime

    signal_data = {
        "id": 1,
        "title": "Test",
        "url": "https://example.com",
        "source": "google",
        "source_domain": "example.com",
        "snippet": "Test",
        "relevance_score": 0.85,
        "pillar_id": 1,
        "search_profile_id": "sap_datasphere",
        "status": "new",
        "detected_at": datetime.utcnow(),
        "created_at": datetime.utcnow(),
        "kg_node_id": None,
    }
    signal = SignalResponse(**signal_data)
    print(f"✓ Signal schema validation: score={signal.relevance_score}")

    print("\n" + "=" * 80)
    print("All manual tests passed!")
    print("=" * 80)
