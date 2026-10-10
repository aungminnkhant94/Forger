"""Decide whether scraped bookmark text is usable enough to save / compare.

Aligned with article_scraper success rule: title + text with len(text) > 200.
Failed scrapes used to invent stubs like ``Article from example.com`` which
later poisoned DUPLICATE_TOPIC matching — those stubs must not be saved or
used as similarity targets.
"""
from __future__ import annotations

# Must stay in sync with forger.scrapers.article_scraper success check
# (len(text) > 200).
MIN_USABLE_ARTICLE_TEXT_CHARS = 200

_X_FAILURE_STUB_MARKER = "View on X for full content."
_ARTICLE_FAILURE_STUB_PREFIX = "[URL content not available]"


def is_scrape_failure_stub(text: str | None) -> bool:
    """True for the synthetic bodies formerly saved when scraping failed."""
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if cleaned.startswith(_ARTICLE_FAILURE_STUB_PREFIX):
        return True
    if cleaned.startswith("Twitter/X post from @") and _X_FAILURE_STUB_MARKER in cleaned:
        return True
    return False


def is_usable_scrape_text(text: str | None, *, source: str = "article") -> bool:
    """True when *text* is non-stub content worth saving or comparing.

    - Empty / whitespace → not usable
    - Known failure stubs → not usable
    - ``article`` (and unknown sources): require at least
      ``MIN_USABLE_ARTICLE_TEXT_CHARS`` characters (same bar as the scraper)
    - ``x``: any non-empty non-stub text is usable (tweets can be short)
    """
    cleaned = (text or "").strip()
    if not cleaned or is_scrape_failure_stub(cleaned):
        return False
    if (source or "article").lower() == "x":
        return True
    return len(cleaned) > MIN_USABLE_ARTICLE_TEXT_CHARS
