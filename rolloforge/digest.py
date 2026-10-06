"""
Weekly Digest Generation for RolloForge

Generates comprehensive weekly reports of bookmarks with:
- Summary statistics
- Priority items by bucket
- Trend analysis
- Action items extraction
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from collections import Counter
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Shanghai")

from rolloforge.models import Bookmark, AnalysisResult
from rolloforge.storage import load_bookmarks, load_analysis_results


@dataclass
class WeeklyStats:
    """Statistics for the week."""
    total_new: int = 0
    analyzed: int = 0
    test_this_week: int = 0
    build_later: int = 0
    archive: int = 0
    ignore: int = 0
    avg_worth_score: float = 0.0
    avg_priority_score: float = 0.0
    top_sources: list[tuple[str, int]] = field(default_factory=list)
    top_authors: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class DigestItem:
    """A bookmark with analysis for digest display."""
    bookmark: Bookmark
    analysis: AnalysisResult
    action_items: list[str] = field(default_factory=list)


@dataclass
class WeeklyDigest:
    """Complete weekly digest."""
    week_start: datetime
    week_end: datetime
    generated_at: datetime
    stats: WeeklyStats
    test_this_week: list[DigestItem] = field(default_factory=list)
    build_later: list[DigestItem] = field(default_factory=list)
    archive: list[DigestItem] = field(default_factory=list)
    trends: dict[str, Any] = field(default_factory=dict)
    insights: list[str] = field(default_factory=list)


def parse_datetime(dt_str: str | None) -> datetime | None:
    """Parse ISO datetime string and normalize to local timezone."""
    if not dt_str:
        return None
    try:
        dt_str = dt_str.replace('Z', '+00:00')
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is not None:
            dt = dt.astimezone(LOCAL_TZ).replace(tzinfo=None)
        return dt
    except (ValueError, TypeError):
        return None


def extract_action_items(analysis: AnalysisResult) -> list[str]:
    """Extract actionable items from analysis."""
    actions = []
    
    # From next_action field
    if analysis.next_action and analysis.next_action.lower() not in ['none', 'null', '']:
        actions.append(analysis.next_action)
    
    # From key insights - look for imperative statements
    for insight in analysis.key_insights:
        insight_lower = insight.lower()
        action_words = ['build', 'create', 'implement', 'try', 'test', 'use', 'explore', 
                       'consider', 'research', 'learn', 'setup', 'deploy', 'integrate']
        if any(word in insight_lower for word in action_words):
            # Clean up and add as action
            action = insight.strip()
            if action and action not in actions:
                actions.append(action)
    
    # From summary - extract recommendations
    if 'should' in analysis.summary.lower() or 'recommend' in analysis.summary.lower():
        sentences = analysis.summary.split('.')
        for sent in sentences:
            sent_lower = sent.lower()
            if any(word in sent_lower for word in ['should', 'recommend', 'worth', 'consider']):
                action = sent.strip()
                if action and action not in actions:
                    actions.append(action)
    
    return actions[:3]  # Limit to top 3 actions per item


def calculate_stats(bookmarks: list[Bookmark], analyses: list[AnalysisResult]) -> WeeklyStats:
    """Calculate statistics for the week."""
    # Count by bucket
    test_this_week = sum(1 for a in analyses if a.recommendation_bucket == 'test_this_week')
    build_later = sum(1 for a in analyses if a.recommendation_bucket == 'build_later')
    archive = sum(1 for a in analyses if a.recommendation_bucket == 'archive')
    ignore = sum(1 for a in analyses if a.recommendation_bucket == 'ignore')
    
    # Calculate averages
    worth_scores = [a.worth_score for a in analyses]
    priority_scores = [a.priority_score for a in analyses]
    
    # Source and author counts
    source_counter = Counter(b.source for b in bookmarks if b.source)
    author_counter = Counter(b.author for b in bookmarks if b.author)
    
    return WeeklyStats(
        total_new=len(bookmarks),
        analyzed=len(analyses),
        test_this_week=test_this_week,
        build_later=build_later,
        archive=archive,
        ignore=ignore,
        avg_worth_score=sum(worth_scores) / len(worth_scores) if worth_scores else 0,
        avg_priority_score=sum(priority_scores) / len(priority_scores) if priority_scores else 0,
        top_sources=source_counter.most_common(5),
        top_authors=author_counter.most_common(5),
    )


def analyze_trends(
    current_bookmarks: list[Bookmark], 
    current_analyses: list[AnalysisResult],
    all_bookmarks: list[Bookmark],
    all_analyses: list[AnalysisResult]
) -> dict[str, Any]:
    """Analyze trends compared to historical data."""
    # Topic extraction (simple keyword-based)
    topic_keywords = {
        'ai-agents': ['agent', 'autonomous', 'multi-agent', 'orchestration'],
        'llm': ['llm', 'gpt', 'claude', 'language model', 'fine-tuning'],
        'coding': ['code', 'programming', 'github', 'developer', 'ide'],
        'infra': ['docker', 'gpu', 'server', 'deploy', 'kubernetes', 'cloud'],
        'productivity': ['workflow', 'automation', 'productivity', 'tool'],
        'ml-research': ['training', 'neural', 'deep learning', 'model', 'dataset'],
    }
    
    current_topics = Counter()
    for analysis in current_analyses:
        text = f"{analysis.summary} {' '.join(analysis.key_insights)}".lower()
        for topic, keywords in topic_keywords.items():
            if any(kw in text for kw in keywords):
                current_topics[topic] += 1
    
    # Calculate trend (vs previous week would need historical data)
    # For now, just show current distribution
    total = sum(current_topics.values()) or 1
    topic_distribution = {
        topic: {'count': count, 'percentage': round(count / total * 100, 1)}
        for topic, count in current_topics.most_common()
    }
    
    # Scoring trends
    current_scores = [a.worth_score for a in current_analyses]
    all_scores = [a.worth_score for a in all_analyses]
    
    avg_current = sum(current_scores) / len(current_scores) if current_scores else 0
    avg_all = sum(all_scores) / len(all_scores) if all_scores else 0
    
    return {
        'topic_distribution': topic_distribution,
        'quality_trend': 'up' if avg_current > avg_all else 'down' if avg_current < avg_all else 'stable',
        'quality_delta': round(avg_current - avg_all, 2),
        'avg_current_week_score': round(avg_current, 2),
        'avg_historical_score': round(avg_all, 2),
    }


def generate_insights(digest: WeeklyDigest) -> list[str]:
    """Generate high-level insights from the digest."""
    insights = []
    stats = digest.stats
    
    # Priority insight
    if stats.test_this_week > 0:
        insights.append(f"⚡ You have {stats.test_this_week} high-priority item{'s' if stats.test_this_week > 1 else ''} to test this week.")
    
    # Build later insight
    if stats.build_later > 5:
        insights.append(f"📚 Your 'build later' backlog has {stats.build_later} items. Consider scheduling time to review.")
    
    # Quality insight
    if stats.avg_worth_score > 8:
        insights.append(f"🎯 This week's bookmarks are high quality (avg worth: {stats.avg_worth_score:.1f}/10).")
    elif stats.avg_worth_score < 5:
        insights.append(f"💡 Bookmark quality is lower this week (avg worth: {stats.avg_worth_score:.1f}/10). Consider being more selective.")
    
    # Source insight
    if stats.top_sources:
        top_source, count = stats.top_sources[0]
        if count > len(digest.test_this_week + digest.build_later + digest.archive) * 0.5:
            insights.append(f"📱 {count} bookmarks came from {top_source} this week - that's {(count/stats.total_new*100):.0f}% of new items.")
    
    # Action density
    total_actions = sum(len(item.action_items) for item in 
                       digest.test_this_week + digest.build_later + digest.archive)
    if total_actions == 0 and stats.analyzed > 0:
        insights.append("🤔 No clear action items extracted this week. Bookmarks may be more inspirational than actionable.")
    elif total_actions > 10:
        insights.append(f"✅ {total_actions} potential actions identified this week. Lots to explore!")
    
    return insights


def generate_weekly_digest(days: int = 7) -> WeeklyDigest:
    """Generate a weekly digest of bookmarks."""
    now = datetime.now()
    week_start = now - timedelta(days=days)
    
    # Load all data
    all_bookmarks = load_bookmarks()
    all_analyses = load_analysis_results()
    analysis_map = {a.bookmark_id: a for a in all_analyses}
    
    # Filter to current week
    current_bookmarks = []
    current_analyses = []
    
    for bookmark in all_bookmarks:
        bookmarked_at = parse_datetime(bookmark.bookmarked_at)
        if bookmarked_at and bookmarked_at >= week_start:
            current_bookmarks.append(bookmark)
            if bookmark.id in analysis_map:
                current_analyses.append(analysis_map[bookmark.id])
    
    # Calculate stats
    stats = calculate_stats(current_bookmarks, current_analyses)
    
    # Create digest items by bucket
    test_items = []
    build_items = []
    archive_items = []
    
    for bookmark in current_bookmarks:
        if bookmark.id not in analysis_map:
            continue
        analysis = analysis_map[bookmark.id]
        action_items = extract_action_items(analysis)
        digest_item = DigestItem(bookmark, analysis, action_items)
        
        if analysis.recommendation_bucket == 'test_this_week':
            test_items.append(digest_item)
        elif analysis.recommendation_bucket == 'build_later':
            build_items.append(digest_item)
        elif analysis.recommendation_bucket == 'archive':
            archive_items.append(digest_item)
    
    # Sort by priority score
    test_items.sort(key=lambda x: x.analysis.priority_score, reverse=True)
    build_items.sort(key=lambda x: x.analysis.priority_score, reverse=True)
    archive_items.sort(key=lambda x: x.analysis.worth_score, reverse=True)
    
    # Analyze trends
    trends = analyze_trends(current_bookmarks, current_analyses, all_bookmarks, all_analyses)
    
    # Create digest
    digest = WeeklyDigest(
        week_start=week_start,
        week_end=now,
        generated_at=now,
        stats=stats,
        test_this_week=test_items,
        build_later=build_items,
        archive=archive_items,
        trends=trends,
        insights=[]
    )
    
    # Generate insights
    digest.insights = generate_insights(digest)
    
    return digest


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"
