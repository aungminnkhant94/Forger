"""
SQLite-backed storage layer for RolloForge.

Mirrors the JSON-file-based storage.py API using SQLite as the backend.
This is a drop-in alternative — all public functions have the same
signatures and return types as storage.py, with the addition of an
optional `db_path` parameter for testing.

Usage:
    from rolloforge.storage_sqlite import load_bookmarks, save_bookmarks

    # First, initialize the database schema
    from rolloforge.db import init_db
    init_db()

    # Then use the same API you're used to
    bookmarks = load_bookmarks()
    save_bookmarks(bookmarks)

Design notes:
- All JSON nested fields (tags, key_insights, scoring_inputs, raw_payload)
  are stored as TEXT columns with JSON serialization.
- On read, they are deserialized back to Python lists/dicts.
- Database connections are created per-operation (not pooled),
  relying on WAL mode for concurrent read performance.
- This design supports 10K+ records comfortably.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from rolloforge.db import _json_deserialize, _json_serialize, get_db, get_db_path, init_db
from rolloforge.models import AnalysisResult, Bookmark, ScoringInputs
from rolloforge.utils import utc_now_iso


# ── helpers ────────────────────────────────────────────────────────────────

def _ensure_init() -> None:
    """Ensure the database schema exists (idempotent)."""
    init_db()


def _bookmark_from_row(row: sqlite3.Row) -> Bookmark:
    """Reconstruct a Bookmark from a sqlite3.Row."""
    # sqlite3.Row is subscriptable and iterable by column name
    d = dict(row)
    d["tags"] = _json_deserialize(d.get("tags", "[]")) or []
    d["raw_payload"] = _json_deserialize(d.get("raw_payload", "{}")) or {}
    return Bookmark.from_dict(d)


def _bookmark_to_row(bm: Bookmark) -> dict[str, Any]:
    """Convert a Bookmark to a dict suitable for INSERT/REPLACE."""
    d = bm.to_dict()
    d["tags"] = _json_serialize(d.get("tags", []))
    d["raw_payload"] = _json_serialize(d.get("raw_payload", {}))
    d["updated_db_at"] = utc_now_iso()
    return d


def _analysis_from_row(row: sqlite3.Row) -> AnalysisResult:
    """Reconstruct an AnalysisResult from a sqlite3.Row."""
    d = dict(row)
    d["key_insights"] = _json_deserialize(d.get("key_insights", "[]")) or []
    d["scoring_inputs"] = _json_deserialize(d.get("scoring_inputs", "{}")) or {}
    d["tags"] = _json_deserialize(d.get("tags", "[]")) or []
    return AnalysisResult.from_dict(d)


def _analysis_to_row(ar: AnalysisResult) -> dict[str, Any]:
    """Convert an AnalysisResult to a dict suitable for INSERT/REPLACE."""
    d = ar.to_dict()
    d["scoring_inputs"] = _json_serialize(d.get("scoring_inputs", {}))
    d["key_insights"] = _json_serialize(d.get("key_insights", []))
    d["tags"] = _json_serialize(d.get("tags", []))
    d["updated_db_at"] = utc_now_iso()
    return d


# ── bookmark CRUD ──────────────────────────────────────────────────────────

def load_bookmarks() -> list[Bookmark]:
    """Load all bookmarks from SQLite, sorted by bookmarked_at DESC."""
    _ensure_init()
    with get_db(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM bookmarks ORDER BY bookmarked_at DESC, created_at DESC"
        ).fetchall()
    return [_bookmark_from_row(r) for r in rows]


def save_bookmarks(bookmarks: Iterable[Bookmark]) -> None:
    """Replace the bookmarks table contents with the provided collection."""
    _ensure_init()
    rows = [_bookmark_to_row(bm) for bm in bookmarks]
    ids = [row["id"] for row in rows]
    with get_db() as db:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            db.execute(f"DELETE FROM bookmarks WHERE id NOT IN ({placeholders})", ids)
        else:
            db.execute("DELETE FROM bookmarks")

        db.executemany(
            """
            INSERT OR REPLACE INTO bookmarks
                (id, source, url, text, title, note, author, created_at,
                 bookmarked_at, tags, raw_payload, updated_db_at)
            VALUES
                (:id, :source, :url, :text, :title, :note, :author, :created_at,
                 :bookmarked_at, :tags, :raw_payload, :updated_db_at)
            """,
            rows,
        )
        db.commit()
    _refresh_stats_summary()


def merge_bookmarks(existing: Iterable[Bookmark], incoming: Iterable[Bookmark]) -> list[Bookmark]:
    """Merge bookmarks, with incoming taking precedence by ID."""
    merged: dict[str, Bookmark] = {bm.id: bm for bm in existing}
    for bm in incoming:
        merged[bm.id] = bm
    return sorted(
        merged.values(),
        key=lambda item: item.bookmarked_at or item.created_at or "",
        reverse=True,
    )


def get_bookmark_by_id(bookmark_id: str) -> Bookmark | None:
    """Get a single bookmark by ID."""
    _ensure_init()
    with get_db(readonly=True) as db:
        row = db.execute("SELECT * FROM bookmarks WHERE id = ?", (bookmark_id,)).fetchone()
    if row is None:
        return None
    return _bookmark_from_row(row)


def count_bookmarks() -> int:
    """Return the total number of bookmarks."""
    _ensure_init()
    with get_db(readonly=True) as db:
        row = db.execute("SELECT COUNT(*) as cnt FROM bookmarks").fetchone()
    return row["cnt"]


def delete_bookmark(bookmark_id: str) -> bool:
    """Delete a bookmark by ID. Returns True if deleted."""
    _ensure_init()
    with get_db() as db:
        cur = db.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        db.commit()
        deleted = cur.rowcount > 0
    if deleted:
        _refresh_stats_summary()
    return deleted


# ── analysis CRUD ──────────────────────────────────────────────────────────

def load_analysis_results() -> list[AnalysisResult]:
    """Load all analysis results sorted by priority_score DESC."""
    _ensure_init()
    with get_db(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM analysis_results ORDER BY priority_score DESC"
        ).fetchall()
    return [_analysis_from_row(r) for r in rows]


def save_analysis_results(results: Iterable[AnalysisResult]) -> None:
    """Replace the analysis_results table contents with the provided collection."""
    _ensure_init()
    rows = [_analysis_to_row(ar) for ar in results]
    ids = [row["bookmark_id"] for row in rows]
    with get_db() as db:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            db.execute(f"DELETE FROM analysis_results WHERE bookmark_id NOT IN ({placeholders})", ids)
        else:
            db.execute("DELETE FROM analysis_results")

        db.executemany(
            """
            INSERT OR REPLACE INTO analysis_results
                (bookmark_id, summary, recommendation_reason, key_insights,
                 scoring_inputs, worth_score, effort_score, priority_score,
                 recommendation_bucket, analysis_source, analyzed_at,
                 confidence, difficulty_reason, next_action, title, relates_to,
                 personalized_worth_score, personalized_priority_score,
                 personalized_bucket, personalized_why,
                 original_worth_score, original_priority_score,
                 original_bucket, alignment_score,
                 pinned, pinned_reason, decayed_at, decayed_from_bucket, decay_reason,
                 tags, updated_db_at)
            VALUES
                (:bookmark_id, :summary, :recommendation_reason, :key_insights,
                 :scoring_inputs, :worth_score, :effort_score, :priority_score,
                 :recommendation_bucket, :analysis_source, :analyzed_at,
                 :confidence, :difficulty_reason, :next_action, :title, :relates_to,
                 :personalized_worth_score, :personalized_priority_score,
                 :personalized_bucket, :personalized_why,
                 :original_worth_score, :original_priority_score,
                 :original_bucket, :alignment_score,
                 :pinned, :pinned_reason, :decayed_at, :decayed_from_bucket, :decay_reason,
                 :tags, :updated_db_at)
            """,
            rows,
        )
        db.commit()
    _refresh_stats_summary()


def upsert_analysis_results(
    existing: Iterable[AnalysisResult],
    new_results: Iterable[AnalysisResult],
) -> list[AnalysisResult]:
    """Merge new analysis results into existing, sorted by priority_score DESC."""
    merged: dict[str, AnalysisResult] = {ar.bookmark_id: ar for ar in existing}
    for ar in new_results:
        merged[ar.bookmark_id] = ar
    ordered = sorted(merged.values(), key=lambda item: item.priority_score, reverse=True)
    save_analysis_results(ordered)
    return ordered


def get_analysis_by_bookmark_id(bookmark_id: str) -> AnalysisResult | None:
    """Get a single analysis result by bookmark_id."""
    _ensure_init()
    with get_db(readonly=True) as db:
        row = db.execute(
            "SELECT * FROM analysis_results WHERE bookmark_id = ?", (bookmark_id,)
        ).fetchone()
    if row is None:
        return None
    return _analysis_from_row(row)


def count_analyses() -> int:
    """Return the total number of analysis results."""
    _ensure_init()
    with get_db(readonly=True) as db:
        row = db.execute("SELECT COUNT(*) as cnt FROM analysis_results").fetchone()
    return row["cnt"]


def load_analyses_by_bucket(bucket: str) -> list[AnalysisResult]:
    """Load analysis results filtered by recommendation_bucket."""
    _ensure_init()
    with get_db(readonly=True) as db:
        rows = db.execute(
            "SELECT * FROM analysis_results WHERE recommendation_bucket = ? ORDER BY priority_score DESC",
            (bucket,),
        ).fetchall()
    return [_analysis_from_row(r) for r in rows]


# ── seen / known bookmark IDs ──────────────────────────────────────────────

def _load_seen_ids(key: str) -> set[str]:
    """Load a set of IDs from the seen_bookmarks table."""
    _ensure_init()
    with get_db(readonly=True) as db:
        row = db.execute("SELECT value FROM seen_bookmarks WHERE id = ?", (key,)).fetchone()
    if row is None:
        return set()
    parsed = _json_deserialize(row["value"])
    return set(str(s).strip() for s in (parsed or []) if str(s).strip())


def _save_seen_ids(key: str, ids: Iterable[str]) -> None:
    """Save a sorted, unique set of IDs to the seen_bookmarks table."""
    _ensure_init()
    sorted_ids = sorted({str(s).strip() for s in ids if str(s).strip()})
    value = _json_serialize(sorted_ids)
    with get_db() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO seen_bookmarks (id, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, value, utc_now_iso()),
        )
        db.commit()


def load_known_bookmark_ids() -> set[str]:
    return _load_seen_ids("bookmark_ids")


def save_known_bookmark_ids(bookmark_ids: Iterable[str]) -> None:
    _save_seen_ids("bookmark_ids", bookmark_ids)


def load_seen_bookmark_ids() -> set[str]:
    return _load_seen_ids("analyzed_bookmark_ids")


def save_seen_bookmark_ids(bookmark_ids: Iterable[str]) -> None:
    _save_seen_ids("analyzed_bookmark_ids", bookmark_ids)


# ── stats summary ──────────────────────────────────────────────────────────

def _refresh_stats_summary() -> None:
    """Regenerate stats_summary from the SQLite tables."""
    _ensure_init()
    with get_db(readonly=True) as db:
        total_bm_row = db.execute("SELECT COUNT(*) as cnt FROM bookmarks").fetchone()
        total_ar_row = db.execute("SELECT COUNT(*) as cnt FROM analysis_results").fetchone()
        bucket_rows = db.execute(
            "SELECT recommendation_bucket, COUNT(*) as cnt FROM analysis_results GROUP BY recommendation_bucket"
        ).fetchall()

    buckets = {r["recommendation_bucket"]: r["cnt"] for r in bucket_rows}

    stats = {
        "total_bookmarks": total_bm_row["cnt"],
        "total_analyses": total_ar_row["cnt"],
        "buckets": buckets,
        "last_updated": utc_now_iso(),
    }
    with get_db() as db:
        db.execute(
            "INSERT OR REPLACE INTO stats_summary (id, data) VALUES (1, ?)",
            (_json_serialize(stats),),
        )
        db.commit()


def load_stats_summary() -> dict[str, Any]:
    """Load the cached stats summary."""
    _ensure_init()
    with get_db(readonly=True) as db:
        row = db.execute("SELECT data FROM stats_summary WHERE id = 1").fetchone()
    if row is None:
        return {}
    return _json_deserialize(row["data"]) or {}


# ── bulk import (for migration) ────────────────────────────────────────────

def import_bookmarks_bulk(bookmarks: Iterable[Bookmark]) -> int:
    """Import bookmarks in bulk using executemany. Returns count."""
    _ensure_init()
    rows = [_bookmark_to_row(bm) for bm in bookmarks]
    if not rows:
        return 0
    with get_db() as db:
        db.executemany(
            """
            INSERT OR REPLACE INTO bookmarks
                (id, source, url, text, title, note, author, created_at,
                 bookmarked_at, tags, raw_payload, updated_db_at)
            VALUES
                (:id, :source, :url, :text, :title, :note, :author, :created_at,
                 :bookmarked_at, :tags, :raw_payload, :updated_db_at)
            """,
            rows,
        )
        db.commit()
    _refresh_stats_summary()
    return len(rows)


def import_analyses_bulk(analyses: Iterable[AnalysisResult]) -> int:
    """Import analysis results in bulk using executemany. Returns count."""
    _ensure_init()
    rows = [_analysis_to_row(ar) for ar in analyses]
    if not rows:
        return 0
    with get_db() as db:
        db.executemany(
            """
            INSERT OR REPLACE INTO analysis_results
                (bookmark_id, summary, recommendation_reason, key_insights,
                 scoring_inputs, worth_score, effort_score, priority_score,
                 recommendation_bucket, analysis_source, analyzed_at,
                 confidence, difficulty_reason, next_action, title, relates_to,
                 personalized_worth_score, personalized_priority_score,
                 personalized_bucket, personalized_why,
                 original_worth_score, original_priority_score,
                 original_bucket, alignment_score,
                 pinned, pinned_reason, decayed_at, decayed_from_bucket, decay_reason,
                 tags, updated_db_at)
            VALUES
                (:bookmark_id, :summary, :recommendation_reason, :key_insights,
                 :scoring_inputs, :worth_score, :effort_score, :priority_score,
                 :recommendation_bucket, :analysis_source, :analyzed_at,
                 :confidence, :difficulty_reason, :next_action, :title, :relates_to,
                 :personalized_worth_score, :personalized_priority_score,
                 :personalized_bucket, :personalized_why,
                 :original_worth_score, :original_priority_score,
                 :original_bucket, :alignment_score,
                 :pinned, :pinned_reason, :decayed_at, :decayed_from_bucket, :decay_reason,
                 :tags, :updated_db_at)
            """,
            rows,
        )
        db.commit()
    _refresh_stats_summary()
    return len(rows)


def import_seen_bookmarks_bulk(
    bookmark_ids: Iterable[str],
    analyzed_bookmark_ids: Iterable[str],
) -> None:
    """Import seen/known bookmark ID sets."""
    _ensure_init()
    for key, ids in [("bookmark_ids", bookmark_ids), ("analyzed_bookmark_ids", analyzed_bookmark_ids)]:
        _save_seen_ids(key, ids)
