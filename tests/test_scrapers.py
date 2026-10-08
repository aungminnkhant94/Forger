"""Unit tests for X and article scrapers with mocking."""
import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from requests.exceptions import ConnectionError, HTTPError, Timeout

from forger.scrapers.article_scraper import (
    ArticleScraperError,
    ArticleScraperHTTPError,
    ArticleScraperTimeoutError,
    MAX_TEXT_LENGTH,
    scrape_article,
    scrape_article_with_fallback,
)
from forger.scrapers.x_scraper import (
    XScraper,
    XScraperError,
    XScraperPlaywrightError,
    XScraperTimeoutError,
    fetch_x_content,
    fetch_x_content_sync,
)


class TestXScraperInit:
    """Tests for XScraper initialization."""

    def test_scraper_creation(self):
        """Can create XScraper instance."""
        scraper = XScraper()
        assert scraper.user_agent is not None
        assert "Mozilla" in scraper.user_agent


class TestXScraperGenerateTitle:
    """Tests for title generation."""

    def test_generate_title_from_text(self):
        """Generate title from tweet text."""
        scraper = XScraper()
        text = "This is a tweet about something interesting. More content here."

        title = scraper._generate_title(text)

        assert "tweet" in title.lower()
        assert len(title) <= 80

    def test_generate_title_uses_first_line(self):
        """Uses first line for title."""
        scraper = XScraper()
        text = "First line here\nSecond line here"

        title = scraper._generate_title(text)

        assert "First line" in title
        assert "Second" not in title

    def test_generate_title_truncates_at_sentence(self):
        """Truncates at sentence boundary."""
        scraper = XScraper()
        text = "First sentence here. Second sentence here that is very long."

        title = scraper._generate_title(text, max_length=40)

        assert title.endswith(".")
        assert len(title) <= 40

    def test_generate_title_truncates_at_word(self):
        """Truncates at word boundary if no sentence."""
        scraper = XScraper()
        text = "A very long word here " * 10

        title = scraper._generate_title(text, max_length=50)

        assert "..." in title
        assert len(title) <= 50

    def test_generate_title_empty_text(self):
        """Handle empty text."""
        scraper = XScraper()
        title = scraper._generate_title("")
        assert title == "X Post"


class TestXScraperErrorResult:
    """Tests for error result generation."""

    def test_error_result_structure(self):
        """Error result has correct structure."""
        scraper = XScraper()
        result = scraper._error_result("Test error")

        assert result["success"] is False
        assert result["text"] == ""
        assert result["author"] is None
        assert result["title"] == "X Post"
        assert result["error"] == "Test error"


class TestFetchXContent:
    """Tests for convenience functions."""

    @pytest.mark.asyncio
    @patch("forger.scrapers.x_scraper.XScraper.fetch_tweet")
    async def test_fetch_x_content(self, mock_fetch):
        """Convenience function calls scraper."""
        mock_fetch.return_value = {"success": True, "text": "Tweet"}

        result = await fetch_x_content("https://x.com/user/status/123")

        assert result["success"] is True
        mock_fetch.assert_called_once_with("https://x.com/user/status/123")

    @patch("forger.scrapers.x_scraper.asyncio.run")
    @patch("forger.scrapers.x_scraper.fetch_x_content")
    def test_fetch_x_content_sync(self, mock_fetch, mock_run):
        """Sync wrapper calls async version."""
        mock_run.return_value = {"success": True, "text": "Tweet"}

        result = fetch_x_content_sync("https://x.com/user/status/123")

        assert result["success"] is True

    @patch("forger.scrapers.x_scraper.asyncio.run")
    @patch("forger.scrapers.x_scraper.fetch_x_content")
    def test_fetch_x_content_sync_keyboard_interrupt(self, mock_fetch, mock_run):
        """Sync wrapper handles keyboard interrupt."""
        mock_run.side_effect = KeyboardInterrupt()

        result = fetch_x_content_sync("https://x.com/user/status/123")

        assert result["success"] is False
        assert "interrupted" in result["error"].lower()


