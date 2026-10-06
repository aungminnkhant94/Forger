"""Smoke tests for the add workflow — guards against import/contract breakage
in process_bookmark_url (the core path behind `forge add`)."""
from forger import bookmark_workflow as bw
from forger.models import Bookmark


def _make_bookmark():
    return Bookmark(
        id="bookmark_test1",
        source="article",
        url="https://example.com/post",
        text="Some article text",
        title="Test Article",
    )


def _patch_workflow(monkeypatch):
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    monkeypatch.setattr(bw, "scrape_and_create_bookmark", lambda url: _make_bookmark())
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b: (None, None))
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: None)
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda existing, incoming: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)


def test_workflow_public_surface():
    assert callable(bw.process_bookmark_url)
    assert callable(bw.resolve_pending_analysis)


def test_agent_mode_saves_pending(monkeypatch):
    _patch_workflow(monkeypatch)
    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://example.com/post", analyze=False
    )
    assert ok, message
    assert analysis.analysis_source == "pending_agent"
    assert analysis.recommendation_bucket == "archive"


def test_note_is_stored_on_bookmark(monkeypatch):
    _patch_workflow(monkeypatch)
    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://example.com/post", analyze=False, note="checking this for deploy"
    )
    assert ok, message
    assert bookmark.note == "checking this for deploy"
    assert bookmark.raw_payload.get("capture_mode") == "url_with_note"


def test_duplicate_url_short_circuits(monkeypatch):
    existing = _make_bookmark()
    monkeypatch.setattr(bw, "check_duplicate", lambda url: existing)
    ok, message, bookmark, analysis = bw.process_bookmark_url(existing.url, analyze=False)
    assert not ok
    assert "DUPLICATE" in message
