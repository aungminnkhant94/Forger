"""Decide whether scraped bookmark text is usable enough to save / compare.

Aligned with article_scraper success rule: title + text with len(text) > 200.
Failed scrapes used to invent stubs like ``Article from example.com`` which
later poisoned DUPLICATE_TOPIC matching — those stubs must not be saved or
used as similarity targets.
"""
from __future__ import annotations

import re

# Must stay in sync with forger.scrapers.article_scraper success check
# (len(text) > 200).
MIN_USABLE_ARTICLE_TEXT_CHARS = 200

# Link-only X posts (bare t.co / expanded URL, almost no prose) are not
# worth saving — same refusal path as empty article stubs.
MIN_X_PROSE_CHARS = 20

_X_FAILURE_STUB_MARKER = "View on X for full content."
_ARTICLE_FAILURE_STUB_PREFIX = "[URL content not available]"
_URL_IN_TEXT_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def prose_without_urls(text: str | None) -> str:
    """Strip http(s) URLs and collapse whitespace; leftover is real prose."""
    stripped = _URL_IN_TEXT_RE.sub(" ", text or "")
    return re.sub(r"\s+", " ", stripped).strip()


def is_link_only_text(text: str | None, *, min_prose: int = MIN_X_PROSE_CHARS) -> bool:
    """True when *text* is empty or almost entirely URL(s) with little prose.

    Plain short tweets with no URLs are *not* link-only (they stay usable).
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    if not _URL_IN_TEXT_RE.search(cleaned):
        return False
    return len(prose_without_urls(cleaned)) < min_prose


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
    - ``x``: non-empty non-stub prose (tweets can be short, but bare t.co /
      link-only bodies are refused — enrich or SCRAPE_FAILED)
    """
    cleaned = (text or "").strip()
    if not cleaned or is_scrape_failure_stub(cleaned):
        return False
    if (source or "article").lower() == "x":
        return not is_link_only_text(cleaned)
    return len(cleaned) > MIN_USABLE_ARTICLE_TEXT_CHARS