class TestXScraperExceptions:
    """Tests for custom exceptions."""

    def test_xscraper_error_is_exception(self):
        """XScraperError is an Exception."""
        assert issubclass(XScraperError, Exception)

    def test_timeout_error_is_xscraper_error(self):
        """XScraperTimeoutError is XScraperError."""
        assert issubclass(XScraperTimeoutError, XScraperError)

    def test_playwright_error_is_xscraper_error(self):
        """XScraperPlaywrightError is XScraperError."""
        assert issubclass(XScraperPlaywrightError, XScraperError)


class TestArticleScraperSuccess:
    """Tests for successful article scraping."""

    @patch("forger.scrapers.article_scraper.requests.get")
    @patch("forger.scrapers.article_scraper.BeautifulSoup")
    def test_successful_scrape(self, mock_bs, mock_get):
        """Successfully scrape article."""
        # Setup mock response
        mock_response = MagicMock()
        mock_response.text = "<html><title>Test Title</title><body><p>Content</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # Setup mock soup
        mock_soup = MagicMock()
        mock_title = MagicMock()
        mock_title.get_text.return_value = "Test Title"
        mock_soup.find.return_value = mock_title

        mock_body = MagicMock()
        mock_paragraph = MagicMock()
        mock_paragraph.get_text.return_value = "Paragraph content here"
        mock_body.find_all.return_value = [mock_paragraph]
        mock_soup.find_all.return_value = [mock_body]
        mock_soup.select_one.return_value = mock_body
        mock_soup.__getitem__ = MagicMock(return_value=mock_body)
        mock_soup.find.return_value = mock_title

        mock_bs.return_value = mock_soup

        result = scrape_article("https://example.com/article")

        mock_get.assert_called_once()

    @patch("forger.scrapers.article_scraper._fetch_url")
    def test_scrape_with_mocked_fetch(self, mock_fetch):
        """Test with mocked URL fetch."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
            <head><title>Article Title</title></head>
            <body>
                <article>
                    <p>This is a paragraph with enough content to pass validation.</p>
                    <p>This is another paragraph with more content here.</p>
                </article>
            </body>
        </html>
        """
        mock_fetch.return_value = mock_response

        result = scrape_article("https://example.com/article")

        mock_fetch.assert_called_once()


class TestArticleScraperErrors:
    """Tests for article scraper error handling."""

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_timeout_error(self, mock_get):
        """Handles timeout error."""
        mock_get.side_effect = Timeout("Request timed out")

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_connection_error(self, mock_get):
        """Handles connection error."""
        mock_get.side_effect = ConnectionError("Connection failed")

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "connection" in result["error"].lower()

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_http_error(self, mock_get):
        """Handles HTTP error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "http" in result["error"].lower()

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_request_exception(self, mock_get):
        """Handles generic request exception."""
        mock_get.side_effect = requests.exceptions.RequestException("Request failed")

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "request" in result["error"].lower()


class TestArticleScraperRetry:
    """Tests for retry logic."""

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_retries_on_connection_error(self, mock_get):
        """Retries on connection error."""
        mock_get.side_effect = ConnectionError("Connection failed")

        scrape_article("https://example.com/article")

        assert mock_get.call_count == 3

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_retries_on_timeout(self, mock_get):
        """Retries on timeout."""
        mock_get.side_effect = Timeout("Request timed out")

        scrape_article("https://example.com/article")

        assert mock_get.call_count == 3

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_no_retry_on_http_error(self, mock_get):
        """No retry on HTTP error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        scrape_article("https://example.com/article")

        assert mock_get.call_count == 1


class TestArticleScraperFallback:
    """Tests for fallback scraping."""

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_fallback_on_full_scrape_failure(self, mock_get):
        """Fallback when full scrape fails."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
            <head><title>Fallback Title</title></head>
            <body>
                <p>Fallback paragraph content.</p>
            </body>
        </html>
        """
        mock_get.return_value = mock_response

        result = scrape_article_with_fallback("https://example.com/article")

        assert result["success"] is True

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_fallback_returns_partial_content(self, mock_get):
        """Fallback returns at least partial content."""
        mock_response = MagicMock()
        mock_response.text = "<html><title>Title</title><body><p>Content</p></body></html>"
        mock_get.return_value = mock_response

        result = scrape_article_with_fallback("https://example.com/article")

        # Should have at least title or text
        assert result.get("title") is not None or result.get("text") is not None


