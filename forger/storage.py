from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from config.settings import ANALYSIS_RESULTS_PATH, BOOKMARKS_RAW_PATH, SEEN_BOOKMARKS_PATH, DATA_DIR
from forger.cache import cached_load, invalidate_path, get_cache
from forger.models import AnalysisResult, Bookmark
from forger.utils import ensure_parent, utc_now_iso


_STORAGE_BACKEND_ENV = "FORGER_STORAGE_BACKEND"
_STATS_PATH = DATA_DIR / "stats_summary.json"

# One lock file guards every read-modify-write of the shared data files
# (bookmarks_raw.json, analysis_results.json, seen_bookmarks.json,
# stats_summary.json). Without it two `forge add` processes both read N
# bookmarks, each writes N+1, and the slower write drops the other's id.
LOCK_PATH = DATA_DIR / ".forger.lock"
LOCK_TIMEOUT_SECONDS = 60.0

_thread_lock = threading.RLock()
_lock_depth = 0
_lock_handle = None


def _os_lock(handle, timeout: float) -> None:
    """Exclusive lock on *handle*: fcntl on POSIX, msvcrt on Windows."""
    deadline = time.monotonic() + timeout
    try:
        import fcntl
    except ImportError:  # Windows
        import msvcrt

        while True:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for {LOCK_PATH}")
                time.sleep(0.05)
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for {LOCK_PATH}")
            time.sleep(0.02)


def _os_unlock(handle) -> None:
    try:
        import fcntl
    except ImportError:
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def data_lock(timeout: float | None = None):
    """Hold the cross-process data lock. Re-entrant within one process."""
    global _lock_depth, _lock_handle
    with _thread_lock:
        if _lock_depth == 0:
            ensure_parent(LOCK_PATH)
            handle = open(LOCK_PATH, "a+b")
            try:
                _os_lock(handle, LOCK_TIMEOUT_SECONDS if timeout is None else timeout)
            except BaseException:
                handle.close()
                raise
            _lock_handle = handle
        _lock_depth += 1
        try:
            yield
        finally:
            _lock_depth -= 1
            if _lock_depth == 0:
                handle, _lock_handle = _lock_handle, None
                try:
                    _os_unlock(handle)
                finally:
                    handle.close()


def get_storage_backend() -> str:
    value = os.getenv(_STORAGE_BACKEND_ENV, "json").strip().lower()
    return value if value in {"json", "sqlite"} else "json"


def using_sqlite_backend() -> bool:
    return get_storage_backend() == "sqlite"


def _sqlite_storage():
    from forger import storage_sqlite

    return storage_sqlite


def load_json(path: Path, default: Any, *, fresh: bool = False) -> Any:
    """Load JSON with caching support. ``fresh`` skips the in-process cache
    (required inside data_lock, where another process may have written)."""
    if fresh:
        invalidate_path(path)

    def _load() -> Any:
        if not path.exists():
            return default
        with path.open("r", encoding="utf-8") as handle:
            try:
                return json.load(handle)
            except json.JSONDecodeError as exc:
                # Do not swallow corrupt files as []. cached_load would keep
                # that empty list, and the next save would wipe the real data.
                raise json.JSONDecodeError(
                    f"Corrupt JSON in {path}: {exc.msg}",
                    exc.doc,
                    exc.pos,
                ) from exc

    return cached_load(path, _load)


def write_json(path: Path, payload: Any) -> None:
    """Write JSON and invalidate cache.

    CRITICAL SAFETY RULE: This function overwrites the file.
    If you are saving analyses or bookmarks, you MUST merge first:

    - For analyses: use upsert_analysis_results()
    - For bookmarks: use merge_bookmarks() + save_bookmarks()

    NEVER call write_json() directly on production data files.
    """
    ensure_parent(path)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink()

    invalidate_path(path)


