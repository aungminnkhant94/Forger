"""Fetch DOI paper metadata via Crossref when publisher HTML is blocked.

ACS/JACS pages (pubs.acs.org) often return HTTP 403 to plain scrapers;
Nature article HTML is often a Client Challenge interstitial.
Crossref still exposes title, abstract, authors, and journal for the DOI,
which is enough to bookmark without a paywalled PDF.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import unquote, urlsplit

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from forger.url_safety import UnsafeURLError, assert_safe_fetch_url

LOGGER = logging.getLogger(__name__)

CROSSREF_WORKS = "https://api.crossref.org/works"
DEFAULT_TIMEOUT = 15
MAX_TEXT_LENGTH = 5000
MIN_TEXT_CHARS = 200

# Hosts that commonly DOI-gate HTML and are worth trying Crossref first.
_ACS_HOSTS = frozenset(
    {
        "pubs.acs.org",
        "www.pubs.acs.org",
    }
)

# DOI path on ACS: /doi/10.1021/jacs.6c12509, /doi/abs/..., /doi/full/..., /doi/pdf/...
_ACS_DOI_PATH_RE = re.compile(
    r"^/doi/(?:(?:abs|full|pdf|pdfplus)/)?(?P<doi>10\.\d{4,9}/[^\s?#]+)",
    re.IGNORECASE,
)


_NATURE_HOSTS = frozenset(
    {
        "nature.com",
        "www.nature.com",
    }
)

# Nature journal articles: /articles/s41567-026-03465-3 → 10.1038/s41567-026-03465-3
_NATURE_ARTICLE_PATH_RE = re.compile(
    r"^/articles/(?P<id>s\d{4,5}-\d{2,4}-\d{4,6}-[0-9a-z]+)/?$",
    re.IGNORECASE,
)

# Generic doi.org / dx.doi.org
_DOI_ORG_PATH_RE = re.compile(
    r"^/(?P<doi>10\.\d{4,9}/[^\s?#]+)",
    re.IGNORECASE,
)

# Bare DOI anywhere in a URL path or query
_DOI_INLINE_RE = re.compile(
    r"(10\.\d{4,9}/[^\s?#]+)",
    re.IGNORECASE,
)

_JATS_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def is_acs_doi_url(url: str) -> bool:
    """True when *url* is an ACS pubs.acs.org DOI landing page."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in _ACS_HOSTS:
        return False
    return bool(_ACS_DOI_PATH_RE.match(parts.path or ""))


