"""Tests for the SQLite-backed storage layer.

These tests use a temporary database file so production data is never touched.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from rolloforge.models import AnalysisResult, Bookmark, ScoringInputs
from rolloforge import storage_sqlite as s
from rolloforge.db import drop_all_tables, get_db_path, init_db


# ── helpers ────────────────────────────────────────────────────────────────

def _make_bookmark(id_: str = "bm1", **overrides) -> Bookmark:
    defaults = {
        "id": id_,
        "source": "x",
        "url": f"https://x.com/test/{id_}",
        "text": f"Test tweet {id_}",
        "title": f"Title {id_}",
        "author": "testuser",
        "tags": ["ai", "tech"],
        "bookmarked_at": "2024-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return Bookmark(**defaults)


def _make_analysis(bookmark_id: str = "bm1", **overrides) -> AnalysisResult:
    defaults = {
        "bookmark_id": bookmark_id,
        "summary": f"Summary for {bookmark_id}",
        "recommendation_reason": "Because",
        "key_insights": ["insight1"],
        "scoring_inputs": ScoringInputs(
            relevance=8.0, practical_value=7.0, actionability=6.0,
            stage_fit=7.0, novelty=5.0, excitement=6.0,
            difficulty=4.0, time_cost=3.0,
        ),
        "worth_score": 7.0,
        "effort_score": 3.0,
        "priority_score": 5.0,
        "recommendation_bucket": "test_this_week",
        "analysis_source": "deepseek",
        "analyzed_at": "2024-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return AnalysisResult(**defaults)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect the database to a temp file and clean up after each test."""
    db_file = tmp_path / "test_rolloforge.db"

    # Patch the DB_PATH constant in storage_sqlite's scope
    monkeypatch.setattr("rolloforge.db.DB_PATH", db_file)
    monkeypatch.setattr("rolloforge.storage_sqlite.get_db_path", lambda: db_file)

    init_db()
    yield db_file
    # Cleanup
    drop_all_tables()
    try:
        db_file.unlink(missing_ok=True)
    except Exception:
        pass


# ── bookmark tests ─────────────────────────────────────────────────────────

class TestBookmarkCRUD:
    def test_save_and_load_roundtrip(self):
        bm = _make_bookmark("bm1")
        s.save_bookmarks([bm])

        loaded = s.load_bookmarks()
        assert len(loaded) == 1
        assert loaded[0].id == "bm1"
        assert loaded[0].url == "https://x.com/test/bm1"
        assert loaded[0].tags == ["ai", "tech"]

    def test_load_empty(self):
        loaded = s.load_bookmarks()
        assert loaded == []

    def test_save_multiple(self):
        bm1 = _make_bookmark("bm1")
        bm2 = _make_bookmark("bm2", url="https://example.com/2")
        s.save_bookmarks([bm1, bm2])

        loaded = s.load_bookmarks()
        assert len(loaded) == 2
        assert {b.id for b in loaded} == {"bm1", "bm2"}

    def test_save_overwrites_existing(self):
        bm = _make_bookmark("bm1", text="Original")
        s.save_bookmarks([bm])

        bm_updated = _make_bookmark("bm1", text="Updated")
        s.save_bookmarks([bm_updated])

        loaded = s.load_bookmarks()
        assert len(loaded) == 1
        assert loaded[0].text == "Updated"

    def test_get_by_id_found(self):
        bm = _make_bookmark("bm1")
        s.save_bookmarks([bm])

        result = s.get_bookmark_by_id("bm1")
        assert result is not None
        assert result.id == "bm1"

    def test_get_by_id_not_found(self):
        result = s.get_bookmark_by_id("nonexistent")
        assert result is None

    def test_count(self):
        assert s.count_bookmarks() == 0
        s.save_bookmarks([_make_bookmark("bm1"), _make_bookmark("bm2")])
        assert s.count_bookmarks() == 2

    def test_delete(self):
        s.save_bookmarks([_make_bookmark("bm1")])
        assert s.count_bookmarks() == 1

        assert s.delete_bookmark("bm1") is True
        assert s.count_bookmarks() == 0

    def test_delete_nonexistent(self):
        assert s.delete_bookmark("nonexistent") is False

    def test_preserves_raw_payload(self):
        bm = _make_bookmark("bm1", raw_payload={"custom": "data", "nested": {"a": 1}})
        s.save_bookmarks([bm])

        loaded = s.load_bookmarks()
        assert loaded[0].raw_payload == {"custom": "data", "nested": {"a": 1}}

    def test_preserves_tags(self):
        bm = _make_bookmark("bm1", tags=["python", "ai", "web"])
        s.save_bookmarks([bm])

        loaded = s.load_bookmarks()
        assert loaded[0].tags == ["python", "ai", "web"]


