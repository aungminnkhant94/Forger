"""Agent-mode placeholders (analysis_source=pending_agent) count as pending,
not as analyzed, in forge stats, forge health and the digest."""
from __future__ import annotations

import argparse
from dataclasses import replace
from unittest.mock import patch

import forge
from forger.bookmark_workflow import _build_pending_result
from forger.digest import calculate_stats
from tests.test_digest_week_counts import _analysis, _bookmark


def _data():
    done = replace(_analysis("a", "build_later", priority=5.0), worth_score=7.0)
    bms = [_bookmark(x, bookmarked_at="2026-10-12T00:00:00Z") for x in "ab"]
    pending = _build_pending_result(bms[1])  # what `forge add --agent` stores
    return bms, [done, pending]


def _run(cmd, capsys):
    bms, analyses = _data()
    with patch.object(forge, "load_bookmarks", return_value=bms), \
            patch.object(forge, "load_analysis_results", return_value=analyses):
        cmd(argparse.Namespace(watch=False, interval=5))
    return capsys.readouterr().out


def test_stats_counts_placeholder_as_pending(capsys):
    out = _run(forge.cmd_stats, capsys)
    assert "With analysis:    1" in out
    assert "Pending analysis: 1" in out
    assert "archive" not in out  # placeholder's stub bucket is not shown
    assert "Worth:    7.0/10" in out  # placeholder's 0 worth not averaged


def test_health_reports_pending(capsys):
    out = _run(forge.cmd_health, capsys)
    assert "All bookmarks analyzed" not in out
    assert "1 bookmarks pending analysis" in out


def test_digest_analyzed_excludes_placeholder():
    bms, analyses = _data()
    stats = calculate_stats(bms, analyses)
    assert stats.analyzed == 1
    assert stats.archive == 0
    assert stats.avg_worth_score == 7.0
