"""Regression: X pointer post → t.co → doi.org → ACS /acsodf/article/doi/... reader URL.

Real shape (TomManz3/status/2113362396710654301): oEmbed text carries only a
bare t.co; it 302s to doi.org/10.1021/acsomega.6c06602, which lands on
pubs.acs.org/acsodf/article/doi/10.1021/acsomega.6c06602/5455982/<slug>.
ACS 403s the HTML, and DOI extraction used to swallow "/5455982/<slug>" into
the DOI so Crossref 404'd and only the tweet text was saved.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from forger.scrapers import article_scraper, doi_metadata
from forger.scrapers.doi_metadata import extract_doi_from_url, is_acs_doi_url
from forger.scrapers.x_scraper import XScraper

FIXTURE = Path(__file__).parent / "fixtures" / "doi_metadata" / "acsomega_6c06602_crossref.json"
ACS_READER_URL = (
    "https://pubs.acs.org/acsodf/article/doi/10.1021/acsomega.6c06602/5455982/"
    "A-Study-of-Factors-Influencing-the-Selectivity-and"
)
OEMBED_TEXT = (
    "My most recently published research ...https://t.co/85GrHsIqCJ\n"
    "Fe,Cr promoted Raney nickel catalysts for nitrile hydrogenation#Chemtwitter "
    "#organicchemistry #catalysis #hetcat #catalysisscience #chem #chemistry "
    "#realtimechem #RaneyNickel #OrganicSynthesis #OrgChem #Catalyst pic.twitter.com/Fno7cvBy4q"
)


def test_acs_reader_path_doi_stops_at_suffix():
    assert is_acs_doi_url(ACS_READER_URL)
    assert extract_doi_from_url(ACS_READER_URL) == "10.1021/acsomega.6c06602"
    assert extract_doi_from_url("https://pubs.acs.org/doi/full/10.1021/jacs.6c12509/") == "10.1021/jacs.6c12509"


def test_pointer_post_saves_paper_via_crossref_when_acs_403s(monkeypatch):
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    seen = []

    def fake_get(url, headers=None, timeout=None):
        seen.append(url)
        if not url.endswith("/works/10.1021/acsomega.6c06602"):
            raise requests.exceptions.HTTPError("404 Client Error: Not Found")
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = payload
        return resp

    def raise_403(*a, **k):
        resp = MagicMock()
        resp.status_code = 403
        err = requests.exceptions.HTTPError("403 Client Error: Forbidden")
        err.response = resp
        raise err

    monkeypatch.setattr(doi_metadata.requests, "get", fake_get)
    monkeypatch.setattr(article_scraper, "_fetch_url", raise_403)

    result = {"success": True, "source": "oembed", "text": OEMBED_TEXT,
              "outbound_urls": ["https://t.co/85GrHsIqCJ"]}
    with patch("forger.scrapers.x_scraper.resolve_redirect_url", return_value=ACS_READER_URL):
        out = XScraper()._enrich_pointer_post(result)

    assert seen and seen[0].endswith("/works/10.1021/acsomega.6c06602")
    assert out["source"].endswith("+link")
    assert out["text"].startswith("My most recently published research")
    assert "Linked article: A Study of Factors Influencing the Selectivity" in out["text"]
    assert "DOI: 10.1021/acsomega.6c06602" in out["text"]
    assert "butyronitrile hydrogenation" in out["text"]


def _http_error(code):
    resp = MagicMock()
    resp.status_code = code
    err = requests.exceptions.HTTPError(f"{code} Client Error: Forbidden")
    err.response = resp
    return err


def test_403_to_browser_ua_retries_with_honest_ua(monkeypatch):
    """mirtitles.org shape: Chrome UA from requests → 403, ForgerBot UA → 200."""
    uas = []

    def fake_fetch(url, headers, timeout):
        uas.append(headers["User-Agent"])
        if "Chrome" in headers["User-Agent"]:
            raise _http_error(403)
        resp = MagicMock()
        resp.status_code = 200
        return resp

    monkeypatch.setattr(article_scraper, "_fetch_url", fake_fetch)
    r = article_scraper._fetch_url_with_ua_fallback(
        "https://mirtitles.org/x/", {"User-Agent": "Mozilla/5.0 Chrome/120"}, 5)
    assert r.status_code == 200
    assert "Chrome" in uas[0] and "ForgerBot" in uas[1]


def test_pointer_refusal_sets_clear_warning():
    url = "https://chemistry-europe.onlinelibrary.wiley.com/doi/toc/x"
    result = {"success": True, "source": "syndication",
              "text": "Explore the collection:\nhttps://t.co/TidTef1C6e"}
    with patch("forger.scrapers.x_scraper.resolve_redirect_url", return_value=url), \
            patch("forger.scrapers.article_scraper.scrape_article",
                  return_value={"success": False, "error": "HTTP error: 403 Client Error: Forbidden"}):
        out = XScraper()._enrich_pointer_post(result)
    assert out["text"] == result["text"]
    assert out["link_warning"] == f"Linked page refused (403: {url}); saved post text only"


def test_same_destination_scraped_once():
    """t.co and its expanded_url resolve to one page: fetch it once, not twice."""
    url = "https://chemistry-europe.onlinelibrary.wiley.com/doi/toc/x"
    result = {"success": True, "source": "syndication",
              "text": "Explore the collection:\nhttps://t.co/TidTef1C6e",
              "outbound_urls": [url]}
    with patch("forger.scrapers.x_scraper.resolve_redirect_url", return_value=url), \
            patch("forger.scrapers.article_scraper.scrape_article",
                  return_value={"success": False, "error": "HTTP error: 403"}) as sa:
        XScraper()._enrich_pointer_post(result)
    assert sa.call_count == 1