class TestMergeBookmarks:
    def test_merge_no_overlap(self):
        existing = [_make_bookmark("bm1", text="First")]
        incoming = [_make_bookmark("bm2", text="Second")]

        merged = s.merge_bookmarks(existing, incoming)
        assert len(merged) == 2
        assert {b.id for b in merged} == {"bm1", "bm2"}

    def test_merge_incoming_wins(self):
        existing = [_make_bookmark("bm1", text="Old")]
        incoming = [_make_bookmark("bm1", text="Updated")]

        merged = s.merge_bookmarks(existing, incoming)
        assert len(merged) == 1
        assert merged[0].text == "Updated"

    def test_merge_sorted_by_date(self):
        existing = [_make_bookmark("old", bookmarked_at="2024-01-01T00:00:00Z")]
        incoming = [_make_bookmark("new", bookmarked_at="2024-01-02T00:00:00Z")]

        merged = s.merge_bookmarks(existing, incoming)
        assert merged[0].id == "new"


# ── analysis tests ─────────────────────────────────────────────────────────

class TestAnalysisCRUD:
    def test_save_and_load_roundtrip(self):
        ar = _make_analysis("bm1")
        s.save_analysis_results([ar])

        loaded = s.load_analysis_results()
        assert len(loaded) == 1
        assert loaded[0].bookmark_id == "bm1"
        assert loaded[0].priority_score == 5.0
        assert loaded[0].key_insights == ["insight1"]

    def test_load_empty(self):
        assert s.load_analysis_results() == []

    def test_sorted_by_priority_desc(self):
        ar1 = _make_analysis("bm1", priority_score=3.0)
        ar2 = _make_analysis("bm2", priority_score=9.0)
        ar3 = _make_analysis("bm3", priority_score=5.0)
        s.save_analysis_results([ar1, ar2, ar3])

        loaded = s.load_analysis_results()
        assert loaded[0].bookmark_id == "bm2"  # highest priority
        assert loaded[2].bookmark_id == "bm1"  # lowest priority

    def test_get_by_bookmark_id(self):
        s.save_analysis_results([_make_analysis("bm1")])

        result = s.get_analysis_by_bookmark_id("bm1")
        assert result is not None
        assert result.bookmark_id == "bm1"

    def test_get_by_bookmark_id_not_found(self):
        assert s.get_analysis_by_bookmark_id("nonexistent") is None

    def test_load_by_bucket(self):
        s.save_analysis_results([
            _make_analysis("bm1", recommendation_bucket="test_this_week"),
            _make_analysis("bm2", recommendation_bucket="archive"),
            _make_analysis("bm3", recommendation_bucket="test_this_week"),
        ])

        this_week = s.load_analyses_by_bucket("test_this_week")
        assert len(this_week) == 2

        archive = s.load_analyses_by_bucket("archive")
        assert len(archive) == 1

        empty = s.load_analyses_by_bucket("nonexistent")
        assert empty == []

    def test_count(self):
        assert s.count_analyses() == 0
        s.save_analysis_results([_make_analysis("bm1"), _make_analysis("bm2")])
        assert s.count_analyses() == 2


class TestUpsertAnalysisResults:
    def test_upsert_new(self):
        existing = [_make_analysis("bm1", priority_score=3.0)]
        new = [_make_analysis("bm2", priority_score=7.0)]

        result = s.upsert_analysis_results(existing, new)
        assert len(result) == 2
        assert result[0].bookmark_id == "bm2"

    def test_upsert_update(self):
        existing = [_make_analysis("bm1", summary="Old", priority_score=3.0)]
        new = [_make_analysis("bm1", summary="Updated", priority_score=8.0)]

        result = s.upsert_analysis_results(existing, new)
        assert len(result) == 1
        assert result[0].summary == "Updated"
        assert result[0].priority_score == 8.0


# ── seen / known IDs tests ─────────────────────────────────────────────────

class TestSeenBookmarkIDs:
    def test_known_ids_roundtrip(self):
        s.save_known_bookmark_ids(["bm1", "bm2", "bm3"])
        result = s.load_known_bookmark_ids()
        assert result == {"bm1", "bm2", "bm3"}

    def test_known_ids_dedupe(self):
        s.save_known_bookmark_ids(["bm1", "bm1", "bm2"])
        result = s.load_known_bookmark_ids()
        assert result == {"bm1", "bm2"}

    def test_seen_ids_roundtrip(self):
        s.save_seen_bookmark_ids(["bm1", "bm2"])
        result = s.load_seen_bookmark_ids()
        assert result == {"bm1", "bm2"}

    def test_empty_on_no_data(self):
        assert s.load_known_bookmark_ids() == set()
        assert s.load_seen_bookmark_ids() == set()

    def test_seen_and_known_independent(self):
        s.save_known_bookmark_ids(["a", "b"])
        s.save_seen_bookmark_ids(["b", "c"])

        assert s.load_known_bookmark_ids() == {"a", "b"}
        assert s.load_seen_bookmark_ids() == {"b", "c"}