def _sync_sqlite_json_mirrors() -> None:
    """Keep legacy JSON files in sync while SQLite is the live backend."""
    sqlite = _sqlite_storage()

    bookmarks = sqlite.load_bookmarks()
    analyses = sqlite.load_analysis_results()
    known_ids = sqlite.load_known_bookmark_ids()
    seen_ids = sqlite.load_seen_bookmark_ids()

    write_json(BOOKMARKS_RAW_PATH, [bookmark.to_dict() for bookmark in bookmarks])
    write_json(ANALYSIS_RESULTS_PATH, [result.to_dict() for result in analyses])
    write_json(
        SEEN_BOOKMARKS_PATH,
        {
            "bookmark_ids": sorted(known_ids),
            "analyzed_bookmark_ids": sorted(seen_ids),
            "updated_at": utc_now_iso(),
        },
    )


def refresh_stats_summary() -> None:
    """Regenerate stats_summary.json from the active source of truth."""
    with data_lock():
        _refresh_stats_summary_locked()


def _refresh_stats_summary_locked() -> None:
    if using_sqlite_backend():
        sqlite = _sqlite_storage()
        bookmarks = sqlite.load_bookmarks()
        analyses = sqlite.load_analysis_results()
    else:
        bookmarks = load_bookmarks(path=BOOKMARKS_RAW_PATH, fresh=True)
        analyses = load_analysis_results(path=ANALYSIS_RESULTS_PATH, fresh=True)

    buckets: dict[str, int] = {}
    for analysis in analyses:
        bucket = getattr(analysis, "recommendation_bucket", None) or "unknown"
        buckets[bucket] = buckets.get(bucket, 0) + 1

    bookmark_ids = {bookmark.id for bookmark in bookmarks if bookmark.id}
    analysis_ids = {analysis.bookmark_id for analysis in analyses if analysis.bookmark_id}

    duplicates = 0
    seen_ids: set[str] = set()
    for bookmark in bookmarks:
        if not bookmark.id:
            continue
        if bookmark.id in seen_ids:
            duplicates += 1
        seen_ids.add(bookmark.id)

    stats = {
        "total_bookmarks": len(bookmarks),
        "total_analyses": len(analyses),
        "buckets": buckets,
        "last_updated": utc_now_iso(),
        "data_quality": {
            "missing_analyses": len(bookmark_ids - analysis_ids),
            "orphan_analyses": len(analysis_ids - bookmark_ids),
            "duplicates": duplicates,
        },
    }
    write_json(_STATS_PATH, stats)


def load_bookmarks(path: Path | None = None, *, fresh: bool = False) -> list[Bookmark]:
    if using_sqlite_backend() and path is None:
        return _sqlite_storage().load_bookmarks()

    source_path = path or BOOKMARKS_RAW_PATH
    raw_items = load_json(source_path, default=[], fresh=fresh)
    bookmarks = [Bookmark.from_dict(item) for item in raw_items if isinstance(item, dict)]
    return [bookmark for bookmark in bookmarks if bookmark.id and bookmark.url]


def save_bookmarks(bookmarks: Iterable[Bookmark], path: Path | None = None) -> None:
    """Overwrite the bookmark list. Prefer add_bookmarks() for adding: it
    re-reads under the lock so concurrent writers cannot drop rows."""
    with data_lock():
        _save_bookmarks_locked(bookmarks, path)


def _save_bookmarks_locked(bookmarks: Iterable[Bookmark], path: Path | None = None) -> None:
    if using_sqlite_backend() and path is None:
        _sqlite_storage().save_bookmarks(bookmarks)
        _sync_sqlite_json_mirrors()
        refresh_stats_summary()
        return

    target_path = path or BOOKMARKS_RAW_PATH
    write_json(target_path, [bookmark.to_dict() for bookmark in bookmarks])
    if target_path == BOOKMARKS_RAW_PATH:
        refresh_stats_summary()


