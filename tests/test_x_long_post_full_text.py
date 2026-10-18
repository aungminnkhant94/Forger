"""Long X posts (note tweets) must not be saved as the ~280-char preview.

Fixtures are real payloads captured 2026-10-17 from the newest X bookmarks.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from forger.scrapers.x_scraper import XScraper, looks_truncated

FIXTURES = Path(__file__).parent / "fixtures" / "x_scrape"
NICHO = "https://x.com/nichochar/status/2110589417811579362"
POTETO = "https://x.com/poteto/status/2111133080526495985"
FELIX = "https://x.com/felixrieseberg/status/2110023283169247623"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _router(mapping: dict):
    """Return an _http_get_json stand-in keyed by host substring."""
    def fake(api_url, user_agent=None):
        for key, payload in mapping.items():
            if key in api_url:
                return payload
        return None
    return fake


def _no_oembed(*_a, **_k):
    return {"success": False, "error": "oembed off in test"}


class TestLooksTruncated:
    def test_ellipsis_long(self):
        assert looks_truncated("x" * 250 + "…")

    def test_trailing_tco_long(self):
        assert looks_truncated("word " * 55 + "https://t.co/AbC123")

    def test_short_text_not_truncated(self):
        assert not looks_truncated("short post https://t.co/AbC123")
        assert not looks_truncated("hm...")

    def test_link_on_own_line_not_truncated(self):
        assert not looks_truncated("word " * 55 + "\n\nhttps://t.co/AbC123")

    def test_empty(self):
        assert not looks_truncated(None)
        assert not looks_truncated("")


class TestLayerTruncationFlags:
    def test_syndication_note_tweet_marked_truncated(self):
        s = XScraper()
        with patch.object(s, "_http_get_json", return_value=_load("syndication_poteto_long.json")):
            r = s._fetch_with_syndication("2111133080526495985", "poteto")
        assert r["success"] and r.get("truncated") is True

    def test_fxtwitter_note_tweet_is_full(self):
        s = XScraper()
        with patch.object(s, "_http_get_json", return_value=_load("fxtwitter_poteto_long.json")):
            r = s._fetch_with_fxtwitter("2111133080526495985", "poteto")
        assert r["success"] and not r.get("truncated")
        assert len(r["text"]) > 1500

    def test_vxtwitter_uses_api_client_user_agent(self):
        s = XScraper()
        seen = {}

        def fake(api_url, user_agent=None):
            seen["ua"] = user_agent
            return _load("vxtwitter_nichochar.json")

        with patch.object(s, "_http_get_json", side_effect=fake):
            r = s._fetch_with_vxtwitter("2110589417811579362", "nichochar")
        assert r["success"]
        assert seen["ua"] and "Mozilla" not in seen["ua"]


class TestChainPicksFullText:
    def test_note_tweet_falls_through_to_fxtwitter(self):
        s = XScraper()
        fake = _router({
            "syndication": _load("syndication_poteto_long.json"),
            "fxtwitter": _load("fxtwitter_poteto_long.json"),
        })
        with patch.object(s, "_http_get_json", side_effect=fake), \
                patch.object(s, "_fetch_with_oembed", side_effect=_no_oembed):
            r = s._fetch_with_public_apis(POTETO)
        assert r["success"] and r["source"].startswith("fxtwitter")
        assert len(r["text"]) > 1500
        assert "truncated" not in r and "outer_len" not in r

    def test_vxtwitter_wins_when_fx_is_also_preview(self):
        # fx is longer overall only because of the quoted post; its own text is
        # the same 274-char preview, so vxtwitter's 497-char text must win.
        s = XScraper()
        fake = _router({
            "syndication": _load("syndication_nichochar.json"),
            "fxtwitter": _load("fxtwitter_nichochar.json"),
            "vxtwitter": _load("vxtwitter_nichochar.json"),
        })
        with patch.object(s, "_http_get_json", side_effect=fake), \
                patch.object(s, "_fetch_with_oembed", side_effect=_no_oembed), \
                patch.object(s, "_enrich_pointer_post", side_effect=lambda r: r):
            r = s._fetch_with_public_apis(NICHO)
        assert r["success"] and r["source"].startswith("vxtwitter")
        full = _load("vxtwitter_nichochar.json")["text"]
        assert full[:400] in r["text"]

    def test_truncated_kept_when_no_full_layer(self):
        s = XScraper()
        fake = _router({"syndication": _load("syndication_nichochar.json")})
        with patch.object(s, "_http_get_json", side_effect=fake), \
                patch.object(s, "_fetch_with_oembed", side_effect=_no_oembed), \
                patch.object(s, "_enrich_pointer_post", side_effect=lambda r: r):
            r = s._fetch_with_public_apis(NICHO)
        # Real (if cut) prose is still saved, never invented.
        assert r["success"] and r["source"].startswith("syndication")


class TestPointerPost:
    ARTICLE = {"success": True, "title": "A tutorial", "text": "Tutorial body. " * 40}

    def _run(self, scrape_ret):
        s = XScraper()
        fake = _router({"syndication": _load("syndication_felix.json")})
        with patch.object(s, "_http_get_json", side_effect=fake), \
                patch("forger.scrapers.x_scraper.resolve_redirect_url",
                      return_value="https://example.com/tutorial"), \
                patch("forger.scrapers.article_scraper.scrape_article",
                      return_value=scrape_ret) as sa:
            r = s._fetch_with_public_apis(FELIX)
        return r, sa

    def test_pointer_appends_linked_article(self):
        r, sa = self._run(self.ARTICLE)
        sa.assert_called_once_with("https://example.com/tutorial")
        orig = _load("syndication_felix.json")["text"][:100]
        assert orig[:60] in r["text"]
        assert "Linked article: A tutorial" in r["text"]
        assert "Tutorial body." in r["text"]
        assert r["source"].endswith("+link")

    def test_pointer_link_failure_keeps_x_text(self):
        r, _ = self._run({"success": False, "error": "blocked"})
        assert r["success"]
        assert "Linked article" not in r["text"]
        assert "+link" not in r["source"]

    def test_pointer_thin_article_not_appended(self):
        r, _ = self._run({"success": True, "title": "t", "text": "too short"})
        assert "Linked article" not in r["text"]

    def test_long_prose_post_not_treated_as_pointer(self):
        s = XScraper()
        res = {"success": True, "text": "real words " * 60 + "https://example.com/x", "source": "fxtwitter"}
        with patch("forger.scrapers.article_scraper.scrape_article") as sa:
            out = s._enrich_pointer_post(res)
        sa.assert_not_called()
        assert out == res
