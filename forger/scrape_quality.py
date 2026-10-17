"""Decide whether scraped bookmark text is usable enough to save / compare.

Aligned with article_scraper success rule: title + text with len(text) > 200.
Failed scrapes used to invent stubs like ``Article from example.com`` which
later poisoned DUPLICATE_TOPIC matching — those stubs must not be saved or
used as similarity targets.

Also refuses bot-challenge / captcha interstitial HTML (Cloudflare "Just a
moment…", publisher "Client Challenge", etc.) so challenge trash never enters
the library and agent mode cannot fill it later.
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

# --- Bot-challenge / captcha interstitial detection -------------------------
# Nature/Fastly and Cloudflare return HTTP 200 with enough extracted text to
# pass the >200 char bar; treat those pages as unusable scrapes.

# Source-level markers that never appear in a real article body.
# Note: bare "cdn-cgi/challenge-platform" is too broad — Cloudflare injects
# /cdn-cgi/challenge-platform/scripts/jsd/ (JS detection) on *successful*
# pages (e.g. Substack). Only managed-challenge / orchestrate paths are walls.
_CHALLENGE_HTML_MARKERS = (
    "_cf_chl_opt",
    "cdn-cgi/challenge-platform/h/",
    "cdn-cgi/challenge-platform/orchestrate",
    "cf-browser-verification",
    "/_fs-ch-",  # Fastly / publisher Client Challenge asset prefix
)

# Page titles that are themselves the interstitial.
_CHALLENGE_TITLE_MARKERS = (
    "client challenge",
    "just a moment",
    "attention required! | cloudflare",
    "attention required!",
)

# Visible interstitial copy (survives script/style stripping).
_CHALLENGE_TEXT_PHRASES = (
    "please enable javascript to proceed",
    "enable javascript and cookies to continue",
    "checking your browser before accessing",
    "verifying you are human",
    "needs to review the security of your connection before proceeding",
    "javascript is disabled in your browser",
    "please turn javascript on and reload the page",
)

# Challenge pages are short; a long real article that quotes one phrase once
# should not trip this. Nature Client Challenge extracts ~286 chars.
_CHALLENGE_TEXT_MAX_CHARS = 1500


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


def _normalize_title(title: str | None) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).lower()


def is_bot_challenge_html(html: str | None) -> bool:
    """True when raw HTML is a bot-wall / captcha interstitial, not the page.

    Matches Cloudflare managed-challenge / orchestrate paths and publisher
    Client Challenge pages (e.g. Nature ``/_fs-ch-…`` + title Client Challenge).
    Passive ``/cdn-cgi/challenge-platform/scripts/jsd/`` on otherwise-good
    pages (Substack et al.) is *not* a challenge.
    """
    if not html:
        return False
    haystack = html.lower()
    if any(marker in haystack for marker in _CHALLENGE_HTML_MARKERS):
        return True
    # Title-only HTML signal (no source marker yet, e.g. stripped fixtures).
    title_match = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
    if title_match:
        title = _normalize_title(title_match.group(1))
        if any(marker in title for marker in _CHALLENGE_TITLE_MARKERS):
            return True
    return False


def is_bot_challenge_headers(headers: dict | None) -> bool:
    """True when response headers advertise a Cloudflare Challenge Page."""
    if not headers:
        return False
    # requests uses case-insensitive keys; tolerate plain dicts too.
    for key, value in headers.items():
        if str(key).lower() == "cf-mitigated" and str(value).strip().lower() == "challenge":
            return True
    return False


def is_bot_challenge_content(
    *,
    title: str | None = None,
    text: str | None = None,
    html: str | None = None,
) -> bool:
    """True when title/body/HTML look like a bot challenge interstitial.

    Used both on the raw response (HTML) and on extracted title+text so a
    challenge page that somehow passes length checks still refuses to save.
    """
    if is_bot_challenge_html(html):
        return True
    title_norm = _normalize_title(title)
    if title_norm and any(marker in title_norm for marker in _CHALLENGE_TITLE_MARKERS):
        return True
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    lower = cleaned.lower()
    hits = sum(1 for phrase in _CHALLENGE_TEXT_PHRASES if phrase in lower)
    if hits == 0:
        return False
    # Strong: two+ interstitial phrases, or one phrase on a short page.
    if hits >= 2:
        return True
    return len(cleaned) <= _CHALLENGE_TEXT_MAX_CHARS


def is_usable_scrape_text(text: str | None, *, source: str = "article", title: str | None = None) -> bool:
    """True when *text* is non-stub content worth saving or comparing.

    - Empty / whitespace → not usable
    - Known failure stubs → not usable
    - Bot-challenge / captcha interstitial title+body → not usable
    - ``article`` (and unknown sources): require at least
      ``MIN_USABLE_ARTICLE_TEXT_CHARS`` characters (same bar as the scraper)
    - ``x``: non-empty non-stub prose (tweets can be short, but bare t.co /
      link-only bodies are refused — enrich or SCRAPE_FAILED)
    """
    cleaned = (text or "").strip()
    if not cleaned or is_scrape_failure_stub(cleaned):
        return False
    if is_bot_challenge_content(title=title, text=cleaned):
        return False
    if (source or "article").lower() == "x":
        return not is_link_only_text(cleaned)
    return len(cleaned) > MIN_USABLE_ARTICLE_TEXT_CHARS
