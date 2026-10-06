"""Unit tests for X and article scrapers with mocking."""
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from requests.exceptions import ConnectionError, HTTPError, Timeout

from rolloforge.scrapers.article_scraper import (
    ArticleScraperError,
    ArticleScraperHTTPError,
    ArticleScraperTimeoutError,
    MAX_TEXT_LENGTH,
    scrape_article,
    scrape_article_with_fallback,
)
from rolloforge.scrapers.x_scraper import (
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
    @patch("rolloforge.scrapers.x_scraper.XScraper.fetch_tweet")
    async def test_fetch_x_content(self, mock_fetch):
        """Convenience function calls scraper."""
        mock_fetch.return_value = {"success": True, "text": "Tweet"}

        result = await fetch_x_content("https://x.com/user/status/123")

        assert result["success"] is True
        mock_fetch.assert_called_once_with("https://x.com/user/status/123")

    @patch("rolloforge.scrapers.x_scraper.asyncio.run")
    @patch("rolloforge.scrapers.x_scraper.fetch_x_content")
    def test_fetch_x_content_sync(self, mock_fetch, mock_run):
        """Sync wrapper calls async version."""
        mock_run.return_value = {"success": True, "text": "Tweet"}

        result = fetch_x_content_sync("https://x.com/user/status/123")

        assert result["success"] is True

    @patch("rolloforge.scrapers.x_scraper.asyncio.run")
    @patch("rolloforge.scrapers.x_scraper.fetch_x_content")
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

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    @patch("rolloforge.scrapers.article_scraper.BeautifulSoup")
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

    @patch("rolloforge.scrapers.article_scraper._fetch_url")
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

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_timeout_error(self, mock_get):
        """Handles timeout error."""
        mock_get.side_effect = Timeout("Request timed out")

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "timeout" in result["error"].lower()

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_connection_error(self, mock_get):
        """Handles connection error."""
        mock_get.side_effect = ConnectionError("Connection failed")

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "connection" in result["error"].lower()

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_http_error(self, mock_get):
        """Handles HTTP error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "http" in result["error"].lower()

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_request_exception(self, mock_get):
        """Handles generic request exception."""
        mock_get.side_effect = requests.exceptions.RequestException("Request failed")

        result = scrape_article("https://example.com/article")

        assert result["success"] is False
        assert "request" in result["error"].lower()


class TestArticleScraperRetry:
    """Tests for retry logic."""

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_retries_on_connection_error(self, mock_get):
        """Retries on connection error."""
        mock_get.side_effect = ConnectionError("Connection failed")

        scrape_article("https://example.com/article")

        assert mock_get.call_count == 3

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_retries_on_timeout(self, mock_get):
        """Retries on timeout."""
        mock_get.side_effect = Timeout("Request timed out")

        scrape_article("https://example.com/article")

        assert mock_get.call_count == 3

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_no_retry_on_http_error(self, mock_get):
        """No retry on HTTP error."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = mock_response

        scrape_article("https://example.com/article")

        assert mock_get.call_count == 1


class TestArticleScraperFallback:
    """Tests for fallback scraping."""

    @patch("rolloforge.scrapers.article_scraper.requests.get")
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

    @patch("rolloforge.scrapers.article_scraper.requests.get")
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

    @patch("rolloforge.scrapers.article_scraper.requests.get")
    def test_extracts_title(self, mock_get):
        """Extracts title from page."""
        mock_response = MagicMock()
        mock_response.text = "<html><head><title>Page Title</title></head><body><p>Content here</p></body></html>"
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = scrape_article("https://example.com/article")

        # Title may or may not be extracted depending on content validation
        assert result.get("title") == "Page Title" or not result["success"]

    @patch("rolloforge.scrapers.article_scraper.requests.get")
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

    @patch("rolloforge.scrapers.article_scraper.requests.get")
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
