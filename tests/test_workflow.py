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
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b, exclude_ids=None: (None, None))
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: None)
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda existing, incoming: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    # invariant check reads real storage; meaningless under mocks
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a, **k: ([], []))


def test_workflow_public_surface():
    assert callable(bw.process_bookmark_url)
    assert callable(bw.resolve_pending_analysis)


def test_agent_mode_saves_pending(monkeypatch):
    _patch_workflow(monkeypatch)
    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://example.com/post", analyze=False
    )
    assert ok, message
    assert analysis is None  # pending is content file, not a fake AnalysisResult
    assert "pending" in message.lower()


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


def test_agent_mode_defers_tags_until_resolve(monkeypatch):
    """forge add --agent must not save heuristic junk tags before resolve."""
    saved = {}

    def capture_save(bookmarks):
        saved["bookmarks"] = list(bookmarks)

    def capture_upsert(existing, incoming):
        saved["analyses"] = list(incoming)
        return list(incoming)

    junk_tagged = _make_bookmark()
    junk_tagged.tags = ["research", "ai-tools"]  # what old scrape heuristics invented

    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    monkeypatch.setattr(bw, "scrape_and_create_bookmark", lambda url: junk_tagged)
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b, exclude_ids=None: (None, None))
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", capture_save)
    monkeypatch.setattr(bw, "upsert_analysis_results", capture_upsert)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a, **k: ([], []))
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://example.com/post", analyze=False
    )
    assert ok, message
    assert bookmark.tags == []
    assert saved["bookmarks"][0].tags == []
    assert analysis is None
    assert "analyses" not in saved  # no placeholder AnalysisResult written


def test_scrape_creates_bookmark_with_empty_tags(monkeypatch):
    body = ("Useful article body about ester synthesis methods. " * 20)[:250]

    monkeypatch.setattr(
        "forger.scrapers.article_scraper.scrape_article",
        lambda url: {
            "success": True,
            "title": "Ester synthesis",
            "text": body,
            "author": "Ada",
            "source": "trafilatura",
        },
    )
    bookmark = bw.scrape_and_create_bookmark("https://example.com/chem")
    assert bookmark is not None
    assert bookmark.tags == []


def test_resolve_writes_analysis_tags(monkeypatch):
    stored = {}
    pending = _make_bookmark()
    pending.tags = []

    def capture_save(bookmarks):
        stored["bookmark"] = list(bookmarks)[0]

    monkeypatch.setattr(bw, "load_bookmarks", lambda: [pending])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", capture_save)
    monkeypatch.setattr(bw, "merge_bookmarks", lambda existing, incoming: list(incoming))
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: list(a[1]))
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "refine_bucket", lambda bookmark, analysis: analysis.recommendation_bucket)
    monkeypatch.setattr(bw, "clean_analysis_text", lambda bookmark, analysis: analysis)

    ok, message, analysis = bw.resolve_pending_analysis(
        pending.id,
        {
            "summary": "A methods note on ester synthesis for lab use this week.",
            "recommendation_bucket": "archive",
            "relates_to": (
                "Connects to the PhD catalysis project because ester routes "
                "show up in the current substrate screen. Worth keeping as "
                "reference when planning the next wet-lab batch."
            ),
            "actionable_this_week": False,
            "reduces_friction": False,
            "reference_material": True,
            "tags": ["catalysis", "organic-synthesis", "methods"],
        },
    )
    assert ok, message
    assert stored["bookmark"].tags[:3] == ["catalysis", "organic-synthesis", "methods"]
    assert stored["bookmark"].agent_tags == ["catalysis", "organic-synthesis", "methods"]
