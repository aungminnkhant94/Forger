"""
SQLite database layer for Forger.

Uses stdlib sqlite3 with WAL mode for concurrent read performance.
All schema management is idempotent. The database file is created
on first access within DATA_DIR.

Thread safety: connections are not shared across threads. Each call
to get_db() returns a new connection. Callers are responsible for
closing connections or using the context manager.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = DATA_DIR / "forger.db"

SCHEMA_VERSION = 1


def _json_serialize(obj: Any) -> str:
    """Serialize Python object to JSON string for SQLite storage."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=False)


def _json_deserialize(raw: str | None) -> Any:
    """Deserialize JSON string from SQLite back to Python object."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def get_db_path() -> Path:
    """Return the configured database path."""
    return DB_PATH


def db_exists() -> bool:
    """Check if the database file already exists."""
    return DB_PATH.exists()


def connect(readonly: bool = False) -> sqlite3.Connection:
    """Open a connection to the SQLite database.

    Enables WAL mode, foreign keys, and returns rows as dicts.
    """
    if not readonly:
        # Fresh install: data/ may not exist yet — create it before opening.
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{DB_PATH}?mode={'ro' if readonly else 'rwc'}"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def get_db(readonly: bool = False) -> Generator[sqlite3.Connection, None, None]:
    """Context manager for database connections.

    Usage:
        with get_db() as db:
            rows = db.execute("SELECT ...").fetchall()
    """
    conn = connect(readonly=readonly)
    try:
        yield conn
    finally:
        conn.close()


def _migrate_add_personalized_columns(db: sqlite3.Connection) -> None:
    """Add personalized scoring columns if they don't exist (safe to re-run)."""
    columns = [
        ("personalized_worth_score", "REAL"),
        ("personalized_priority_score", "REAL"),
        ("personalized_bucket", "TEXT"),
        ("personalized_why", "TEXT"),
        ("original_worth_score", "REAL"),
        ("original_priority_score", "REAL"),
        ("original_bucket", "TEXT"),
        ("alignment_score", "REAL"),
        ("pinned", "INTEGER NOT NULL DEFAULT 0"),
        ("pinned_reason", "TEXT"),
        ("decayed_at", "TEXT"),
        ("decayed_from_bucket", "TEXT"),
        ("decay_reason", "TEXT"),
        ("tags", "TEXT NOT NULL DEFAULT '[]'"),
    ]
    existing = {row[1] for row in db.execute("PRAGMA table_info(analysis_results)")}
    for col_name, col_type in columns:
        if col_name not in existing:
            db.execute(f"ALTER TABLE analysis_results ADD COLUMN {col_name} {col_type}")
            logger.info("Added column analysis_results.%s", col_name)


def _migrate_add_title_column(db: sqlite3.Connection) -> None:
    """Add title column to analysis_results if missing (safe to re-run)."""
    existing = {row[1] for row in db.execute("PRAGMA table_info(analysis_results)")}
    if "title" not in existing:
        db.execute("ALTER TABLE analysis_results ADD COLUMN title TEXT")
        logger.info("Added column analysis_results.title")
        db.commit()


def _migrate_add_relates_to_column(db: sqlite3.Connection) -> None:
    """Add relates_to column to analysis_results if missing (safe to re-run)."""
    existing = {row[1] for row in db.execute("PRAGMA table_info(analysis_results)")}
    if "relates_to" not in existing:
        db.execute("ALTER TABLE analysis_results ADD COLUMN relates_to TEXT")
        logger.info("Added column analysis_results.relates_to")
        db.commit()