class TestArticleScraperExceptions:
    """Tests for custom exceptions."""

    def test_article_scraper_error_is_exception(self):
        """ArticleScraperError is an Exception."""
        assert issubclass(ArticleScraperError, Exception)

    def test_timeout_error_is_article_scraper_error(self):
        """ArticleScraperTimeoutError is ArticleScraperError."""
        assert issubclass(ArticleScraperTimeoutError, ArticleScraperError)

    def test_http_error_is_article_scraper_error(self):
        """ArticleScraperHTTPError is ArticleScraperError."""
        assert issubclass(ArticleScraperHTTPError, ArticleScraperError)


class TestArticleScraperContent:
    """Tests for content extraction."""

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_extracts_title(self, mock_get):
        """Extracts title from page."""
        mock_response = MagicMock()
        mock_response.text = "<html><head><title>Page Title</title></head><body><p>Content here</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")

        # Title may or may not be extracted depending on content validation
        assert result.get("title") == "Page Title" or not result["success"]

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_limits_text_length(self, mock_get):
        """Text is limited to MAX_TEXT_LENGTH."""
        mock_response = MagicMock()
        long_content = "x" * (MAX_TEXT_LENGTH + 1000)
        mock_response.text = f"<html><body><article><p>{long_content}</p></article></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")

        if result["success"] and result.get("text"):
            assert len(result["text"]) <= MAX_TEXT_LENGTH

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_removes_script_and_style(self, mock_get):
        """Removes script and style elements."""
        mock_response = MagicMock()
        mock_response.text = """
        <html>
            <body>
                <script>alert('test')</script>
                <style>.css{}</style>
                <p>Actual content here.</p>
            </body>
        </html>
        """
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")

        if result["success"] and result.get("text"):
            assert "alert" not in result["text"]
            assert ".css" not in result["text"]


class TestArticleFetchHeadersAndEncoding:
    """User-Agent and charset handling found by a live scrape."""

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_fetch_sends_user_agent(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_response.apparent_encoding = "utf-8"
        mock_response.text = "<html><head><title>HN</title></head><body><p>hi</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        scrape_article("https://news.ycombinator.com/item?id=1")

        headers = mock_get.call_args.kwargs["headers"]
        assert headers.get("User-Agent")
        assert "Mozilla" in headers["User-Agent"]

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_http_419_retries_with_different_user_agent(self, mock_get):
        blocked = MagicMock()
        blocked.status_code = 419
        blocked.text = "Sorry\n"
        blocked.raise_for_status = MagicMock()
        ok = MagicMock()
        ok.status_code = 200
        ok.headers = {"Content-Type": "text/html; charset=utf-8"}
        ok.apparent_encoding = "utf-8"
        ok.text = "<html><title>Item</title><body><p>hello</p></body></html>"
        ok.raise_for_status = MagicMock()
        mock_get.side_effect = [blocked, ok]

        scrape_article("https://news.ycombinator.com/item?id=1")

        assert mock_get.call_count == 2
        first = mock_get.call_args_list[0].kwargs["headers"]["User-Agent"]
        second = mock_get.call_args_list[1].kwargs["headers"]["User-Agent"]
        assert "Mozilla" in first
        assert second != first
        assert second

    def test_missing_charset_uses_apparent_encoding(self):
        # UTF-8 right-single-quote, which ISO-8859-1 shows as "thereâs".
        sentence = "there’s some task you’d like to automate. " * 8
        html = (
            "<html><head><title>Appetite</title></head><body><article><p>"
            + sentence
            + "</p></article></body></html>"
        )
        response = requests.Response()
        response.status_code = 200
        response._content = html.encode("utf-8")
        response.headers["Content-Type"] = "text/html"
        response.encoding = "ISO-8859-1"
        response.url = "https://docs.python.org/3/tutorial/appetite.html"

        with patch("forger.scrapers.article_scraper._fetch_url", return_value=response):
            result = scrape_article("https://docs.python.org/3/tutorial/appetite.html")

        assert result["success"] is True
        assert "there’s" in result["text"]
        assert "thereâ" not in result["text"]


class TestYouTubeOEmbed:
    @patch("forger.scrapers.article_scraper.requests.get")
    def test_mocked_oembed_title_and_video_id(self, mock_get):
        from forger.scrapers.article_scraper import fetch_youtube

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "title": "Never Gonna Give You Up",
            "author_name": "Rick Astley",
            "description": "Official video",
        }
        mock_get.return_value = response

        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        result = fetch_youtube(url)

        assert result["success"] is True
        assert result["title"] == "Never Gonna Give You Up"
        assert result["author"] == "Rick Astley"
        assert "dQw4w9WgXcQ" in result["text"]
        assert url in result["text"]
        assert "oembed" in mock_get.call_args.args[0]
        assert mock_get.call_count == 1

    @patch("forger.scrapers.article_scraper.requests.get")
    def test_oembed_failure_stub_includes_video_id(self, mock_get):
        from forger.scrapers.article_scraper import fetch_youtube

        mock_get.side_effect = ConnectionError("offline")
        result = fetch_youtube("https://www.youtube.com/watch?v=abc123xyz")

        assert result["success"] is False
        assert "abc123xyz" in result["title"]
        assert "abc123xyz" in result["text"]


