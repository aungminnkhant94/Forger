"""Quote tweets must include nested quoted text; titles must not keep raw t.co."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from forger.scrapers.x_scraper import (
    XScraper,
    _extract_quoted_tweet,
    _format_with_quote,
    is_thin_x_result,
)

FIXTURES = Path(__file__).parent / "fixtures" / "x_scrape"
J0WIMO_URL = "https://x.com/j0wimo/status/2108723087214620910"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestExtractQuotedTweet:
    def test_syndication_fixture(self):
        payload = _load("syndication_j0wimo_quote.json")
        author, text = _extract_quoted_tweet(payload)
        assert author == "AnthropicAI"
        assert text and "beginning a process" in text
        assert "model behavior" in text

    def test_fxtwitter_fixture(self):
        payload = _load("fxtwitter_j0wimo_quote.json")
        author, text = _extract_quoted_tweet(payload)
        assert author == "AnthropicAI"
        assert text and "beginning a process" in text

    def test_missing_quote_returns_none(self):
        assert _extract_quoted_tweet({"text": "hello"}) == (None, None)
        assert _extract_quoted_tweet(None) == (None, None)


class TestFormatWithQuote:
    def test_appends_quoted_body(self):
        merged = _format_with_quote(
            "outer commentary https://t.co/abc",
            "AnthropicAI",
            "Quoted body here",
        )
        assert merged.startswith("outer commentary")
        assert "Quoting @AnthropicAI:" in merged
        assert "Quoted body here" in merged

    def test_skips_duplicate_merge(self):
        already = "outer\n\nQuoting @AnthropicAI:\nQuoted body here"
        assert _format_with_quote(already, "AnthropicAI", "Quoted body here") == already


class TestTitleStripsTco:
    def test_trailing_tco_not_in_title(self):
        scraper = XScraper()
        title = scraper._generate_title(
            "this is purely insane btw https://t.co/olDx5YYBqY"
        )
        assert title == "this is purely insane btw"
        assert "t.co" not in title
        assert "http" not in title.lower()

    def test_link_only_becomes_x_post(self):
        scraper = XScraper()
        assert scraper._generate_title("https://t.co/abc123") == "X Post"

    def test_quote_header_skipped_for_title(self):
        scraper = XScraper()
        text = (
            "https://t.co/abc\n\n"
            "Quoting @AnthropicAI:\n"
            "We’re beginning a process of publishing more frequent reports."
        )
        title = scraper._generate_title(text)
        assert "t.co" not in title
        assert "beginning a process" in title or "We’re beginning" in title


class TestSyndicationQuoteMerge:
    def test_merges_quoted_tweet_and_clean_title(self):
        scraper = XScraper()
        payload = _load("syndication_j0wimo_quote.json")
        with patch.object(scraper, "_http_get_json", return_value=payload):
            result = scraper._fetch_with_syndication(
                "2108723087214620910", "j0wimo"
            )
        assert result["success"] is True
        assert result.get("quote_enrichment") is True
        assert "Quoting @AnthropicAI:" in result["text"]
        assert "beginning a process" in result["text"]
        assert "purely insane" in result["text"]
        assert "t.co" not in (result["title"] or "")
        assert "purely insane" in (result["title"] or "")
        assert not is_thin_x_result(result)

    def test_fxtwitter_merges_quote(self):
        scraper = XScraper()
        payload = _load("fxtwitter_j0wimo_quote.json")
        with patch.object(scraper, "_http_get_json", return_value=payload):
            result = scraper._fetch_with_fxtwitter(
                "2108723087214620910", "j0wimo"
            )
        assert result["success"] is True
        assert result.get("quote_enrichment") is True
        assert "Quoting @AnthropicAI:" in result["text"]
        assert "beginning a process" in result["text"]
        assert "t.co" not in (result["title"] or "")


class TestPublicApiChainQuote:
    def test_syndication_quote_short_circuits_with_full_body(self):
        scraper = XScraper()
        synd = _load("syndication_j0wimo_quote.json")

        def fake_json(api_url: str):
            if "tweet-result" in api_url or "syndication" in api_url:
                return synd
            return None

        with patch.object(scraper, "_http_get_json", side_effect=fake_json):
            result = scraper._fetch_with_public_apis(J0WIMO_URL)
        assert result["success"] is True
        assert "Quoting @AnthropicAI:" in result["text"]
        assert "beginning a process" in result["text"]
        assert "t.co" not in (result["title"] or "")
        # Internal enrich flags stripped before return.
        assert "quote_enrichment" not in result
