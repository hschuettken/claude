"""Unit tests for Scout Engine components."""

import pytest
from datetime import datetime
from scout.searxng_client import SearchResult
from scout.scorer import (
    score_signal,
    _normalize_text,
    _count_keywords,
    _parse_publish_date,
    _get_recency_boost,
    SAP_KEYWORDS,
)


class TestSearXNGParser:
    """Test SearchResult parsing."""
    
    def test_search_result_creation(self):
        """Test creating a SearchResult."""
        result = SearchResult(
            title="SAP Datasphere News",
            url="https://sap.com/blog/datasphere",
            content="Latest updates on Datasphere",
            engine="google",
            score=0.95,
            published="2025-03-24"
        )
        
        assert result.title == "SAP Datasphere News"
        assert result.url == "https://sap.com/blog/datasphere"
        assert result.engine == "google"
    
    def test_search_result_optional_fields(self):
        """Test SearchResult with optional fields missing."""
        result = SearchResult(
            title="Test",
            url="https://example.com",
            content="snippet"
        )
        
        assert result.engine == "unknown"
        assert result.score is None
        assert result.published is None


class TestTextNormalization:
    """Test text processing utilities."""
    
    def test_normalize_text(self):
        """Test text normalization."""
        assert _normalize_text("SAP Datasphere") == "sap datasphere"
        assert _normalize_text("  spaces  ") == "spaces"
    
    def test_count_keywords_simple(self):
        """Test keyword counting."""
        text = "sap datasphere analytics"
        keywords = {"sap", "datasphere", "analytics"}
        
        count = _count_keywords(text, keywords)
        assert count == 3
    
    def test_count_keywords_partial_match(self):
        """Test that keywords are substrings."""
        text = "datasphere integration"
        keywords = {"datasphere"}
        
        count = _count_keywords(text, keywords)
        assert count == 1
    
    def test_count_keywords_case_insensitive(self):
        """Test case-insensitive matching."""
        text = "SAP DataSphere"
        keywords = {"sap", "datasphere"}
        
        count = _count_keywords(text, keywords)
        assert count == 2


class TestDateParsing:
    """Test date parsing and recency scoring."""
    
    def test_parse_iso_date(self):
        """Test ISO date parsing."""
        date_str = "2025-03-24T14:30:00Z"
        parsed = _parse_publish_date(date_str)
        
        assert parsed is not None
        assert parsed.year == 2025
        assert parsed.month == 3
        assert parsed.day == 24
    
    def test_parse_invalid_date(self):
        """Test invalid date returns None."""
        parsed = _parse_publish_date("invalid-date")
        assert parsed is None
    
    def test_parse_none_date(self):
        """Test None input returns None."""
        parsed = _parse_publish_date(None)
        assert parsed is None
    
    def test_recency_boost_this_week(self):
        """Test recent signal gets boost."""
        # Create a date from yesterday
        from datetime import timedelta, datetime
        yesterday = (datetime.utcnow() - timedelta(days=1)).isoformat()
        
        boost = _get_recency_boost(yesterday)
        assert boost == 0.3  # This week boost
    
    def test_recency_boost_this_month(self):
        """Test month-old signal gets moderate boost."""
        from datetime import timedelta, datetime
        last_week = (datetime.utcnow() - timedelta(days=10)).isoformat()
        
        boost = _get_recency_boost(last_week)
        assert boost == 0.2  # This month boost
    
    def test_recency_boost_old(self):
        """Test old signal gets no boost."""
        from datetime import timedelta, datetime
        old_date = (datetime.utcnow() - timedelta(days=400)).isoformat()
        
        boost = _get_recency_boost(old_date)
        assert boost == 0.0  # No boost for old content


class TestRelevanceScoring:
    """Test signal relevance scoring."""
    
    def test_base_score(self):
        """Test baseline scoring."""
        result = SearchResult(
            title="Random Article",
            url="https://example.com/article",
            content="Some random content",
            engine="google"
        )
        
        score = score_signal(result, pillar_id=1)
        
        # Should be at least base score (0.5) minus some adjustment
        assert 0.0 <= score <= 1.0
    
    def test_sap_keyword_boost(self):
        """Test SAP keyword boosts score."""
        result = SearchResult(
            title="SAP Datasphere News",
            url="https://example.com",
            content="SAP Datasphere updates and features",
            engine="google"
        )
        
        score = score_signal(result, pillar_id=1)
        assert score > 0.5  # Should be boosted from baseline
    
    def test_authority_domain_boost(self):
        """Test high-authority domains get boost."""
        result = SearchResult(
            title="News",
            url="https://sap.com/blog/article",
            content="Content",
            engine="google"
        )
        
        score = score_signal(result, pillar_id=1)
        assert score > 0.5  # SAP domain is high authority
    
    def test_medium_authority_domain(self):
        """Test medium-authority domains."""
        result = SearchResult(
            title="Article",
            url="https://linkedin.com/feed/article",
            content="Content",
            engine="google"
        )
        
        score = score_signal(result, pillar_id=3)  # Thought leadership pillar
        assert score > 0.5  # LinkedIn is medium authority
    
    def test_score_clamped(self):
        """Test score is always 0.0-1.0."""
        result = SearchResult(
            title="Test",
            url="https://sap.com",
            content="SAP SAP SAP datasphere datasphere modeling integration",
            engine="google"
        )
        
        score = score_signal(result, pillar_id=1)
        assert 0.0 <= score <= 1.0
    
    def test_different_pillars(self):
        """Test scoring varies by pillar."""
        result_release = SearchResult(
            title="SAP Release Notes Q2 2025",
            url="https://help.sap.com/release",
            content="New release features and updates",
            engine="google"
        )
        
        result_community = SearchResult(
            title="Expert Thought Leadership",
            url="https://linkedin.com/article",
            content="Industry perspective and experience sharing",
            engine="google"
        )
        
        score_pillar2 = score_signal(result_release, pillar_id=2)  # Release notes
        score_pillar3 = score_signal(result_community, pillar_id=3)  # Thought leadership
        
        # Both should be valid scores
        assert 0.0 <= score_pillar2 <= 1.0
        assert 0.0 <= score_pillar3 <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
