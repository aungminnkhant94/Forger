"""ACS/JACS DOI scrape via Crossref metadata (mocked 403 + fixtures)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from forger.scrapers import article_scraper, doi_metadata
from forger.scrapers.doi_metadata import (
    extract_doi_from_url,
    is_acs_doi_url,
    scrape_doi_metadata,
)
from forger.scrapers.article_scraper import scrape_article

FIXTURES = Path(__file__).parent / "fixtures" / "doi_metadata"
JACS_URL = "https://pubs.acs.org/doi/10.1021/jacs.6c12509"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestAcsDoiUrlDetection:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (JACS_URL, True),
            ("https://pubs.acs.org/doi/abs/10.1021/jacs.6c12509", True),
            ("https://pubs.acs.org/doi/full/10.1021/jacs.6c12509", True),
            ("https://pubs.acs.org/doi/pdf/10.1021/jacs.6c12509", True),
            ("https://www.pubs.acs.org/doi/10.1021/jacs.6c12509", True),
            ("https://pubs.acs.org/", False),
            ("https://pubs.acs.org/journal/jacsat", False),
            ("https://doi.org/10.1021/jacs.6c12509", False),
            ("https://example.com/doi/10.1021/jacs.6c12509", False),
            ("", False),
        ],
    )
    def test_is_acs_doi_url(self, url, expected):
        assert is_acs_doi_url(url) is expected

    @pytest.mark.parametrize(
        "url,doi",
        [
            (JACS_URL, "10.1021/jacs.6c12509"),
            ("https://pubs.acs.org/doi/abs/10.1021/jacs.6c12509", "10.1021/jacs.6c12509"),
            ("https://pubs.acs.org/doi/full/10.1021/jacs.6c12509/", "10.1021/jacs.6c12509"),
            ("https://doi.org/10.1021/jacs.6c12509", "10.1021/jacs.6c12509"),
            ("https://dx.doi.org/10.1021/jacs.6c12509", "10.1021/jacs.6c12509"),
            ("https://example.com/paper", None),
            ("", None),
        ],
    )
    def test_extract_doi_from_url(self, url, doi):
        assert extract_doi_from_url(url) == doi


def _mock_crossref_get(payload: dict | None | Exception):
    def fake_get(url, headers=None, timeout=None):
        if "api.crossref.org/works/" not in url:
            raise AssertionError(f"Unexpected URL: {url}")
        if isinstance(payload, Exception):
            raise payload
        if payload is None:
            raise requests.exceptions.HTTPError("404")
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = payload
        return response

    return fake_get


class TestScrapeDoiMetadata:
    def test_jacs_crossref_mocked(self, monkeypatch):
        fixture = _load("jacs_6c12509_crossref.json")
        monkeypatch.setattr(doi_metadata.requests, "get", _mock_crossref_get(fixture))

        result = scrape_doi_metadata(JACS_URL)

        assert result["success"] is True
        assert result["source"] == "crossref-doi-metadata"
        assert result["error"] is None
        assert "Alkyl-to-Alkyl" in result["title"]
        assert "Journal of the American Chemical Society" in result["title"]
        assert "Palladium-catalyzed" in result["text"]
        assert "10.1021/jacs.6c12509" in result["text"]
        assert "Yangjin Kuang" in (result["author"] or "")
        assert len(result["text"]) > 200
        # JATS tags stripped
        assert "<jats:" not in result["text"]

    def test_crossref_failure(self, monkeypatch):
        monkeypatch.setattr(
            doi_metadata.requests,
            "get",
            _mock_crossref_get(requests.exceptions.HTTPError("404")),
        )
        result = scrape_doi_metadata(JACS_URL)
        assert result["success"] is False
        assert "failed" in (result["error"] or "").lower()

    def test_no_doi_in_url(self, monkeypatch):
        called = {"get": False}

        def boom(*a, **k):
            called["get"] = True
            raise AssertionError("must not fetch")

        monkeypatch.setattr(doi_metadata.requests, "get", boom)
        result = scrape_doi_metadata("https://pubs.acs.org/journal/jacsat")
        assert result["success"] is False
        assert "No DOI" in (result["error"] or "")
        assert called["get"] is False

    def test_unsafe_url_blocked(self, monkeypatch):
        called = {"get": False}

        def boom(*a, **k):
            called["get"] = True
            raise AssertionError("must not fetch")

        monkeypatch.setattr(doi_metadata.requests, "get", boom)
        result = scrape_doi_metadata("http://127.0.0.1/doi/10.1021/jacs.6c12509")
        assert result["success"] is False
        assert "Unsafe URL" in (result["error"] or "")
        assert called["get"] is False

    def test_crossref_api_url_is_safety_checked(self, monkeypatch):
        """Outbound Crossref URL must pass assert_safe_fetch_url."""
        seen = []

        real_assert = doi_metadata.assert_safe_fetch_url

        def tracking_assert(url):
            seen.append(url)
            return real_assert(url)

        monkeypatch.setattr(doi_metadata, "assert_safe_fetch_url", tracking_assert)
        fixture = _load("jacs_6c12509_crossref.json")
        monkeypatch.setattr(doi_metadata.requests, "get", _mock_crossref_get(fixture))

        result = scrape_doi_metadata(JACS_URL)
        assert result["success"] is True
        assert any("api.crossref.org/works/10.1021/jacs.6c12509" in u for u in seen)


class TestArticleScraperAcsHook:
    def test_scrape_article_uses_crossref_for_acs(self, monkeypatch):
        fixture = _load("jacs_6c12509_crossref.json")
        monkeypatch.setattr(doi_metadata.requests, "get", _mock_crossref_get(fixture))

        html_called = {"fetch": False}

        def html_boom(*a, **k):
            html_called["fetch"] = True
            raise AssertionError("HTML scrape must not run when Crossref succeeds")

        monkeypatch.setattr(article_scraper, "_fetch_url", html_boom)

        result = scrape_article(JACS_URL)

        assert result["success"] is True
        assert result["source"] == "crossref-doi-metadata"
        assert "Alkyl-to-Alkyl" in result["title"]
        assert "Palladium-catalyzed" in result["text"]
        assert html_called["fetch"] is False

    def test_html_403_recovers_via_crossref_for_doi_url(self, monkeypatch):
        """Non-ACS DOI URL that 403s still recovers via Crossref fallback."""
        fixture = _load("jacs_6c12509_crossref.json")
        monkeypatch.setattr(doi_metadata.requests, "get", _mock_crossref_get(fixture))

        def raise_403(*a, **k):
            response = MagicMock()
            response.status_code = 403
            err = requests.exceptions.HTTPError("403 Client Error: Forbidden")
            err.response = response
            raise err

        monkeypatch.setattr(article_scraper, "_fetch_url", raise_403)

        # doi.org is not ACS-first path, so HTML runs then HTTPError → Crossref
        result = scrape_article("https://doi.org/10.1021/jacs.6c12509")

        assert result["success"] is True
        assert result["source"] == "crossref-doi-metadata"
        assert "Alkyl-to-Alkyl" in result["title"]

    def test_acs_falls_back_to_html_when_crossref_fails(self, monkeypatch):
        monkeypatch.setattr(
            doi_metadata.requests,
            "get",
            _mock_crossref_get(requests.exceptions.HTTPError("404")),
        )

        mock_response = MagicMock()
        mock_response.text = """
        <html>
            <head><title>Fallback Chemistry Article Title</title></head>
            <body>
                <article>
                    <p>This is a paragraph with enough content to pass validation for ACS HTML fallback path testing when Crossref is down.</p>
                    <p>This is another paragraph with more content so the extracted text exceeds two hundred characters easily here.</p>
                </article>
            </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()
        monkeypatch.setattr(article_scraper, "_fetch_url", lambda *a, **k: mock_response)

        result = scrape_article(JACS_URL)

        assert result["success"] is True
        assert result["source"] == "requests+bs4"
        assert result["title"] == "Fallback Chemistry Article Title"

    def test_non_doi_unchanged(self, monkeypatch):
        doi_called = {"get": False}

        def doi_boom(*a, **k):
            doi_called["get"] = True
            raise AssertionError("Crossref must not run for non-DOI URLs")

        monkeypatch.setattr(doi_metadata.requests, "get", doi_boom)

        mock_response = MagicMock()
        mock_response.text = """
        <html>
            <head><title>Plain Blog Post</title></head>
            <body>
                <article>
                    <p>This is a paragraph with enough content to pass validation on a normal HTML site that is not a DOI publisher page.</p>
                    <p>This is another paragraph with more content so the extracted text exceeds two hundred characters easily.</p>
                </article>
            </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()
        monkeypatch.setattr(article_scraper, "_fetch_url", lambda *a, **k: mock_response)

        result = scrape_article("https://example.com/blog/post")

        assert result["success"] is True
        assert result["source"] == "requests+bs4"
        assert result["title"] == "Plain Blog Post"
        assert doi_called["get"] is False

    def test_acs_crossref_fail_and_html_403_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            doi_metadata.requests,
            "get",
            _mock_crossref_get(requests.exceptions.HTTPError("404")),
        )

        def raise_403(*a, **k):
            raise requests.exceptions.HTTPError("403 Client Error: Forbidden")

        monkeypatch.setattr(article_scraper, "_fetch_url", raise_403)

        result = scrape_article(JACS_URL)

        assert result["success"] is False
        assert "HTTP error" in (result["error"] or "")
