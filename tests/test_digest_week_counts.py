"""Digest week window counts + bucket label honesty."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from forger.digest import (
    LOCAL_TZ,
    WeeklyStats,
    bookmark_event_time,
    generate_insights,
    generate_weekly_digest,
    parse_datetime,
)
from forger.digest import WeeklyDigest, DigestItem
from forger.digest_render import print_console_summary, render_html_digest, render_markdown_digest
from forger.models import AnalysisResult, Bookmark, ScoringInputs
from integrations.telegram.send_digest import TelegramFormatter


def _scoring() -> ScoringInputs:
    return ScoringInputs(8, 8, 8, 8, 5, 5, 2, 2)


def _bookmark(
    bid: str,
    *,
    bookmarked_at: str | None,
    created_at: str | None = None,
    title: str = "Title",
) -> Bookmark:
    return Bookmark(
        id=bid,
        source="article",
        url=f"https://example.com/{bid}",
        text="body",
        title=title,
        bookmarked_at=bookmarked_at,
        created_at=created_at,
    )


def _analysis(bid: str, bucket: str, *, priority: float = 7.0) -> AnalysisResult:
    return AnalysisResult(
        bookmark_id=bid,
        summary="Summary",
        recommendation_reason="Reason",
        key_insights=[],
        scoring_inputs=_scoring(),
        worth_score=8.0,
        effort_score=2.0,
        priority_score=priority,
        recommendation_bucket=bucket,
        analysis_source="test",
        analyzed_at="2026-10-13T00:00:00Z",
    )


def test_local_tz_is_iana_not_cst_abbreviation():
    # Regression: tzname() "CST" used to make ZoneInfo fail → UTC skew.
    assert isinstance(LOCAL_TZ, ZoneInfo)
    assert LOCAL_TZ.key != "CST"
    # On this box /etc/timezone is Asia/Macau; FORGER_TZ may override in CI.
    assert "/" in LOCAL_TZ.key or LOCAL_TZ.key == "UTC"


def test_parse_datetime_converts_z_into_local_wall_time():
    dt = parse_datetime("2026-10-10T00:00:00Z")
    assert dt is not None
    assert dt.tzinfo is None
    # 00:00Z in Asia/Macau is 08:00 local; in UTC stays 00:00.
    expected = datetime(2026, 10, 10, 0, 0, 0, tzinfo=ZoneInfo("UTC")).astimezone(LOCAL_TZ).replace(
        tzinfo=None
    )
    assert dt == expected


def test_bookmark_event_time_falls_back_to_created_at():
    b = _bookmark("b1", bookmarked_at=None, created_at="2026-10-12T01:00:00Z")
    assert bookmark_event_time(b) is not None


def test_generate_weekly_digest_excludes_outside_window(monkeypatch):
    """Old library items must not inflate New bookmarks / bucket totals."""
    fixed_now = datetime(2026, 10, 13, 18, 0, 0)  # naive local wall clock

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now
            return fixed_now.replace(tzinfo=tz)

    monkeypatch.setattr("forger.digest.datetime", _FixedDateTime)

    in_week = _bookmark("in", bookmarked_at="2026-10-12T10:00:00Z", title="In window")
    out_week = _bookmark("out", bookmarked_at="2026-09-01T10:00:00Z", title="Too old")
    edge_old = _bookmark("edge", bookmarked_at="2026-10-05T10:00:00Z", title="Just outside 7d")

    analyses = [
        _analysis("in", "test_this_week"),
        _analysis("out", "test_this_week"),
        _analysis("edge", "ignore"),
    ]

    monkeypatch.setattr(
        "forger.digest.load_bookmarks",
        lambda: [in_week, out_week, edge_old],
    )
    monkeypatch.setattr("forger.digest.load_analysis_results", lambda: analyses)

    digest = generate_weekly_digest(days=7)

    assert digest.stats.total_new == 1
    assert digest.stats.analyzed == 1
    assert digest.stats.test_this_week == 1
    assert digest.stats.ignore == 0
    assert len(digest.test_this_week) == 1
    assert digest.test_this_week[0].bookmark.id == "in"
    # Range printed for the digest should be the week window, not all-time.
    assert digest.week_start.date().isoformat() == "2026-10-06"
    assert digest.week_end.date().isoformat() == "2026-10-13"


def test_generate_weekly_digest_counts_ignore_in_window(monkeypatch):
    fixed_now = datetime(2026, 10, 13, 18, 0, 0)

    class _FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now
            return fixed_now.replace(tzinfo=tz)

    monkeypatch.setattr("forger.digest.datetime", _FixedDateTime)

    bookmarks = [
        _bookmark("a", bookmarked_at="2026-10-12T10:00:00Z"),
        _bookmark("b", bookmarked_at="2026-10-11T10:00:00Z"),
        _bookmark("c", bookmarked_at="2026-10-10T10:00:00Z"),
    ]
    analyses = [
        _analysis("a", "test_this_week"),
        _analysis("b", "ignore"),
        _analysis("c", "build_later"),
    ]
    monkeypatch.setattr("forger.digest.load_bookmarks", lambda: bookmarks)
    monkeypatch.setattr("forger.digest.load_analysis_results", lambda: analyses)

    digest = generate_weekly_digest(days=7)
    assert digest.stats.total_new == 3
    assert digest.stats.test_this_week == 1
    assert digest.stats.build_later == 1
    assert digest.stats.ignore == 1


def test_insight_labels_test_this_week_not_high_priority():
    digest = WeeklyDigest(
        week_start=datetime(2026, 10, 6),
        week_end=datetime(2026, 10, 13),
        generated_at=datetime(2026, 10, 13),
        stats=WeeklyStats(total_new=9, analyzed=9, test_this_week=9, ignore=2),
        test_this_week=[],
        build_later=[],
        archive=[],
        trends={},
        insights=[],
    )
    insights = generate_insights(digest)
    joined = " ".join(insights)
    assert "test_this_week" in joined
    assert "high-priority" not in joined


def test_console_and_templates_show_ignore(capsys):
    digest = WeeklyDigest(
        week_start=datetime(2026, 10, 6),
        week_end=datetime(2026, 10, 13),
        generated_at=datetime(2026, 10, 13, 12, 0),
        stats=WeeklyStats(
            total_new=5,
            analyzed=5,
            test_this_week=1,
            build_later=1,
            archive=1,
            ignore=2,
            avg_worth_score=6.0,
            avg_priority_score=5.0,
        ),
        test_this_week=[],
        build_later=[],
        archive=[],
        trends={},
        insights=["⚡ You have 1 item in test_this_week."],
    )
    print_console_summary(digest)
    console = capsys.readouterr().out
    assert "Ignore" in console
    assert "2" in console

    md = render_markdown_digest(digest)
    assert "Ignore" in md
    assert "**2**" in md

    html = render_html_digest(digest)
    assert "Ignore" in html
    assert ">2<" in html or ">2</div>" in html


def test_telegram_formats_show_ignore_and_bucket_label():
    bookmark = _bookmark("b1", bookmarked_at="2026-10-12T00:00:00Z", title="Hello. World")
    analysis = _analysis("b1", "test_this_week")
    digest = WeeklyDigest(
        week_start=datetime(2026, 10, 6),
        week_end=datetime(2026, 10, 13),
        generated_at=datetime(2026, 10, 13, 12, 0),
        stats=WeeklyStats(
            total_new=4,
            analyzed=4,
            test_this_week=1,
            build_later=1,
            archive=1,
            ignore=1,
            avg_worth_score=8.0,
            avg_priority_score=7.0,
            top_sources=[("HN.news", 2)],
        ),
        test_this_week=[DigestItem(bookmark=bookmark, analysis=analysis, action_items=[])],
        build_later=[],
        archive=[],
        insights=["You have 1 item in test_this_week."],
        trends={"quality_trend": "up", "quality_delta": 0.5},
    )

    concise = TelegramFormatter.format_concise(digest)
    assert "Ignore: 1" in concise
    assert "Test This Week" in concise
    assert "Top Priority Items" not in concise

    full = "\n".join(TelegramFormatter.format_full(digest))
    assert "Ignore: 1" in full

    stats_only = TelegramFormatter.format_stats_only(digest)
    assert "1" in stats_only  # ignore count present in the pipe line
    # New | test | build | archive | ignore
    assert stats_only.count("|") >= 4