def is_nature_article_url(url: str) -> bool:
    """True when *url* is a Nature journal article page (DOI-bearing)."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in _NATURE_HOSTS:
        return False
    return bool(_NATURE_ARTICLE_PATH_RE.match(parts.path or ""))


def extract_doi_from_url(url: str) -> str | None:
    """Pull a DOI string from ACS, Nature articles, doi.org, or other DOI URLs."""
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None

    host = (parts.hostname or "").lower().rstrip(".")
    path = unquote(parts.path or "")

    if host in _ACS_HOSTS:
        match = _ACS_DOI_PATH_RE.match(path)
        if match:
            return _normalize_doi(match.group("doi"))

    if host in _NATURE_HOSTS:
        match = _NATURE_ARTICLE_PATH_RE.match(path)
        if match:
            return _normalize_doi(f"10.1038/{match.group('id')}")

    if host in {"doi.org", "www.doi.org", "dx.doi.org"}:
        match = _DOI_ORG_PATH_RE.match(path)
        if match:
            return _normalize_doi(match.group("doi"))

    # Last resort: any 10.xxxx/... in path (e.g. other publishers)
    inline = _DOI_INLINE_RE.search(path)
    if inline:
        return _normalize_doi(inline.group(1))
    return None


def _normalize_doi(doi: str) -> str:
    doi = unquote(doi or "").strip().rstrip("/")
    # ACS sometimes appends .pdf or similar in path segments we already stripped;
    # trim trailing punctuation from inline matches.
    doi = doi.rstrip(".,;)")
    return doi


def _error_result(error: str, *, title: str | None = None, text: str | None = None) -> dict:
    return {
        "success": False,
        "title": title,
        "text": text,
        "author": None,
        "source": None,
        "error": error,
    }


def _strip_jats_abstract(raw: str) -> str:
    """Remove JATS/XML tags and a leading 'Abstract' heading from Crossref HTML."""
    text = _JATS_TAG_RE.sub(" ", raw or "")
    text = _WS_RE.sub(" ", text).strip()
    if text.lower().startswith("abstract "):
        text = text[9:].lstrip()
    elif text.lower() == "abstract":
        text = ""
    return text


def _format_authors(authors: list[dict[str, Any]] | None) -> str | None:
    if not authors:
        return None
    names: list[str] = []
    for author in authors[:12]:
        given = (author.get("given") or "").strip()
        family = (author.get("family") or "").strip()
        if given and family:
            names.append(f"{given} {family}")
        elif family:
            names.append(family)
        elif given:
            names.append(given)
    if not names:
        return None
    if len(authors) > 12:
        names.append("et al.")
    return ", ".join(names)


def _build_text(
    *,
    title: str,
    abstract: str,
    authors: str | None,
    journal: str | None,
    doi: str,
    publisher: str | None,
) -> str:
    parts: list[str] = []
    if journal:
        parts.append(f"Journal: {journal}")
    if publisher:
        parts.append(f"Publisher: {publisher}")
    parts.append(f"DOI: {doi}")
    if authors:
        parts.append(f"Authors: {authors}")
    if abstract:
        parts.append("")
        parts.append(abstract)
    elif title:
        # Title alone rarely clears 200 chars; note missing abstract.
        parts.append("")
        parts.append(f"{title} (abstract unavailable via Crossref)")
    text = "\n".join(parts).strip()
    return text[:MAX_TEXT_LENGTH]


def _fetch_crossref(doi: str, timeout: int) -> dict[str, Any] | None:
    # Keep the slash in the DOI path unencoded (Crossref convention).
    api_url = f"{CROSSREF_WORKS}/{doi}"
    try:
        assert_safe_fetch_url(api_url)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe Crossref URL %s: %s", api_url, e)
        return None

    headers = {
        "User-Agent": (
            "Forger/1.0 (https://github.com/aungminnkhant94/Forger; "
            "mailto:forger@users.noreply.github.com)"
        ),
        "Accept": "application/json",
    }
    try:
        response = requests.get(api_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return payload.get("message") if isinstance(payload, dict) else None
    except (Timeout, ConnectionError, HTTPError, RequestException, ValueError) as e:
        LOGGER.warning("Crossref request failed for %s: %s", doi, e)
        return None


def scrape_doi_metadata(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Scrape title/abstract for a DOI-bearing URL via Crossref.

    Returns the same dict shape as ``scrape_article``. On non-DOI URLs or
    hard failures, ``success`` is False so the caller can fall back or fail.
    """
    try:
        assert_safe_fetch_url(url)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe DOI URL %s: %s", url, e)
        return _error_result(f"Unsafe URL blocked: {e}")

    doi = extract_doi_from_url(url)
    if not doi:
        return _error_result("No DOI found in URL")

    LOGGER.info("Fetching DOI metadata via Crossref: %s (%s)", doi, url)
    message = _fetch_crossref(doi, timeout)
    if not message:
        return _error_result("Crossref metadata lookup failed")

    titles = message.get("title") or []
    title = (titles[0] if titles else "").strip()
    title = _WS_RE.sub(" ", title).strip()
    if not title:
        return _error_result("Crossref returned no title")

    abstract = _strip_jats_abstract(message.get("abstract") or "")
    authors = _format_authors(message.get("author"))
    containers = message.get("container-title") or []
    journal = _WS_RE.sub(" ", (containers[0] if containers else "")).strip() or None
    publisher = (message.get("publisher") or "").strip() or None
    resolved_doi = (message.get("DOI") or doi).strip()

    # Nature: title+journal+DOI alone is not content. Require a real abstract.
    if resolved_doi.lower().startswith("10.1038/") and not abstract:
        LOGGER.warning("Crossref has no abstract for Nature DOI %s; refusing", doi)
        return _error_result("Crossref has no abstract for Nature DOI", title=title)

    text = _build_text(
        title=title,
        abstract=abstract,
        authors=authors,
        journal=journal,
        doi=resolved_doi,
        publisher=publisher,
    )

    if not text or len(text) <= MIN_TEXT_CHARS:
        LOGGER.warning("Insufficient Crossref content for %s", doi)
        return _error_result(
            "Insufficient Crossref content extracted",
            title=title,
            text=text or None,
        )

    display_title = title
    if journal and journal.lower() not in title.lower():
        display_title = f"{title} ({journal})"

    LOGGER.info("Successfully scraped DOI metadata: %s", display_title[:80])
    return {
        "success": True,
        "title": display_title,
        "text": text,
        "author": authors,
        "source": "crossref-doi-metadata",
        "error": None,
    }
