"""Fetch DOI paper metadata via Crossref when publisher HTML is blocked.

ACS/JACS pages (pubs.acs.org) often return HTTP 403 to plain scrapers;
Nature article HTML is often a Client Challenge interstitial;
Cell/ScienceDirect PII URLs lack a DOI in the path but Crossref maps
``alternative-id`` to the DOI. bioRxiv/medRxiv versioned paths
(``…002386v1``, ``…v1.full.pdf``) need suffix stripping before lookup.
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
EUROPEPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
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
# Newer ACS reader paths: /acsodf/article/doi/10.1021/acsomega.6c06602/5455982/<slug>
# — ACS DOI suffixes never contain "/", so stop at the next path segment.
_ACS_DOI_PATH_RE = re.compile(
    r"^(?:/[a-z]+/article)?/doi/(?:(?:abs|full|pdf|pdfplus|epdf)/)?(?P<doi>10\.\d{4,9}/[^\s?#/]+)",
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

# Cell / ScienceDirect PII landing pages (Elsevier).
_ELSEVIER_PII_HOSTS = frozenset(
    {
        "cell.com",
        "www.cell.com",
        "sciencedirect.com",
        "www.sciencedirect.com",
    }
)

# /fulltext/S0092-8674(25)00197-7 or /pii/S0092867425001977
_ELSEVIER_PII_PATH_RE = re.compile(
    r"/(?:fulltext|pii)/(?P<pii>S[0-9A-Za-z()\-–]+)/?",
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


def is_elsevier_pii_url(url: str) -> bool:
    """True when *url* is a Cell/ScienceDirect PII article path."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in _ELSEVIER_PII_HOSTS:
        return False
    return bool(_ELSEVIER_PII_PATH_RE.search(parts.path or ""))


def extract_pii_from_url(url: str) -> str | None:
    """Pull an Elsevier PII from cell.com / sciencedirect.com paths."""
    raw = (url or "").strip()
    if not raw:
        return None
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in _ELSEVIER_PII_HOSTS:
        return None
    path = unquote(parts.path or "")
    match = _ELSEVIER_PII_PATH_RE.search(path)
    if not match:
        return None
    pii = (match.group("pii") or "").strip().rstrip("/")
    return pii or None


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
    # bioRxiv/medRxiv (10.1101/) URLs carry HTML/PDF suffixes and version tags
    # (…002386v1.full.pdf) that are not part of the DOI. Other registrants
    # (e.g. chemRxiv 10.26434/…/v1) include versions in the real DOI, so scope it.
    if doi.lower().startswith("10.1101/"):
        doi = re.sub(r"\.full\.pdf$", "", doi, flags=re.IGNORECASE)
        doi = re.sub(r"\.pdf$", "", doi, flags=re.IGNORECASE)
        doi = re.sub(r"\.full$", "", doi, flags=re.IGNORECASE)
        doi = re.sub(r"v\d+$", "", doi, flags=re.IGNORECASE)
    doi = doi.rstrip("/")
    return doi


def _normalize_pii(pii: str) -> str:
    """Crossref alternative-id is the PII with non-alphanumerics stripped."""
    return re.sub(r"[^0-9A-Za-z]", "", pii or "")


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


def _fetch_crossref_by_alternative_id(pii: str, timeout: int) -> dict[str, Any] | None:
    """Resolve Elsevier PII → Crossref work via filter=alternative-id (exact match)."""
    key = _normalize_pii(pii)
    if not key:
        return None
    try:
        assert_safe_fetch_url(CROSSREF_WORKS)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe Crossref URL %s: %s", CROSSREF_WORKS, e)
        return None

    headers = {
        "User-Agent": (
            "Forger/1.0 (https://github.com/aungminnkhant94/Forger; "
            "mailto:forger@users.noreply.github.com)"
        ),
        "Accept": "application/json",
    }
    params = {"filter": f"alternative-id:{key}", "rows": 5}
    try:
        response = requests.get(
            CROSSREF_WORKS, headers=headers, params=params, timeout=timeout
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") if isinstance(payload, dict) else None
        items = (message or {}).get("items") if isinstance(message, dict) else None
        if not isinstance(items, list):
            return None
        for item in items:
            if not isinstance(item, dict):
                continue
            alts = item.get("alternative-id") or []
            if not isinstance(alts, list):
                continue
            # Exact alternative-id match only (Crossref stores stripped PII).
            if any(str(a) == key for a in alts):
                return item
        return None
    except (Timeout, ConnectionError, HTTPError, RequestException, ValueError) as e:
        LOGGER.warning("Crossref alternative-id lookup failed for %s: %s", key, e)
        return None


def _fetch_europepmc_abstract(doi: str, timeout: int) -> str:
    """Abstract for *doi* from Europe PMC, or "" when it has none.

    Crossref often lacks abstracts for Nature papers, and nature.com serves a
    Client Challenge to non-browser TLS clients, so this is the honest
    fallback before refusing.
    """
    try:
        assert_safe_fetch_url(EUROPEPMC_SEARCH)
        response = requests.get(
            EUROPEPMC_SEARCH,
            params={"query": f'DOI:"{doi}"', "resultType": "core", "format": "json"},
            headers={"User-Agent": "Forger/1.0 (https://github.com/aungminnkhant94/Forger)"},
            timeout=timeout,
        )
        response.raise_for_status()
        results = (response.json().get("resultList") or {}).get("result") or []
    except (UnsafeURLError, RequestException, ValueError, AttributeError) as e:
        LOGGER.warning("Europe PMC request failed for %s: %s", doi, e)
        return ""
    for item in results:
        if str(item.get("doi") or "").lower() == doi.lower():
            return _strip_jats_abstract(item.get("abstractText") or "")
    return ""


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
    message: dict[str, Any] | None = None
    if doi:
        LOGGER.info("Fetching DOI metadata via Crossref: %s (%s)", doi, url)
        message = _fetch_crossref(doi, timeout)
    else:
        pii = extract_pii_from_url(url)
        if not pii:
            return _error_result("No DOI found in URL")
        LOGGER.info("Resolving Elsevier PII via Crossref alternative-id: %s (%s)", pii, url)
        message = _fetch_crossref_by_alternative_id(pii, timeout)
        if message:
            doi = (message.get("DOI") or "").strip() or None

    if not message:
        return _error_result("Crossref metadata lookup failed")
    if not doi:
        doi = (message.get("DOI") or "").strip()
    if not doi:
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
        abstract = _fetch_europepmc_abstract(resolved_doi, timeout)
        if abstract:
            LOGGER.info("Using Europe PMC abstract for Nature DOI %s", resolved_doi)
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
