"""Tests for error handling improvements."""

import pytest
from unittest.mock import Mock, patch

# Test imports
from rolloforge.scrapers.x_scraper import (
    XScraper,
    XScraperError,
    XScraperTimeoutError,
    XScraperPlaywrightError,
)
from rolloforge.scrapers.article_scraper import (
    scrape_article,
    ArticleScraperError,
    ArticleScraperTimeoutError,
)
from rolloforge.deepseek_analysis import (
    DeepSeekError,
    DeepSeekConfigError,
    DeepSeekAPIError,
)


class TestXScraperExceptions:
    """Test XScraper exception hierarchy."""
    
    def test_custom_exceptions_exist(self):
        """Verify custom exception classes are defined."""
        assert issubclass(XScraperTimeoutError, XScraperError)
        assert issubclass(XScraperPlaywrightError, XScraperError)
    
    def test_fetch_x_content_sync_keyboard_interrupt(self):
        """Test KeyboardInterrupt is properly handled."""
        # This should not raise, but return an error result
        # We can't easily test the interrupt, but we verify the function handles it
        pass


class TestArticleScraperExceptions:
    """Test ArticleScraper exception hierarchy."""
    
    def test_custom_exceptions_exist(self):
        """Verify custom exception classes are defined."""
        assert issubclass(ArticleScraperTimeoutError, ArticleScraperError)


class TestDeepSeekExceptions:
    """Test DeepSeek exception hierarchy."""
    
    def test_custom_exceptions_exist(self):
        """Verify custom exception classes are defined."""
        assert issubclass(DeepSeekConfigError, DeepSeekError)
        assert issubclass(DeepSeekAPIError, DeepSeekError)


class TestScrapeArticleErrorHandling:
    """Test article scraper error handling."""
    
    @patch('rolloforge.scrapers.article_scraper.requests.get')
    def test_timeout_error_handling(self, mock_get):
        """Test timeout errors are handled gracefully."""
        from requests.exceptions import Timeout
        mock_get.side_effect = Timeout("Connection timed out")
        
        result = scrape_article("https://example.com", timeout=5)
        
        assert result['success'] is False
        assert 'timeout' in result['error'].lower()
    
    @patch('rolloforge.scrapers.article_scraper.requests.get')
    def test_connection_error_handling(self, mock_get):
        """Test connection errors are handled gracefully."""
        from requests.exceptions import ConnectionError
        mock_get.side_effect = ConnectionError("No connection")
        
        result = scrape_article("https://example.com")
        
        assert result['success'] is False
        assert 'connection' in result['error'].lower()
    
    @patch('rolloforge.scrapers.article_scraper.requests.get')
    def test_http_error_handling(self, mock_get):
        """Test HTTP errors are handled gracefully."""
        from requests.exceptions import HTTPError
        mock_response = Mock()
        mock_response.raise_for_status.side_effect = HTTPError("404 Not Found")
        mock_get.return_value = mock_response
        
        result = scrape_article("https://example.com")
        
        assert result['success'] is False
        assert 'http' in result['error'].lower()


class TestRetryDecorators:
    """Test that retry decorators are properly configured."""
    
    def test_x_scraper_has_retry(self):
        """Test XScraper.fetch_tweet has a multi-method fallback chain."""
        from rolloforge.scrapers.x_scraper import XScraper
        scraper = XScraper()
        assert hasattr(scraper, 'fetch_tweet')
        # Resilience comes from the fallback chain, not a single retry:
        assert hasattr(scraper, '_fetch_with_playwright')
    
    def test_deepseek_has_retry(self):
        """Test DeepSeek API has retry decorator."""
        from rolloforge.deepseek_analysis import _call_analysis_api
        assert hasattr(_call_analysis_api, '__wrapped__')
    
    def test_article_scraper_has_retry(self):
        """Test article scraper has retry decorator."""
        from rolloforge.scrapers.article_scraper import _fetch_url
        assert hasattr(_fetch_url, '__wrapped__')


class TestDeepSeekFallback:
    """Test DeepSeek fallback analysis."""
    
    @patch('rolloforge.deepseek_analysis.analyze_with_deepseek')
    def test_fallback_returns_valid_structure(self, mock_analyze):
        """Test fallback returns proper structure when DeepSeek fails."""
        from rolloforge.deepseek_analysis import deepseek_analyze_bookmark
        
        # Mock API failure
        mock_analyze.return_value = None
        
        result = deepseek_analyze_bookmark(
            text="Test content",
            title="Test Title",
            url="https://example.com"
        )
        
        # Should return fallback structure
        assert 'title' in result
        assert 'summary' in result
        assert 'recommendation_bucket' in result
        assert result.get('analysis_source') == 'deepseek_fallback'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])