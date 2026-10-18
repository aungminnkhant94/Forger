"""WeChat (mp.weixin.qq.com): empty <title>, hidden #js_content."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from forger.scrape_result import Refused, Saved, scrape_url

FIXTURES = Path(__file__).parent / "fixtures" / "wechat"
URL = "https://mp.weixin.qq.com/s/TestArticleId123"


def _resp(name: str):
    raw = (FIXTURES / name).read_bytes()
    r = MagicMock()
    r.status_code = 200
    r.content = raw
    r.text = raw.decode("utf-8")
    r.encoding = "utf-8"
    r.apparent_encoding = "utf-8"
    r.headers = {"Content-Type": "text/html; charset=utf-8"}
    r.url = URL
    return r


def _scrape(name: str, url: str = URL):
    with patch("forger.scrapers.article_scraper._fetch_url", return_value=_resp(name)):
        return scrape_url(url)


def test_hidden_js_content_saved_with_og_title():
    out = _scrape("article.html")
    assert isinstance(out, Saved), out
    assert out.title == "測試公眾號文章標題"
    assert "第1段" in out.text and "第8段" in out.text
    assert "小说阅读器" not in out.text  # page chrome outside #js_content
    assert "var x" not in out.text
    assert out.via == "requests+bs4:wechat"


def test_title_falls_back_to_msg_title():
    out = _scrape("article_msg_title_only.html")
    assert isinstance(out, Saved), out
    assert out.title == "腳本標題測試"


def test_empty_js_content_refused():
    out = _scrape("empty.html")
    assert isinstance(out, Refused), out


def test_verify_page_refused_as_challenge():
    out = _scrape("verify.html")
    assert isinstance(out, Refused), out
    assert out.reason.value == "challenge"


def test_private_url_still_blocked():
    with patch("forger.scrapers.article_scraper._fetch_url") as fetch:
        out = scrape_url("http://127.0.0.1/s/x")
    fetch.assert_not_called()
    assert isinstance(out, Refused)
