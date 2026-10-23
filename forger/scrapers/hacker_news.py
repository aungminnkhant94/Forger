"""Fetch Hacker News item pages via the public Firebase API.

``news.ycombinator.com/item?id=…`` HTML often returns HTTP 419 to datacenter
IPs. The Firebase HN API still exposes title, text, kids, and the submitted
URL. Bookmarking an HN *item* URL keeps the discussion as primary content;
an outbound story URL may be summarized under the discussion but never
replaces it.
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
MAX_TOP_COMMENTS = 12
MAX_REPLY_PER_TOP = 3
# Leave room for a short Linked article block under the discussion.
_LINKED_ARTICLE_BUDGET = 1200

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


def _format_comment_line(by: str | None, body: str, *, indent: int = 0) -> str:
    prefix = "  " * indent
    who = (by or "unknown").strip() or "unknown"
    return f"{prefix}{who}: {body}"


def _collect_discussion_comments(
    kid_ids: list[Any],
    timeout: int,
    *,
    budget: int,
) -> str:
    """Top-level kids plus one reply level, truncated to *budget* chars."""
    if budget <= 0:
        return ""
    lines: list[str] = []
    used = 0
    top_seen = 0
    for kid in kid_ids:
        if top_seen >= MAX_TOP_COMMENTS:
            break
        if not isinstance(kid, int) or kid <= 0:
            continue
        item = _fetch_item(kid, timeout)
        if not item or item.get("deleted") or item.get("dead"):
            continue
        if (item.get("type") or "").strip().lower() != "comment":
            continue
        body = _strip_hn_html(item.get("text") or "")
        if not body:
            continue
        top_seen += 1
        line = _format_comment_line(item.get("by"), body, indent=0)
        if used + len(line) + 1 > budget:
            break
        lines.append(line)
        used += len(line) + 1

        reply_ids = item.get("kids") or []
        reply_seen = 0
        if not isinstance(reply_ids, list):
            continue
        for reply_id in reply_ids:
            if reply_seen >= MAX_REPLY_PER_TOP:
                break
            if not isinstance(reply_id, int) or reply_id <= 0:
                continue
            reply = _fetch_item(reply_id, timeout)
            if not reply or reply.get("deleted") or reply.get("dead"):
                continue
            if (reply.get("type") or "").strip().lower() != "comment":
                continue
            reply_body = _strip_hn_html(reply.get("text") or "")
            if not reply_body:
                continue
            reply_line = _format_comment_line(reply.get("by"), reply_body, indent=1)
            if used + len(reply_line) + 1 > budget:
                return "\n".join(lines).strip()
            lines.append(reply_line)
            used += len(reply_line) + 1
            reply_seen += 1
    return "\n".join(lines).strip()


def _linked_article_block(story_url: str, timeout: int) -> tuple[str, str | None]:
    """Optional short outbound summary. Returns (block, source_suffix)."""
    if is_hn_item_url(story_url):
        return "", None
    from forger.scrapers.article_scraper import scrape_article

    LOGGER.info("HN discussion may append outbound URL %s", story_url)
    followed = scrape_article(story_url, timeout=timeout)
    if not followed.get("success"):
        LOGGER.warning(
            "HN outbound scrape failed for %s (%s); discussion-only",
            story_url,
            followed.get("error") or "unknown",
        )
        return "", None
    art_title = (followed.get("title") or "").strip()
    art_text = (followed.get("text") or "").strip()
    if not art_text:
        return "", None
    header = f"Linked article: {art_title}\n{story_url}" if art_title else f"Linked article: {story_url}"
    # Keep the linked block short so discussion stays primary.
    body = art_text[: max(0, _LINKED_ARTICLE_BUDGET - len(header) - 2)]
    block = f"{header}\n\n{body}".strip()
    suffix = followed.get("source") or "article"
    return block, str(suffix)


def scrape_hn_item(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Scrape an HN item URL via Firebase.

    Discussion (title, submitted URL, Ask/text body, comments) is primary.
    Outbound story pages may be appended as a short ``Linked article:`` block.
    Returns the same dict shape as ``scrape_article``, plus optional
    ``outbound_url`` for overlap warnings on add.
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
    story_url = (item.get("url") or "").strip()
    outbound_url = story_url if (item_type == "story" and story_url) else None

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
        source = "hn-firebase"
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

        header = "\n".join(parts).strip()
        # Reserve space for comments (+ optional linked article).
        linked_block = ""
        linked_suffix = None
        if story_url and not is_hn_item_url(story_url):
            linked_block, linked_suffix = _linked_article_block(story_url, timeout)

        linked_cost = (len(linked_block) + 2) if linked_block else 0
        comment_budget = max(0, MAX_TEXT_LENGTH - len(header) - linked_cost - 20)
        kids = item.get("kids") or []
        comments = ""
        if isinstance(kids, list) and kids and comment_budget > 40:
            comments = _collect_discussion_comments(kids, timeout, budget=comment_budget)

        chunks = [header]
        if comments:
            chunks.append("")
            chunks.append("Comments:")
            chunks.append(comments)
        if linked_block:
            chunks.append("")
            chunks.append(linked_block)
        text = "\n".join(chunks).strip()[:MAX_TEXT_LENGTH]
        source = "hn-firebase"
        if linked_suffix:
            source = f"hn-firebase+{linked_suffix}"
    else:
        # poll / job / unknown — use whatever text we have
        title = title or f"HN {item_type or 'item'}"
        text = body or title
        source = "hn-firebase"

    if not text or len(text) <= MIN_TEXT_CHARS:
        LOGGER.warning("Insufficient HN content for item %s", item_id)
        return _error_result(
            "Insufficient HN content extracted",
            title=title,
            text=text or None,
        )

    LOGGER.info("Successfully scraped HN item %s: %s", item_id, title[:80])
    result = {
        "success": True,
        "title": title[:200],
        "text": text,
        "author": by,
        "source": source,
        "error": None,
    }
    if outbound_url:
        result["outbound_url"] = outbound_url
    return result
