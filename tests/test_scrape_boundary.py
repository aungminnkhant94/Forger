"""Scraped content reaches bookmarks only through forger.scrape_result."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from forger.scrape_result import RefuseReason, Refused, Saved, classify

ROOT = Path(__file__).resolve().parent.parent
_DIRECT_SCRAPER_USE = re.compile(
    r"\b(scrape_article|scrape_article_with_fallback|fetch_x_content(_sync)?|"
    r"scrape_doi_metadata|scrape_pubchem_compound)\b"
)
_ALLOWED = {
    "forger/scrape_result.py",
    # Unreferenced legacy module (no imports, no tests); still writes failure
    # stubs. Delete it rather than migrate. Added 2026-10-17, review by 2026-11-17.
    "integrations/telegram/telegram_ingest.py",
}


def _sources():
    for base in ("forger", "integrations", "forge.py"):
        path = ROOT / base
        files = [path] if path.is_file() else path.rglob("*.py")
        for f in files:
            rel = f.relative_to(ROOT).as_posix()
            if rel.startswith("forger/scrapers/"):
                continue
            yield rel, f.read_text(encoding="utf-8")


def test_no_direct_scraper_calls_outside_boundary():
    offenders = [rel for rel, src in _sources() if rel not in _ALLOWED and _DIRECT_SCRAPER_USE.search(src)]
    assert not offenders, (
        f"{offenders} call scrapers directly. Use forger.scrape_result.scrape_url(url) "
        "and handle Saved | Refused instead."
    )


def test_saved_rejects_tco_title():
    with pytest.raises(ValueError, match="URL-free"):
        Saved(source="x", url="u", text="a real tweet with enough prose", title="hi https://t.co/x")


def test_saved_rejects_trash_text():
    with pytest.raises(ValueError, match="Refused"):
        Saved(source="article", url="u", text="[URL content not available] https://e.com", title="Stub")


@pytest.mark.parametrize(
    "raw,reason",
    [
        ({"success": False, "error": "HTTP error: 403"}, RefuseReason.FETCH_FAILED),
        ({"success": False, "error": "Bot challenge / anti-bot interstitial (x)"}, RefuseReason.CHALLENGE),
        ({"success": True, "text": "   ", "title": "t"}, RefuseReason.EMPTY),
        ({"success": True, "text": "https://t.co/abc", "title": "X Post"}, RefuseReason.LINK_ONLY),
        ({"success": True, "text": "too short", "title": "Fine title"}, RefuseReason.THIN),
    ],
)
def test_classify_refusals(raw, reason):
    source = "x" if reason is RefuseReason.LINK_ONLY else "article"
    out = classify(source, "https://e.com/a", raw)
    assert isinstance(out, Refused) and out.reason is reason


def test_missing_title_comes_from_body_prose_not_host():
    body = "Graph neural networks for molecule design. " + "More detail here. " * 20
    out = classify("article", "https://example.com/p", {"success": True, "text": body, "title": None})
    assert isinstance(out, Saved)
    assert out.title == "Graph neural networks for molecule design. More detail here. More detail..."
    assert "example.com" not in out.title


def test_x_placeholder_title_replaced_with_prose():
    out = classify("x", "https://x.com/a/status/1", {"success": True, "text": "real words about agents and trust https://t.co/z", "title": "X Post"})
    assert isinstance(out, Saved) and out.title == "real words about agents and trust"
