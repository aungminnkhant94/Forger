"""Failed/thin scrapes must not save stubs or cause false DUPLICATE_TOPIC."""
from forger import bookmark_workflow as bw
from forger.models import Bookmark
from forger.scrape_quality import (
    MIN_USABLE_ARTICLE_TEXT_CHARS,
    is_scrape_failure_stub,
    is_usable_scrape_text,
)
from forger.similarity import check_duplicate_topic, find_similar_bookmarks


def _rich_text(n: int = MIN_USABLE_ARTICLE_TEXT_CHARS + 50) -> str:
    return ("Useful article body about chemistry research methods. " * 20)[:n]


def test_thin_definition_matches_article_scraper_bar():
    assert MIN_USABLE_ARTICLE_TEXT_CHARS == 200
    assert not is_usable_scrape_text("x" * 200, source="article")  # need > 200
    assert is_usable_scrape_text("x" * 201, source="article")
    assert is_usable_scrape_text("short tweet ok", source="x")
    assert is_scrape_failure_stub("[URL content not available] https://example.com")
    assert is_scrape_failure_stub(
        "Twitter/X post from @alice. View on X for full content."
    )
    assert not is_usable_scrape_text(
        "[URL content not available] https://example.com", source="article"
    )


def test_failed_article_scrape_does_not_save(monkeypatch):
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    saved = {"bookmarks": None}

    def capture_save(bookmarks):
        saved["bookmarks"] = list(bookmarks)

    monkeypatch.setattr(bw, "save_bookmarks", capture_save)
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    def fake_scrape(url):
        return {
            "success": False,
            "title": None,
            "text": None,
            "author": None,
            "source": None,
            "error": "HTTP error: 403",
        }

    monkeypatch.setattr(
        "forger.scrapers.article_scraper.scrape_article",
        fake_scrape,
    )

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://example.com/blocked", analyze=False
    )
    assert not ok
    assert "SCRAPE_FAILED" in message
    assert bookmark is None
    assert analysis is None
    assert saved["bookmarks"] is None


def test_thin_article_body_does_not_save(monkeypatch):
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    saved = {"called": False}
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: saved.__setitem__("called", True))
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    monkeypatch.setattr(
        "forger.scrapers.article_scraper.scrape_article",
        lambda url: {
            "success": True,  # liar / legacy path — body still thin
            "title": "Article from example.com",
            "text": "too short",
            "author": None,
            "source": "requests+bs4",
            "error": None,
        },
    )

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://example.com/thin", analyze=False
    )
    assert not ok
    assert "SCRAPE_FAILED" in message
    assert bookmark is None
    assert saved["called"] is False


def test_thin_stub_not_used_as_similarity_target():
    stub = {
        "id": "bookmark_stub",
        "url": "https://example.com/old",
        "title": "Article from example.com",
        "text": "[URL content not available] https://example.com/old",
        "tags": ["article"],
        "source": "article",
    }
    rich = {
        "id": "bookmark_rich",
        "url": "https://journals.example.edu/paper",
        "title": "Methods in organometallic chemistry",
        "text": _rich_text(),
        "tags": ["chemistry"],
        "source": "article",
    }
    similar = find_similar_bookmarks(
        "Methods in organometallic chemistry",
        ["chemistry"],
        _rich_text(),
        [stub, rich],
        threshold=0.3,
    )
    ids = [hit["bookmark"]["id"] for hit in similar]
    assert "bookmark_stub" not in ids
    assert "bookmark_rich" in ids


def test_thin_new_text_skips_duplicate_topic():
    stub = {
        "id": "bookmark_stub",
        "url": "https://example.com/a",
        "title": "Article from example.com",
        "text": "[URL content not available] https://example.com/a",
        "tags": [],
        "source": "article",
    }
    result = check_duplicate_topic(
        "https://example.com/b",
        "Article from example.com",
        [],
        "[URL content not available] https://example.com/b",
        [stub],
    )
    assert result["similar"] == []
    assert result["is_duplicate"] is False


def test_find_similar_duplicate_skips_thin_new_bookmark(monkeypatch):
    thin = Bookmark(
        id="bookmark_aaaaaaaaaaaa",
        source="article",
        url="https://example.com/new",
        text="[URL content not available] https://example.com/new",
        title="Article from example.com",
    )
    monkeypatch.setattr(
        bw,
        "load_bookmarks",
        lambda: [
            Bookmark(
                id="bookmark_bbbbbbbbbbbb",
                source="article",
                url="https://example.com/old",
                text="[URL content not available] https://example.com/old",
                title="Article from example.com",
            )
        ],
    )
    match, message = bw.find_similar_duplicate(thin)
    assert match is None
    assert message is None


def test_good_scrape_still_saves(monkeypatch):
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b: (None, None))
    stored = {}

    def save_bookmarks(bookmarks):
        stored["bookmarks"] = list(bookmarks)

    monkeypatch.setattr(bw, "save_bookmarks", save_bookmarks)
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a: ([], []))
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    body = _rich_text()
    monkeypatch.setattr(
        "forger.scrapers.article_scraper.scrape_article",
        lambda url: {
            "success": True,
            "title": "Real Chemistry Paper",
            "text": body,
            "author": "Dr. X",
            "source": "requests+bs4",
            "error": None,
        },
    )

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://journals.example.edu/paper", analyze=False
    )
    assert ok, message
    assert bookmark is not None
    assert bookmark.title == "Real Chemistry Paper"
    assert len(bookmark.text) > MIN_USABLE_ARTICLE_TEXT_CHARS
    assert stored.get("bookmarks")
    assert analysis.analysis_source == "pending_agent"
