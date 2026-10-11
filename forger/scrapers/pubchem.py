"""Fetch PubChem compound pages via PUG REST (public JSON API).

Compound HTML pages are JS-heavy and often blocked by bot challenges, so
requests+BeautifulSoup yields empty/thin scrapes. PUG REST returns title,
description, and key properties as plain structured text.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from forger.url_safety import UnsafeURLError, assert_safe_fetch_url

LOGGER = logging.getLogger(__name__)

PUBCHEM_HOST = "pubchem.ncbi.nlm.nih.gov"
PUG_REST_PREFIX = f"https://{PUBCHEM_HOST}/rest/pug"
DEFAULT_TIMEOUT = 15
# Keep in sync with article_scraper / scrape_quality usable-text bar.
MAX_TEXT_LENGTH = 5000
MIN_TEXT_CHARS = 200

# Properties that read well as bookmark body text.
_PROPERTY_TAGS = (
    "Title,MolecularFormula,MolecularWeight,IUPACName,"
    "SMILES,InChIKey,XLogP,TPSA,HBondDonorCount,HBondAcceptorCount"
)

# Human-readable labels for property keys in the JSON response.
_PROPERTY_LABELS = {
    "CID": "PubChem CID",
    "Title": "Title",
    "MolecularFormula": "Molecular Formula",
    "MolecularWeight": "Molecular Weight",
    "IUPACName": "IUPAC Name",
    "SMILES": "SMILES",
    "InChIKey": "InChIKey",
    "XLogP": "XLogP",
    "TPSA": "TPSA",
    "HBondDonorCount": "H-Bond Donors",
    "HBondAcceptorCount": "H-Bond Acceptors",
}

_COMPOUND_PATH_RE = re.compile(
    r"^/compound/(?P<ref>[^/?#]+)/?",
    re.IGNORECASE,
)


def is_pubchem_compound_url(url: str) -> bool:
    """True when *url* is a PubChem compound summary page."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host != PUBCHEM_HOST:
        return False
    return bool(_COMPOUND_PATH_RE.match(parts.path or ""))


def parse_pubchem_compound_ref(url: str) -> tuple[str, str] | None:
    """Return ``(\"cid\", \"2519\")`` or ``(\"name\", \"caffeine\")``, or None."""
    if not is_pubchem_compound_url(url):
        return None
    parts = urlsplit(url.strip())
    match = _COMPOUND_PATH_RE.match(parts.path or "")
    if not match:
        return None
    raw = unquote(match.group("ref")).strip()
    if not raw:
        return None
    if raw.isdigit():
        return ("cid", raw)
    return ("name", raw)


def _error_result(error: str, *, title: str | None = None, text: str | None = None) -> dict:
    return {
        "success": False,
        "title": title,
        "text": text,
        "author": None,
        "source": None,
        "error": error,
    }


def _fetch_json(api_url: str, timeout: int) -> dict[str, Any] | None:
    """GET *api_url* as JSON after a safety check. Returns None on failure."""
    try:
        assert_safe_fetch_url(api_url)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe PubChem API URL %s: %s", api_url, e)
        return None
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; Forger/1.0; +https://github.com/aungminnkhant94/Forger)"
        ),
        "Accept": "application/json",
    }
    try:
        response = requests.get(api_url, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except (Timeout, ConnectionError, HTTPError, RequestException, ValueError) as e:
        LOGGER.warning("PubChem API request failed for %s: %s", api_url, e)
        return None


def _format_properties(props: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, label in _PROPERTY_LABELS.items():
        if key not in props or props[key] is None or props[key] == "":
            continue
        lines.append(f"{label}: {props[key]}")
    return lines


def _extract_descriptions(desc_json: dict[str, Any] | None) -> list[tuple[str, str | None]]:
    """Return list of (description, source_name) pairs."""
    if not desc_json:
        return []
    out: list[tuple[str, str | None]] = []
    for item in (desc_json.get("InformationList") or {}).get("Information") or []:
        description = (item.get("Description") or "").strip()
        if not description:
            continue
        source = (item.get("DescriptionSourceName") or "").strip() or None
        out.append((description, source))
    return out


def _build_text(
    props: dict[str, Any],
    descriptions: list[tuple[str, str | None]],
) -> str:
    parts = _format_properties(props)
    if descriptions:
        parts.append("")
        parts.append("Description:")
        for description, source in descriptions:
            if source:
                parts.append(f"{description} (Source: {source})")
            else:
                parts.append(description)
    text = "\n".join(parts).strip()
    return text[:MAX_TEXT_LENGTH]


def scrape_pubchem_compound(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Scrape a PubChem compound URL via PUG REST.

    Returns the same dict shape as ``scrape_article``. On non-compound URLs
    or hard failures, ``success`` is False so the caller can fall back to HTML.
    """
    try:
        assert_safe_fetch_url(url)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe PubChem URL %s: %s", url, e)
        return _error_result(f"Unsafe URL blocked: {e}")

    ref = parse_pubchem_compound_ref(url)
    if ref is None:
        return _error_result("Not a PubChem compound URL")

    kind, value = ref
    if kind == "cid":
        ident_path = f"compound/cid/{value}"
    else:
        ident_path = f"compound/name/{quote(value, safe='')}"

    props_url = f"{PUG_REST_PREFIX}/{ident_path}/property/{_PROPERTY_TAGS}/JSON"
    desc_url = f"{PUG_REST_PREFIX}/{ident_path}/description/JSON"

    LOGGER.info("Fetching PubChem compound via PUG REST: %s", url)
    props_json = _fetch_json(props_url, timeout)
    if not props_json:
        return _error_result("PubChem property lookup failed")

    properties_list = (props_json.get("PropertyTable") or {}).get("Properties") or []
    if not properties_list:
        return _error_result("PubChem returned no compound properties")
    props = properties_list[0]

    # Description is best-effort; properties alone can still clear the length bar.
    desc_json = _fetch_json(desc_url, timeout)
    descriptions = _extract_descriptions(desc_json)

    compound_title = (props.get("Title") or "").strip()
    cid = props.get("CID")
    if compound_title and cid is not None:
        display_title = f"{compound_title} (PubChem CID {cid})"
    elif compound_title:
        display_title = compound_title
    elif cid is not None:
        display_title = f"PubChem CID {cid}"
    else:
        display_title = value

    text = _build_text(props, descriptions)
    if not display_title or not text or len(text) <= MIN_TEXT_CHARS:
        LOGGER.warning("Insufficient PubChem content for %s", url)
        return _error_result(
            "Insufficient PubChem content extracted",
            title=display_title or None,
            text=text or None,
        )

    LOGGER.info("Successfully scraped PubChem compound: %s", display_title[:80])
    return {
        "success": True,
        "title": display_title,
        "text": text,
        "author": "PubChem",
        "source": "pubchem-pug-rest",
        "error": None,
    }
