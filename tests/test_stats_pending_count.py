"""Leftover pending_agent rows are ignored; pending count comes from content files."""
from __future__ import annotations

import argparse
from dataclasses import replace
from unittest.mock import patch

import forge
from forger.bookmark_workflow import _build_pending_result
from forger.digest import calculate_stats
from tests.test_digest_week_counts import _analysis, _bookmark


def test_stats_counts_leftover_placeholder_via_pending_dir(tmp_path, monkeypatch, capsys):
    done = replace(_analysis("a", "build_later", priority=5.0), worth_score=7.0)
    bms = [_bookmark(x, bookmarked_at="2026-10-12T00:00:00Z") for x in "ab"]
    pending_row = _build_pending_result(bms[1])  # leftover from pre-P2 agent add
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / f"{bms[1].id}.content.md").write_text("# pending\n", encoding="utf-8")

    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)
    with patch.object(forge, "load_bookmarks", return_value=bms), patch.object(
        forge, "load_analysis_results", return_value=[done, pending_row]
    ):
        forge.cmd_stats(argparse.Namespace(watch=False, interval=5))
    out = capsys.readouterr().out
    assert "With analysis:    1" in out
    assert "Pending analysis: 1" in out
    assert "archive" not in out
    assert "Worth:    7.0/10" in out


def test_health_reports_pending_from_dir(tmp_path, monkeypatch, capsys):
    done = replace(_analysis("a", "build_later", priority=5.0), worth_score=7.0)
    bms = [_bookmark(x, bookmarked_at="2026-10-12T00:00:00Z") for x in "ab"]
    pending_row = _build_pending_result(bms[1])
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / f"{bms[1].id}.content.md").write_text("# pending\n", encoding="utf-8")

    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)
    with patch.object(forge, "load_bookmarks", return_value=bms), patch.object(
        forge, "load_analysis_results", return_value=[done, pending_row]
    ), patch("forge.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = ""
        forge.cmd_health(argparse.Namespace(watch=False, interval=5))
    out = capsys.readouterr().out
    assert "All bookmarks analyzed" not in out
    assert "1 bookmarks pending analysis" in out


def test_digest_analyzed_excludes_placeholder():
    done = replace(_analysis("a", "build_later", priority=5.0), worth_score=7.0)
    bms = [_bookmark(x, bookmarked_at="2026-10-12T00:00:00Z") for x in "ab"]
    pending_row = _build_pending_result(bms[1])
    stats = calculate_stats(bms, [done, pending_row])
    assert stats.analyzed == 1
    assert stats.archive == 0
    assert stats.avg_worth_score == 7.0


def test_agent_add_prints_pending_not_bucket(capsys, tmp_path, monkeypatch):
    from forger import bookmark_workflow as bw

    bms = [_bookmark("b", bookmarked_at="2026-10-12T00:00:00Z")]
    bm = bms[0]
    msg = "✓ Saved: t\n✓ Analysis: pending (run forge resolve)\n✓ Saved locally"
    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)
    with patch.object(bw, "process_bookmark_url", return_value=(True, msg, bm, None)):
        forge.cmd_add(argparse.Namespace(url="https://e.com/b", note=None, agent=True, replace=False))
    out = capsys.readouterr().out
    assert "pending analysis" in out
    assert "Priority: 0.0" not in out and "Bucket:   archive" not in out
