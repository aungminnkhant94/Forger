"""forge digest --send-telegram must not re-parse the forge argv."""
import argparse
import sys
from datetime import datetime

from forger.digest import DigestItem, WeeklyDigest, WeeklyStats
from forger.models import AnalysisResult, Bookmark, ScoringInputs
from integrations.telegram.send_digest import TelegramFormatter


def _digest() -> WeeklyDigest:
    now = datetime(2026, 10, 8, 12, 0, 0)
    bookmark = Bookmark(
        id="bookmark_1",
        source="article",
        url="https://example.com/watch?v=abc.def",
        text="Hello",
        title="Hello. World",
    )
    analysis = AnalysisResult(
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
    return WeeklyDigest(
        week_start=now,
        week_end=now,
        generated_at=now,
        stats=WeeklyStats(total_new=1, analyzed=1, test_this_week=1, avg_priority_score=7.0),
        test_this_week=[DigestItem(bookmark=bookmark, analysis=analysis, action_items=["Try it"])],
        insights=[],
        trends={},
    )


def test_markdown_link_escapes_url_dots():
    message = TelegramFormatter.format_concise(_digest())
    assert r"https://example\.com/watch?v\=abc\.def" in message
    assert "https://example.com/watch?v=abc.def" not in message


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
    assert r"example\.com" in captured["json"]["text"]
    assert "digest" not in (captured["url"] or "")
