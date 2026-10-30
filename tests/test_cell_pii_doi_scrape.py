"""Cell/ScienceDirect Elsevier PII → Crossref DOI scrape (mocked)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from forger.scrapers import article_scraper, doi_metadata
from forger.scrapers.doi_metadata import (
    extract_doi_from_url,
    extract_pii_from_url,
    is_elsevier_pii_url,
    scrape_doi_metadata,
)
from forger.scrapers.article_scraper import scrape_article

FIXTURES = Path(__file__).parent / "fixtures" / "doi_metadata"
CELL_URL = "https://www.cell.com/cell/fulltext/S0092-8674(25)00197-7"
CELL_DOI = "10.1016/j.cell.2025.02.012"
SD_URL = "https://www.sciencedirect.com/science/article/pii/S0092867425001977"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestElsevierPiiDetection:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (CELL_URL, True),
            (SD_URL, True),
            ("https://www.cell.com/neuron/fulltext/S0896-6273(24)00800-1", True),
            ("https://www.sciencedirect.com/science/article/pii/S0092-8674(25)00197-7", True),
            ("https://www.cell.com/", False),
            ("https://www.cell.com/cell/home", False),
            ("https://example.com/fulltext/S0092-8674(25)00197-7", False),
            ("https://doi.org/10.1016/j.cell.2025.02.012", False),
            ("", False),
        ],
    )
    def test_is_elsevier_pii_url(self, url, expected):
        assert is_elsevier_pii_url(url) is expected

    @pytest.mark.parametrize(
        "url,pii",
        [
            (CELL_URL, "S0092-8674(25)00197-7"),
            (SD_URL, "S0092867425001977"),
            ("https://www.cell.com/cell/home", None),
            ("https://example.com/pii/S0092867425001977", None),
            ("", None),
        ],
    )
    def test_extract_pii_from_url(self, url, pii):
        assert extract_pii_from_url(url) == pii

    def test_cell_url_has_no_inline_doi(self):
        assert extract_doi_from_url(CELL_URL) is None


def _mock_crossref_get(*, work: dict | None = None, search: dict | None = None, error=None):
    def fake_get(url, headers=None, timeout=None, params=None):
        if error is not None:
            raise error
        u = url or ""
        response = MagicMock()
        response.raise_for_status = MagicMock()
        if "api.crossref.org/works/" in u and not u.rstrip("/").endswith("/works"):
            # direct DOI lookup
            if work is None:
                raise requests.exceptions.HTTPError("404")
            response.json.return_value = work
            return response
        if u.rstrip("/").endswith("/works") or u.endswith("/works"):
            filt = (params or {}).get("filter") or ""
            assert filt.startswith("alternative-id:"), filt
            # No fuzzy query= param
            assert "query" not in (params or {})
            if search is None:
                raise requests.exceptions.HTTPError("404")
            response.json.return_value = search
            return response
        raise AssertionError(f"Unexpected URL: {url} params={params}")

    return fake_get


class TestScrapeCellPiiMetadata:
    def test_cell_pii_crossref_mocked(self, monkeypatch):
        search = _load("cell_pii_alternative_id_search.json")
        monkeypatch.setattr(
            doi_metadata.requests, "get", _mock_crossref_get(search=search)
        )

        result = scrape_doi_metadata(CELL_URL)

        assert result["success"] is True
        assert result["source"] == "crossref-doi-metadata"
        assert result["error"] is None
        assert "Simultaneous CRISPR" in result["title"]
        assert "Journal: Cell" in result["text"]
        assert CELL_DOI in result["text"]
        assert "Loϊc Binan" in (result["author"] or "") or "Binan" in (result["author"] or "")
        assert len(result["text"]) > 200

    def test_requires_exact_alternative_id_match(self, monkeypatch):
        search = _load("cell_pii_alternative_id_search.json")
        # Tamper: alternative-id does not match requested PII key
        search = json.loads(json.dumps(search))
        search["message"]["items"][0]["alternative-id"] = ["S9999999999999999"]
        monkeypatch.setattr(
            doi_metadata.requests, "get", _mock_crossref_get(search=search)
        )
        result = scrape_doi_metadata(CELL_URL)
        assert result["success"] is False
        assert "failed" in (result["error"] or "").lower()

    def test_crossref_failure(self, monkeypatch):
        monkeypatch.setattr(
            doi_metadata.requests,
            "get",
            _mock_crossref_get(error=requests.exceptions.HTTPError("404")),
        )
        result = scrape_doi_metadata(CELL_URL)
        assert result["success"] is False
        assert "failed" in (result["error"] or "").lower()


class TestArticleScraperCellHook:
    def test_scrape_article_uses_crossref_for_cell_pii(self, monkeypatch):
        search = _load("cell_pii_alternative_id_search.json")
        monkeypatch.setattr(
            doi_metadata.requests, "get", _mock_crossref_get(search=search)
        )

        html_called = {"fetch": False}

        def html_boom(*a, **k):
            html_called["fetch"] = True
            raise AssertionError("HTML scrape must not run when Crossref succeeds")

        monkeypatch.setattr(article_scraper, "_fetch_url", html_boom)

        result = scrape_article(CELL_URL)

        assert result["success"] is True
        assert result["source"] == "crossref-doi-metadata"
        assert "Simultaneous CRISPR" in result["title"]
        assert html_called["fetch"] is False

    def test_html_403_recovers_via_pii_crossref(self, monkeypatch):
        search = _load("cell_pii_alternative_id_search.json")
        monkeypatch.setattr(
            doi_metadata.requests, "get", _mock_crossref_get(search=search)
        )

        # Force non-proactive path: pretend is_elsevier_pii_url is False so HTML runs,
        # then 403 recovery still hits PII via _can_try_doi_metadata.
        # Actually proactive path will catch it first. Test 403 recovery by
        # making proactive Crossref fail then HTML 403... or use a URL that
        # extract_pii works but proactive already covers.
        # Mirror ACS: doi.org-style isn't applicable; instead fail proactive
        # then recover on 403 — but proactive uses same scrape_doi_metadata.
        # So test HTTPError recovery when proactive is skipped by monkeypatch.
        monkeypatch.setattr(article_scraper, "is_elsevier_pii_url", lambda u: False)
        monkeypatch.setattr(article_scraper, "is_acs_doi_url", lambda u: False)
        monkeypatch.setattr(article_scraper, "is_nature_article_url", lambda u: False)

        def raise_403(*a, **k):
            response = MagicMock()
            response.status_code = 403
            err = requests.exceptions.HTTPError("403 Client Error: Forbidden")
            err.response = response
            raise err

        monkeypatch.setattr(article_scraper, "_fetch_url", raise_403)

        result = scrape_article(CELL_URL)

        assert result["success"] is True
        assert result["source"] == "crossref-doi-metadata"
        assert CELL_DOI in result["text"]

    def test_nih_403_with_no_doi_still_refuses(self, monkeypatch):
        """NIH page with no DOI/PII must not invent Crossref recovery."""
        doi_called = {"get": False}

        def doi_boom(*a, **k):
            doi_called["get"] = True
            raise AssertionError("Crossref must not run for non-DOI/PII URLs")

        monkeypatch.setattr(doi_metadata.requests, "get", doi_boom)

        def raise_403(*a, **k):
            raise requests.exceptions.HTTPError("403 Client Error: Forbidden")

        monkeypatch.setattr(article_scraper, "_fetch_url", raise_403)

        result = scrape_article("https://www.ncbi.nlm.nih.gov/books/NBK123/")

        assert result["success"] is False
        assert "HTTP error" in (result["error"] or "")
        assert doi_called["get"] is False

    def test_allrecipes_403_with_no_doi_still_refuses(self, monkeypatch):
        doi_called = {"get": False}

        def doi_boom(*a, **k):
            doi_called["get"] = True
            raise AssertionError("Crossref must not run for non-DOI/PII URLs")

        monkeypatch.setattr(doi_metadata.requests, "get", doi_boom)

        def raise_403(*a, **k):
            raise requests.exceptions.HTTPError("403 Client Error: Forbidden")

        monkeypatch.setattr(article_scraper, "_fetch_url", raise_403)

        result = scrape_article("https://www.allrecipes.com/recipe/12345/something/")

        assert result["success"] is False
        assert "HTTP error" in (result["error"] or "")
        assert doi_called["get"] is False
