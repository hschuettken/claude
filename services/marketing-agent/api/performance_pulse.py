"""
Performance Pulse API — Sparkline charts, topic heatmap, pillar effectiveness radar, hook analysis.

Endpoints:
  - GET /api/v1/performance-pulse/sparklines — Topic performance sparklines
  - GET /api/v1/performance-pulse/heatmap — Weekly performance heatmap by pillar
  - GET /api/v1/performance-pulse/pillar-radar — Pillar effectiveness radar data
  - GET /api/v1/performance-pulse/hook-analysis — Top-performing hooks and patterns

Aggregates performance data from blog_posts and performance_snapshots, keyed by:
- Topics (pillar-based)
- Pillars (1-6 strategic content areas)
- Hooks (from LinkedInPost.hook field)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from sqlalchemy import select, func, desc, and_, or_
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from models import (
    Draft, BlogPost, LinkedInPost, PerformanceSnapshot, Topic,
    ContentPillar, DraftStatus, Platform
)

router = APIRouter(tags=["performance-pulse"])


# ============================================================================
# Response Models
# ============================================================================

class SparklinePoint(BaseModel):
    """Single point in a sparkline time series."""
    date: str
    value: float


class SparklineData(BaseModel):
    """Sparkline chart data for a single topic/metric."""
    name: str
    topic_id: Optional[int] = None
    pillar_id: Optional[int] = None
    data: List[SparklinePoint]
    color: str
    trend: Optional[float] = None  # Percentage change (recent vs. previous period)


class HeatmapCell(BaseModel):
    """Single cell in a heatmap (week x pillar)."""
    week: int
    pillar_id: int
    pillar_name: str
    views: int
    engagement_rate: float
    post_count: int
    color: Optional[str] = None  # For UI rendering


class Heatmap(BaseModel):
    """Weekly performance heatmap by pillar."""
    weeks: List[int]
    pillars: List[Dict[str, Any]]
    cells: List[HeatmapCell]


class RadarMetric(BaseModel):
    """Single metric in pillar effectiveness radar."""
    pillar_id: int
    pillar_name: str
    effectiveness_score: float  # 0.0-1.0
    avg_views: int
    avg_engagement: float
    post_count: int


class Radar(BaseModel):
    """Pillar effectiveness radar data."""
    metrics: List[RadarMetric]
    max_effectiveness: float


class Hook(BaseModel):
    """Hook pattern analysis."""
    hook_text: str
    usage_count: int
    avg_engagement_rate: float
    avg_views: int
    pillar_id: Optional[int] = None
    pillar_name: Optional[str] = None


class HookAnalysis(BaseModel):
    """Hook effectiveness analysis."""
    top_hooks: List[Hook]
    total_hooks_analyzed: int
    avg_hook_engagement: float


class PerformancePulse(BaseModel):
    """Complete performance pulse dashboard."""
    sparklines: List[SparklineData]
    heatmap: Heatmap
    radar: Radar
    hook_analysis: HookAnalysis
    period_days: int
    generated_at: datetime


# ============================================================================
# Helper Functions
# ============================================================================

def _calculate_trend(values: List[float]) -> float:
    """Calculate percentage change: recent 50% vs. older 50%."""
    if len(values) < 2:
        return 0.0
    
    mid = len(values) // 2
    recent = sum(values[mid:]) / len(values[mid:]) if values[mid:] else 0
    older = sum(values[:mid]) / len(values[:mid]) if values[:mid] else 0
    
    if older == 0:
        return 0.0
    
    return ((recent - older) / older) * 100


def _normalize_effectiveness(score: float, max_score: float) -> float:
    """Normalize effectiveness score to 0.0-1.0 range."""
    if max_score == 0:
        return 0.5
    normalized = min(score / max_score, 1.0)
    return round(normalized, 3)


def _get_color_for_pillar(pillar_id: Optional[int]) -> str:
    """Return a consistent color for a pillar."""
    colors = {
        1: "#FF6B6B",  # SAP deep technical — red
        2: "#4ECDC4",  # SAP roadmap & features — teal
        3: "#45B7D1",  # Architecture & decisions — blue
        4: "#FFA07A",  # AI in the enterprise — coral
        5: "#98D8C8",  # Builder / lab / infrastructure — mint
        6: "#F7DC6F",  # Personal builder lifestyle — yellow
    }
    return colors.get(pillar_id, "#95A5A6")  # Gray default


def _get_intensity_color(engagement_rate: float) -> str:
    """Return a color intensity based on engagement rate (0.0-1.0)."""
    if engagement_rate < 0.2:
        return "#EBF5FB"  # Very light blue
    elif engagement_rate < 0.4:
        return "#AED6F1"  # Light blue
    elif engagement_rate < 0.6:
        return "#5DADE2"  # Medium blue
    elif engagement_rate < 0.8:
        return "#2E86C1"  # Dark blue
    else:
        return "#1B4F72"  # Very dark blue


# ============================================================================
# API Endpoints
# ============================================================================

@router.get(
    "/performance-pulse/sparklines",
    response_model=List[SparklineData],
    summary="Topic Performance Sparklines",
    description="30-day sparkline trends for each topic (views, engagement).",
)
async def get_sparklines(
    days: int = Query(30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
) -> List[SparklineData]:
    """
    Get performance sparklines for all topics over the past N days.
    
    Returns views and engagement trends grouped by topic.
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    sparklines: List[SparklineData] = []
    
    # Query all topics
    topics_query = select(Topic)
    result = await db.execute(topics_query)
    topics = result.scalars().all()
    
    for topic in topics:
        # Get snapshots for this topic's posts
        snapshots_query = (
            select(
                func.date_trunc("day", PerformanceSnapshot.recorded_at).label("day"),
                func.sum(PerformanceSnapshot.views).label("total_views"),
                func.avg(PerformanceSnapshot.engagement_rate).label("avg_engagement"),
            )
            .select_from(PerformanceSnapshot)
            .join(BlogPost, BlogPost.id == PerformanceSnapshot.post_id)
            .join(Draft, Draft.id == BlogPost.draft_id)
            .where(
                and_(
                    Draft.topic_id == topic.id,
                    PerformanceSnapshot.recorded_at >= cutoff_date,
                )
            )
            .group_by(func.date_trunc("day", PerformanceSnapshot.recorded_at))
            .order_by(func.date_trunc("day", PerformanceSnapshot.recorded_at))
        )
        
        snapshot_result = await db.execute(snapshots_query)
        snapshots = snapshot_result.all()
        
        if not snapshots:
            continue
        
        # Build sparkline data (views)
        data_points = [
            SparklinePoint(
                date=snap[0].strftime("%Y-%m-%d") if snap[0] else "unknown",
                value=float(snap[1] or 0),
            )
            for snap in snapshots
        ]
        
        trend = _calculate_trend([pt.value for pt in data_points])
        
        sparklines.append(
            SparklineData(
                name=topic.name,
                topic_id=topic.id,
                pillar_id=topic.pillar_id,
                data=data_points,
                color=_get_color_for_pillar(topic.pillar_id),
                trend=trend,
            )
        )
    
    return sparklines