def init_db() -> None:
    """Create tables and indexes if they do not exist (idempotent).

    Safe to call multiple times — uses IF NOT EXISTS.
    """
    with get_db() as db:
        db.executescript(_SCHEMA_SQL)
        # Migration: add personalized scoring columns (2026-05-01)
        _migrate_add_personalized_columns(db)
        # Migration: add tags column (2026-05-02)
        # _migrate_add_tags_column(db)  # merged into personalized columns
        # Migration: add title column (2026-05-04)
        _migrate_add_title_column(db)
        # Migration: add relates_to column (2026-09-17)
        _migrate_add_relates_to_column(db)
        db.commit()
        logger.info("Database initialized at %s (schema v%d)", DB_PATH, SCHEMA_VERSION)


def drop_all_tables() -> None:
    """Drop all Forger tables. Use with caution — for testing/reset."""
    with get_db() as db:
        db.execute("DROP TABLE IF EXISTS bookmarks")
        db.execute("DROP TABLE IF EXISTS analysis_results")
        db.execute("DROP TABLE IF EXISTS seen_bookmarks")
        db.execute("DROP TABLE IF EXISTS stats_summary")
        db.execute("DROP TABLE IF EXISTS schema_version")
        db.commit()
        logger.warning("All Forger tables dropped from %s", DB_PATH)


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bookmarks (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL DEFAULT 'x',
    url             TEXT NOT NULL,
    text            TEXT NOT NULL DEFAULT '',
    title           TEXT,
    note            TEXT,
    author          TEXT,
    created_at      TEXT,
    bookmarked_at   TEXT,
    tags            TEXT NOT NULL DEFAULT '[]',
    raw_payload     TEXT NOT NULL DEFAULT '{}',
    created_db_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_db_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_source ON bookmarks(source);
CREATE INDEX IF NOT EXISTS idx_bookmarks_bookmarked_at ON bookmarks(bookmarked_at);
CREATE INDEX IF NOT EXISTS idx_bookmarks_created_at ON bookmarks(created_at);

CREATE TABLE IF NOT EXISTS analysis_results (
    bookmark_id           TEXT PRIMARY KEY,
    summary               TEXT NOT NULL DEFAULT '',
    recommendation_reason TEXT NOT NULL DEFAULT '',
    key_insights          TEXT NOT NULL DEFAULT '[]',
    scoring_inputs        TEXT NOT NULL DEFAULT '{}',
    worth_score           REAL NOT NULL DEFAULT 0,
    effort_score          REAL NOT NULL DEFAULT 0,
    priority_score        REAL NOT NULL DEFAULT 0,
    recommendation_bucket TEXT NOT NULL DEFAULT 'archive',
    analysis_source       TEXT NOT NULL DEFAULT 'fallback',
    analyzed_at           TEXT NOT NULL DEFAULT '',
    confidence            TEXT,
    difficulty_reason     TEXT,
    next_action           TEXT,
    -- Title from DeepSeek analysis (2026-05-04)
    title                 TEXT,
    -- Prose tying the bookmark to the user's goals/preferences (from profile.md)
    relates_to            TEXT,
    -- Personalized scoring fields (2026-05-01)
    personalized_worth_score    REAL,
    personalized_priority_score REAL,
    personalized_bucket         TEXT,
    personalized_why            TEXT,
    original_worth_score        REAL,
    original_priority_score     REAL,
    original_bucket             TEXT,
    alignment_score             REAL,
    pinned                      INTEGER NOT NULL DEFAULT 0,
    pinned_reason               TEXT,
    decayed_at                  TEXT,
    decayed_from_bucket         TEXT,
    decay_reason                TEXT,
    tags                        TEXT NOT NULL DEFAULT '[]',
    created_db_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_db_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_analysis_bucket ON analysis_results(recommendation_bucket);
CREATE INDEX IF NOT EXISTS idx_analysis_priority ON analysis_results(priority_score);
CREATE INDEX IF NOT EXISTS idx_analysis_source ON analysis_results(analysis_source);

CREATE TABLE IF NOT EXISTS seen_bookmarks (
    id         TEXT PRIMARY KEY,
    value      TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stats_summary (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);

-- Seed schema version if empty
INSERT OR IGNORE INTO schema_version (version) VALUES (1);
"""
