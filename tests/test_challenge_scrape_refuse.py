"""Bot-challenge / trash HTML must hard-refuse with SCRAPE_FAILED (no agent fill)."""
from pathlib import Path

import pytest

from forger import bookmark_workflow as bw
from forger.scrape_quality import (
    is_bot_challenge_content,
    is_bot_challenge_headers,
    is_bot_challenge_html,
    is_usable_scrape_text,
)
from forger.scrapers.article_scraper import scrape_article

FIXTURES = Path(__file__).parent / "fixtures" / "challenge"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_nature_client_challenge_html_detected():
    html = _read("nature_client_challenge.html")
    assert is_bot_challenge_html(html)
    assert is_bot_challenge_content(html=html)
    assert "Client Challenge" in html
    assert "/_fs-ch-" in html


def test_cloudflare_just_a_moment_html_detected():
    html = _read("cloudflare_just_a_moment.html")
    assert is_bot_challenge_html(html)
    assert is_bot_challenge_content(html=html)


def test_normal_article_html_not_challenge():
    html = _read("normal_article.html")
    assert not is_bot_challenge_html(html)
    assert not is_bot_challenge_content(html=html)
    assert is_usable_scrape_text(
        # Approximate extracted body length from the fixture article.
        "Topological superconductors host Majorana bound states. " * 8,
        source="article",
        title="Advances in topological superconductivity",
    )


def test_cf_jsd_script_on_real_article_is_not_challenge():
    """Passive CF JSD (/scripts/jsd/) on a real page must not trip refuse.

    Substack and other Cloudflare sites inject challenge-platform/scripts/jsd
    on HTTP 200 article HTML. That is not a bot wall — PR#22's bare
    cdn-cgi/challenge-platform marker caused a Substack regression.
    """
    html = _read("article_with_cf_jsd.html")
    assert "cdn-cgi/challenge-platform/scripts/jsd" in html
    assert not is_bot_challenge_html(html)
    assert not is_bot_challenge_content(html=html)


def test_scrape_article_saves_html_with_cf_jsd(monkeypatch):
    html = _read("article_with_cf_jsd.html")

    class Resp:
        content = html.encode("utf-8")
        encoding = "utf-8"
        headers = {"Content-Type": "text/html; charset=utf-8"}
        text = html
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "forger.scrapers.article_scraper._fetch_url",
        lambda url, headers, timeout: Resp(),
    )
    result = scrape_article("https://axial.substack.com/p/transannular-ch-functionalization")
    assert result["success"] is True
    assert "Transannular" in (result["title"] or "")
    assert result["text"] and len(result["text"]) > 200


def test_cf_mitigated_header_detected():
    assert is_bot_challenge_headers({"cf-mitigated": "challenge"})
    assert is_bot_challenge_headers({"CF-Mitigated": "challenge"})
    assert not is_bot_challenge_headers({"cf-mitigated": "something-else"})
    assert not is_bot_challenge_headers({})


def test_challenge_title_and_body_refuse_usable_text():
    challenge_body = (
        "JavaScript is disabled in your browser.\n"
        "Please enable JavaScript to proceed.\n"
        "A required part of this site couldn’t load. This may be due to a browser "
        "extension, network issues, or browser settings. Please check your "
        "connection, disable any ad blockers, or try using a different browser."
    )
    # This is the exact Nature extract shape: >200 chars, still trash.
    assert len(challenge_body) > 200
    assert is_bot_challenge_content(title="Client Challenge", text=challenge_body)
    assert not is_usable_scrape_text(
        challenge_body, source="article", title="Client Challenge"
    )


def test_scrape_article_refuses_nature_challenge_without_doi(monkeypatch):
    """Nature subject / non-article pages have no DOI — challenge still refuses."""
    html = _read("nature_client_challenge.html")

    class Resp:
        text = html
        headers = {}
        content = html.encode("utf-8")
        encoding = "utf-8"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "forger.scrapers.article_scraper._fetch_url",
        lambda url, headers, timeout: Resp(),
    )
    result = scrape_article("https://www.nature.com/subjects/catalysis")
    assert result["success"] is False
    assert "challenge" in (result["error"] or "").lower()
    assert result["title"] == "Client Challenge"


