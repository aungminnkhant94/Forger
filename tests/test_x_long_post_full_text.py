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


class TestOutboundPointerGate:
    """Short/medium X prose with a clear outbound URL must follow the link
    even when the URL is mid-sentence or only in entities (not text-endswith).
    """

    ARTICLE = {
        "success": True,
        "title": "Senior Scientist Process Chemistry",
        "text": ("Job description body. " * 30).strip(),
    }
    NATUREISH = {
        "success": True,
        "title": "Nature Catalysis volume cover",
        "text": ("Cover story abstract paragraph. " * 25).strip(),
    }

    def test_roche_like_mid_sentence_url_appends_linked_article(self):
        """fxtwitter expands the job URL mid-sentence; text does not endswith it."""
        s = XScraper()
        text = (
            "We have just published a vacancy for a Senior Scientist in Process "
            "Chemistry & Catalysis at Roche in Basel, Switzerland - "
            "https://www.organic-chemistry.org/jobs/offers/?q=oct-22-roche-1.pdf"
            " - please check and share!"
        )
        res = {
            "success": True,
            "text": text,
            "title": "We have just published a vacancy",
            "source": "fxtwitter",
            "outbound_urls": [
                "https://x.com/organic_portal/status/2113251699099877390",
                "https://www.organic-chemistry.org/jobs/offers/?q=oct-22-roche-1.pdf",
            ],
        }
        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            side_effect=lambda u: u,
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value=self.ARTICLE,
        ) as sa:
            out = s._enrich_pointer_post(res)
        assert sa.called
        called_urls = [c.args[0] for c in sa.call_args_list]
        assert any("organic-chemistry.org" in u for u in called_urls)
        assert "Linked article: Senior Scientist Process Chemistry" in out["text"]
        assert text[:40] in out["text"]
        assert out["source"].endswith("+link")

    def test_roche_like_multi_tco_prefers_entity_over_trailing_media(self):
        """Syndication keeps two trailing t.co; last is often media — prefer entity."""
        s = XScraper()
        text = (
            "Vacancy at Roche in Basel - https://t.co/i5ZGDN41bA - please share! "
            "https://t.co/WMAMVLwF5M"
        )
        res = {
            "success": True,
            "text": text,
            "title": "Vacancy at Roche",
            "source": "syndication",
            "outbound_urls": [
                "https://www.organic-chemistry.org/jobs/offers/?q=oct-22-roche-1.pdf",
                "https://t.co/i5ZGDN41bA",
                "https://t.co/WMAMVLwF5M",
            ],
        }

        def resolve(u):
            if u.endswith("WMAMVLwF5M"):
                return "https://x.com/organic_portal/status/2113251699099877390/photo/1"
            if u.endswith("i5ZGDN41bA") or "organic-chemistry.org" in u:
                return "https://www.organic-chemistry.org/jobs/offers/?q=oct-22-roche-1.pdf"
            return u

        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            side_effect=resolve,
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value=self.ARTICLE,
        ) as sa:
            out = s._enrich_pointer_post(res)
        assert "Linked article" in out["text"]
        assert out.get("outbound_resolved", "").startswith("https://www.organic-chemistry.org")

    def test_nature_like_non_thin_pointer_appends(self):
        """~300 char cover announcement is not thin; still follow the paper URL."""
        s = XScraper()
        text = (
            "Thrilled to share that our latest research is featured on the cover of "
            "Nature Catalysis! Being highlighted on the cover is a huge honor.\n\n"
            "https://www.nature.com/natcatal/volumes/9/issues/10"
        )
        assert len(text) > 150
        res = {
            "success": True,
            "text": text,
            "title": "Thrilled to share",
            "source": "fxtwitter",
            "outbound_urls": ["https://www.nature.com/natcatal/volumes/9/issues/10"],
        }
        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            side_effect=lambda u: u,
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value=self.NATUREISH,
        ):
            out = s._enrich_pointer_post(res)
        assert "Linked article: Nature Catalysis volume cover" in out["text"]

    def test_entity_only_url_when_text_ends_with_hashtags(self):
        """Paper t.co mid-body; trailing hashtags — follow entity DOI."""
        s = XScraper()
        text = (
            "My most recently published research ...https://t.co/85GrHsIqCJ\n"
            "Fe,Cr promoted Raney nickel catalysts for nitrile hydrogenation "
            "#catalysis #OrgChem #Catalyst"
        )
        res = {
            "success": True,
            "text": text,
            "title": "My most recently published research",
            "source": "fxtwitter",
            "outbound_urls": [
                "https://x.com/TomManz3/status/2113362396710654301",
                "https://doi.org/10.1021/acsomega.6c06602",
            ],
        }
        paper = {
            "success": True,
            "title": "Raney nickel catalysts",
            "text": ("Abstract of the Raney Ni paper. " * 20).strip(),
        }
        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            side_effect=lambda u: u,
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value=paper,
        ) as sa:
            out = s._enrich_pointer_post(res)
        assert sa.called
        assert any("doi.org" in c.args[0] for c in sa.call_args_list)
        assert "Linked article: Raney nickel catalysts" in out["text"]

    def test_koenig_style_trailing_tco_still_works(self):
        s = XScraper()
        text = (
            "We merged cobalt catalysis with photochemistry. Congrats!\n"
            "https://t.co/YgLSlmorQ1"
        )
        res = {
            "success": True,
            "text": text,
            "title": "We merged cobalt catalysis",
            "source": "syndication",
            "outbound_urls": [
                "https://doi.org/10.1002/adsc.70830",
                "https://t.co/YgLSlmorQ1",
            ],
        }
        wiley = {
            "success": True,
            "title": "Visible-Light Cobalt-Catalyzed Synthesis",
            "text": ("A versatile strategy leveraging arylazo sulfones. " * 20).strip(),
        }

        def resolve(u):
            if "YgLSlmorQ1" in u or "doi.org" in u:
                return "https://advanced.onlinelibrary.wiley.com/doi/10.1002/adsc.70830"
            return u

        with patch(
            "forger.scrapers.x_scraper.resolve_redirect_url",
            side_effect=resolve,
        ), patch(
            "forger.scrapers.article_scraper.scrape_article",
            return_value=wiley,
        ):
            out = s._enrich_pointer_post(res)
        assert "Linked article: Visible-Light Cobalt-Catalyzed Synthesis" in out["text"]


class TestXArticleNotBeatenByOembed:
    """oEmbed tweet body must not short-circuit past an X Article preview/full."""

    WARP = "https://x.com/AlokVasudev/status/2113316408205390211"

    def test_continues_past_oembed_to_fxtwitter_full_article(self):
        s = XScraper()
        fake = _router({
            "syndication": _load("syndication_warp_article_preview.json"),
            "publish.twitter.com": _load("oembed_warp.json"),
            "fxtwitter": _load("fxtwitter_warp_article_full.json"),
        })
        with patch.object(s, "_http_get_json", side_effect=fake), \
                patch.object(s, "_enrich_pointer_post", side_effect=lambda r: r):
            r = s._fetch_with_public_apis(self.WARP)
        assert r["success"]
        assert "Warp" in (r.get("title") or "") or "Warp" in (r.get("text") or "")
        assert len(r["text"]) > 400
        assert "fxtwitter" in (r.get("source") or "")
        assert "x_article" in (r.get("source") or "")
