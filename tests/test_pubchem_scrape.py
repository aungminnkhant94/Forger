"""PubChem compound scrape via PUG REST (mocked API fixtures)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from forger.scrape_result import Refused, Saved
from forger.scrapers import article_scraper, pubchem
from forger.scrapers.pubchem import (
    is_pubchem_compound_url,
    parse_pubchem_compound_ref,
    scrape_pubchem_compound,
)
from forger.scrapers.article_scraper import scrape_article

FIXTURES = Path(__file__).parent / "fixtures" / "pubchem"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestPubChemUrlDetection:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://pubchem.ncbi.nlm.nih.gov/compound/2519", True),
            ("https://pubchem.ncbi.nlm.nih.gov/compound/Caffeine", True),
            ("https://pubchem.ncbi.nlm.nih.gov/compound/caffeine/", True),
            ("https://pubchem.ncbi.nlm.nih.gov/compound/2519?foo=1", True),
            ("http://pubchem.ncbi.nlm.nih.gov/compound/2244", True),
            ("https://pubchem.ncbi.nlm.nih.gov/assay/1", False),
            ("https://pubchem.ncbi.nlm.nih.gov/", False),
            ("https://example.com/compound/2519", False),
            ("https://www.ncbi.nlm.nih.gov/compound/2519", False),
            ("", False),
        ],
    )
    def test_is_pubchem_compound_url(self, url, expected):
        assert is_pubchem_compound_url(url) is expected

    def test_parse_cid(self):
        assert parse_pubchem_compound_ref(
            "https://pubchem.ncbi.nlm.nih.gov/compound/2519"
        ) == ("cid", "2519")

    def test_parse_name(self):
        assert parse_pubchem_compound_ref(
            "https://pubchem.ncbi.nlm.nih.gov/compound/Caffeine"
        ) == ("name", "Caffeine")

    def test_parse_urlencoded_name(self):
        assert parse_pubchem_compound_ref(
            "https://pubchem.ncbi.nlm.nih.gov/compound/sodium%20chloride"
        ) == ("name", "sodium chloride")


def _mock_get_factory(props: dict | None, desc: dict | Exception | None):
    """Return a requests.get stand-in that answers property/description URLs."""

    def fake_get(url, headers=None, timeout=None):
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "/property/" in url:
            if props is None:
                raise requests.exceptions.HTTPError("404")
            response.json.return_value = props
            return response
        if "/description/" in url:
            if isinstance(desc, Exception):
                raise desc
            if desc is None:
                raise requests.exceptions.HTTPError("404")
            response.json.return_value = desc
            return response
        raise AssertionError(f"Unexpected PubChem URL: {url}")

    return fake_get


class TestScrapePubChemCompound:
    def test_caffeine_by_cid_mocked(self, monkeypatch):
        props = _load("caffeine_properties.json")
        desc = _load("caffeine_description.json")
        monkeypatch.setattr(pubchem.requests, "get", _mock_get_factory(props, desc))

        result = scrape_pubchem_compound(
            "https://pubchem.ncbi.nlm.nih.gov/compound/2519"
        )

        assert isinstance(result, Saved)
        assert result.via == "pubchem-pug-rest"
        assert result.author == "PubChem"
        assert "Caffeine" in result.title
        assert "2519" in result.title
        assert "C8H10N4O2" in result.text
        assert "trimethylxanthine" in result.text
        assert "ChEBI" in result.text
        assert len(result.text) > 200

    def test_caffeine_by_name_mocked(self, monkeypatch):
        props = _load("caffeine_properties.json")
        desc = _load("caffeine_description.json")
        monkeypatch.setattr(pubchem.requests, "get", _mock_get_factory(props, desc))

        result = scrape_pubchem_compound(
            "https://pubchem.ncbi.nlm.nih.gov/compound/Caffeine"
        )

        assert isinstance(result, Saved)
        assert "Caffeine" in result.title
        assert "Molecular Formula: C8H10N4O2" in result.text

    def test_properties_without_description_still_ok(self, monkeypatch):
        props = _load("caffeine_properties.json")
        monkeypatch.setattr(
            pubchem.requests,
            "get",
            _mock_get_factory(props, requests.exceptions.HTTPError("404")),
        )

        result = scrape_pubchem_compound(
            "https://pubchem.ncbi.nlm.nih.gov/compound/2519"
        )

        # Property block alone should clear the >200 char bar for caffeine.
        assert isinstance(result, Saved)
        assert "C8H10N4O2" in result.text
        assert "Description:" not in result.text

    def test_api_failure_returns_error(self, monkeypatch):
        monkeypatch.setattr(
            pubchem.requests,
            "get",
            _mock_get_factory(None, None),
        )

        result = scrape_pubchem_compound(
            "https://pubchem.ncbi.nlm.nih.gov/compound/999999999"
        )

        assert isinstance(result, Refused)
        assert "failed" in (result.detail or "").lower()

    def test_unsafe_url_blocked(self, monkeypatch):
        called = {"get": False}

        def boom(*a, **k):
            called["get"] = True
            raise AssertionError("must not fetch")

        monkeypatch.setattr(pubchem.requests, "get", boom)
        # Not a pubchem host — parse fails before fetch; also covers safety on
        # scrape_pubchem_compound entry for blocked hosts when forced.
        result = scrape_pubchem_compound("http://127.0.0.1/compound/1")
        assert isinstance(result, Refused)
        assert "Unsafe URL" in (result.detail or "")
        assert called["get"] is False


class TestArticleScraperPubChemHook:
    def test_scrape_article_uses_pubchem_path(self, monkeypatch):
        props = _load("caffeine_properties.json")
        desc = _load("caffeine_description.json")
        monkeypatch.setattr(pubchem.requests, "get", _mock_get_factory(props, desc))

        html_called = {"fetch": False}

        def html_boom(*a, **k):
            html_called["fetch"] = True
            raise AssertionError("HTML scrape must not run when PubChem succeeds")

        # Patch the HTML helper, not requests.get (shared with pubchem module).
        monkeypatch.setattr(article_scraper, "_fetch_url", html_boom)

        result = scrape_article("https://pubchem.ncbi.nlm.nih.gov/compound/Caffeine")

        assert result["success"] is True
        assert result["source"] == "pubchem-pug-rest"
        assert "Caffeine" in result["title"]
        assert html_called["fetch"] is False

    def test_scrape_article_falls_back_to_html_when_api_fails(self, monkeypatch):
        def api_fail(*a, **k):
            raise requests.exceptions.HTTPError("404")

        monkeypatch.setattr(pubchem.requests, "get", api_fail)

        mock_response = MagicMock()
        mock_response.text = """
        <html>
            <head><title>Fallback Article Title</title></head>
            <body>
                <article>
                    <p>This is a paragraph with enough content to pass validation for non-pubchem HTML fallback path testing here.</p>
                    <p>This is another paragraph with more content so the extracted text exceeds two hundred characters easily.</p>
                </article>
            </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()

        # _fetch_url is what HTML scraping uses; keep it separate from pubchem.requests.get
        monkeypatch.setattr(article_scraper, "_fetch_url", lambda *a, **k: mock_response)

        result = scrape_article("https://pubchem.ncbi.nlm.nih.gov/compound/Caffeine")

        assert result["success"] is True
        assert result["source"] == "requests+bs4"
        assert result["title"] == "Fallback Article Title"

    def test_non_pubchem_unchanged(self, monkeypatch):
        """Ordinary HTML sites still use requests+bs4 only."""
        pubchem_called = {"get": False}

        def pubchem_boom(*a, **k):
            pubchem_called["get"] = True
            raise AssertionError("PubChem API must not run for non-PubChem URLs")

        monkeypatch.setattr(pubchem.requests, "get", pubchem_boom)

        mock_response = MagicMock()
        mock_response.text = """
        <html>
            <head><title>Plain Blog Post</title></head>
            <body>
                <article>
                    <p>This is a paragraph with enough content to pass validation on a normal HTML site that is not PubChem at all.</p>
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
        assert pubchem_called["get"] is False
