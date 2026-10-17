"""Replay every past scrape-bug fixture through the real save boundary.

Each row drives real scraper code with HTTP faked from tests/fixtures and
asserts what ``scrape_and_create_bookmark`` does: save (with a clean title and
the expected content) or refuse with a reason. A scraper change that brings
back an old bug fails the row named after the PR that fixed it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from unittest.mock import MagicMock

import pytest
import requests

import forger.bookmark_workflow as bw
from forger.scrape_quality import prose_without_urls
from forger.scrape_result import Refused, RefuseReason, Saved, scrape_url
from forger.scrapers import article_scraper, doi_metadata, hacker_news, pubchem, x_scraper
from forger.url_safety import UnsafeURLError

FIX = Path(__file__).parent / "fixtures"


def _json(*parts: str) -> dict:
    return json.loads(FIX.joinpath(*parts).read_text(encoding="utf-8"))


def _noop(*_a, **_k):
    return None


def _offline(monkeypatch):
    """Block every real network path the scrapers could take."""
    for mod in (x_scraper, article_scraper, doi_metadata, hacker_news, pubchem):
        monkeypatch.setattr(mod, "assert_safe_fetch_url", _noop, raising=False)
    monkeypatch.setattr(x_scraper, "load_cookies", lambda: None)
    monkeypatch.setattr(x_scraper.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        x_scraper.XScraper, "_fetch_with_jina", lambda self, url: self._error_result("offline")
    )

    def no_redirect(url, *a, **k):
        raise UnsafeURLError("offline replay")

    monkeypatch.setattr(x_scraper, "resolve_redirect_url", no_redirect)

    def no_html(*a, **k):
        raise requests.exceptions.ConnectionError("offline replay")

    monkeypatch.setattr(article_scraper, "_fetch_url", no_html)
    monkeypatch.setattr(doi_metadata.requests, "get", no_html)
    monkeypatch.setattr(pubchem.requests, "get", no_html)
    monkeypatch.setattr(hacker_news.requests, "get", no_html)


def _x_api(monkeypatch, *, syndication=None, oembed=None, fxtwitter=None):
    def fake(self, api_url):
        if "tweet-result" in api_url:
            return _json("x_scrape", syndication) if syndication else None
        if "publish.twitter.com" in api_url:
            return _json("x_scrape", oembed) if oembed else None
        if "fxtwitter" in api_url:
            return _json("x_scrape", fxtwitter) if fxtwitter else None
        return None

    monkeypatch.setattr(x_scraper.XScraper, "_http_get_json", fake)


def _html(monkeypatch, *parts: str, content_type: str = "text/html"):
    raw = FIX.joinpath(*parts).read_bytes()

    class Resp:
        content = raw
        encoding = "ISO-8859-1"
        headers = {"Content-Type": content_type}
        text = raw.decode("latin-1")
        status_code = 200

        def raise_for_status(self):
            return None

    monkeypatch.setattr(article_scraper, "_fetch_url", lambda url, headers, timeout: Resp())


def _json_get(module, routes: dict[str, str]):
    def fake_get(url, headers=None, timeout=None):
        for needle, fixture in routes.items():
            if needle in url:
                resp = MagicMock()
                resp.raise_for_status = MagicMock()
                resp.json.return_value = _json(*fixture.split("/"))
                return resp
        raise requests.exceptions.HTTPError("404")

    return fake_get


def _html_403(*a, **k):
    resp = MagicMock()
    resp.status_code = 403
    err = requests.exceptions.HTTPError("403 Client Error: Forbidden")
    err.response = resp
    raise err


@dataclass
class Case:
    name: str
    url: str
    setup: Callable
    saved: bool
    title_has: Optional[str] = None
    text_has: list[str] = field(default_factory=list)
    text_lacks: list[str] = field(default_factory=list)
    reason: Optional[RefuseReason] = None


CASES = [
    Case(
        "PR#19 thin X link post enriched from X Article",
        "https://x.com/gregisenberg/status/2101760050108797268",
        lambda mp: _x_api(mp, syndication="syndication_greg_thin.json", fxtwitter="fxtwitter_greg_article.json"),
        saved=True,
        title_has="AI-native",
    ),
    Case(
        "PR#18 public X post without cookies",
        "https://x.com/poteto/status/1",
        lambda mp: _x_api(
            mp, syndication="syndication_poteto.json", oembed="oembed_poteto.json", fxtwitter="fxtwitter_poteto.json"
        ),
        saved=True,
    ),
    Case(
        "PR#25 quote post keeps quoted text, no t.co in title",
        "https://x.com/j0wimo/status/2108723087214620910",
        lambda mp: _x_api(mp, syndication="syndication_j0wimo_quote.json"),
        saved=True,
        title_has="purely insane",
        text_has=["Quoting @AnthropicAI:", "beginning a process"],
    ),
    Case(
        "PR#11/#19 bare t.co X post is refused",
        "https://x.com/someone/status/2",
        lambda mp: _x_api(mp, syndication="syndication_link_only.json"),
        saved=False,
    ),
    Case(
        "PR#22 Cloudflare challenge is refused",
        "https://example.com/paywalled",
        lambda mp: _html(mp, "challenge", "cloudflare_just_a_moment.html"),
        saved=False,
        reason=RefuseReason.CHALLENGE,
    ),
    Case(
        "PR#22 Nature Client Challenge is refused",
        "https://www.nature.com/articles/s41567-026-03465-3",
        lambda mp: _html(mp, "challenge", "nature_client_challenge.html"),
        saved=False,
        reason=RefuseReason.CHALLENGE,
    ),
    Case(
        "Nature article with Crossref abstract saves",
        "https://www.nature.com/articles/s41586-020-2649-2",
        lambda mp: mp.setattr(
            doi_metadata.requests, "get",
            _json_get(doi_metadata, {"api.crossref.org/works/": "doi_metadata/nature_with_abstract_crossref.json"}),
        ),
        saved=True,
    ),
    Case(
        "Nature title+journal+DOI-only Crossref is refused",
        "https://www.nature.com/articles/s41567-026-03465-3",
        lambda mp: (
            _html(mp, "challenge", "nature_client_challenge.html"),
            mp.setattr(
                doi_metadata.requests, "get",
                _json_get(doi_metadata, {"api.crossref.org/works/": "doi_metadata/nature_s41567_026_03465_3_crossref.json"}),
            ),
        ),
        saved=False,
        reason=RefuseReason.CHALLENGE,
    ),
    Case(
        "PR#22 normal article still saves",
        "https://journals.example.edu/topo",
        lambda mp: _html(mp, "challenge", "normal_article.html"),
        saved=True,
        title_has="topological",
    ),
    Case(
        "PR#23 UTF-8 article without mojibake (jsomers)",
        "https://example.com/jsomers_utf8.html",
        lambda mp: _html(mp, "encoding", "jsomers_utf8.html"),
        saved=True,
        text_has=["It\u2019s"],
        text_lacks=["It\u00e2"],
    ),
    Case(
        "PR#23 UTF-8 article without mojibake (bbc nbsp)",
        "https://example.com/bbc_nbsp_utf8.html",
        lambda mp: _html(mp, "encoding", "bbc_nbsp_utf8.html"),
        saved=True,
        text_has=["5\u00a0mg"],
        text_lacks=["\u00c2"],
    ),
    Case(
        "PR#21 DOI 403 recovers via Crossref",
        "https://doi.org/10.1021/jacs.6c12509",
        lambda mp: (
            mp.setattr(article_scraper, "_fetch_url", _html_403),
            mp.setattr(
                doi_metadata.requests, "get",
                _json_get(doi_metadata, {"api.crossref.org/works/": "doi_metadata/jacs_6c12509_crossref.json"}),
            ),
        ),
        saved=True,
        title_has="Alkyl-to-Alkyl",
    ),
    Case(
        "PR#17 PubChem compound via PUG REST",
        "https://pubchem.ncbi.nlm.nih.gov/compound/2519",
        lambda mp: mp.setattr(
            pubchem.requests, "get",
            _json_get(pubchem, {"/property/": "pubchem/caffeine_properties.json",
                                "/description/": "pubchem/caffeine_description.json"}),
        ),
        saved=True,
        title_has="Caffeine",
        text_has=["C8H10N4O2"],
    ),
    Case(
        "HN Ask item via Firebase (no HTML 419)",
        "https://news.ycombinator.com/item?id=50128412",
        lambda mp: (
            mp.setattr(hacker_news, "assert_safe_fetch_url", lambda u: u),
            mp.setattr(
                hacker_news.requests,
                "get",
                _json_get(hacker_news, {"/item/50128412.json": "hacker_news/item_ask_hn.json"}),
            ),
        ),
        saved=True,
        title_has="most useful thing AI",
        text_has=["running toilet"],
    ),
    Case(
        "network failure is refused, never stubbed",
        "https://example.com/down",
        lambda mp: None,
        saved=False,
        reason=RefuseReason.FETCH_FAILED,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_replay(monkeypatch, case: Case):
    _offline(monkeypatch)
    case.setup(monkeypatch)

    outcome = scrape_url(case.url)
    bookmark = bw.scrape_and_create_bookmark(case.url)

    if not case.saved:
        assert isinstance(outcome, Refused), f"expected refusal, got {outcome!r}"
        if case.reason:
            assert outcome.reason == case.reason
        assert bookmark is None
        return

    assert isinstance(outcome, Saved), f"expected save, got {outcome!r}"
    assert bookmark is not None
    assert bookmark.title == outcome.title
    assert bookmark.title and prose_without_urls(bookmark.title) == bookmark.title
    assert not bookmark.title.startswith("Article from ")
    if case.title_has:
        assert case.title_has.lower() in bookmark.title.lower()
    for needle in case.text_has:
        assert needle in bookmark.text
    for poison in case.text_lacks:
        assert poison not in bookmark.text + bookmark.title
