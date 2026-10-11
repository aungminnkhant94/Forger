"""Replace vs duplicate: forge add --replace re-scrapes; default stays DUPLICATE."""
from forger import bookmark_workflow as bw
from forger.models import AnalysisResult, Bookmark, ScoringInputs


def _bookmark(
    *,
    bookmark_id: str = "bookmark_aaaaaaaaaaaa",
    url: str = "https://example.com/post",
    text: str = "Thin stub body",
    title: str = "Old thin title",
):
    return Bookmark(
        id=bookmark_id,
        source="article",
        url=url,
        text=text,
        title=title,
        created_at="2026-01-01T00:00:00Z",
        bookmarked_at="2026-01-01T00:00:00Z",
        tags=[],
        raw_payload={"scraped_via": "old"},
    )


def _fresh_bookmark(
    *,
    bookmark_id: str = "bookmark_aaaaaaaaaaaa",
    url: str = "https://example.com/post",
):
    body = ("Fresh rich article body about catalysis methods. " * 20)[:280]
    return Bookmark(
        id=bookmark_id,
        source="article",
        url=url,
        text=body,
        title="Fresh rich title",
        created_at="2026-10-12T00:00:00Z",
        bookmarked_at="2026-10-12T00:00:00Z",
        tags=[],
        raw_payload={"scraped_via": "trafilatura", "ingestion_channel": "url"},
    )


def _pending(bookmark: Bookmark) -> AnalysisResult:
    return AnalysisResult(
        bookmark_id=bookmark.id,
        summary="[PENDING ANALYSIS] old",
        recommendation_reason="Awaiting agent analysis.",
        key_insights=[],
        scoring_inputs=ScoringInputs.from_dict({}),
        worth_score=0.0,
        effort_score=0.0,
        priority_score=0.0,
        recommendation_bucket="archive",
        analysis_source="pending_agent",
        analyzed_at=bookmark.bookmarked_at or "2026-01-01T00:00:00Z",
        title=bookmark.title,
    )


def test_duplicate_without_replace_unchanged(monkeypatch):
    existing = _bookmark()
    monkeypatch.setattr(bw, "check_duplicate", lambda url: existing)
    scrape_called = {"n": 0}

    def no_scrape(url):
        scrape_called["n"] += 1
        return _fresh_bookmark()

    monkeypatch.setattr(bw, "scrape_and_create_bookmark", no_scrape)

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        existing.url, analyze=False, replace=False
    )
    assert not ok
    assert "DUPLICATE" in message
    assert bookmark is existing
    assert analysis is None
    assert scrape_called["n"] == 0


def test_replace_rescrapes_and_overwrites(monkeypatch):
    existing = _bookmark()
    fresh = _fresh_bookmark()
    saved = {}

    monkeypatch.setattr(bw, "check_duplicate", lambda url: existing)
    monkeypatch.setattr(bw, "scrape_and_create_bookmark", lambda url: fresh)
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b, exclude_ids=None: (None, None))
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [existing])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [_pending(existing)])

    def capture_save(bookmarks):
        saved["bookmarks"] = list(bookmarks)

    def capture_upsert(existing_analyses, incoming):
        saved["analyses"] = list(incoming)
        return list(incoming)

    monkeypatch.setattr(bw, "save_bookmarks", capture_save)
    monkeypatch.setattr(bw, "upsert_analysis_results", capture_upsert)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a: ([], []))
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        existing.url, analyze=False, replace=True
    )
    assert ok, message
    assert "Replaced" in message
    assert bookmark.title == "Fresh rich title"
    assert bookmark.text.startswith("Fresh rich")
    assert bookmark.created_at == existing.created_at  # preserved
    assert bookmark.raw_payload.get("replaced") is True
    assert analysis.analysis_source == "pending_agent"
    assert saved["bookmarks"][0].title == "Fresh rich title"
    assert saved["analyses"][0].analysis_source == "pending_agent"


def test_replace_excludes_self_from_duplicate_topic(monkeypatch):
    """Without exclude_ids, exact URL in storage would trip DUPLICATE_TOPIC."""
    existing = _bookmark(text=("Old but usable article body about chemistry. " * 20)[:280])
    fresh = _fresh_bookmark()
    stored = [existing]

    monkeypatch.setattr(bw, "check_duplicate", lambda url: existing)
    monkeypatch.setattr(bw, "scrape_and_create_bookmark", lambda url: fresh)
    monkeypatch.setattr(bw, "load_bookmarks", lambda: list(stored))
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: None)
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a: ([], []))
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        existing.url, analyze=False, replace=True
    )
    assert ok, message
    assert bookmark.id == existing.id


def test_replace_scrape_failure_leaves_existing(monkeypatch):
    existing = _bookmark()
    saved = {"called": False}

    monkeypatch.setattr(bw, "check_duplicate", lambda url: existing)
    monkeypatch.setattr(bw, "scrape_and_create_bookmark", lambda url: None)
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: saved.__setitem__("called", True))

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        existing.url, analyze=False, replace=True
    )
    assert not ok
    assert "SCRAPE_FAILED" in message
    assert bookmark is None
    assert saved["called"] is False


def test_replace_when_nothing_exists_adds_normally(monkeypatch):
    fresh = _fresh_bookmark()
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    monkeypatch.setattr(bw, "scrape_and_create_bookmark", lambda url: fresh)
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b, exclude_ids=None: (None, None))
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: None)
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a: ([], []))
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        fresh.url, analyze=False, replace=True
    )
    assert ok, message
    assert "Saved" in message
    assert "Replaced" not in message


def test_find_bookmark_by_id(monkeypatch):
    existing = _bookmark()
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [existing])
    assert bw.find_bookmark_by_id(existing.id) is existing
    assert bw.find_bookmark_by_id("bookmark_bbbbbbbbbbbb") is None


def test_cli_replace_flag_wired():
    from forge import create_parser

    parser = create_parser()
    args = parser.parse_args(["add", "https://example.com/x", "--replace", "--agent"])
    assert args.replace is True
    assert args.agent is True
    args_default = parser.parse_args(["add", "https://example.com/x"])
    assert args_default.replace is False
