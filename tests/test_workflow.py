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
    # invariant check reads real storage; meaningless under mocks
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a: ([], []))


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


def test_schemeless_example_com_does_not_raise_indexerror(monkeypatch):
    def fake_scrape(url, timeout=15):
        assert url == "https://example.com"
        return {
            "success": False,
            "title": None,
            "text": None,
            "author": None,
            "source": None,
            "error": "mocked",
        }

    monkeypatch.setattr("forger.scrapers.article_scraper.scrape_article", fake_scrape)
    try:
        bookmark = bw.scrape_and_create_bookmark("example.com")
    except IndexError as exc:
        raise AssertionError(f"IndexError on schemeless URL: {exc}") from exc
    assert bookmark is not None
    assert bookmark.url == "https://example.com"
    assert "example.com" in (bookmark.title or "")
    assert bookmark.raw_payload.get("scrape_failed") is True


def test_invalid_schemeless_string_fails_without_traceback():
    ok, message, bookmark, analysis = bw.process_bookmark_url("not a url", analyze=False)
    assert ok is False
    assert bookmark is None
    assert message
    assert "scheme" in message.lower() or "invalid" in message.lower()


def test_failed_scrape_stubs_both_save_but_utm_is_still_duplicate(monkeypatch):
    store = {"bookmarks": [], "analyses": []}

    def load_bookmarks():
        return list(store["bookmarks"])

    def save_bookmarks(items):
        store["bookmarks"] = list(items)

    def load_analyses():
        return list(store["analyses"])

    def upsert(existing, incoming):
        store["analyses"] = list(existing) + list(incoming)

    monkeypatch.setattr(bw, "load_bookmarks", load_bookmarks)
    monkeypatch.setattr(bw, "save_bookmarks", save_bookmarks)
    monkeypatch.setattr(bw, "load_analysis_results", load_analyses)
    monkeypatch.setattr(bw, "upsert_analysis_results", upsert)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *args: ([], []))
    monkeypatch.setattr(
        "forger.scrapers.article_scraper.scrape_article",
        lambda url, timeout=15: {
            "success": False,
            "title": None,
            "text": None,
            "author": None,
            "source": None,
            "error": "blocked",
        },
    )

    first = "https://news.ycombinator.com/item?id=1"
    second = "https://news.ycombinator.com/item?id=2"
    tracked = "https://news.ycombinator.com/item?id=1&utm_source=twitter"
    ok1, msg1, bookmark1, _ = bw.process_bookmark_url(first, analyze=False)
    ok2, msg2, bookmark2, _ = bw.process_bookmark_url(second, analyze=False)
    ok3, msg3, _, _ = bw.process_bookmark_url(tracked, analyze=False)

    assert ok1, msg1
    assert ok2, msg2
    assert bookmark1.title == bookmark2.title
    assert bookmark1.id != bookmark2.id
    assert len(store["bookmarks"]) == 2
    assert ok3 is False
    assert "DUPLICATE" in msg3


def test_two_mocked_youtube_videos_both_save(monkeypatch):
    store = {"bookmarks": [], "analyses": []}
    monkeypatch.setattr(bw, "load_bookmarks", lambda: list(store["bookmarks"]))
    monkeypatch.setattr(bw, "save_bookmarks", lambda items: store.__setitem__("bookmarks", list(items)))
    monkeypatch.setattr(bw, "load_analysis_results", lambda: list(store["analyses"]))
    monkeypatch.setattr(
        bw,
        "upsert_analysis_results",
        lambda existing, incoming: store.__setitem__("analyses", list(existing) + list(incoming)),
    )
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *args: ([], []))

    def fake_youtube(url, timeout=15):
        video_id = url.split("v=")[1]
        return {
            "success": True,
            "title": f"Video {video_id}",
            "text": f"Description for {video_id}\nVideo id: {video_id}\nURL: {url}",
            "author": "channel",
            "source": "youtube-oembed",
            "error": None,
            "video_id": video_id,
        }

    monkeypatch.setattr("forger.scrapers.article_scraper.fetch_youtube", fake_youtube)
    ok1, msg1, first, _ = bw.process_bookmark_url(
        "https://www.youtube.com/watch?v=aaaaaaaaaaa", analyze=False
    )
    ok2, msg2, second, _ = bw.process_bookmark_url(
        "https://www.youtube.com/watch?v=bbbbbbbbbbb", analyze=False
    )
    assert ok1, msg1
    assert ok2, msg2
    assert first.title != second.title
    assert "aaaaaaaaaaa" in first.text
    assert "bbbbbbbbbbb" in second.text
    assert len(store["bookmarks"]) == 2


def test_real_extracted_text_still_hits_similarity_gate(monkeypatch):
    text = "Raft consensus explained for operators who run distributed storage. " * 6
    existing = Bookmark(
        id="bookmark_real",
        source="article",
        url="https://example.com/raft-a",
        text=text,
        title="Raft explained",
        tags=["research", "coding"],
        raw_payload={"scraped_via": "requests+bs4", "content_kind": "extracted", "scrape_failed": False},
    )
    incoming = Bookmark(
        id="bookmark_real2",
        source="article",
        url="https://example.com/raft-b",
        text=text,
        title="Raft explained",
        tags=["research", "coding"],
        raw_payload={"scraped_via": "requests+bs4", "content_kind": "extracted", "scrape_failed": False},
    )
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [existing])
    dup, message = bw.find_similar_duplicate(incoming)
    assert dup is not None
    assert dup.url == existing.url
    assert message