@router.get(
    "/performance-pulse/heatmap",
    response_model=Heatmap,
    summary="Weekly Performance Heatmap",
    description="Performance by week and content pillar (4-week rolling window).",
)
async def get_heatmap(
    weeks: int = Query(4, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> Heatmap:
    """
    Get a heatmap of performance metrics by week and pillar.
    
    Weeks are ISO weeks counting backward from today.
    """
    # Get recent weeks
    week_range = []
    for i in range(weeks):
        date = datetime.utcnow() - timedelta(weeks=i)
        week_num = date.isocalendar()[1]
        week_range.insert(0, week_num)
    
    # Get all pillars
    pillars_query = select(ContentPillar).order_by(ContentPillar.kg_id)
    pillar_result = await db.execute(pillars_query)
    pillars = pillar_result.scalars().all()
    
    pillar_info = [
        {"id": p.kg_id, "name": p.name, "color": p.color or _get_color_for_pillar(p.kg_id)}
        for p in pillars
    ]
    
    # Build heatmap cells
    cells: List[HeatmapCell] = []
    
    for week_num in week_range:
        for pillar in pillars:
            # Query posts published in this week, in this pillar
            cell_query = (
                select(
                    func.count(BlogPost.id).label("post_count"),
                    func.sum(PerformanceSnapshot.views).label("total_views"),
                    func.avg(PerformanceSnapshot.engagement_rate).label("avg_engagement"),
                )
                .select_from(BlogPost)
                .join(Draft, Draft.id == BlogPost.draft_id)
                .join(Topic, Topic.id == Draft.topic_id)
                .outerjoin(PerformanceSnapshot, PerformanceSnapshot.post_id == BlogPost.id)
                .where(
                    and_(
                        Topic.pillar_id == pillar.kg_id,
                        func.extract("isodow", BlogPost.published_at) == week_num,
                    )
                )
            )
            
            cell_result = await db.execute(cell_query)
            cell_data = cell_result.one_or_none()
            
            post_count = cell_data[0] if cell_data and cell_data[0] else 0
            total_views = int(cell_data[1] or 0) if cell_data else 0
            avg_engagement = float(cell_data[2] or 0.0) if cell_data else 0.0
            
            cells.append(
                HeatmapCell(
                    week=week_num,
                    pillar_id=pillar.kg_id,
                    pillar_name=pillar.name,
                    views=total_views,
                    engagement_rate=avg_engagement,
                    post_count=post_count,
                    color=_get_intensity_color(avg_engagement if post_count > 0 else 0),
                )
            )
    
    return Heatmap(
        weeks=week_range,
        pillars=pillar_info,
        cells=cells,
    )


@router.get(
    "/performance-pulse/pillar-radar",
    response_model=Radar,
    summary="Pillar Effectiveness Radar",
    description="Effectiveness scores for each content pillar.",
)
async def get_pillar_radar(
    days: int = Query(90, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
) -> Radar:
    """
    Get pillar effectiveness radar data.
    
    Effectiveness = (avg_engagement * 0.6) + (normalized_views * 0.4)
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Get all pillars
    pillars_query = select(ContentPillar).order_by(ContentPillar.kg_id)
    pillar_result = await db.execute(pillars_query)
    pillars = pillar_result.scalars().all()
    
    metrics: List[RadarMetric] = []
    max_effectiveness = 0.0
    
    for pillar in pillars:
        # Get posts in this pillar published in the period
        stats_query = (
            select(
                func.count(BlogPost.id).label("post_count"),
                func.avg(PerformanceSnapshot.engagement_rate).label("avg_engagement"),
                func.avg(PerformanceSnapshot.views).label("avg_views"),
            )
            .select_from(BlogPost)
            .join(Draft, Draft.id == BlogPost.draft_id)
            .join(Topic, Topic.id == Draft.topic_id)
            .outerjoin(PerformanceSnapshot, PerformanceSnapshot.post_id == BlogPost.id)
            .where(
                and_(
                    Topic.pillar_id == pillar.kg_id,
                    BlogPost.published_at >= cutoff_date,
                )
            )
        )
        
        stats_result = await db.execute(stats_query)
        stats = stats_result.one_or_none()
        
        post_count = stats[0] if stats and stats[0] else 0
        avg_engagement = float(stats[1] or 0.0) if stats else 0.0
        avg_views = int(stats[2] or 0) if stats else 0
        
        # Calculate effectiveness score: weighted average of engagement and views
        effectiveness = (avg_engagement * 0.6) + (min(avg_views / 1000, 1.0) * 0.4)
        max_effectiveness = max(max_effectiveness, effectiveness)
        
        metrics.append(
            RadarMetric(
                pillar_id=pillar.kg_id,
                pillar_name=pillar.name,
                effectiveness_score=round(effectiveness, 3),
                avg_views=avg_views,
                avg_engagement=round(avg_engagement, 3),
                post_count=post_count,
            )
        )
    
    return Radar(
        metrics=metrics,
        max_effectiveness=max_effectiveness,
    )


@router.get(
    "/performance-pulse/hook-analysis",
    response_model=HookAnalysis,
    summary="Hook Pattern Analysis",
    description="Most effective LinkedIn hooks and hook patterns.",
)
async def get_hook_analysis(
    limit: int = Query(10, ge=5, le=50),
    days: int = Query(90, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
) -> HookAnalysis:
    """
    Analyze hook effectiveness across LinkedIn posts.
    
    Hooks are the opening lines of LinkedIn posts (from LinkedInPost.hook field).
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    # Get hooks with performance data
    hooks_query = (
        select(
            LinkedInPost.hook,
            func.count(LinkedInPost.id).label("usage_count"),
            func.avg(PerformanceSnapshot.engagement_rate).label("avg_engagement"),
            func.avg(PerformanceSnapshot.views).label("avg_views"),
            Topic.pillar_id,
            ContentPillar.name.label("pillar_name"),
        )
        .select_from(LinkedInPost)
        .join(Draft, Draft.id == LinkedInPost.draft_id)
        .join(Topic, Topic.id == Draft.topic_id)
        .outerjoin(ContentPillar, ContentPillar.kg_id == Topic.pillar_id)
        .outerjoin(
            PerformanceSnapshot,
            and_(
                PerformanceSnapshot.post_id == LinkedInPost.draft_id,
                PerformanceSnapshot.platform == "linkedin",
            ),
        )
        .where(
            and_(
                LinkedInPost.hook.isnot(None),
                LinkedInPost.posted_at >= cutoff_date,
            )
        )
        .group_by(LinkedInPost.hook, Topic.pillar_id, ContentPillar.name)
        .order_by(desc(func.avg(PerformanceSnapshot.engagement_rate)))
        .limit(limit)
    )
    
    hooks_result = await db.execute(hooks_query)
    hooks_data = hooks_result.all()
    
    top_hooks = [
        Hook(
            hook_text=row[0],
            usage_count=int(row[1] or 0),
            avg_engagement_rate=round(float(row[2] or 0.0), 3),
            avg_views=int(row[3] or 0),
            pillar_id=row[4],
            pillar_name=row[5],
        )
        for row in hooks_data
        if row[0]  # Filter out None hooks
    ]
    
    # Calculate overall hook engagement average
    avg_hook_engagement_query = (
        select(func.avg(PerformanceSnapshot.engagement_rate))
        .select_from(LinkedInPost)
        .outerjoin(
            PerformanceSnapshot,
            and_(
                PerformanceSnapshot.post_id == LinkedInPost.draft_id,
                PerformanceSnapshot.platform == "linkedin",
            ),
        )
        .where(LinkedInPost.posted_at >= cutoff_date)
    )
    
    avg_result = await db.execute(avg_hook_engagement_query)
    avg_engagement = float(avg_result.scalar() or 0.0)
    
    # Count total hooks analyzed
    total_hooks_query = (
        select(func.count(LinkedInPost.id))
        .where(
            and_(
                LinkedInPost.hook.isnot(None),
                LinkedInPost.posted_at >= cutoff_date,
            )
        )
    )
    
    total_result = await db.execute(total_hooks_query)
    total_hooks = int(total_result.scalar() or 0)
    
    return HookAnalysis(
        top_hooks=top_hooks,
        total_hooks_analyzed=total_hooks,
        avg_hook_engagement=round(avg_engagement, 3),
    )


@router.get(
    "/performance-pulse",
    response_model=PerformancePulse,
    summary="Complete Performance Pulse Dashboard",
    description="Integrated dashboard with sparklines, heatmap, radar, and hook analysis.",
)
async def get_performance_pulse(
    days: int = Query(30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
) -> PerformancePulse:
    """
    Get the complete performance pulse dashboard.
    
    Integrates:
    - Sparklines per topic
    - Weekly heatmap by pillar
    - Pillar effectiveness radar
    - Hook pattern analysis
    """
    sparklines = await get_sparklines(days=days, db=db)
    heatmap = await get_heatmap(weeks=4, db=db)
    radar = await get_pillar_radar(days=days, db=db)
    hooks = await get_hook_analysis(days=days, db=db)
    
    return PerformancePulse(
        sparklines=sparklines,
        heatmap=heatmap,
        radar=radar,
        hook_analysis=hooks,
        period_days=days,
        generated_at=datetime.utcnow(),
    )
