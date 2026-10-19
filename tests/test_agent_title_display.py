"""The agent's analysis title is the display title; the page title stays stored."""
from __future__ import annotations

import argparse
from dataclasses import replace
from unittest.mock import patch

import forge
from forger.bookmark_workflow import _build_pending_result
from forger.models import display_title
from forger.reporting import _build_rows
from forger.search import search_bookmarks
from tests.test_digest_week_counts import _analysis, _bookmark


def _pair():
    b = replace(_bookmark("a", bookmarked_at="2026-10-12T00:00:00Z"), title="Tips to improve your local ranking - Google Busine")
    a = replace(_analysis("a", "build_later", priority=5.0), title="Local Ranking Tips (Google Business Profile)")
    return b, a


def test_display_title_prefers_agent_title():
    b, a = _pair()
    assert display_title(b, a) == "Local Ranking Tips (Google Business Profile)"
    assert b.title.startswith("Tips to improve")  # original kept


def test_pending_placeholder_title_not_used():
    b, _ = _pair()
    assert display_title(b, _build_pending_result(b)) == b.title


def test_search_and_stats_show_agent_title(capsys):
    b, a = _pair()
    with patch.object(forge, "load_bookmarks", return_value=[b]), \
            patch.object(forge, "load_analysis_results", return_value=[a]):
        forge.cmd_search(argparse.Namespace(query="local", limit=10))
        forge.cmd_stats(argparse.Namespace())
    out = capsys.readouterr().out
    assert "Local Ranking Tips (Google Business" in out
    assert "Tips to improve your local" not in out


def test_search_finds_words_only_in_agent_title():
    b, a = _pair()
    assert search_bookmarks("profile", [b], {b.id: a})


def test_report_rows_use_agent_title():
    b, a = _pair()
    assert _build_rows([b], {b.id: a})[0]["title"] == a.title
