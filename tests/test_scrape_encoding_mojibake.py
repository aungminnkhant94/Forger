"""UTF-8 HTML must not be saved as Latin-1/Windows-1252 mojibake."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from forger.scrapers.article_scraper import (
    decode_html_bytes,
    html_text_from_response,
    scrape_article,
)

FIXTURES = Path(__file__).parent / "fixtures" / "encoding"


def _raw(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_fixture_shows_mojibake_when_misdecoded_as_latin1():
    """Document the before state testers reported (itâs / stray Â)."""
    jsomers = _raw("jsomers_utf8.html")
    bbc = _raw("bbc_nbsp_utf8.html")

    mangled_jsomers = jsomers.decode("latin-1")
    mangled_bbc = bbc.decode("latin-1")

    assert "Itâ" in mangled_jsomers  # curly apostrophe as Latin-1
    assert "It\u2019s" not in mangled_jsomers
    assert "Â" in mangled_bbc  # UTF-8 NBSP lead byte as Â
    assert "5\u00a0mg" not in mangled_bbc


def test_decode_html_bytes_fixes_jsomers_curly_apostrophe():
    raw = _raw("jsomers_utf8.html")
    # Simulate requests default when Content-Type omits charset.
    text = decode_html_bytes(
        raw,
        header_encoding="ISO-8859-1",
        content_type="text/html",
    )
    assert "It\u2019s" in text
    assert "You\u2019re" in text
    assert "Itâ" not in text


def test_decode_html_bytes_fixes_bbc_nbsp():
    raw = _raw("bbc_nbsp_utf8.html")
    text = decode_html_bytes(
        raw,
        header_encoding="ISO-8859-1",
        content_type="text/html",
    )
    assert "5\u00a0mg" in text
    assert "£2\u00a0million" in text
    assert "Â" not in text


def test_decode_prefers_explicit_windows_1252_when_declared():
    # "café" in windows-1252 is b'caf\xe9' — not valid UTF-8.
    raw = b"<html><head><title>cafe</title></head><body><p>caf\xe9 au lait</p></body></html>"
    text = decode_html_bytes(
        raw,
        header_encoding="windows-1252",
        content_type="text/html; charset=windows-1252",
    )
    assert "café" in text


def test_decode_uses_meta_charset_when_header_omits_it():
    raw = (
        b'<html><head><meta charset="utf-8"><title>T</title></head>'
        b"<body><p>It\xe2\x80\x99s fine</p></body></html>"
    )
    text = decode_html_bytes(
        raw,
        header_encoding="ISO-8859-1",
        content_type="text/html",
    )
    assert "It\u2019s fine" in text


def test_html_text_from_response_falls_back_to_text_for_test_doubles():
    class Resp:
        text = "<html><title>Only Text</title></html>"
        headers = {}

    assert "Only Text" in html_text_from_response(Resp())


def test_html_text_from_response_ignores_requests_latin1_default():
    raw = _raw("jsomers_utf8.html")
    response = MagicMock()
    response.content = raw
    response.encoding = "ISO-8859-1"
    response.headers = {"Content-Type": "text/html"}
    # Poison .text the way requests would.
    response.text = raw.decode("latin-1")

    text = html_text_from_response(response)
    assert "It\u2019s" in text
    assert "Itâ" not in text


@pytest.mark.parametrize(
    "fixture,needle,poison",
    [
        ("jsomers_utf8.html", "It\u2019s", "Itâ"),
        ("bbc_nbsp_utf8.html", "5\u00a0mg", "Â"),
    ],
)
def test_scrape_article_saves_clean_utf8(monkeypatch, fixture, needle, poison):
    raw = _raw(fixture)

    class Resp:
        content = raw
        encoding = "ISO-8859-1"
        headers = {"Content-Type": "text/html"}
        text = raw.decode("latin-1")  # what requests.text would return

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "forger.scrapers.article_scraper._fetch_url",
        lambda url, headers, timeout: Resp(),
    )
    result = scrape_article(f"https://example.com/{fixture}")
    assert result["success"] is True
    body = (result.get("text") or "") + (result.get("title") or "")
    assert needle in body
    assert poison not in body
