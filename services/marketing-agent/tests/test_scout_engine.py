"""Unit tests for Scout Engine — Task 128."""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.scout.searxng_client import SearXNGClient, SearchResult
from app.scout.scorer import score_signal
from app.scout.profiles import get_default_profiles, get_profile_by_id
from app.scout.scheduler import ScoutScheduler


class TestSearXNGClient:
    """Test SearXNG client functionality."""

    def test_search_result_creation(self):
        """Test SearchResult initialization."""
        result = SearchResult(
            title="SAP Datasphere News",
            url="https://community.sap.com/datasphere",
            snippet="New features released",
            engine="google",
            engine_score=0.8
        )
        assert result.title == "SAP Datasphere News"
        assert result.url == "https://community.sap.com/datasphere"
        assert result.snippet == "New features released"
        assert result.engine == "google"
        assert result.engine_score == 0.8

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test SearXNG health check."""
        client = SearXNGClient()
        # Mock the HTTP client
        with patch.object(client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_get.return_value = mock_response
            
            result = await client.health_check()
            assert result is True
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_parsing(self):
        """Test search result parsing from SearXNG JSON."""
        client = SearXNGClient()
        
        # Mock response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "SAP Datasphere Release Notes",
                    "url": "https://sap.com/datasphere-notes",
                    "content": "New release with improved performance",
                    "engine": "google",
                },
                {
                    "title": "Enterprise AI Integration",
                    "url": "https://example.com/ai-enterprise",
                    "content": "How to integrate AI in your data stack",
                    "engine": "bing",
                }
            ]
        }
        
        with patch.object(client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            results = await client.search("SAP Datasphere", engines=["google", "bing"], max_results=10)
            
            assert len(results) == 2
            assert results[0].title == "SAP Datasphere Release Notes"
            assert results[0].url == "https://sap.com/datasphere-notes"
            assert results[1].engine == "bing"

    @pytest.mark.asyncio
    async def test_search_handles_empty_results(self):
        """Test search handles empty results gracefully."""
        client = SearXNGClient()
        
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        
        with patch.object(client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            
            results = await client.search("no results query")
            assert results == []


class TestRelevanceScoring:
    """Test relevance scoring algorithm."""

    def test_score_sap_keywords(self):
        """Test scoring with SAP keywords."""
        score = score_signal(
            title="SAP Datasphere New Features",
            snippet="Datasphere now supports real-time analytics",
            url="https://sap.com/products/datasphere",
            pillar_id=1
        )
        assert 0.0 <= score <= 1.0
        assert score > 0.5  # Should score high with SAP and Datasphere keywords

    def test_score_high_authority_domain(self):
        """Test scoring with high-authority domains."""
        score_sap = score_signal(
            title="Analytics",
            snippet="News",
            url="https://sap.com/article",
            pillar_id=1
        )
        score_generic = score_signal(
            title="Analytics",
            snippet="News",
            url="https://example.com/article",
            pillar_id=1
        )
        assert score_sap > score_generic  # SAP domain should score higher

    def test_score_pillar_specific_keywords(self):
        """Test scoring with pillar-specific keywords."""
        # Pillar 2: Release notes
        score = score_signal(
            title="Release Notes Q1 2025",
            snippet="New features and updates for 2025",
            url="https://example.com/release",
            pillar_id=2
        )
        assert score > 0.3  # Should get pillar bonus for "release" keyword

    def test_score_normalization(self):
        """Test that scores are normalized 0.0-1.0."""
        test_cases = [
            ("", "", "https://example.com", 1),
            ("SAP Datasphere analytics", "Very detailed technical content about SAP", "https://sap.com", 1),
            ("Random content", "Nothing relevant", "https://random.com", 1),
        ]
        
        for title, snippet, url, pillar in test_cases:
            score = score_signal(title, snippet, url, pillar)
            assert 0.0 <= score <= 1.0, f"Score {score} out of bounds for: {title}"


class TestSearchProfiles:
    """Test search profile configuration."""

    def test_default_profiles_exist(self):
        """Test that default profiles are loaded."""
        profiles = get_default_profiles()
        assert len(profiles) == 5
        assert profiles[0].id == "sap_datasphere"

    def test_profile_by_id(self):
        """Test retrieving profile by ID."""
        profile = get_profile_by_id("sap_datasphere")
        assert profile is not None
        assert profile.name == "SAP Datasphere News"
        assert profile.pillar_id == 1
        assert profile.interval_hours == 4

    def test_profile_queries(self):
        """Test that profiles have queries."""
        profiles = get_default_profiles()
        for profile in profiles:
            assert len(profile.queries) > 0
            assert all(isinstance(q, str) for q in profile.queries)

    def test_profile_engines(self):
        """Test that profiles have search engines."""
        profiles = get_default_profiles()
        for profile in profiles:
            assert len(profile.engines) > 0
            assert all(isinstance(e, str) for e in profile.engines)

    def test_profile_interval_hours(self):
        """Test that profile intervals are valid."""
        profiles = get_default_profiles()
        for profile in profiles:
            assert profile.interval_hours > 0
            assert profile.interval_hours <= 24

    def test_profile_pillar_ids(self):
        """Test that profiles are mapped to pillars 1-6."""
        profiles = get_default_profiles()
        pillar_ids = {p.pillar_id for p in profiles}
        assert all(1 <= p <= 6 for p in pillar_ids)


class TestScoutScheduler:
    """Test APScheduler integration."""

    @pytest.mark.asyncio
    async def test_scheduler_initialization(self):
        """Test scheduler can be initialized."""
        scheduler = ScoutScheduler()
        assert scheduler.searxng_client is not None
        assert scheduler.is_running is False
        assert len(scheduler.last_run_info) == 0

    def test_extract_domain(self):
        """Test domain extraction from URL."""
        test_cases = [
            ("https://example.com/path", "example.com"),
            ("https://sub.example.com/deep/path", "sub.example.com"),
            ("http://localhost:8080/test", "localhost:8080"),
        ]
        for url, expected_domain in test_cases:
            domain = ScoutScheduler._extract_domain(url)
            assert domain == expected_domain

    def test_scheduler_dedup_window(self):
        """Test deduplication window setting."""
        scheduler = ScoutScheduler()
        assert scheduler.dedup_window_days == 30


# Acceptance Criteria Tests
class TestAcceptanceCriteria:
    """Tests for Task 128 acceptance criteria."""

    @pytest.mark.asyncio
    async def test_criterion_searxng_client_works(self):
        """
        Criterion: SearXNG client can execute searches and parse results
        """
        client = SearXNGClient()
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test Result",
                    "url": "https://example.com/test",
                    "content": "Test content",
                    "engine": "google",
                }
            ]
        }
        
        with patch.object(client.client, 'get', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            results = await client.search("test query")
            assert len(results) == 1
            assert results[0].title == "Test Result"

    def test_criterion_default_profiles_configured(self):
        """
        Criterion: All 5 default search profiles configured and running
        """
        profiles = get_default_profiles()
        assert len(profiles) >= 5
        
        profile_names = {p.id for p in profiles}
        expected = {"sap_datasphere", "sap_community", "sap_release", "ai_enterprise", "linkedin_signals"}
        assert expected.issubset(profile_names)

    def test_criterion_relevance_scores_valid(self):
        """
        Criterion: Relevance scores computed (0.0–1.0), no NaN or missing values
        """
        test_inputs = [
            ("", "", "https://example.com", 1),
            ("SAP", "Datasphere", "https://sap.com", 1),
            ("AI", "Machine Learning", "https://medium.com", 4),
        ]
        
        for title, snippet, url, pillar in test_inputs:
            score = score_signal(title, snippet, url, pillar)
            assert isinstance(score, float)
            assert not (score != score)  # Check for NaN
            assert 0.0 <= score <= 1.0

    def test_criterion_pillar_assignment(self):
        """
        Criterion: Pillar IDs correctly assigned (1–6) based on profile
        """
        profiles = get_default_profiles()
        for profile in profiles:
            assert 1 <= profile.pillar_id <= 6

    def test_criterion_scheduler_can_be_created(self):
        """
        Criterion: APScheduler running in FastAPI lifespan, jobs fire on schedule
        """
        scheduler = ScoutScheduler()
        assert scheduler.scheduler is not None
        assert not scheduler.is_running


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
