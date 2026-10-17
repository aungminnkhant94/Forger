"""Nature article Client Challenge → Crossref DOI metadata recovery."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

from forger.scrape_result import RefuseReason, Saved, scrape_url
from forger.scrapers import article_scraper, doi_metadata
from forger.scrapers.doi_metadata import (
    extract_doi_from_url,
    is_nature_article_url,
    scrape_doi_metadata,
)

FIX = Path(__file__).parent / "fixtures"
CHALLENGE = FIX / "challenge"
DOI_FIX = FIX / "doi_metadata"


def test_nature_article_doi_extraction():
    url = "https://www.nature.com/articles/s41567-026-03465-3"
    assert is_nature_article_url(url)
    assert extract_doi_from_url(url) == "10.1038/s41567-026-03465-3"
    assert extract_doi_from_url("https://www.nature.com/subjects/catalysis") is None
    assert not is_nature_article_url("https://www.nature.com/subjects/catalysis")


def test_nature_crossref_without_abstract_is_refused(monkeypatch):
    payload = json.loads(
        (DOI_FIX / "nature_s41567_026_03465_3_crossref.json").read_text(encoding="utf-8")
    )

    def fake_get(url, headers=None, timeout=None):
        assert "10.1038/s41567-026-03465-3" in url
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = payload
        return resp

    monkeypatch.setattr(doi_metadata, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(doi_metadata.requests, "get", fake_get)
    out = scrape_doi_metadata("https://www.nature.com/articles/s41567-026-03465-3")
    assert out["success"] is False
    assert "no abstract" in out["error"].lower()


def _crossref_then_challenge(monkeypatch, fixture):
    html = (CHALLENGE / "nature_client_challenge.html").read_text(encoding="utf-8")
    payload = json.loads((DOI_FIX / fixture).read_text(encoding="utf-8"))

    class Resp:
        content = html.encode("utf-8")
        encoding = "utf-8"
        headers = {"Content-Type": "text/html"}
        text = html
        status_code = 200

        def raise_for_status(self):
            return None

    def fake_get(url, headers=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.json.return_value = payload
        return resp

    monkeypatch.setattr(doi_metadata, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(article_scraper, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(doi_metadata.requests, "get", fake_get)
    monkeypatch.setattr(article_scraper, "_fetch_url", lambda *a, **k: Resp())


def test_nature_article_with_abstract_saves(monkeypatch):
    _crossref_then_challenge(monkeypatch, "nature_with_abstract_crossref.json")
    out = scrape_url("https://www.nature.com/articles/s41586-020-2649-2")
    assert isinstance(out, Saved)
    assert out.via == "crossref-doi-metadata"
    assert "abstract unavailable" not in out.text


def test_nature_article_title_only_is_refused_not_saved(monkeypatch):
    _crossref_then_challenge(monkeypatch, "nature_s41567_026_03465_3_crossref.json")
    out = scrape_url("https://www.nature.com/articles/s41567-026-03465-3")
    assert not isinstance(out, Saved)
    assert out.reason == RefuseReason.CHALLENGE


def test_title_only_nature_hits_scrape_failed_no_bookmark(monkeypatch):
    import forger.bookmark_workflow as bw

    _crossref_then_challenge(monkeypatch, "nature_s41567_026_03465_3_crossref.json")
    monkeypatch.setattr(bw, "check_duplicate", lambda url: None)
    ok, msg, bookmark, analysis = bw.process_bookmark_url(
        "https://www.nature.com/articles/s41567-026-03465-3", analyze=True
    )
    assert ok is False and bookmark is None and analysis is None
    assert msg.startswith("SCRAPE_FAILED")


def test_nature_subject_page_still_refuses_challenge(monkeypatch):
    html = (CHALLENGE / "nature_client_challenge.html").read_text(encoding="utf-8")

    class Resp:
        content = html.encode("utf-8")
        encoding = "utf-8"
        headers = {"Content-Type": "text/html"}
        text = html
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(article_scraper, "assert_safe_fetch_url", lambda u: u)
    monkeypatch.setattr(article_scraper, "_fetch_url", lambda *a, **k: Resp())
    out = scrape_url("https://www.nature.com/subjects/catalysis")
    assert not isinstance(out, Saved)
    assert out.reason == RefuseReason.CHALLENGE