def test_scrape_article_nature_article_prefers_crossref_over_challenge(monkeypatch):
    """DOI-bearing Nature article URLs recover via Crossref (see test_nature_doi_scrape)."""
    import json
    from unittest.mock import MagicMock

    from forger.scrapers import doi_metadata

    payload = json.loads(
        (FIXTURES.parent / "doi_metadata" / "nature_with_abstract_crossref.json").read_text(
            encoding="utf-8"
        )
    )

    def fake_get(url, headers=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = payload
        return resp

    monkeypatch.setattr(doi_metadata, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(doi_metadata.requests, "get", fake_get)
    result = scrape_article("https://www.nature.com/articles/s41586-020-2649-2")
    assert result["success"] is True
    assert result["source"] == "crossref-doi-metadata"


def test_scrape_article_refuses_cloudflare_challenge(monkeypatch):
    html = _read("cloudflare_just_a_moment.html")

    class Resp:
        text = html
        headers = {"cf-mitigated": "challenge"}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "forger.scrapers.article_scraper._fetch_url",
        lambda url, headers, timeout: Resp(),
    )
    result = scrape_article("https://example.com/paywalled")
    assert result["success"] is False
    assert "challenge" in (result["error"] or "").lower()


def test_scrape_article_accepts_normal_page(monkeypatch):
    html = _read("normal_article.html")

    class Resp:
        text = html
        headers = {}

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "forger.scrapers.article_scraper._fetch_url",
        lambda url, headers, timeout: Resp(),
    )
    result = scrape_article("https://journals.example.edu/topo")
    assert result["success"] is True
    assert "topological" in (result["title"] or "").lower()
    assert len(result["text"] or "") > 200
    assert result["error"] is None


def _stub_workflow_io(monkeypatch, saved):
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    monkeypatch.setattr(bw, "find_similar_duplicate", lambda b, exclude_ids=None: (None, None))
    monkeypatch.setattr(
        bw, "save_bookmarks", lambda bookmarks: saved.__setitem__("bookmarks", list(bookmarks))
    )
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "_verify_ingestion_invariants", lambda *a: ([], []))
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)


@pytest.mark.parametrize("analyze", [True, False], ids=["api_mode", "agent_mode"])
def test_process_bookmark_refuses_challenge_no_save_no_pending(monkeypatch, analyze):
    """Hard refuse: no bookmark, no pending_agent stub for the agent to fill."""
    saved = {"bookmarks": None}
    _stub_workflow_io(monkeypatch, saved)

    def fake_scrape(url):
        return {
            "success": False,
            "title": "Client Challenge",
            "text": None,
            "author": None,
            "source": None,
            "error": "Bot challenge / anti-bot interstitial (challenge HTML markers)",
        }

    monkeypatch.setattr(
        "forger.scrapers.article_scraper.scrape_article",
        fake_scrape,
    )
    # Avoid real LLM if analyze=True somehow got past scrape refusal.
    monkeypatch.setattr(
        bw,
        "analyze_bookmark",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not analyze")),
    )

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://www.nature.com/articles/s41567-026-03465-3",
        analyze=analyze,
    )
    assert not ok
    assert "SCRAPE_FAILED" in message
    assert bookmark is None
    assert analysis is None
    assert saved["bookmarks"] is None


def test_lying_success_challenge_body_still_refused(monkeypatch):
    """Defense in depth: success=True with challenge title/body still refuses."""
    saved = {"called": False}
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    monkeypatch.setattr(
        bw, "save_bookmarks", lambda bookmarks: saved.__setitem__("called", True)
    )
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "git_auto_push", lambda title: False)

    challenge_body = (
        "JavaScript is disabled in your browser.\n"
        "Please enable JavaScript to proceed.\n" + ("x" * 220)
    )
    monkeypatch.setattr(
        "forger.scrapers.article_scraper.scrape_article",
        lambda url: {
            "success": True,
            "title": "Client Challenge",
            "text": challenge_body,
            "author": None,
            "source": "requests+bs4",
            "error": None,
        },
    )

    ok, message, bookmark, analysis = bw.process_bookmark_url(
        "https://www.nature.com/articles/s41567-026-03465-3",
        analyze=False,
    )
    assert not ok
    assert "SCRAPE_FAILED" in message
    assert bookmark is None
    assert analysis is None
    assert saved["called"] is False