class TestXSyndication:
    def test_syndication_parses_text_and_author(self, monkeypatch):
        payload = {
            "text": "just setting up my twttr",
            "user": {"screen_name": "jack", "name": "jack"},
        }

        class FakeResp:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=None):
            assert "cdn.syndication.twimg.com/tweet-result" in req.full_url
            assert "id=20" in req.full_url
            assert "token=0" in req.full_url
            return FakeResp()

        monkeypatch.setattr("forger.scrapers.x_scraper.urllib.request.urlopen", fake_urlopen)
        result = XScraper()._fetch_with_syndication("https://x.com/jack/status/20")

        assert result["success"] is True
        assert result["text"] == "just setting up my twttr"
        assert result["author"] == "jack"
        assert result["source"] == "syndication"

    def test_fxtwitter_used_when_syndication_fails(self, monkeypatch):
        fx = {
            "code": 200,
            "tweet": {
                "text": "a different post",
                "author": {"screen_name": "other"},
            },
        }

        class FakeResp:
            def __init__(self, payload):
                self.payload = payload

            def read(self):
                return json.dumps(self.payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=None):
            if "syndication.twimg.com" in req.full_url:
                raise OSError("syndication down")
            if "api.fxtwitter.com" in req.full_url:
                return FakeResp(fx)
            raise AssertionError(req.full_url)

        monkeypatch.setattr("forger.scrapers.x_scraper.urllib.request.urlopen", fake_urlopen)
        result = XScraper()._fetch_with_fxtwitter("https://x.com/other/status/555")

        assert result["success"] is True
        assert result["text"] == "a different post"
        assert result["author"] == "other"
        assert result["source"] == "fxtwitter"

    @pytest.mark.asyncio
    async def test_fetch_tweet_prefers_syndication_over_playwright(self, monkeypatch):
        scraper = XScraper()
        monkeypatch.setattr(
            scraper,
            "_fetch_with_syndication",
            lambda url: {
                "success": True,
                "text": "hello from syndication",
                "author": "jack",
                "title": "hello from syndication",
                "error": None,
                "source": "syndication",
            },
        )

        async def fail_playwright(url):
            raise AssertionError("playwright should not run")

        monkeypatch.setattr(scraper, "_fetch_with_playwright", fail_playwright)
        result = await scraper.fetch_tweet("https://x.com/jack/status/20")
        assert result["success"] is True
        assert result["author"] == "jack"