# ── stats summary tests ────────────────────────────────────────────────────

class TestStatsSummary:
    def test_stats_updated_on_bookmark_save(self):
        s.save_bookmarks([_make_bookmark("bm1")])
        stats = s.load_stats_summary()
        assert stats["total_bookmarks"] == 1

    def test_stats_updated_on_analysis_save(self):
        s.save_bookmarks([_make_bookmark("bm1")])
        s.save_analysis_results([_make_analysis("bm1", recommendation_bucket="test_this_week")])
        stats = s.load_stats_summary()
        assert stats["total_bookmarks"] == 1
        assert stats["total_analyses"] == 1
        assert stats["buckets"]["test_this_week"] == 1

    def test_stats_empty_db(self):
        stats = s.load_stats_summary()
        assert stats == {}  # not yet refreshed


# ── bulk import tests ──────────────────────────────────────────────────────

class TestBulkImport:
    def test_import_bookmarks(self):
        bms = [_make_bookmark(f"bm{i}") for i in range(10)]
        count = s.import_bookmarks_bulk(bms)
        assert count == 10
        assert s.count_bookmarks() == 10

    def test_import_analyses(self):
        ars = [_make_analysis(f"bm{i}") for i in range(5)]
        count = s.import_analyses_bulk(ars)
        assert count == 5
        assert s.count_analyses() == 5

    def test_import_seen(self):
        s.import_seen_bookmarks_bulk(["a", "b", "c"], ["a", "d"])
        assert s.load_known_bookmark_ids() == {"a", "b", "c"}
        assert s.load_seen_bookmark_ids() == {"a", "d"}

    def test_import_idempotent(self):
        s.import_bookmarks_bulk([_make_bookmark("bm1", text="v1")])
        s.import_bookmarks_bulk([_make_bookmark("bm1", text="v2")])
        assert s.count_bookmarks() == 1
        assert s.load_bookmarks()[0].text == "v2"


# ── integration test ───────────────────────────────────────────────────────

class TestIntegration:
    def test_full_workflow(self):
        # 1. Save bookmarks
        bm = _make_bookmark("bm1", text="Full integration test")
        s.save_bookmarks([bm])
        s.save_known_bookmark_ids(["bm1"])

        # 2. Save analysis
        ar = _make_analysis("bm1", recommendation_bucket="build_later")
        s.save_analysis_results([ar])
        s.save_seen_bookmark_ids(["bm1"])

        # 3. Load and verify
        loaded_bm = s.load_bookmarks()
        loaded_ar = s.load_analysis_results()
        known = s.load_known_bookmark_ids()
        seen = s.load_seen_bookmark_ids()

        assert len(loaded_bm) == 1
        assert len(loaded_ar) == 1
        assert known == {"bm1"}
        assert seen == {"bm1"}

        # 4. Stats
        stats = s.load_stats_summary()
        assert stats["total_bookmarks"] == 1
        assert stats["total_analyses"] == 1

    def test_upsert_and_merge_workflow(self):
        # Initial save
        bm1 = _make_bookmark("bm1", text="First")
        bm2 = _make_bookmark("bm2", text="Second")
        s.save_bookmarks([bm1, bm2])

        ar1 = _make_analysis("bm1", priority_score=3.0, summary="Low")
        s.save_analysis_results([ar1])

        # Merge + upsert
        existing_bm = s.load_bookmarks()
        incoming_bm = [_make_bookmark("bm1", text="Updated First"), _make_bookmark("bm3", text="Third")]
        merged_bm = s.merge_bookmarks(existing_bm, incoming_bm)
        s.save_bookmarks(merged_bm)

        existing_ar = s.load_analysis_results()
        new_ar = [_make_analysis("bm2", priority_score=9.0, summary="High")]
        upserted = s.upsert_analysis_results(existing_ar, new_ar)

        # Verify
        bm_all = s.load_bookmarks()
        ar_all = s.load_analysis_results()

        assert len(bm_all) == 3
        bm1_loaded = next(b for b in bm_all if b.id == "bm1")
        assert bm1_loaded.text == "Updated First"

        assert len(ar_all) == 2
        assert ar_all[0].bookmark_id == "bm2"  # highest priority
        assert ar_all[0].summary == "High"
