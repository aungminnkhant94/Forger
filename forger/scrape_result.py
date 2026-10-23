"""The single typed boundary between scrapers and saved bookmarks.

Scrapers keep their internal dict payloads; callers outside ``forger/scrapers``
must go through :func:`scrape_url`, which returns either :class:`Saved` (content
worth keeping, with a URL-free prose title) or :class:`Refused` (with a reason).
``Saved`` checks its own invariants, so trash or a t.co title cannot be built,
and there is no "Article from host" / raw-body title fallback to copy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Literal, Optional, Union

from forger.scrape_quality import (
    is_bot_challenge_content,
    is_link_only_text,
    is_scrape_failure_stub,
    is_usable_scrape_text,
    prose_without_urls,
)

LOGGER = logging.getLogger(__name__)

Source = Literal["x", "article"]
_TITLE_MAX = 80
_PLACEHOLDER_TITLES = {"x post"}


class RefuseReason(str, Enum):
    FETCH_FAILED = "fetch_failed"
    CHALLENGE = "challenge"
    EMPTY = "empty"
    STUB = "stub"
    LINK_ONLY = "link_only"
    THIN = "thin"
    NO_TITLE = "no_title"


@dataclass(frozen=True, slots=True)
class Refused:
    source: Source
    url: str
    reason: RefuseReason
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Saved:
    source: Source
    url: str
    text: str
    title: str
    via: Optional[str] = None
    author: Optional[str] = None
    outbound_url: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.title or prose_without_urls(self.title) != self.title:
            raise ValueError(f"Saved.title must be non-empty URL-free prose, got {self.title!r}")
        if not is_usable_scrape_text(self.text, source=self.source, title=self.title):
            raise ValueError("Saved.text is empty/stub/challenge/thin; return Refused instead")


ScrapeOutcome = Union[Saved, Refused]


def source_for_url(url: str) -> Source:
    lower = (url or "").lower()
    return "x" if ("x.com/" in lower or "twitter.com/" in lower) else "article"


def _title_from(raw_title: Optional[str], body: str) -> str:
    title = prose_without_urls(raw_title)
    if title and title.lower() not in _PLACEHOLDER_TITLES:
        return title
    for line in body.split("\n"):
        prose = prose_without_urls(line)
        if prose and not prose.lower().startswith("quoting @"):
            if len(prose) <= _TITLE_MAX:
                return prose
            cut = prose[: _TITLE_MAX - 3]
            space = cut.rfind(" ")
            return (cut[:space] if space > _TITLE_MAX // 2 else cut).rstrip(" .,;:") + "..."
    return ""


def classify(source: Source, url: str, raw: Optional[dict]) -> ScrapeOutcome:
    """Turn a scraper's dict payload into Saved or Refused."""
    raw = raw or {}
    error = str(raw.get("error") or "")
    if not raw.get("success"):
        reason = RefuseReason.CHALLENGE if "challenge" in error.lower() else RefuseReason.FETCH_FAILED
        return Refused(source, url, reason, error or "scraper reported failure")
    body = str(raw.get("text") or "").strip()
    raw_title = raw.get("title")
    if not body:
        return Refused(source, url, RefuseReason.EMPTY)
    if is_scrape_failure_stub(body):
        return Refused(source, url, RefuseReason.STUB)
    if is_bot_challenge_content(title=raw_title, text=body):
        return Refused(source, url, RefuseReason.CHALLENGE, str(raw_title or ""))
    if source == "x" and is_link_only_text(body):
        return Refused(source, url, RefuseReason.LINK_ONLY)
    if not is_usable_scrape_text(body, source=source, title=raw_title):
        return Refused(source, url, RefuseReason.THIN, f"{len(body)} chars")
    title = _title_from(raw_title, body)
    if not title:
        return Refused(source, url, RefuseReason.NO_TITLE)
    author = raw.get("author")
    outbound = raw.get("outbound_url")
    outbound_url = str(outbound).strip() if outbound else None
    return Saved(
        source=source,
        url=url,
        text=body,
        title=title,
        via=raw.get("source"),
        author=str(author) if author else None,
        outbound_url=outbound_url or None,
    )


def scrape_url(url: str) -> ScrapeOutcome:
    """Fetch *url* with the right scraper and return a typed outcome."""
    source = source_for_url(url)
    try:
        if source == "x":
            from forger.scrapers import x_scraper

            raw = x_scraper.fetch_x_content_sync(url)
            outcome = classify(source, url, raw)
        else:
            # P5: PubChem adapter returns ScrapeOutcome directly (no success dict).
            from forger.scrapers.pubchem import is_pubchem_compound_url, scrape_pubchem_compound

            if is_pubchem_compound_url(url):
                outcome = scrape_pubchem_compound(url)
                if isinstance(outcome, Saved):
                    return outcome
                # PUG REST refused — HTML fallback without re-entering PubChem.
                from forger.scrapers import article_scraper

                raw = article_scraper.scrape_article(url, skip_pubchem=True)
                outcome = classify(source, url, raw)
            else:
                from forger.scrapers import article_scraper

                raw = article_scraper.scrape_article(url)
                outcome = classify(source, url, raw)
    except Exception as e:  # scrapers wrap network libs; any raise is a failed fetch
        LOGGER.warning("Scrape raised for %s: %s", url, e)
        return Refused(source, url, RefuseReason.FETCH_FAILED, str(e))
    if isinstance(outcome, Refused):
        LOGGER.warning("Refusing scrape for %s: %s %s", url, outcome.reason.value, outcome.detail)
    return outcome
