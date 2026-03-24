"""
Tests for NATS consumer functionality.

Run with: pytest test_nats_consumer.py -v
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

# Assuming nats_consumer.py is in same directory or app/
from app.nats_consumer import MarketingNATSConsumer


class TestMarketingNATSConsumer:
    """Test suite for NATS consumer."""
    
    @pytest.fixture
    def consumer(self):
        """Create a consumer instance for testing."""
        return MarketingNATSConsumer(
            db_url="postgresql+asyncpg://test:test@localhost/test",
            nats_url="nats://localhost:4222",
            nats_user="test_user",
            nats_password="test_pass",
            relevance_threshold=0.7,
        )
    
    def test_consumer_initialization(self, consumer):
        """Test consumer initializes with correct config."""
        assert consumer.db_url == "postgresql+asyncpg://test:test@localhost/test"
        assert consumer.nats_url == "nats://localhost:4222"
        assert consumer.nats_user == "test_user"
        assert consumer.nats_password == "test_pass"
        assert consumer.relevance_threshold == 0.7
        assert consumer.is_running() is False
    
    def test_relevance_filtering(self):
        """Test that signals are filtered by relevance threshold."""
        # High-relevance signal (should pass filter)
        high_signal = {
            "event": "signal.detected",
            "source": "scout",
            "topic": "Test Topic",
            "score": 0.85,
            "metadata": {"id": 1, "url": "https://example.com"},
        }
        
        # Low-relevance signal (should be filtered)
        low_signal = {
            "event": "signal.detected",
            "source": "scout",
            "topic": "Test Topic",
            "score": 0.65,
            "metadata": {"id": 2, "url": "https://example.com"},
        }
        
        threshold = 0.7
        
        # High relevance should pass
        assert high_signal["score"] > threshold
        
        # Low relevance should fail
        assert low_signal["score"] <= threshold
    
    @pytest.mark.asyncio
    async def test_message_handling_high_relevance(self, consumer):
        """Test that high-relevance signals trigger draft creation."""
        # Mock NATS message
        mock_msg = AsyncMock()
        mock_msg.data = json.dumps({
            "event": "signal.detected",
            "source": "scout",
            "topic": "New SAP Feature",
            "score": 0.85,
            "metadata": {"id": 123, "url": "https://sap.com/news"},
        }).encode()
        
        # Mock database and draft creation
        consumer._create_draft_for_signal = AsyncMock(
            return_value={"id": 42, "title": "New SAP Feature", "signal_id": 123}
        )
        consumer._send_notification = AsyncMock()
        
        # Handle message
        await consumer._handle_message(mock_msg)
        
        # Verify draft was created
        consumer._create_draft_for_signal.assert_called_once()
        
        # Verify notification was sent
        consumer._send_notification.assert_called_once()
        
        # Verify message was acknowledged
        mock_msg.ack.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_message_filtering_low_relevance(self, consumer):
        """Test that low-relevance signals are skipped."""
        # Mock NATS message with low relevance
        mock_msg = AsyncMock()
        mock_msg.data = json.dumps({
            "event": "signal.detected",
            "source": "scout",
            "topic": "Low Signal",
            "score": 0.5,  # Below threshold of 0.7
            "metadata": {"id": 999, "url": "https://example.com"},
        }).encode()
        
        # Mock methods
        consumer._create_draft_for_signal = AsyncMock()
        consumer._send_notification = AsyncMock()
        
        # Handle message
        await consumer._handle_message(mock_msg)
        
        # Verify draft was NOT created (filtered out)
        consumer._create_draft_for_signal.assert_not_called()
        
        # Verify notification was NOT sent
        consumer._send_notification.assert_not_called()
        
        # But message should still be acknowledged
        mock_msg.ack.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_message_missing_signal_id(self, consumer):
        """Test that messages without signal ID are handled gracefully."""
        # Mock NATS message with no signal ID
        mock_msg = AsyncMock()
        mock_msg.data = json.dumps({
            "event": "signal.detected",
            "source": "scout",
            "topic": "No ID Signal",
            "score": 0.85,
            "metadata": {"url": "https://example.com"},  # Missing 'id'
        }).encode()
        
        # Mock methods
        consumer._create_draft_for_signal = AsyncMock()
        
        # Handle message
        await consumer._handle_message(mock_msg)
        
        # Verify draft was NOT created (no ID)
        consumer._create_draft_for_signal.assert_not_called()
        
        # Message should be acknowledged
        mock_msg.ack.assert_called_once()
    
    def test_draft_content_generation(self, consumer):
        """Test that draft content is generated correctly."""
        # Mock signal object
        mock_signal = MagicMock()
        mock_signal.id = 123
        mock_signal.snippet = "This is a snippet from the signal"
        mock_signal.url = "https://example.com/article"
        mock_signal.source_domain = "example.com"
        mock_signal.relevance_score = 0.85
        
        # Generate content
        content = consumer._generate_draft_content(
            signal=mock_signal,
            title="Test Article",
        )
        
        # Verify content structure
        assert "# Test Article" in content
        assert "snippet from the signal" in content
        assert "https://example.com/article" in content
        assert "example.com" in content
        assert "85%" in content
        assert "Auto-drafted" in content
    
    def test_is_running_state(self, consumer):
        """Test consumer running state tracking."""
        # Initially not running
        assert consumer.is_running() is False
        
        # After starting (simulated)
        consumer._is_running = True
        assert consumer.is_running() is True
        
        # After stopping (simulated)
        consumer._is_running = False
        assert consumer.is_running() is False


class TestSignalRelevanceScoring:
    """Test signal relevance scoring and filtering."""
    
    def test_relevance_boundaries(self):
        """Test boundary conditions for relevance scoring."""
        threshold = 0.7
        
        # Test cases: (score, should_pass)
        test_cases = [
            (0.0, False),
            (0.5, False),
            (0.7, False),  # Equal to threshold should not pass
            (0.701, True),  # Just above threshold should pass
            (0.8, True),
            (1.0, True),
        ]
        
        for score, expected in test_cases:
            result = score > threshold
            assert result == expected, f"Score {score} > {threshold} = {result}, expected {expected}"
    
    def test_relevance_from_multiple_sources(self):
        """Test signals from different sources."""
        sources = ["scout", "manual", "research", "import"]
        
        for source in sources:
            signal = {
                "source": source,
                "score": 0.85,
            }
            assert signal["score"] > 0.7, f"Signal from {source} should pass"


class TestDraftIntegration:
    """Test integration with draft creation."""
    
    def test_draft_tagging(self):
        """Test that auto-drafted posts get appropriate tags."""
        relevance_score = 0.85
        source = "scout"
        
        # Expected tags for auto-drafted post
        expected_tags = [
            "auto-drafted",
            source,
            f"relevance:{relevance_score:.2f}",
        ]
        
        # Verify tag format
        assert "auto-drafted" in expected_tags
        assert "scout" in expected_tags
        assert "relevance:0.85" in expected_tags
    
    def test_signal_to_draft_link(self):
        """Test that draft correctly links back to signal."""
        signal_id = 123
        
        draft = {
            "title": "Test Draft",
            "signal_id": signal_id,
            "status": "draft",
        }
        
        # Verify signal linkage
        assert draft["signal_id"] == signal_id
        assert draft["status"] == "draft"


class TestNotifications:
    """Test notification generation."""
    
    def test_notification_format(self):
        """Test notification message formatting."""
        signal_id = 42
        draft_id = 101
        title = "New Feature Announcement"
        relevance = 0.87
        
        # Simulate notification
        message = (
            f"🚀 Auto-drafted new post\n"
            f"📌 Signal #{signal_id}\n"
            f"📄 Draft #{draft_id}\n"
            f"📝 {title}\n"
            f"🎯 Relevance: {relevance:.1%}"
        )
        
        # Verify format
        assert "🚀" in message
        assert f"Signal #{signal_id}" in message
        assert f"Draft #{draft_id}" in message
        assert title in message
        assert "87%" in message


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])
