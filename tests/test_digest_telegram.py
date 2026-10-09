"""Telegram digest MarkdownV2 escaping + forge digest --send-telegram wiring."""
import argparse
import sys
from datetime import datetime

from forger.digest import DigestItem, WeeklyDigest, WeeklyStats
from forger.models import AnalysisResult, Bookmark, ScoringInputs
from integrations.telegram.send_digest import TelegramFormatter


def _analysis(**overrides) -> AnalysisResult:
    base = dict(
        bookmark_id="bookmark_1",
        summary="Summary",
        recommendation_reason="Reason",
        key_insights=[],
        scoring_inputs=ScoringInputs(8, 8, 8, 8, 5, 5, 2, 2),
        worth_score=8.0,
        effort_score=2.0,
        priority_score=7.0,
        recommendation_bucket="test_this_week",
        analysis_source="test",
        analyzed_at="2026-10-08T00:00:00Z",
    )
    base.update(overrides)
    return AnalysisResult(**base)


def _digest(**overrides) -> WeeklyDigest:
    now = datetime(2026, 10, 8, 12, 0, 0)
    bookmark = Bookmark(
        id="bookmark_1",
        source="article",
        url="https://example.com/watch?v=abc.def",
        text="Hello",
        title="Hello. World",
        note="See (docs)!",
        tags=["AI/ML!", "tools_v2"],
    )
    analysis = _analysis()
    payload = dict(
        week_start=now,
        week_end=now,
        generated_at=now,
        stats=WeeklyStats(
            total_new=1,
            analyzed=1,
            test_this_week=1,
            avg_priority_score=7.0,
            avg_worth_score=8.0,
            top_sources=[("HN.news", 3)],
        ),
        test_this_week=[
            DigestItem(bookmark=bookmark, analysis=analysis, action_items=["Try *this*"])
        ],
        build_later=[],
        insights=["Use _care_ with (parens)"],
        trends={
            "quality_trend": "up",
            "quality_delta": 0.5,
            "topic_distribution": {"AI/ML!": {"percentage": 40.5}},
        },
    )
    payload.update(overrides)
    return WeeklyDigest(**payload)


def test_escape_markdown_specials():
    assert TelegramFormatter.escape_markdown("a_b*c[d]") == r"a\_b\*c\[d\]"
    assert TelegramFormatter.escape_markdown("path\\file") == r"path\\file"
    assert TelegramFormatter.escape_markdown(None) == ""


def test_escape_link_url_only_paren_and_backslash():
    # Dots / '=' stay literal inside the URL entity; ')' and '\' do not.
    assert (
        TelegramFormatter.escape_markdown_link_url("https://example.com/watch?v=abc.def")
        == "https://example.com/watch?v=abc.def"
    )
    assert (
        TelegramFormatter.escape_markdown_link_url("https://ex.com/wiki/Foo_(bar)")
        == r"https://ex.com/wiki/Foo_(bar\)"
    )
    assert TelegramFormatter.escape_markdown_link_url(r"https://ex.com/a\b") == r"https://ex.com/a\\b"


def test_format_link_escapes_label_and_url_correctly():
    link = TelegramFormatter.format_link("Hello. World_(1)", "https://ex.com/a(b)")
    assert link == r"[Hello\. World\_\(1\)](https://ex.com/a(b\))"


def test_markdown_link_in_concise_does_not_over_escape_url():
    message = TelegramFormatter.format_concise(_digest())
    assert r"[Hello\. World](https://example.com/watch?v=abc.def)" in message
    # Old bug: full-text escaping of the URL broke Telegram parsing.
    assert r"example\.com" not in message
    assert r"See \(docs\)\!" in message
    assert r"Try \*this\*" in message
    assert r"Use \_care\_ with \(parens\)" in message
    assert "Quality is up" in message  # "up" has no specials
    assert r"\+0\.50" in message


def test_format_full_escapes_scores_topics_and_sources():
    messages = TelegramFormatter.format_full(_digest())
    overview = messages[0]
    assert r"Avg worth: 8\.0/10" in overview
    assert r"Avg priority: 7\.0/10" in overview
    assert r"HN\.news" in overview

    items = messages[1]
    assert r"[Hello\. World](https://example.com/watch?v=abc.def)" in items
    assert r"AI/ML\!" in items or r"tools\_v2" in items
    assert r"See \(docs\)\!" in items

    insights = messages[-1]
    assert r"AI/ML\!" in insights
    assert r"40\.5" in insights
    assert "Quality Trend:* up" in insights or r"*Quality Trend:* up" in insights


def test_format_stats_only_escapes_pipes_and_trend():
    text = TelegramFormatter.format_stats_only(_digest())
    assert r"*Forger Digest* \| " in text
    assert r"New: 1 \| ⚡ 1 \| " in text
    assert "Trend: up" in text


def test_format_full_with_build_later_and_injection_title():
    now = datetime(2026, 10, 8, 12, 0, 0)
    evil = Bookmark(
        id="bookmark_2",
        source="article",
        url="https://example.com/path_(x)",
        text="x",
        title="*](https://evil.example) ignored",
    )
    analysis = _analysis(bookmark_id="bookmark_2", recommendation_bucket="build_later")
    digest = _digest(
        build_later=[DigestItem(bookmark=evil, analysis=analysis, action_items=[])],
        test_this_week=[],
        insights=[],
        trends={},
        stats=WeeklyStats(total_new=1, analyzed=1, build_later=1),
    )
    messages = TelegramFormatter.format_full(digest)
    body = "\n".join(messages)
    # Title specials escaped so they cannot break out of the link label.
    assert r"\*\]\(https://evil\.example\) ignored" in body
    assert "(https://example.com/path_(x\\))" in body


def test_cmd_digest_send_telegram_does_not_system_exit(monkeypatch):
    import forge

    monkeypatch.setattr(sys, "argv", ["forge", "digest", "--send-telegram"])
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    digest = _digest()
    monkeypatch.setattr(forge, "generate_weekly_digest", lambda days=7: digest)
    monkeypatch.setattr(
        "integrations.telegram.send_digest.generate_weekly_digest",
        lambda days=7: digest,
    )
    monkeypatch.setattr("forger.digest_render.render_html_digest", lambda d: "<html></html>")
    monkeypatch.setattr("forger.digest_render.render_markdown_digest", lambda d: "# digest")
    monkeypatch.setattr("forger.digest_render.print_console_summary", lambda d: None)

    captured = {}

    class _Response:
        def json(self):
            return {"ok": True}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return _Response()

    import requests

    monkeypatch.setattr(requests, "post", fake_post)

    args = argparse.Namespace(
        days=7,
        output="both",
        save=False,
        send_telegram=True,
        telegram_format="concise",
        quiet=True,
    )
    assert forge.cmd_digest(args) == 0
    assert captured["json"]["chat_id"] == "12345"
    assert captured["json"]["parse_mode"] == "MarkdownV2"
    assert "https://example.com/watch?v=abc.def" in captured["json"]["text"]
    assert r"Hello\. World" in captured["json"]["text"]
    assert "digest" not in (captured["url"] or "")