def add_bookmarks(incoming: Iterable[Bookmark], drop_ids: Iterable[str] = ()) -> list[Bookmark]:
    """Atomically merge *incoming* into the stored bookmarks (optionally
    removing *drop_ids*). Read, merge and write all happen under data_lock."""
    incoming = list(incoming)
    drop = set(drop_ids)
    with data_lock():
        current = [b for b in load_bookmarks(fresh=True) if b.id not in drop]
        merged = merge_bookmarks(current, incoming)
        _save_bookmarks_locked(merged)
        return merged


def merge_bookmarks(existing: Iterable[Bookmark], incoming: Iterable[Bookmark]) -> list[Bookmark]:
    merged: dict[str, Bookmark] = {bookmark.id: bookmark for bookmark in existing}
    for bookmark in incoming:
        merged[bookmark.id] = bookmark
    return sorted(
        merged.values(),
        key=lambda item: item.bookmarked_at or item.created_at or "",
        reverse=True,
    )


def load_analysis_results(path: Path | None = None, *, fresh: bool = False) -> list[AnalysisResult]:
    if using_sqlite_backend() and path is None:
        return _sqlite_storage().load_analysis_results()

    source_path = path or ANALYSIS_RESULTS_PATH
    raw_items = load_json(source_path, default=[], fresh=fresh)
    return [AnalysisResult.from_dict(item) for item in raw_items if isinstance(item, dict) and item.get("bookmark_id")]


def save_analysis_results(results: Iterable[AnalysisResult], path: Path | None = None) -> None:
    with data_lock():
        _save_analysis_results_locked(results, path)


def _save_analysis_results_locked(results: Iterable[AnalysisResult], path: Path | None = None) -> None:
    if using_sqlite_backend() and path is None:
        _sqlite_storage().save_analysis_results(results)
        _sync_sqlite_json_mirrors()
        refresh_stats_summary()
        return

    target_path = path or ANALYSIS_RESULTS_PATH
    write_json(target_path, [result.to_dict() for result in results])
    if target_path == ANALYSIS_RESULTS_PATH:
        refresh_stats_summary()


def upsert_analysis_results(
    existing: Iterable[AnalysisResult],
    new_results: Iterable[AnalysisResult],
    path: Path | None = None,
) -> list[AnalysisResult]:
    merged: dict[str, AnalysisResult] = {result.bookmark_id: result for result in existing}
    for result in new_results:
        merged[result.bookmark_id] = result
    ordered = sorted(merged.values(), key=lambda item: item.priority_score, reverse=True)
    save_analysis_results(ordered, path=path)
    return ordered


def add_analysis_results(
    incoming: Iterable[AnalysisResult], drop_ids: Iterable[str] = ()
) -> list[AnalysisResult]:
    """Atomically upsert *incoming* analyses (read+merge+write under lock)."""
    incoming = list(incoming)
    drop = set(drop_ids)
    with data_lock():
        current = [a for a in load_analysis_results(fresh=True) if a.bookmark_id not in drop]
        return upsert_analysis_results(current, incoming)


def _load_seen_payload(path: Path = SEEN_BOOKMARKS_PATH, *, fresh: bool = False) -> dict[str, Any]:
    payload = load_json(path, default={"bookmark_ids": [], "analyzed_bookmark_ids": []}, fresh=fresh)
    if not isinstance(payload, dict):
        return {"bookmark_ids": [], "analyzed_bookmark_ids": []}
    payload.setdefault("bookmark_ids", [])
    payload.setdefault("analyzed_bookmark_ids", [])
    return payload


def load_known_bookmark_ids(path: Path | None = None) -> set[str]:
    if using_sqlite_backend() and path is None:
        return _sqlite_storage().load_known_bookmark_ids()

    source_path = path or SEEN_BOOKMARKS_PATH
    payload = _load_seen_payload(source_path)
    bookmark_ids = payload.get("bookmark_ids", []) if isinstance(payload, dict) else []
    return {str(item).strip() for item in bookmark_ids if str(item).strip()}


