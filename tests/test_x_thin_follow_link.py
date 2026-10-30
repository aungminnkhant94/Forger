"""Thin X/Twitter posts (bare t.co / X Articles) get title+text enrichment."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from forger.scrape_quality import is_link_only_text, is_usable_scrape_text
from forger.scrapers.x_scraper import (
    XScraper,
    _text_from_x_article,
    _urls_from_text,
    is_thin_x_result,
)
from forger.url_safety import UnsafeURLError, resolve_redirect_url

FIXTURES = Path(__file__).parent / "fixtures" / "x_scrape"

GREG_URL = "https://x.com/gregisenberg/status/2101760050108797268"
KEL_URL = "https://x.com/kelxyz_/status/2057865155845796069"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestLinkOnlyQuality:
    def test_bare_tco_not_usable(self):
        body = "https://t.co/wfHAsNRGZT"
        assert is_link_only_text(body)
        assert not is_usable_scrape_text(body, source="x")

    def test_short_prose_tweet_still_usable(self):
        assert is_usable_scrape_text("short tweet ok", source="x")
        assert not is_link_only_text("short tweet ok")


class TestArticlePayload:
    def test_preview_from_syndication_fixture(self):
        payload = _load("syndication_greg_thin.json")
        title, text, kind = _text_from_x_article(payload["article"])
        assert title and "AI-native" in title
        assert text and "AI-native services are here" in text
        assert kind == "preview"

    def test_full_from_fxtwitter_fixture(self):
        payload = _load("fxtwitter_greg_article.json")
        title, text, kind = _text_from_x_article(payload["tweet"]["article"])
        assert title and "AI-native" in title
        assert kind == "full"
        assert text and len(text) > 200
        assert "QuickBooks" in text or "AI-native" in text


class TestSyndicationEnrich:
    def test_syndication_merges_article_preview(self):
        scraper = XScraper()
        payload = _load("syndication_greg_thin.json")
        with patch.object(scraper, "_http_get_json", return_value=payload):
            result = scraper._fetch_with_syndication("2101760050108797268", "gregisenberg")
        assert result["success"] is True
        assert result["title"] != "X Post"
        assert "AI-native" in result["title"]
        assert not is_thin_x_result(result)
        assert result.get("article_enrichment") == "preview"
        assert result.get("outbound_urls")

    def test_fxtwitter_merges_full_article(self):
        scraper = XScraper()
        payload = _load("fxtwitter_greg_article.json")
        with patch.object(scraper, "_http_get_json", return_value=payload):
            result = scraper._fetch_with_fxtwitter("2101760050108797268", "gregisenberg")
        assert result["success"] is True
        assert result["article_enrichment"] == "full"
        assert len(result["text"]) > 200
        assert "x_article" in result["source"]


class TestPublicApiChainPrefersFullArticle:
    def test_continues_past_preview_to_fxtwitter(self):
        scraper = XScraper()
        synd = _load("syndication_greg_thin.json")
        fx = _load("fxtwitter_greg_article.json")

        def fake_json(api_url: str):
            if "syndication" in api_url or "tweet-result" in api_url:
                return synd
            if "fxtwitter" in api_url:
                return fx
            if "publish.twitter.com" in api_url:
                return None
            return None

        with patch.object(scraper, "_http_get_json", side_effect=fake_json):
            result = scraper._fetch_with_public_apis(GREG_URL)
        assert result["success"] is True
        assert result["title"] != "X Post"
        assert "AI-native" in (result.get("title") or "")
        # Full article body from fxtwitter, not the short preview alone.
        assert len(result["text"]) > 400
        assert "fxtwitter" in (result.get("source") or "")


class TestOutboundLinkEnrich:
    def test_follow_external_link_merges_article_scrape(self):
        scraper = XScraper()
        thin = {
            "success": True,
            "text": "https://t.co/abcdefghij",
            "author": "someone",
            "title": "X Post",
            "error": None,
            "source": "syndication",
            "outbound_urls": ["https://t.co/abcdefghij"],
        }
        scraped = {
            "success": True,
            "title": "Real Blog Post Title About Something",
            "text": "A" * 250,
            "author": None,
            "source": "requests+bs4",
            "error": None,
        }
        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            return_value="https://example.com/real-post",
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value=scraped,
        ):
            out = scraper._enrich_thin_via_outbound_links(thin)
        assert out["success"] is True
        assert out["title"] == "Real Blog Post Title About Something"
        assert len(out["text"]) >= 200
        assert "+link" in out["source"]
        assert out.get("outbound_resolved") == "https://example.com/real-post"

    def test_skips_x_status_loop(self):
        scraper = XScraper()
        thin = {
            "success": True,
            "text": "https://t.co/abcdefghij",
            "author": "someone",
            "title": "X Post",
            "error": None,
            "source": "syndication",
            "outbound_urls": ["https://t.co/abcdefghij"],
        }
        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            return_value="https://x.com/other/status/1234567890",
        ), patch(
            "forger.scrapers.article_scraper.scrape_article"
        ) as scrape:
            out = scraper._enrich_thin_via_outbound_links(thin)
        scrape.assert_not_called()
        assert is_thin_x_result(out)

    def test_refuse_thin_when_enrich_fails(self):
        scraper = XScraper()
        thin = {
            "success": True,
            "text": "https://t.co/abcdefghij",
            "author": "someone",
            "title": "X Post",
            "error": None,
            "source": "syndication",
            "outbound_urls": ["https://t.co/abcdefghij"],
        }
        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            return_value="https://example.com/gone",
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value={"success": False, "error": "404", "text": None, "title": None},
        ):
            enriched = scraper._enrich_thin_via_outbound_links(thin)
            refused = scraper._refuse_if_thin(enriched)
        assert refused["success"] is False
        assert "Thin link-only" in (refused.get("error") or "")


class TestResolveRedirectSafety:
    def test_blocks_localhost(self):
        with pytest.raises(UnsafeURLError):
            resolve_redirect_url("http://127.0.0.1/secret")

    def test_blocks_redirect_to_private(self):
        import io
        import urllib.error
        import urllib.request

        class FakeHeaders(dict):
            def get_all(self, name, default=None):
                v = self.get(name)
                if v is None:
                    return default or []
                return [v]

        class BoomOpener:
            def open(self, req, timeout=None):
                raise urllib.error.HTTPError(
                    "https://example.com/r",
                    302,
                    "Found",
                    FakeHeaders({"Location": "http://169.254.169.254/latest"}),
                    io.BytesIO(b""),
                )

        with patch("urllib.request.build_opener", return_value=BoomOpener()):
            with pytest.raises(UnsafeURLError):
                resolve_redirect_url("https://example.com/r")


class TestLiveThinEnrichment:
    """Live hits — skip on network flake."""

    @pytest.mark.parametrize("url", [GREG_URL, KEL_URL])
    def test_live_thin_gets_real_title(self, url):
        scraper = XScraper()
        try:
            result = scraper._fetch_with_public_apis(url)
        except Exception as exc:  # pragma: no cover
            pytest.skip(f"network unavailable: {exc}")
        if not result.get("success"):
            pytest.skip(f"public APIs unavailable: {result.get('error')}")
        assert result["title"] != "X Post"
        assert len((result.get("text") or "").strip()) > 50
        assert is_usable_scrape_text(result["text"], source="x")


class TestDlvrItZwspEnrich:
    """Bare dlvr.it with ZWSP + t.co self-loop → enrich via Cell PII scrape."""

    def test_urls_from_text_strips_zwsp_and_allows_bare_shortener(self):
        text = "New paper dlvr.​it/AbCdEf https://t.co/abcdefghij"
        urls = _urls_from_text(text)
        assert "https://dlvr.it/AbCdEf" in urls
        assert "https://t.co/abcdefghij" in urls

    def test_bare_arbitrary_host_not_followed(self):
        assert _urls_from_text("see evil.example/nope now") == []
        assert _urls_from_text("see example.com/x") == []

    def test_dlvr_zwsp_tco_loop_enriches_via_cell_pii(self):
        scraper = XScraper()
        # Thin link-only stub (~short); ZWSP splits dlvr.it until stripped.
        body = "dlvr.​it/AbCdEf https://t.co/abcdefghij"
        assert is_thin_x_result(
            {
                "success": True,
                "text": body,
                "title": "X Post",
                "outbound_urls": ["https://t.co/abcdefghij"],
            }
        )
        thin = {
            "success": True,
            "text": body,
            "author": "someone",
            "title": "X Post",
            "error": None,
            "source": "syndication",
            "outbound_urls": ["https://t.co/abcdefghij"],
        }
        enriched_body = (
            "Journal: Cell\n"
            "Publisher: Elsevier BV\n"
            "DOI: 10.1016/j.cell.2025.02.012\n"
            "Authors: Loic Binan et al.\n\n"
            + ("Simultaneous CRISPR screening and spatial transcriptomics. " * 8)
        )
        scraped = {
            "success": True,
            "title": (
                "Simultaneous CRISPR screening and spatial transcriptomics "
                "reveal intracellular circuits (Cell)"
            ),
            "text": enriched_body,
            "author": "Loic Binan",
            "source": "crossref-doi-metadata",
            "error": None,
        }

        def fake_resolve(url: str) -> str:
            if "t.co" in url:
                return "https://x.com/someone/status/1234567890123456789"
            if "dlvr.it" in url:
                return (
                    "https://www.cell.com/cell/fulltext/S0092-8674(25)00197-7"
                )
            return url

        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            side_effect=fake_resolve,
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value=scraped,
        ) as scrape:
            out = scraper._enrich_thin_via_outbound_links(thin)

        scrape.assert_called()
        called_url = scrape.call_args[0][0]
        assert "cell.com" in called_url or "S0092-8674" in called_url
        assert out["success"] is True
        assert len(out["text"]) > 143
        assert "10.1016/j.cell.2025.02.012" in out["text"]
        assert not is_thin_x_result(out)
