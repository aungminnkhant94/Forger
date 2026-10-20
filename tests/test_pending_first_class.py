"""P2: pending is first-class — no placeholder AnalysisResult on agent add.

Prove-it: fails on main's placeholder-as-analyzed pattern (writing a
pending_agent AnalysisResult / counting it as finished); passes when agent
add writes bookmark only and stats pending matches the pending dir.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from unittest.mock import patch

import forge
from forger import bookmark_workflow as bw
from forger.bookmark_workflow import _build_pending_result
from forger.models import finished_analyses, is_pending_analysis, pending_content_ids
from tests.test_digest_week_counts import _analysis, _bookmark


def _patch_agent_add(monkeypatch, saved):
    bm = replace(
        _bookmark("b", bookmarked_at="2026-10-12T00:00:00Z"),
        id="bookmark_bbbbbbbbbbbb",
        title="Pending Title",
        text="Body text for pending agent add. " * 10,
        url="https://example.com/pending-p2",
    )

    def capture_save(bookmarks):
        saved["bookmarks"] = list(bookmarks)

    def capture_upsert(existing, incoming):
        saved["upsert"] = list(incoming)
        return list(incoming)

    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    monkeypatch.setattr(bw, "scrape_and_create_bookmark", lambda url: bm)
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b, exclude_ids=None: (None, None))
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", capture_save)
    monkeypatch.setattr(bw, "upsert_analysis_results", capture_upsert)
    monkeypatch.setattr(bw, "save_analysis_results", lambda results: saved.__setitem__("cleared", list(results)))
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a, **k: ([], []))
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)
    return bm


def test_agent_add_does_not_write_placeholder_analysis(monkeypatch):
    """Regression: main wrote analysis_source=pending_agent; that is not pending."""
    saved = {}
    _patch_agent_add(monkeypatch, saved)
    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://example.com/pending-p2", analyze=False
    )
    assert ok, message
    assert analysis is None
    assert "upsert" not in saved
    assert bookmark is not None
    assert "pending" in message.lower()


def test_leftover_pending_agent_is_not_finished():
    """Old libraries may still have pending_agent rows — never count as done."""
    done = replace(_analysis("a", "build_later", priority=5.0), worth_score=7.0)
    bm = _bookmark("b", bookmarked_at="2026-10-12T00:00:00Z")
    leftover = _build_pending_result(bm)
    assert is_pending_analysis(leftover)
    finished = finished_analyses([done, leftover])
    assert [a.bookmark_id for a in finished] == ["a"]
    # Main's bug pattern: leftover looks like a finished archive analysis.
    assert leftover.recommendation_bucket == "archive"
    assert leftover.worth_score == 0.0


def test_stats_pending_matches_pending_dir(tmp_path, monkeypatch, capsys):
    """forge stats Pending analysis equals *.content.md count, not fake rows."""
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "bookmark_aaaaaaaaaaaa.content.md").write_text("# A\n", encoding="utf-8")
    (pending / "bookmark_bbbbbbbbbbbb.content.md").write_text("# B\n", encoding="utf-8")

    bms = [
        replace(_bookmark("a", bookmarked_at="2026-10-12T00:00:00Z"), id="bookmark_aaaaaaaaaaaa"),
        replace(_bookmark("b", bookmarked_at="2026-10-12T00:00:00Z"), id="bookmark_bbbbbbbbbbbb"),
        replace(_bookmark("c", bookmarked_at="2026-10-12T00:00:00Z"), id="bookmark_cccccccccccc"),
    ]
    done = replace(
        _analysis("c", "build_later", priority=5.0),
        worth_score=7.0,
        bookmark_id="bookmark_cccccccccccc",
    )
    leftover = _build_pending_result(bms[1])

    assert len(pending_content_ids(pending)) == 2

    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)
    with patch.object(forge, "load_bookmarks", return_value=bms), patch.object(
        forge, "load_analysis_results", return_value=[done, leftover]
    ):
        forge.cmd_stats(argparse.Namespace())
    out = capsys.readouterr().out
    assert "With analysis:    1" in out
    assert "Pending analysis: 2" in out
    assert "archive" not in out  # leftover stub bucket must not appear


def test_health_pending_from_content_files(tmp_path, monkeypatch, capsys):
    pending = tmp_path / "pending"
    pending.mkdir()
    (pending / "bookmark_aaaaaaaaaaaa.content.md").write_text("# A\n", encoding="utf-8")
    bms = [replace(_bookmark("a", bookmarked_at="2026-10-12T00:00:00Z"), id="bookmark_aaaaaaaaaaaa")]
    leftover = _build_pending_result(bms[0])

    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)
    with patch.object(forge, "load_bookmarks", return_value=bms), patch.object(
        forge, "load_analysis_results", return_value=[leftover]
    ):
        # Avoid real git noise in health
        with patch("forge.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = ""
            forge.run_health_check()
    out = capsys.readouterr().out
    assert "All bookmarks analyzed" not in out
    assert "1 bookmarks pending analysis" in out
