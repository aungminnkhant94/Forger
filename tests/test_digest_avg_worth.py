"""Digest averages exclude the 'ignore' bucket and say how many were left out."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from forger.digest import (
    WeeklyDigest,
    analyze_trends,
    calculate_stats,
    generate_insights,
)
from forger.digest_render import print_console_summary, render_markdown_digest
from integrations.telegram.send_digest import TelegramFormatter
from tests.test_digest_week_counts import _analysis, _bookmark


def _three():
    # worth 8, 7 kept; worth 2 is a thin X post bucketed ignore
    a = replace(_analysis("a", "test_this_week", priority=7.0), worth_score=8.0)
    b = replace(_analysis("b", "build_later", priority=5.0), worth_score=7.0)
    c = replace(_analysis("c", "ignore", priority=1.0), worth_score=2.0)
    bms = [_bookmark(x, bookmarked_at="2026-10-12T00:00:00Z") for x in "abc"]
    return bms, [a, b, c]


def test_avg_worth_excludes_ignore_8_7_2_gives_7_5():
    bms, analyses = _three()
    stats = calculate_stats(bms, analyses)
    assert stats.avg_worth_score == 7.5  # was (8+7+2)/3 = 5.67
    assert stats.avg_priority_score == 6.0
    assert stats.avg_excluded_ignore == 1
    assert stats.analyzed == 3 and stats.ignore == 1  # counts unchanged


def test_trend_averages_use_same_rule():
    bms, analyses = _three()
    trends = analyze_trends(bms, analyses, bms, analyses)
    assert trends["avg_current_week_score"] == 7.5
    assert trends["avg_historical_score"] == 7.5


def test_all_ignored_gives_zero_and_no_quality_insight():
    bm = [_bookmark("c", bookmarked_at="2026-10-12T00:00:00Z")]
    c = replace(_analysis("c", "ignore"), worth_score=2.0)
    stats = calculate_stats(bm, [c])
    assert stats.avg_worth_score == 0 and stats.avg_excluded_ignore == 1
    digest = WeeklyDigest(
        week_start=datetime(2026, 10, 6), week_end=datetime(2026, 10, 13),
        generated_at=datetime(2026, 10, 13), stats=stats,
        test_this_week=[], build_later=[], archive=[], trends={}, insights=[],
    )
    assert not any("quality" in i.lower() for i in generate_insights(digest))


def test_outputs_show_excluded_count(capsys):
    bms, analyses = _three()
    digest = WeeklyDigest(
        week_start=datetime(2026, 10, 6), week_end=datetime(2026, 10, 13),
        generated_at=datetime(2026, 10, 13, 12, 0), stats=calculate_stats(bms, analyses),
        test_this_week=[], build_later=[], archive=[], trends={}, insights=[],
    )
    print_console_summary(digest)
    assert "exclude 1 ignored" in capsys.readouterr().out
    md = render_markdown_digest(digest)
    assert "7.5" in md and "excludes 1 ignored" in md
    tg = "\n".join(TelegramFormatter.format_full(digest))
    assert "7\\.5" in tg and "excludes 1 ignored" in tg
