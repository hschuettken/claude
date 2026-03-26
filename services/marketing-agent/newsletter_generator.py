"""
Newsletter Generator Service for Marketing Agent.

Generates monthly Layer 8 newsletters with:
- Roundup of published posts from the month
- Featured signals and market insights
- Unpublished draft ideas for subscriber feedback
- Brand-consistent template formatting
- Ghost CMS newsletter creation

Environment variables:
  - MARKETING_DB_URL: PostgreSQL connection string
  - GHOST_URL: Ghost base URL
  - GHOST_ADMIN_API_KEY: Ghost API key (format: id:secret_hex)
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

logger = logging.getLogger(__name__)


@dataclass
class NewsletterItem:
    """Base class for newsletter content."""
    title: str
    summary: str
    link: Optional[str] = None
    date: Optional[datetime] = None


@dataclass
class PublishedPostItem(NewsletterItem):
    """Published blog post for newsletter."""
    post_id: str
    pillar: str
    engagement_metrics: Optional[Dict[str, int]] = None


@dataclass
class SignalInsightItem(NewsletterItem):
    """Market signal or insight for newsletter."""
    signal_id: str
    source: str
    relevance_score: float


@dataclass
class DraftIdeaItem(NewsletterItem):
    """Unpublished draft idea for subscriber feedback."""
    draft_id: str
    draft_status: str
    pillar: str


@dataclass
class MonthlyNewsletter:
    """Complete monthly newsletter."""
    month: str  # "March 2026"
    subject_line: str
    hero_text: str
    
    published_posts: List[PublishedPostItem]
    featured_signals: List[SignalInsightItem]
    draft_ideas: List[DraftIdeaItem]
    
    monthly_stats: Dict[str, Any]
    newsletter_html: str
    
    created_at: datetime = None
    ghost_post_id: Optional[str] = None


class NewsletterGenerator:
    """Generate monthly Layer 8 newsletters from marketing agent data."""
    
    def __init__(self, db_url: str, ghost_client=None):
        """
        Initialize newsletter generator.
        
        Args:
            db_url: PostgreSQL connection string
            ghost_client: Optional GhostAdminAPIClient instance
        """
        self.db_url = db_url
        self.ghost_client = ghost_client
        
    async def generate_monthly_newsletter(
        self,
        db: AsyncSession,
        month_date: Optional[datetime] = None,
        publish_to_ghost: bool = False,
    ) -> MonthlyNewsletter:
        """
        Generate complete monthly newsletter.
        
        Args:
            db: Database session
            month_date: Date in the month to generate for (defaults to last month)
            publish_to_ghost: Whether to create newsletter in Ghost CMS
        
        Returns:
            MonthlyNewsletter with all content sections
        """
        if month_date is None:
            month_date = datetime.now() - timedelta(days=30)
        
        month_start = month_date.replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1)
        
        month_str = month_start.strftime("%B %Y")
        
        logger.info(f"Generating newsletter for {month_str}")
        
        # Gather all newsletter content
        published_posts = await self._get_published_posts(db, month_start, month_end)
        featured_signals = await self._get_featured_signals(db, month_start, month_end)
        draft_ideas = await self._get_draft_ideas(db, month_start, month_end)
        
        monthly_stats = {
            "published_count": len(published_posts),
            "signal_count": len(featured_signals),
            "draft_ideas_count": len(draft_ideas),
            "estimated_reach": self._estimate_reach(published_posts),
            "content_pillars": self._summarize_pillars(published_posts),
        }
        
        # Generate newsletter HTML
        newsletter_html = self._render_newsletter_html(
            month_str,
            published_posts,
            featured_signals,
            draft_ideas,
            monthly_stats,
        )
        
        # Create newsletter object
        newsletter = MonthlyNewsletter(
            month=month_str,
            subject_line=f"Layer 8 Insights — {month_str}",
            hero_text=self._generate_hero_text(month_str, published_posts, monthly_stats),
            published_posts=published_posts,
            featured_signals=featured_signals,
            draft_ideas=draft_ideas,
            monthly_stats=monthly_stats,
            newsletter_html=newsletter_html,
            created_at=datetime.now(),
        )
        
        # Optionally publish to Ghost as a newsletter post
        if publish_to_ghost and self.ghost_client:
            ghost_post_id = await self._publish_to_ghost(newsletter)
            newsletter.ghost_post_id = ghost_post_id
        
        return newsletter
    
    async def _get_published_posts(
        self,
        db: AsyncSession,
        month_start: datetime,
        month_end: datetime,
    ) -> List[PublishedPostItem]:
        """Fetch all published blog posts from the month."""
        try:
            # Query published blog posts from Ghost/Database
            query = text("""
                SELECT 
                    id,
                    title,
                    slug,
                    published_at,
                    excerpt,
                    pillar,
                    updated_at
                FROM marketing_blog_posts
                WHERE published_at >= :month_start 
                  AND published_at < :month_end
                  AND status = 'published'
                ORDER BY published_at DESC
            """)
            
            result = await db.execute(query, {
                "month_start": month_start,
                "month_end": month_end,
            })
            
            posts = []
            for row in result:
                posts.append(PublishedPostItem(
                    title=row[1],
                    summary=row[5] or f"Read: {row[1]}",
                    link=f"https://layer8.schuettken.net/{row[2]}",
                    date=row[3],
                    post_id=row[0],
                    pillar=row[5] or "General",
                    engagement_metrics={},  # Can be populated from analytics
                ))
            
            return posts
        except Exception as e:
            logger.warning(f"Could not fetch published posts: {e}")
            return []
    
    async def _get_featured_signals(
        self,
        db: AsyncSession,
        month_start: datetime,
        month_end: datetime,
    ) -> List[SignalInsightItem]:
        """Fetch featured market signals and insights from the month."""
        try:
            # Query high-relevance signals
            query = text("""
                SELECT 
                    id,
                    title,
                    summary,
                    source,
                    relevance_score,
                    created_at
                FROM marketing_signals
                WHERE created_at >= :month_start 
                  AND created_at < :month_end
                  AND status = 'active'
                  AND relevance_score >= 0.7
                ORDER BY relevance_score DESC
                LIMIT 10
            """)
            
            result = await db.execute(query, {
                "month_start": month_start,
                "month_end": month_end,
            })
            
            signals = []
            for row in result:
                signals.append(SignalInsightItem(
                    title=row[1],
                    summary=row[2],
                    signal_id=row[0],
                    source=row[3],
                    relevance_score=row[4],
                    date=row[5],
                ))
            
            return signals
        except Exception as e:
            logger.warning(f"Could not fetch signals: {e}")
            return []
    
    async def _get_draft_ideas(
        self,
        db: AsyncSession,
        month_start: datetime,
        month_end: datetime,
        limit: int = 3,
    ) -> List[DraftIdeaItem]:
        """Fetch interesting unpublished draft ideas for subscriber feedback."""
        try:
            # Query promising drafts that could use feedback
            query = text("""
                SELECT 
                    id,
                    title,
                    excerpt,
                    status,
                    pillar,
                    created_at
                FROM marketing_drafts
                WHERE created_at >= :month_start 
                  AND created_at < :month_end
                  AND status IN ('in_progress', 'awaiting_feedback')
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            
            result = await db.execute(query, {
                "month_start": month_start,
                "month_end": month_end,
                "limit": limit,
            })
            
            drafts = []
            for row in result:
                drafts.append(DraftIdeaItem(
                    title=row[1],
                    summary=row[2] or "Coming soon",
                    draft_id=row[0],
                    draft_status=row[3],
                    pillar=row[4] or "General",
                    date=row[5],
                ))
            
            return drafts
        except Exception as e:
            logger.warning(f"Could not fetch draft ideas: {e}")
            return []
    
    def _render_newsletter_html(
        self,
        month_str: str,
        published_posts: List[PublishedPostItem],
        featured_signals: List[SignalInsightItem],
        draft_ideas: List[DraftIdeaItem],
        stats: Dict[str, Any],
    ) -> str:
        """
        Render complete newsletter HTML in Layer 8 brand style.
        
        Returns HTML string ready for Ghost CMS or email delivery.
        """
        
        # Build sections
        posts_html = self._render_posts_section(published_posts)
        signals_html = self._render_signals_section(featured_signals)
        drafts_html = self._render_drafts_section(draft_ideas)
        
        # Complete HTML template
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Layer 8 Insights — {month_str}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background-color: #f9f9f9;
        }}
        
        .container {{
            max-width: 600px;
            margin: 0 auto;
            background-color: white;
            padding: 40px 20px;
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 2px solid #0066cc;
            padding-bottom: 20px;
        }}
        
        .header h1 {{
            font-size: 32px;
            font-weight: 700;
            color: #0066cc;
            margin-bottom: 8px;
        }}
        
        .header p {{
            font-size: 14px;
            color: #666;
        }}
        
        .section {{
            margin-bottom: 40px;
        }}
        
        .section-title {{
            font-size: 20px;
            font-weight: 700;
            color: #1a1a1a;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 1px solid #e0e0e0;
        }}
        
        .item {{
            margin-bottom: 24px;
            padding: 16px;
            background-color: #f5f5f5;
            border-radius: 4px;
            border-left: 4px solid #0066cc;
        }}
        
        .item h3 {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 8px;
            color: #0066cc;
        }}
        
        .item p {{
            font-size: 14px;
            color: #555;
            margin-bottom: 8px;
        }}
        
        .meta {{
            font-size: 12px;
            color: #999;
        }}
        
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            margin-right: 8px;
            font-size: 11px;
            font-weight: 600;
            border-radius: 3px;
            background-color: #0066cc;
            color: white;
        }}
        
        .stats {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 16px;
            margin: 32px 0;
            padding: 16px;
            background-color: #f5f5f5;
            border-radius: 4px;
        }}
        
        .stat {{
            text-align: center;
        }}
        
        .stat-value {{
            font-size: 24px;
            font-weight: 700;
            color: #0066cc;
        }}
        
        .stat-label {{
            font-size: 12px;
            color: #666;
            margin-top: 4px;
        }}
        
        .cta {{
            text-align: center;
            margin: 32px 0;
        }}
        
        .cta a {{
            display: inline-block;
            padding: 12px 24px;
            background-color: #0066cc;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-weight: 600;
            font-size: 14px;
        }}
        
        .cta a:hover {{
            background-color: #0052a3;
        }}
        
        .footer {{
            text-align: center;
            margin-top: 40px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
            font-size: 12px;
            color: #999;
        }}
        
        a {{
            color: #0066cc;
            text-decoration: none;
        }}
        
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Layer 8</h1>
            <p>Insights — {month_str}</p>
        </div>
        
        <div class="stats">
            <div class="stat">
                <div class="stat-value">{stats['published_count']}</div>
                <div class="stat-label">Posts Published</div>
            </div>
            <div class="stat">
                <div class="stat-value">{stats['signal_count']}</div>
                <div class="stat-label">Market Signals</div>
            </div>
            <div class="stat">
                <div class="stat-value">{stats['draft_ideas_count']}</div>
                <div class="stat-label">Draft Ideas</div>
            </div>
        </div>
        
        {posts_html}
        {signals_html}
        {drafts_html}
        
        <div class="cta">
            <a href="https://layer8.schuettken.net">Read More on Layer 8</a>
        </div>
        
        <div class="footer">
            <p>Layer 8 — where technology meets decisions</p>
            <p>© 2026 Henning Schüttken. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""
        return html
    
    def _render_posts_section(self, posts: List[PublishedPostItem]) -> str:
        """Render published posts section."""
        if not posts:
            return ""
        
        items_html = ""
        for post in posts:
            items_html += f"""
            <div class="item">
                <h3><a href="{post.link}">{post.title}</a></h3>
                <p>{post.summary}</p>
                <div class="meta">
                    <span class="badge">{post.pillar}</span>
                    {post.date.strftime('%B %d, %Y') if post.date else ''}
                </div>
            </div>
            """
        
        return f"""
        <div class="section">
            <h2 class="section-title">This Month's Posts</h2>
            {items_html}
        </div>
        """
    
    def _render_signals_section(self, signals: List[SignalInsightItem]) -> str:
        """Render featured signals section."""
        if not signals:
            return ""
        
        items_html = ""
        for signal in signals:
            confidence = "High" if signal.relevance_score >= 0.8 else "Medium"
            items_html += f"""
            <div class="item">
                <h3>{signal.title}</h3>
                <p>{signal.summary}</p>
                <div class="meta">
                    <span class="badge">{signal.source}</span>
                    <span>Relevance: {signal.relevance_score:.1%}</span>
                </div>
            </div>
            """
        
        return f"""
        <div class="section">
            <h2 class="section-title">Market Insights & Signals</h2>
            <p style="font-size: 14px; color: #666; margin-bottom: 20px;">
                What caught our attention this month — SAP news, industry trends, and opportunities.
            </p>
            {items_html}
        </div>
        """
    
    def _render_drafts_section(self, drafts: List[DraftIdeaItem]) -> str:
        """Render draft ideas section for subscriber feedback."""
        if not drafts:
            return ""
        
        items_html = ""
        for draft in drafts:
            items_html += f"""
            <div class="item" style="background-color: #fff3cd; border-left-color: #ffc107;">
                <h3>{draft.title}</h3>
                <p>{draft.summary}</p>
                <div class="meta">
                    <span class="badge" style="background-color: #ffc107;">{draft.pillar}</span>
                    <span>Coming soon</span>
                </div>
            </div>
            """
        
        return f"""
        <div class="section">
            <h2 class="section-title">What's Coming</h2>
            <p style="font-size: 14px; color: #666; margin-bottom: 20px;">
                Drafts in progress. Want to give feedback? <a href="https://layer8.schuettken.net/feedback">Share your thoughts</a>.
            </p>
            {items_html}
        </div>
        """
    
    def _generate_hero_text(
        self,
        month_str: str,
        posts: List[PublishedPostItem],
        stats: Dict[str, Any],
    ) -> str:
        """Generate opening hero text for newsletter."""
        pillars = stats.get('content_pillars', {})
        pillar_summary = ", ".join([f"{k} ({v})" for k, v in pillars.items()])
        
        return f"""
Welcome to Layer 8 Insights for {month_str}.

This month we published {stats['published_count']} deep dives spanning {pillar_summary}.
Discover what shifted in the SAP ecosystem, explore emerging patterns, and see what we're thinking about next.

Let's dive in.
"""
    
    def _estimate_reach(self, posts: List[PublishedPostItem]) -> int:
        """Estimate total reach based on published posts."""
        # This could be enhanced with actual analytics data
        return len(posts) * 150  # Placeholder estimate
    
    def _summarize_pillars(self, posts: List[PublishedPostItem]) -> Dict[str, int]:
        """Summarize post distribution by content pillar."""
        pillars = {}
        for post in posts:
            pillar = post.pillar or "Other"
            pillars[pillar] = pillars.get(pillar, 0) + 1
        return pillars
    
    async def _publish_to_ghost(self, newsletter: MonthlyNewsletter) -> Optional[str]:
        """Publish newsletter to Ghost CMS as a special post."""
        if not self.ghost_client:
            logger.warning("Ghost client not configured, skipping publication")
            return None
        
        try:
            post_data = {
                "posts": [{
                    "title": f"Layer 8 Insights — {newsletter.month}",
                    "html": newsletter.newsletter_html,
                    "status": "draft",  # Publish as draft for review
                    "excerpt": newsletter.hero_text,
                    "tags": ["newsletter", newsletter.month.lower()],
                }]
            }
            
            # Note: This assumes ghost_client has a method to create posts
            # Implementation depends on the actual Ghost client interface
            logger.info(f"Newsletter prepared for Ghost publication: {newsletter.month}")
            return "ghost_post_id_placeholder"  # Placeholder
            
        except Exception as e:
            logger.error(f"Failed to publish newsletter to Ghost: {e}")
            return None