def save_known_bookmark_ids(bookmark_ids: Iterable[str], path: Path | None = None) -> None:
    if using_sqlite_backend() and path is None:
        _sqlite_storage().save_known_bookmark_ids(bookmark_ids)
        _sync_sqlite_json_mirrors()
        return

    target_path = path or SEEN_BOOKMARKS_PATH
    with data_lock():
        payload = _load_seen_payload(target_path, fresh=True)
        payload["bookmark_ids"] = sorted({str(item).strip() for item in bookmark_ids if str(item).strip()})
        payload["updated_at"] = utc_now_iso()
        write_json(target_path, payload)


def load_seen_bookmark_ids(path: Path | None = None) -> set[str]:
    if using_sqlite_backend() and path is None:
        return _sqlite_storage().load_seen_bookmark_ids()

    source_path = path or SEEN_BOOKMARKS_PATH
    payload = _load_seen_payload(source_path)
    bookmark_ids = payload.get("analyzed_bookmark_ids", []) if isinstance(payload, dict) else []
    return {str(item).strip() for item in bookmark_ids if str(item).strip()}


def save_seen_bookmark_ids(bookmark_ids: Iterable[str], path: Path | None = None) -> None:
    if using_sqlite_backend() and path is None:
        _sqlite_storage().save_seen_bookmark_ids(bookmark_ids)
        _sync_sqlite_json_mirrors()
        return

    target_path = path or SEEN_BOOKMARKS_PATH
    with data_lock():
        payload = _load_seen_payload(target_path, fresh=True)
        payload["analyzed_bookmark_ids"] = sorted({str(item).strip() for item in bookmark_ids if str(item).strip()})
        payload["updated_at"] = utc_now_iso()
        write_json(target_path, payload)


def add_known_bookmark_ids(bookmark_ids: Iterable[str]) -> None:
    """Union *bookmark_ids* into the known set under the lock."""
    with data_lock():
        save_known_bookmark_ids(load_known_bookmark_ids_fresh() | set(bookmark_ids))


def add_seen_bookmark_ids(bookmark_ids: Iterable[str]) -> None:
    """Union *bookmark_ids* into the analyzed set under the lock."""
    with data_lock():
        save_seen_bookmark_ids(load_seen_bookmark_ids_fresh() | set(bookmark_ids))


def load_known_bookmark_ids_fresh() -> set[str]:
    invalidate_path(SEEN_BOOKMARKS_PATH)
    return load_known_bookmark_ids()


def load_seen_bookmark_ids_fresh() -> set[str]:
    invalidate_path(SEEN_BOOKMARKS_PATH)
    return load_seen_bookmark_ids()


def bootstrap_sqlite_from_json() -> None:
    """Populate SQLite from JSON once when enabling the sqlite backend."""
    sqlite = _sqlite_storage()
    if sqlite.count_bookmarks() or sqlite.count_analyses():
        return

    bookmarks = load_bookmarks(path=BOOKMARKS_RAW_PATH)
    analyses = load_analysis_results(path=ANALYSIS_RESULTS_PATH)
    known_ids = load_known_bookmark_ids(path=SEEN_BOOKMARKS_PATH)
    seen_ids = load_seen_bookmark_ids(path=SEEN_BOOKMARKS_PATH)

    sqlite.import_bookmarks_bulk(bookmarks)
    sqlite.import_analyses_bulk(analyses)
    sqlite.import_seen_bookmarks_bulk(known_ids, seen_ids)
    _sync_sqlite_json_mirrors()
    refresh_stats_summary()


def get_cache_stats() -> dict[str, Any]:
    """Get cache statistics for monitoring."""
    return get_cache().get_stats()


def invalidate_cache(path: Path | None = None) -> bool:
    """
    Invalidate cache for a specific path or all cache.

    Args:
        path: Specific file path to invalidate, or None for all

    Returns:
        True if cache was invalidated
    """
    if path:
        return invalidate_path(path)
    else:
        get_cache().invalidate_all()
        return True
