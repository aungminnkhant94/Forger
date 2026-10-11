"""Cookie-free X/Twitter status scraping (syndication / oEmbed / fxtwitter)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forger.scrapers.x_scraper import (
    XScraper,
    _syndication_token,
    _text_from_oembed_html,
    extract_status_id,
    extract_status_parts,
    fetch_x_content,
)

FIXTURES = Path(__file__).parent / "fixtures" / "x_scrape"

EXAMPLE_URLS = [
    "https://x.com/poteto/status/2109110547824378140",
    "https://x.com/rowancheung/status/2108328114552000842",
    "https://x.com/undefinedKi/status/2102373393718784336",
    "https://x.com/brandonluumd/status/2102338491942347175",
]


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestExtractStatusId:
    @pytest.mark.parametrize(
        "url, expected_user, expected_id",
        [
            (
                "https://x.com/poteto/status/2109110547824378140",
                "poteto",
                "2109110547824378140",
            ),
            (
                "https://twitter.com/rowancheung/status/2108328114552000842",
                "rowancheung",
                "2108328114552000842",
            ),
            (
                "https://www.x.com/undefinedKi/statuses/2102373393718784336?s=20",
                "undefinedKi",
                "2102373393718784336",
            ),
            (
                "https://x.com/i/web/status/2102338491942347175",
                None,
                "2102338491942347175",
            ),
            ("https://x.com/poteto", None, None),
            ("https://example.com/status/123", None, None),
        ],
    )
    def test_extract_status_parts(self, url, expected_user, expected_id):
        parts = extract_status_parts(url)
        if expected_id is None:
            assert parts is None
            assert extract_status_id(url) is None
        else:
            assert parts == (expected_user, expected_id)
            assert extract_status_id(url) == expected_id

    def test_example_urls_extract(self):
        for url in EXAMPLE_URLS:
            assert extract_status_id(url)
            assert extract_status_id(url).isdigit()


class TestOEmbedHtml:
    def test_strips_tags_and_entities(self):
        raw = (
            '<blockquote class="twitter-tweet"><p lang="en" dir="ltr">'
            "Hello &amp; welcome<br>line two</p></blockquote>"
        )
        assert _text_from_oembed_html(raw) == "Hello & welcome\nline two"

    def test_empty(self):
        assert _text_from_oembed_html("") == ""
        assert _text_from_oembed_html("<div>no p</div>") == ""


class TestSyndicationToken:
    def test_nonzero_for_real_ids(self):
        tok = _syndication_token("2109110547824378140")
        assert tok
        assert tok != "2109110547824378140"
        assert tok.isalnum()


class TestPublicApiFetchers:
    def test_syndication_success(self):
        scraper = XScraper()
        payload = _load("syndication_poteto.json")
        with patch.object(scraper, "_http_get_json", return_value=payload) as mock_get:
            result = scraper._fetch_with_syndication("2109110547824378140", "poteto")
        assert result["success"] is True
        assert "slop" in result["text"]
        assert result["author"] == "poteto"
        assert result["title"]
        assert result["source"] == "syndication"
        assert mock_get.called

    def test_oembed_success(self):
        scraper = XScraper()
        payload = _load("oembed_poteto.json")
        with patch.object(scraper, "_http_get_json", return_value=payload):
            result = scraper._fetch_with_oembed(
                "https://x.com/poteto/status/2109110547824378140", "poteto"
            )
        assert result["success"] is True
        assert "slop" in result["text"]
        assert result["author"] == "poteto"
        assert result["source"] == "oembed"
        assert "&amp;" not in result["text"]

    def test_fxtwitter_success(self):
        scraper = XScraper()
        payload = _load("fxtwitter_poteto.json")
        with patch.object(scraper, "_http_get_json", return_value=payload):
            result = scraper._fetch_with_fxtwitter("2109110547824378140", "poteto")
        assert result["success"] is True
        assert "slop" in result["text"]
        assert result["author"] == "poteto"
        assert result["source"] == "fxtwitter"

    def test_public_apis_chain_uses_first_success(self):
        scraper = XScraper()
        with patch.object(
            scraper,
            "_fetch_with_syndication",
            return_value={
                "success": True,
                "text": "hello from syndication",
                "author": "poteto",
                "title": "hello from syndication",
                "error": None,
                "source": "syndication",
            },
        ) as synd, patch.object(scraper, "_fetch_with_oembed") as oembed, patch.object(
            scraper, "_fetch_with_fxtwitter"
        ) as fx:
            result = scraper._fetch_with_public_apis(EXAMPLE_URLS[0])
        assert result["success"] is True
        assert result["source"] == "syndication"
        synd.assert_called_once()
        oembed.assert_not_called()
        fx.assert_not_called()

    def test_public_apis_fall_through(self):
        scraper = XScraper()
        fail = {"success": False, "text": "", "author": None, "title": "X Post", "error": "x", "source": None}
        ok = {
            "success": True,
            "text": "from oembed",
            "author": "poteto",
            "title": "from oembed",
            "error": None,
            "source": "oembed",
        }
        with patch.object(scraper, "_fetch_with_syndication", return_value=fail), patch.object(
            scraper, "_fetch_with_oembed", return_value=ok
        ), patch.object(scraper, "_fetch_with_fxtwitter") as fx:
            result = scraper._fetch_with_public_apis(EXAMPLE_URLS[0])
        assert result["source"] == "oembed"
        fx.assert_not_called()


class TestFetchTweetOrchestration:
    @pytest.mark.asyncio
    async def test_skips_playwright_without_cookies(self):
        scraper = XScraper()
        public_ok = {
            "success": False,
            "text": "",
            "author": None,
            "title": "X Post",
            "error": "miss",
            "source": None,
        }
        with patch.object(scraper, "_fetch_with_public_apis", return_value=public_ok), patch(
            "forger.scrapers.x_scraper.load_cookies", return_value=None
        ), patch.object(
            scraper, "_fetch_with_playwright", new_callable=AsyncMock
        ) as pw, patch.object(
            scraper, "_fetch_with_jina", return_value=public_ok
        ), patch(
            "forger.scrapers.x_scraper.shutil.which", return_value=None
        ):
            result = await scraper.fetch_tweet(EXAMPLE_URLS[0])
        assert result["success"] is False
        pw.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_public_api_before_playwright(self):
        scraper = XScraper()
        public_ok = {
            "success": True,
            "text": "public text about something useful for tests",
            "author": "poteto",
            "title": "public text",
            "error": None,
            "source": "syndication",
        }
        with patch.object(scraper, "_fetch_with_public_apis", return_value=public_ok), patch(
            "forger.scrapers.x_scraper.load_cookies", return_value=[{"name": "auth_token"}]
        ), patch.object(scraper, "_fetch_with_playwright", new_callable=AsyncMock) as pw:
            result = await scraper.fetch_tweet(EXAMPLE_URLS[0])
        assert result["success"] is True
        assert result["source"] == "syndication"
        assert "public text" in result["text"]
        pw.assert_not_called()

    @pytest.mark.asyncio
    async def test_playwright_when_cookies_and_public_miss(self):
        scraper = XScraper()
        miss = {
            "success": False,
            "text": "",
            "author": None,
            "title": "X Post",
            "error": "miss",
            "source": None,
        }
        pw_ok = {
            "success": True,
            "text": "x" * 120,
            "author": "poteto",
            "title": "t",
            "error": None,
            "source": "playwright",
        }
        with patch.object(scraper, "_fetch_with_public_apis", return_value=miss), patch(
            "forger.scrapers.x_scraper.load_cookies", return_value=[{"name": "auth_token"}]
        ), patch.object(
            scraper, "_fetch_with_playwright", new_callable=AsyncMock, return_value=pw_ok
        ) as pw:
            result = await scraper.fetch_tweet(EXAMPLE_URLS[0])
        assert result["source"] == "playwright"
        pw.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unsafe_url_blocked(self):
        scraper = XScraper()
        result = await scraper.fetch_tweet("http://127.0.0.1/status/1")
        assert result["success"] is False
        assert "unsafe" in result["error"].lower()


class TestLivePublicApis:
    """Live hits against public endpoints (no X cookies). Skip on network errors."""

    @pytest.mark.parametrize("url", EXAMPLE_URLS)
    def test_live_public_fetch_text_and_title(self, url):
        scraper = XScraper()
        try:
            result = scraper._fetch_with_public_apis(url)
        except Exception as exc:  # pragma: no cover - network flake
            pytest.skip(f"network unavailable: {exc}")
        if not result.get("success"):
            pytest.skip(f"public APIs unavailable: {result.get('error')}")
        assert len((result.get("text") or "").strip()) > 10
        assert result.get("title")
        assert result["title"] != ""
        assert result.get("source") in {"syndication", "oembed", "fxtwitter"}
