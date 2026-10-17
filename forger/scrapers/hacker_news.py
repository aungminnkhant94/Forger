"""Fetch Hacker News item pages via the public Firebase API.

``news.ycombinator.com/item?id=…`` HTML often returns HTTP 419 to datacenter
IPs. The Firebase HN API still exposes title, text, and the submitted URL.
Stories with an outbound URL are followed through the normal article scraper;
Ask HN / text posts and comments use the API body.
"""
from __future__ import annotations

import html
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests
from requests.exceptions import ConnectionError, HTTPError, RequestException, Timeout

from forger.url_safety import UnsafeURLError, assert_safe_fetch_url

LOGGER = logging.getLogger(__name__)

HN_HOSTS = frozenset({"news.ycombinator.com", "www.news.ycombinator.com"})
FIREBASE_ITEM = "https://hacker-news.firebaseio.com/v0/item/{id}.json"
DEFAULT_TIMEOUT = 15
MAX_TEXT_LENGTH = 5000
MIN_TEXT_CHARS = 200

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def is_hn_item_url(url: str) -> bool:
    """True when *url* is an HN item discussion page (``/item?id=``)."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in HN_HOSTS:
        return False
    if (parts.path or "").rstrip("/") != "/item":
        return False
    return bool(parse_hn_item_id(url))


def parse_hn_item_id(url: str) -> int | None:
    """Return the numeric HN item id, or None."""
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in HN_HOSTS:
        return None
    qs = parse_qs(parts.query or "")
    raw = (qs.get("id") or [None])[0]
    if raw is None:
        return None
    try:
        item_id = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return item_id if item_id > 0 else None


def _error_result(error: str, *, title: str | None = None, text: str | None = None) -> dict:
    return {
        "success": False,
        "title": title,
        "text": text,
        "author": None,
        "source": None,
        "error": error,
    }


def _strip_hn_html(raw: str) -> str:
    """HN text uses a tiny HTML subset (``<p>``, ``<a>``, entities)."""
    text = html.unescape(raw or "")
    text = text.replace("<p>", "\n\n").replace("<P>", "\n\n")
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _fetch_item(item_id: int, timeout: int) -> dict[str, Any] | None:
    api_url = FIREBASE_ITEM.format(id=item_id)
    try:
        assert_safe_fetch_url(api_url)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe HN API URL %s: %s", api_url, e)
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
        return payload if isinstance(payload, dict) else None
    except (Timeout, ConnectionError, HTTPError, RequestException, ValueError) as e:
        LOGGER.warning("HN Firebase fetch failed for %s: %s", item_id, e)
        return None


def _story_title_for_comment(item: dict[str, Any], timeout: int) -> str | None:
    """Walk parents until a story title is found (cap depth)."""
    parent_id = item.get("parent")
    for _ in range(8):
        if not isinstance(parent_id, int) or parent_id <= 0:
            return None
        parent = _fetch_item(parent_id, timeout)
        if not parent:
            return None
        if parent.get("type") == "story" and parent.get("title"):
            return str(parent["title"]).strip() or None
        parent_id = parent.get("parent")
    return None


def scrape_hn_item(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Scrape an HN item URL via Firebase (and follow story URLs).

    Returns the same dict shape as ``scrape_article``. Non-HN URLs or hard
    failures set ``success`` False so the caller can fall back or refuse.
    """
    try:
        assert_safe_fetch_url(url)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe HN URL %s: %s", url, e)
        return _error_result(f"Unsafe URL blocked: {e}")

    item_id = parse_hn_item_id(url)
    if not item_id:
        return _error_result("Not an HN item URL")

    LOGGER.info("Fetching HN item via Firebase: %s (%s)", item_id, url)
    item = _fetch_item(item_id, timeout)
    if not item or item.get("deleted") or item.get("dead"):
        return _error_result("HN item not found or deleted")

    item_type = (item.get("type") or "").strip().lower()
    by = (item.get("by") or "").strip() or None

    # Story with outbound article URL → scrape that page (same content users want).
    story_url = (item.get("url") or "").strip()
    if item_type == "story" and story_url:
        if is_hn_item_url(story_url):
            return _error_result("HN story URL points at another HN item")
        # Local import avoids circular import at module load.
        from forger.scrapers.article_scraper import scrape_article

        LOGGER.info("HN story %s follows outbound URL %s", item_id, story_url)
        followed = scrape_article(story_url, timeout=timeout)
        if followed.get("success"):
            # Keep the article body; prefer HN title when the article title is weak.
            hn_title = (item.get("title") or "").strip()
            art_title = (followed.get("title") or "").strip()
            # HN titles are the bookmark label users saw on the item page.
            title = hn_title or art_title
            return {
                "success": True,
                "title": title,
                "text": followed.get("text"),
                "author": followed.get("author") or by,
                "source": f"hn-firebase+{followed.get('source') or 'article'}",
                "error": None,
            }
        LOGGER.warning(
            "HN outbound scrape failed for %s (%s); falling back to HN metadata",
            story_url,
            followed.get("error") or "unknown",
        )
        # Fall through to metadata-only if the outbound page is blocked.

    title = (item.get("title") or "").strip()
    body = _strip_hn_html(item.get("text") or "")

    if item_type == "comment":
        parent_title = _story_title_for_comment(item, timeout)
        title = parent_title or (f"Comment by {by}" if by else "HN comment")
        if parent_title and by:
            title = f"{parent_title} (comment by {by})"
        parts = []
        if parent_title:
            parts.append(f"On: {parent_title}")
        if by:
            parts.append(f"Comment by {by}")
        parts.append("")
        parts.append(body or "[empty comment]")
        text = "\n".join(parts).strip()[:MAX_TEXT_LENGTH]
    elif item_type == "story":
        title = title or "HN story"
        parts = [f"Hacker News: {title}"]
        if by:
            parts.append(f"Submitted by {by}")
        if story_url:
            parts.append(f"URL: {story_url}")
        if body:
            parts.append("")
            parts.append(body)
        elif story_url:
            parts.append("")
            parts.append(
                f"{title}. Submitted link: {story_url} "
                "(outbound article could not be scraped)."
            )
        text = "\n".join(parts).strip()[:MAX_TEXT_LENGTH]
    else:
        # poll / job / unknown — use whatever text we have
        title = title or f"HN {item_type or 'item'}"
        text = body or title

    if not text or len(text) <= MIN_TEXT_CHARS:
        LOGGER.warning("Insufficient HN content for item %s", item_id)
        return _error_result(
            "Insufficient HN content extracted",
            title=title,
            text=text or None,
        )

    LOGGER.info("Successfully scraped HN item %s: %s", item_id, title[:80])
    return {
        "success": True,
        "title": title[:200],
        "text": text,
        "author": by,
        "source": "hn-firebase",
        "error": None,
    }
