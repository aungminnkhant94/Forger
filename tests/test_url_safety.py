"""SSRF / private-URL blocklist for scrapers."""
import pytest

from forger.url_safety import UnsafeURLError, assert_safe_fetch_url, is_safe_fetch_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article",
        "http://example.com/",
        "https://news.ycombinator.com/item?id=1",
        "https://x.com/user/status/123",
    ],
)
def test_public_urls_allowed(url):
    assert is_safe_fetch_url(url)
    assert assert_safe_fetch_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "https://localhost/secret",
        "http://localhost.localdomain/",
        "http://[::1]/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
        "file:///etc/passwd",
        "ftp://example.com/a",
        "",
        "not-a-url",
    ],
)
def test_private_and_odd_urls_blocked(url):
    assert not is_safe_fetch_url(url)
    with pytest.raises(UnsafeURLError):
        assert_safe_fetch_url(url)


def test_scrape_article_blocks_localhost(monkeypatch):
    from forger.scrapers import article_scraper

    called = {"get": False}

    def boom(*args, **kwargs):
        called["get"] = True
        raise AssertionError("requests.get must not run for blocked URLs")

    monkeypatch.setattr(article_scraper.requests, "get", boom)
    result = article_scraper.scrape_article("http://127.0.0.1:9/")
    assert result["success"] is False
    assert "Unsafe URL" in (result["error"] or "")
    assert called["get"] is False
