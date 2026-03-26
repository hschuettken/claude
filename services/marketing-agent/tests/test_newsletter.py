"""
Tests for Newsletter Generator.

Task 187: Newsletter engine — Monthly roundup auto-generated from published posts + signals + unpublished insights.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from newsletter_generator import (
    NewsletterGenerator,
    MonthlyNewsletter,
    PublishedPostItem,
    SignalInsightItem,
    DraftIdeaItem,
)


class TestNewsletterGenerator:
    """Test newsletter generation functionality."""
    
    @pytest.fixture
    def generator(self):
        """Create newsletter generator instance."""
        return NewsletterGenerator(db_url="postgresql://test")
    
    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = AsyncMock(spec=AsyncSession)
        return db
    
    def test_init(self, generator):
        """Test generator initialization."""
        assert generator is not None
        assert generator.db_url == "postgresql://test"
        assert generator.ghost_client is None
    
    @pytest.mark.asyncio
    async def test_generate_monthly_newsletter(self, generator, mock_db):
        """Test complete newsletter generation."""
        # Mock database responses
        mock_db.execute.side_effect = [
            MagicMock(  # Published posts
                __iter__=lambda x: iter([
                    ("post-1", "SAP Datasphere Tips", "Tips for using SAP Datasphere",
                     "SAP technical", datetime.now(), datetime.now()),
                    ("post-2", "Enterprise AI", "Building AI into enterprise systems",
                     "AI in enterprise", datetime.now() - timedelta(days=5), datetime.now()),
                ]),
            ),
            MagicMock(  # Signals
                __iter__=lambda x: iter([
                    ("signal-1", "SAP BTP Update", "New SAP BTP capabilities released",
                     "SAP News", 0.85, datetime.now()),
                    ("signal-2", "AI Governance", "Enterprise AI governance best practices",
                     "Industry News", 0.72, datetime.now() - timedelta(days=3)),
                ]),
            ),
            MagicMock(  # Draft ideas
                __iter__=lambda x: iter([
                    ("draft-1", "Building Data Products", "How to approach data product design",
                     "in_progress", "Architecture", datetime.now() - timedelta(days=10)),
                ]),
            ),
        ]
        
        # Generate newsletter
        newsletter = await generator.generate_monthly_newsletter(mock_db)
        
        # Verify structure
        assert isinstance(newsletter, MonthlyNewsletter)
        assert newsletter.month is not None
        assert newsletter.subject_line is not None
        assert newsletter.newsletter_html is not None
        assert len(newsletter.published_posts) == 2
        assert len(newsletter.featured_signals) == 2
        assert len(newsletter.draft_ideas) == 1
    
    @pytest.mark.asyncio
    async def test_get_published_posts(self, generator, mock_db):
        """Test fetching published posts."""
        month_start = datetime(2026, 3, 1)
        month_end = datetime(2026, 4, 1)
        
        mock_db.execute.return_value = MagicMock(
            __iter__=lambda x: iter([
                ("post-1", "Post Title", "slug-1", datetime(2026, 3, 15),
                 "Post excerpt", "SAP technical", datetime(2026, 3, 15)),
                ("post-2", "Another Post", "slug-2", datetime(2026, 3, 20),
                 "Excerpt 2", "Architecture", datetime(2026, 3, 20)),
            ]),
        )
        
        posts = await generator._get_published_posts(mock_db, month_start, month_end)
        
        assert len(posts) == 2
        assert posts[0].title == "Post Title"
        assert posts[0].pillar == "SAP technical"
        assert posts[0].link is not None
        assert "slug-1" in posts[0].link
    
    @pytest.mark.asyncio
    async def test_get_featured_signals(self, generator, mock_db):
        """Test fetching featured signals."""
        month_start = datetime(2026, 3, 1)
        month_end = datetime(2026, 4, 1)
        
        mock_db.execute.return_value = MagicMock(
            __iter__=lambda x: iter([
                ("signal-1", "SAP Release", "New SAP feature release",
                 "SAP News", 0.88, datetime(2026, 3, 10)),
                ("signal-2", "Industry News", "Relevant industry update",
                 "General News", 0.75, datetime(2026, 3, 15)),
            ]),
        )
        
        signals = await generator._get_featured_signals(mock_db, month_start, month_end)
        
        assert len(signals) == 2
        assert signals[0].title == "SAP Release"
        assert signals[0].relevance_score == 0.88
        assert signals[1].relevance_score == 0.75
    
    @pytest.mark.asyncio
    async def test_get_draft_ideas(self, generator, mock_db):
        """Test fetching draft ideas."""
        month_start = datetime(2026, 3, 1)
        month_end = datetime(2026, 4, 1)
        
        mock_db.execute.return_value = MagicMock(
            __iter__=lambda x: iter([
                ("draft-1", "Draft Title", "Draft excerpt here",
                 "in_progress", "SAP technical", datetime(2026, 3, 5)),
                ("draft-2", "Another Draft", "More excerpt text",
                 "awaiting_feedback", "Architecture", datetime(2026, 3, 8)),
            ]),
        )
        
        drafts = await generator._get_draft_ideas(mock_db, month_start, month_end)
        
        assert len(drafts) == 2
        assert drafts[0].title == "Draft Title"
        assert drafts[0].draft_status == "in_progress"
        assert drafts[1].draft_status == "awaiting_feedback"
    
    def test_render_newsletter_html_structure(self, generator):
        """Test that rendered HTML has expected structure."""
        posts = [
            PublishedPostItem(
                title="Test Post",
                summary="Test summary",
                link="https://example.com/post",
                post_id="post-1",
                pillar="SAP technical",
                date=datetime(2026, 3, 15),
            )
        ]
        
        signals = [
            SignalInsightItem(
                title="Test Signal",
                summary="Signal summary",
                signal_id="signal-1",
                source="SAP News",
                relevance_score=0.85,
                date=datetime(2026, 3, 10),
            )
        ]
        
        drafts = [
            DraftIdeaItem(
                title="Draft Idea",
                summary="Draft summary",
                draft_id="draft-1",
                draft_status="in_progress",
                pillar="Architecture",
                date=datetime(2026, 3, 5),
            )
        ]
        
        stats = {
            "published_count": 1,
            "signal_count": 1,
            "draft_ideas_count": 1,
            "estimated_reach": 150,
            "content_pillars": {"SAP technical": 1},
        }
        
        html = generator._render_newsletter_html(
            "March 2026",
            posts,
            signals,
            drafts,
            stats,
        )
        
        # Check structure
        assert "<html" in html
        assert "Layer 8" in html
        assert "March 2026" in html
        assert "Test Post" in html
        assert "Test Signal" in html
        assert "Draft Idea" in html
        assert "This Month's Posts" in html
        assert "Market Insights & Signals" in html
        assert "What's Coming" in html
    
    def test_render_posts_section_empty(self, generator):
        """Test posts section with no posts."""
        html = generator._render_posts_section([])
        assert html == ""
    
    def test_render_signals_section_empty(self, generator):
        """Test signals section with no signals."""
        html = generator._render_signals_section([])
        assert html == ""
    
    def test_render_drafts_section_empty(self, generator):
        """Test drafts section with no drafts."""
        html = generator._render_drafts_section([])
        assert html == ""
    
    def test_estimate_reach(self, generator):
        """Test reach estimation."""
        posts = [
            PublishedPostItem("Post 1", "Summary", post_id="1", pillar="Pillar A"),
            PublishedPostItem("Post 2", "Summary", post_id="2", pillar="Pillar B"),
            PublishedPostItem("Post 3", "Summary", post_id="3", pillar="Pillar C"),
        ]
        
        reach = generator._estimate_reach(posts)
        assert reach == 450  # 3 posts * 150 per post
    
    def test_summarize_pillars(self, generator):
        """Test pillar summarization."""
        posts = [
            PublishedPostItem("Post 1", "Summary", post_id="1", pillar="SAP technical"),
            PublishedPostItem("Post 2", "Summary", post_id="2", pillar="SAP technical"),
            PublishedPostItem("Post 3", "Summary", post_id="3", pillar="Architecture"),
        ]
        
        summary = generator._summarize_pillars(posts)
        assert summary["SAP technical"] == 2
        assert summary["Architecture"] == 1
    
    def test_generate_hero_text(self, generator):
        """Test hero text generation."""
        posts = [
            PublishedPostItem("Post 1", "Summary", post_id="1", pillar="SAP technical"),
            PublishedPostItem("Post 2", "Summary", post_id="2", pillar="Architecture"),
        ]
        
        stats = {
            "published_count": 2,
            "content_pillars": {"SAP technical": 1, "Architecture": 1},
        }
        
        hero = generator._generate_hero_text("March 2026", posts, stats)
        assert "March 2026" in hero
        assert "2" in hero  # Published count
        assert "SAP technical" in hero
        assert "Architecture" in hero
    
    @pytest.mark.asyncio
    async def test_publish_to_ghost_no_client(self, generator):
        """Test publishing when no Ghost client configured."""
        newsletter = MonthlyNewsletter(
            month="March 2026",
            subject_line="Layer 8 Insights — March 2026",
            hero_text="Test hero text",
            published_posts=[],
            featured_signals=[],
            draft_ideas=[],
            monthly_stats={},
            newsletter_html="<html>Test</html>",
        )
        
        result = await generator._publish_to_ghost(newsletter)
        assert result is None
    
    def test_monthly_newsletter_structure(self):
        """Test MonthlyNewsletter data structure."""
        newsletter = MonthlyNewsletter(
            month="March 2026",
            subject_line="Layer 8 Insights — March 2026",
            hero_text="Test hero",
            published_posts=[],
            featured_signals=[],
            draft_ideas=[],
            monthly_stats={"published_count": 0},
            newsletter_html="<html></html>",
            created_at=datetime.now(),
        )
        
        assert newsletter.month == "March 2026"
        assert newsletter.subject_line is not None
        assert newsletter.newsletter_html is not None
        assert newsletter.created_at is not None


class TestNewsletterDataClasses:
    """Test data class models."""
    
    def test_published_post_item(self):
        """Test PublishedPostItem."""
        item = PublishedPostItem(
            title="Test Post",
            summary="Test summary",
            link="https://example.com",
            post_id="post-1",
            pillar="SAP technical",
        )
        
        assert item.title == "Test Post"
        assert item.post_id == "post-1"
        assert item.pillar == "SAP technical"
    
    def test_signal_insight_item(self):
        """Test SignalInsightItem."""
        item = SignalInsightItem(
            title="Market Signal",
            summary="Signal details",
            signal_id="signal-1",
            source="SAP News",
            relevance_score=0.85,
        )
        
        assert item.title == "Market Signal"
        assert item.relevance_score == 0.85
        assert item.source == "SAP News"
    
    def test_draft_idea_item(self):
        """Test DraftIdeaItem."""
        item = DraftIdeaItem(
            title="Draft Title",
            summary="Draft summary",
            draft_id="draft-1",
            draft_status="in_progress",
            pillar="Architecture",
        )
        
        assert item.title == "Draft Title"
        assert item.draft_status == "in_progress"
        assert item.pillar == "Architecture"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
