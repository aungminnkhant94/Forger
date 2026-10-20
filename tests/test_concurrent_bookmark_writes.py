"""Concurrent `forge add` must not lose bookmarks or analyses.

Each worker is a separate OS process (like two terminals running forge add)
that runs the real process_bookmark_url save path against one temp data dir.
Only the network scrape, similarity check, dashboard sync and git are stubbed.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX test harness")

WORKERS = 8
ROUNDS = 3  # each worker adds this many bookmarks


def _point_storage_at(data_dir: Path) -> None:
    import forger.storage as storage

    storage.BOOKMARKS_RAW_PATH = data_dir / "bookmarks_raw.json"
    storage.ANALYSIS_RESULTS_PATH = data_dir / "analysis_results.json"
    storage.SEEN_BOOKMARKS_PATH = data_dir / "seen_bookmarks.json"
    storage._STATS_PATH = data_dir / "stats_summary.json"
    if hasattr(storage, "LOCK_PATH"):
        storage.LOCK_PATH = data_dir / ".forger.lock"


def _worker(data_dir: str, worker: int, start_at: float, out_q) -> None:
    import forger.bookmark_workflow as bw
    from forger.models import Bookmark

    _point_storage_at(Path(data_dir))

    def fake_scrape(url):
        return Bookmark(
            id=bw.stable_bookmark_id(url, url),
            source="article",
            url=url,
            text="Body text long enough to be a real bookmark. " * 10,
            title=f"Title {url}",
            bookmarked_at="2026-10-18T00:00:00Z",
            created_at="2026-10-18T00:00:00Z",
        )

    bw.scrape_and_create_bookmark = fake_scrape
    bw.find_similar_duplicate = lambda bookmark, exclude_ids=None: (None, "")
    bw._sync_dashboard = lambda: None
    bw.git_auto_push = lambda title: False

    while time.time() < start_at:  # line everyone up to collide
        pass
    results = []
    for r in range(ROUNDS):
        url = f"https://example.com/w{worker}/r{r}"
        ok, msg, bookmark, _ = bw.process_bookmark_url(url, analyze=False)
        results.append((ok, bookmark.id if bookmark else None, msg.splitlines()[0]))
    out_q.put(results)


def run_concurrent_adds(data_dir: Path):
    ctx = mp.get_context("spawn")  # same as separate forge processes, also Windows-like
    q = ctx.Queue()
    start_at = time.time() + 3.0
    procs = [ctx.Process(target=_worker, args=(str(data_dir), w, start_at, q)) for w in range(WORKERS)]
    for p in procs:
        p.start()
    reported = []
    for _ in procs:
        reported.extend(q.get(timeout=120))
    for p in procs:
        p.join(timeout=60)
    bookmark_ids = {b["id"] for b in json.loads((data_dir / "bookmarks_raw.json").read_text())}
    analysis_path = data_dir / "analysis_results.json"
    if analysis_path.exists():
        analysis_ids = {a["bookmark_id"] for a in json.loads(analysis_path.read_text())}
    else:
        analysis_ids = set()
    return reported, bookmark_ids, analysis_ids


def test_concurrent_forge_add_loses_nothing(tmp_path):
    reported, bookmark_ids, analysis_ids = run_concurrent_adds(tmp_path)
    saved = {bid for ok, bid, _ in reported if ok}
    failed = [m for ok, _, m in reported if not ok]
    assert len(reported) == WORKERS * ROUNDS
    assert not failed, f"forge add reported failures: {failed[:3]}"
    lost_b = saved - bookmark_ids
    assert not lost_b, f"{len(lost_b)} bookmark ids lost from bookmarks_raw.json"
    # Agent mode writes bookmark only — no placeholder AnalysisResult.
    assert analysis_ids == set(), f"unexpected analyses written: {analysis_ids}"
    assert len(bookmark_ids) == WORKERS * ROUNDS
    assert not list(tmp_path.glob(".*.tmp")), "temp files left behind"


def _storage_worker(data_dir: str, worker: int, start_at: float) -> None:
    import forger.storage as storage
    from forger.models import Bookmark

    _point_storage_at(Path(data_dir))
    while time.time() < start_at:
        pass
    for r in range(ROUNDS):
        bid = f"bookmark_w{worker}r{r}"
        storage.add_bookmarks([Bookmark(id=bid, source="article", url=f"https://e.com/{bid}", text="t", title="t")])
        storage.add_known_bookmark_ids({bid})
        storage.add_seen_bookmark_ids({bid})


def test_storage_add_helpers_are_safe_across_processes(tmp_path):
    """The helpers telegram ingest uses (bookmarks + seen_bookmarks.json)."""
    ctx = mp.get_context("spawn")
    start_at = time.time() + 3.0
    procs = [ctx.Process(target=_storage_worker, args=(str(tmp_path), w, start_at)) for w in range(WORKERS)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0
    expected = {f"bookmark_w{w}r{r}" for w in range(WORKERS) for r in range(ROUNDS)}
    ids = {b["id"] for b in json.loads((tmp_path / "bookmarks_raw.json").read_text())}
    seen = json.loads((tmp_path / "seen_bookmarks.json").read_text())
    assert ids == expected
    assert set(seen["bookmark_ids"]) == expected
    assert set(seen["analyzed_bookmark_ids"]) == expected


def test_lock_uses_msvcrt_when_fcntl_missing(monkeypatch, tmp_path):
    """Windows path (Surface laptop): no fcntl, lock via msvcrt.locking."""
    import builtins
    import sys
    import types

    import forger.storage as storage

    calls = []
    fake = types.SimpleNamespace(
        LK_NBLCK=2, LK_UNLCK=0,
        locking=lambda fd, mode, n: calls.append(mode),
    )
    real_import = builtins.__import__

    def no_fcntl(name, *a, **k):
        if name == "fcntl":
            raise ImportError("no fcntl on Windows")
        return real_import(name, *a, **k)

    monkeypatch.setitem(sys.modules, "msvcrt", fake)
    monkeypatch.setattr(builtins, "__import__", no_fcntl)
    monkeypatch.setattr(storage, "LOCK_PATH", tmp_path / ".forger.lock")
    with storage.data_lock():
        with storage.data_lock():  # re-entrant: locks the OS file once
            pass
    assert calls == [fake.LK_NBLCK, fake.LK_UNLCK]


def test_lock_times_out_instead_of_hanging(tmp_path, monkeypatch):
    import fcntl

    import forger.storage as storage

    lock = tmp_path / ".forger.lock"
    monkeypatch.setattr(storage, "LOCK_PATH", lock)
    holder = open(lock, "a+b")
    fcntl.flock(holder.fileno(), fcntl.LOCK_EX)  # another process holds it
    try:
        # Different fd in this process → flock conflicts like a second process.
        with pytest.raises(TimeoutError):
            with storage.data_lock(timeout=0.2):
                pass
    finally:
        holder.close()
