"""A tiny first <article> (promo card) must not hide the real content."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from forger.scrape_result import Refused, Saved, scrape_url

FIX = Path(__file__).parent / "fixtures" / "article_pick"
URL = "https://blog.example.org/marketing/reports"


def _resp(name):
    raw = (FIX / name).read_bytes()
    r = MagicMock(status_code=200, content=raw, text=raw.decode(), encoding="utf-8",
                  apparent_encoding="utf-8", headers={"Content-Type": "text/html; charset=utf-8"})
    r.url = URL
    return r


def _scrape(name):
    with patch("forger.scrapers.article_scraper._fetch_url", return_value=_resp(name)):
        return scrape_url(URL)


def test_skips_promo_article_cards_and_uses_main():
    out = _scrape("promo_cards_then_main.html")
    assert isinstance(out, Saved), out
    assert "Paragraph 14 explains" in out.text
    assert "Promo card" not in out.text


def test_all_containers_tiny_still_refused():
    assert isinstance(_scrape("all_tiny.html"), Refused)
