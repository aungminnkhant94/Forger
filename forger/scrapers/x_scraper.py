"""X/Twitter content scraper with cookie-free public APIs first.

ESSENTIAL COMPONENT - See ARCHITECTURE.md before modifying.

Fetch order for status URLs:
1. Twitter syndication JSON (cdn.syndication.twimg.com) — no login
2. Twitter oEmbed (publish.twitter.com) — no login
3. fxtwitter JSON API — no login, third-party mirror
4. Playwright + cookies — optional upgrade when X_COOKIES_PATH has cookies
5. jina.ai text extraction — soft fallback
6. yt-dlp — only if the binary is already installed (not required)

Thin link-only posts (bare t.co / X Articles): merge API ``article``
payloads when present; otherwise resolve outbound links (url_safety) and
scrape the destination with article_scraper. Quote tweets merge nested
``quoted_tweet`` / ``quote`` text into the saved body. Titles are built
from prose with raw t.co / URLs stripped. Still-thin results are refused
(no empty/X Post stubs). Bookmark URL stays the original X status.

Public Forger users can bookmark public tweets without an X login.
Free-proxy fetching was removed earlier; fetches always use a direct connection.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import json
import logging
import math
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from forger.scrapers.x_auth import load_cookies
from forger.scrape_quality import is_link_only_text, prose_without_urls
from forger.url_safety import UnsafeURLError, assert_safe_fetch_url, resolve_redirect_url

LOGGER = logging.getLogger(__name__)

# https://x.com/user/status/123, twitter.com, /i/web/status/123, /statuses/
_STATUS_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:x|twitter)\.com/"
    r"(?:(?P<user>[A-Za-z0-9_]{1,15})/|i/web/)?"
    r"(?:status|statuses)/(?P<id>\d+)",
    re.IGNORECASE,
)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HTTP_TIMEOUT = 15
_MAX_ENRICH_TEXT = 5000
_URL_IN_TEXT_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_X_HOSTS = {
    "x.com",
    "www.x.com",
    "twitter.com",
    "www.twitter.com",
    "mobile.twitter.com",
    "mobile.x.com",
    "t.co",
}


class XScraperError(Exception):
    """Base exception for XScraper errors."""
    pass


class XScraperTimeoutError(XScraperError):
    """Raised when scraping times out."""
    pass


class XScraperPlaywrightError(XScraperError):
    """Raised when Playwright encounters an error."""
    pass


def extract_status_id(url: str) -> Optional[str]:
    """Return the numeric status id from an X/Twitter status URL, or None."""
    parts = extract_status_parts(url)
    return parts[1] if parts else None


def extract_status_parts(url: str) -> Optional[tuple[Optional[str], str]]:
    """Return ``(username_or_None, status_id)`` from a status URL, or None."""
    raw = (url or "").strip()
    if not raw:
        return None
    match = _STATUS_RE.search(raw)
    if not match:
        return None
    user = match.group("user")
    status_id = match.group("id")
    if not status_id:
        return None
    return (user, status_id)


def _syndication_token(status_id: str) -> str:
    """Token expected by cdn.syndication.twimg.com (JS Number.toString(36) style)."""
    n = (int(status_id) / 1e15) * math.pi
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0:
        encoded = "0"
    else:
        neg = n < 0
        n = abs(n)
        ip = int(n)
        frac = n - ip
        int_s = ""
        if ip == 0:
            int_s = "0"
        else:
            while ip:
                ip, rem = divmod(ip, 36)
                int_s = digits[rem] + int_s
        frac_s = ""
        x = frac
        for _ in range(16):
            if x < 1e-12:
                break
            x *= 36
            d = int(x)
            frac_s += digits[d]
            x -= d
        encoded = int_s + (("." + frac_s) if frac_s else "")
        if neg:
            encoded = "-" + encoded
    return encoded.replace(".", "").lstrip("0") or "0"


def _text_from_oembed_html(raw_html: str) -> str:
    """Pull tweet body text out of publish.twitter.com oEmbed HTML."""
    if not raw_html:
        return ""
    match = re.search(r"<p[^>]*>(.*?)</p>", raw_html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    inner = match.group(1)
    inner = re.sub(r"<br\s*/?>", "\n", inner, flags=re.IGNORECASE)
    inner = re.sub(r"<[^>]+>", "", inner)
    return html_lib.unescape(inner).strip()



def _extract_entity_urls(payload: dict | None) -> list[str]:
    """Collect expanded_url / url values from syndication or fxtwitter JSON."""
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    seen: set[str] = set()

    def _add(u: str | None) -> None:
        raw = (u or "").strip()
        if not raw or raw in seen:
            return
        seen.add(raw)
        found.append(raw)

    entities = payload.get("entities")
    if isinstance(entities, dict):
        for item in entities.get("urls") or []:
            if isinstance(item, dict):
                _add(item.get("expanded_url") or item.get("url"))

    # fxtwitter sometimes nests under tweet
    tweet = payload.get("tweet")
    if isinstance(tweet, dict):
        for u in _extract_entity_urls(tweet):
            _add(u)
        # fxtwitter may already expand the body link
        _add(tweet.get("url"))

    return found


def _urls_from_text(text: str | None) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(_URL_IN_TEXT_RE.findall(text)))


def _text_from_x_article(
    article: dict | None,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(title, text, kind)`` from syndication/fxtwitter ``article``.

    *kind* is ``"full"`` when content.blocks are present, ``"preview"`` when
    only preview_text/title are available, or ``None`` when empty.
    """
    if not isinstance(article, dict):
        return None, None, None
    title = (article.get("title") or "").strip() or None
    content = article.get("content")
    if isinstance(content, dict):
        blocks = content.get("blocks") or []
        lines: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            piece = (block.get("text") or "").strip()
            if piece:
                lines.append(piece)
        body = "\n\n".join(lines).strip()
        if body:
            return title, body[:_MAX_ENRICH_TEXT], "full"
    preview = (article.get("preview_text") or "").strip()
    if title and preview:
        return title, f"{title}\n\n{preview}"[:_MAX_ENRICH_TEXT], "preview"
    if preview:
        return title, preview[:_MAX_ENRICH_TEXT], "preview"
    if title:
        return title, None, "preview"
    return None, None, None


def _screen_name_from_user(user_obj: dict | None) -> str | None:
    """Pull screen_name from syndication/fxtwitter user/author objects."""
    if not isinstance(user_obj, dict):
        return None
    legacy = user_obj.get("legacy") if isinstance(user_obj.get("legacy"), dict) else {}
    name = (
        user_obj.get("screen_name")
        or legacy.get("screen_name")
        or user_obj.get("user_screen_name")
    )
    if isinstance(name, str) and name.strip():
        return name.strip().lstrip("@")
    return None


def _extract_quoted_tweet(payload: dict | None) -> tuple[str | None, str | None]:
    """Return ``(screen_name, text)`` from nested quote fields, or ``(None, None)``.

    Syndication uses ``quoted_tweet``; fxtwitter uses ``quote`` (sometimes
    nested under ``tweet``).
    """
    if not isinstance(payload, dict):
        return None, None

    candidates: list[dict] = []
    for key in ("quoted_tweet", "quote", "quoted_status"):
        node = payload.get(key)
        if isinstance(node, dict):
            candidates.append(node)
    tweet = payload.get("tweet")
    if isinstance(tweet, dict):
        for key in ("quoted_tweet", "quote", "quoted_status"):
            node = tweet.get(key)
            if isinstance(node, dict):
                candidates.append(node)

    for qt in candidates:
        text = (qt.get("text") or qt.get("full_text") or "").strip()
        if not text:
            raw = qt.get("raw_text")
            if isinstance(raw, dict):
                text = (raw.get("text") or "").strip()
            elif isinstance(raw, str):
                text = raw.strip()
        if not text:
            continue
        author = _screen_name_from_user(
            qt.get("author") if isinstance(qt.get("author"), dict) else None
        )
        if not author:
            author = _screen_name_from_user(
                qt.get("user") if isinstance(qt.get("user"), dict) else None
            )
        if not author and isinstance(qt.get("user_screen_name"), str):
            author = qt.get("user_screen_name").strip().lstrip("@") or None
        return author, text
    return None, None


def _format_with_quote(outer_text: str, quote_author: str | None, quote_text: str) -> str:
    """Append quoted tweet body under the outer status text."""
    outer = (outer_text or "").strip()
    quoted = (quote_text or "").strip()
    if not quoted:
        return outer
    # Already merged (e.g. Playwright captured both).
    probe = quoted[:120]
    if probe and probe in outer:
        return outer[:_MAX_ENRICH_TEXT]
    author = (quote_author or "").strip().lstrip("@")
    header = f"Quoting @{author}:" if author else "Quoted post:"
    if outer:
        merged = f"{outer}\n\n{header}\n{quoted}"
    else:
        merged = f"{header}\n{quoted}"
    return merged[:_MAX_ENRICH_TEXT]


def _is_x_status_url(url: str) -> bool:
    return extract_status_id(url) is not None


def _is_x_hosted_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return host in _X_HOSTS


def is_thin_x_result(result: dict | None) -> bool:
    """True when an X scrape is link-only / title-less stub content."""
    if not result:
        return True
    text = (result.get("text") or "").strip()
    title = (result.get("title") or "").strip()
    if not text:
        return True
    if is_link_only_text(text):
        return True
    if title in ("", "X Post") and is_link_only_text(text):
        return True
    return False


class XScraper:
    """Scrape X/Twitter content using public APIs, then optional cookie Playwright."""

    def __init__(self):
        self.user_agent = _DEFAULT_UA

    def _merge_x_article(self, result: dict, article: dict | None) -> dict:
        """Prefer X Articles payload when the status body is thin."""
        atitle, atext, kind = _text_from_x_article(article)
        if not atext:
            if atitle and (result.get("title") in (None, "", "X Post")):
                out = dict(result)
                out["title"] = atitle
                out["article_enrichment"] = kind or "preview"
                return out
            return result
        out = dict(result)
        if is_thin_x_result(result) or len(atext) > len((result.get("text") or "").strip()):
            out["text"] = atext
            if atitle:
                out["title"] = atitle
            elif out.get("title") in (None, "", "X Post"):
                out["title"] = self._generate_title(atext)
            src = out.get("source") or ""
            if "x_article" not in src:
                out["source"] = f"{src}+x_article" if src else "x_article"
            out["article_enrichment"] = kind
        elif atitle and out.get("title") in (None, "", "X Post"):
            out["title"] = atitle
            out["article_enrichment"] = kind
        return out

    def _attach_outbound_urls(self, result: dict, *url_lists: list[str]) -> dict:
        urls: list[str] = []
        seen: set[str] = set()
        for group in url_lists:
            for u in group or []:
                raw = (u or "").strip()
                if not raw or raw in seen:
                    continue
                seen.add(raw)
                urls.append(raw)
        # Also pull any bare links still in the body.
        for u in _urls_from_text(result.get("text")):
            if u not in seen:
                seen.add(u)
                urls.append(u)
        out = dict(result)
        if urls:
            out["outbound_urls"] = urls
        return out


    def _better_thin_fallback(self, current: dict | None, candidate: dict) -> dict:
        """Keep the richest thin/preview candidate while the public chain continues."""
        if not current:
            return candidate
        cur_len = len((current.get("text") or "").strip())
        new_len = len((candidate.get("text") or "").strip())
        cur_kind = current.get("article_enrichment")
        new_kind = candidate.get("article_enrichment")
        # Prefer full article body, then preview, then longer prose.
        rank = {None: 0, "preview": 1, "full": 2}
        if rank.get(new_kind, 0) > rank.get(cur_kind, 0):
            return candidate
        if rank.get(new_kind, 0) == rank.get(cur_kind, 0) and new_len > cur_len:
            return candidate
        # Never replace a usable preview with a bare t.co stub.
        if not is_thin_x_result(current) and is_thin_x_result(candidate):
            return current
        if new_len > cur_len:
            return candidate
        return current

    def _enrich_thin_via_outbound_links(self, result: dict) -> dict:
        """Resolve outbound links and scrape destinations for thin X posts.

        Keeps the original X status as the bookmark identity; only title/text
        are replaced. Skips X status URLs (no infinite loop) and X-hosted
        HTML pages that do not scrape cleanly (prefer API article payload).
        """
        if not is_thin_x_result(result):
            return result

        candidates = list(result.get("outbound_urls") or [])
        for u in _urls_from_text(result.get("text")):
            if u not in candidates:
                candidates.append(u)
        if not candidates:
            return result

        try:
            from forger.scrapers.article_scraper import scrape_article
        except ImportError:
            LOGGER.warning("article_scraper unavailable for X link enrich")
            return result

        for raw in candidates[:3]:
            try:
                try:
                    resolved = resolve_redirect_url(raw)  # redirect-friendly UA (Chrome UA breaks t.co)
                except UnsafeURLError as e:
                    LOGGER.info("Skip unsafe outbound link %s: %s", raw, e)
                    continue
                except Exception as e:
                    LOGGER.info("Redirect resolve failed for %s: %s", raw, e)
                    resolved = raw
                    try:
                        assert_safe_fetch_url(resolved)
                    except UnsafeURLError:
                        continue

                if _is_x_status_url(resolved):
                    LOGGER.info("Skip outbound X status (loop guard): %s", resolved)
                    continue
                if _is_x_hosted_url(resolved):
                    # x.com/i/article etc. — HTML scrape is a login/404 wall;
                    # API article payload should already have been merged.
                    LOGGER.info("Skip X-hosted outbound HTML scrape: %s", resolved)
                    continue

                scraped = scrape_article(resolved)
                if not scraped or not scraped.get("success"):
                    LOGGER.info(
                        "Outbound scrape failed for %s: %s",
                        resolved,
                        (scraped or {}).get("error"),
                    )
                    continue
                body = (scraped.get("text") or "").strip()
                title = (scraped.get("title") or "").strip()
                if is_link_only_text(body) or len(body) < 50:
                    continue
                out = dict(result)
                out["text"] = body[:_MAX_ENRICH_TEXT]
                if title:
                    out["title"] = title
                else:
                    out["title"] = self._generate_title(body)
                src = out.get("source") or "x"
                out["source"] = f"{src}+link" if "+link" not in src else src
                out["outbound_resolved"] = resolved
                out.pop("outbound_urls", None)
                LOGGER.info(
                    "Enriched thin X post via outbound link (%s chars from %s)",
                    len(out["text"]),
                    resolved,
                )
                return out
            except Exception as e:
                LOGGER.warning("Outbound enrich error for %s: %s", raw, e)
                continue
        return result

    def _refuse_if_thin(self, result: dict) -> dict:
        """Convert still-thin successes into failures (no empty/link stubs)."""
        if not result.get("success"):
            return result
        if not is_thin_x_result(result):
            # Drop internal enrich hints before returning to callers.
            out = dict(result)
            out.pop("outbound_urls", None)
            out.pop("article_enrichment", None)
            out.pop("quote_enrichment", None)
            return out
        LOGGER.warning(
            "Refusing thin link-only X scrape (title=%r text_len=%s)",
            result.get("title"),
            len(result.get("text") or ""),
        )
        return self._error_result(
            "Thin link-only X post; outbound enrich failed or unavailable"
        )

    async def fetch_tweet(self, url: str) -> dict:
        """Fetch tweet content from an X/Twitter status URL.

        Returns:
            dict with keys: text, author, title, success, error, source
        """
        try:
            assert_safe_fetch_url(url)
        except UnsafeURLError as e:
            LOGGER.error("Refusing unsafe X URL %s: %s", url, e)
            return self._error_result(f"Unsafe URL blocked: {e}")

        # Method 1–3: cookie-free public endpoints (preferred for public tweets)
        result = self._fetch_with_public_apis(url)
        if result.get("success") and not is_thin_x_result(result):
            return self._refuse_if_thin(result)

        # Method 4: Playwright only when cookies exist (optional upgrade)
        cookies = load_cookies()
        if cookies:
            LOGGER.info("Public APIs missed; trying Playwright with %d cookies...", len(cookies))
            pw = await self._fetch_with_playwright(url, cookies=cookies)
            if pw.get("success") and not is_thin_x_result(pw):
                return self._refuse_if_thin(pw)
            if pw.get("success"):
                result = pw
        else:
            LOGGER.info("No X cookies — skipping Playwright (login wall without cookies)")

        # Method 5: jina.ai
        LOGGER.info("Trying jina.ai fallback...")
        jina = self._fetch_with_jina(url)
        if jina.get("success") and not is_thin_x_result(jina):
            return self._refuse_if_thin(jina)
        if jina.get("success"):
            result = jina

        # Method 6: yt-dlp only if already installed
        if shutil.which("yt-dlp"):
            LOGGER.info("Trying yt-dlp fallback...")
            yt = self._fetch_with_ytdlp(url)
            if yt.get("success") and not is_thin_x_result(yt):
                return self._refuse_if_thin(yt)
            if yt.get("success"):
                result = yt
        else:
            LOGGER.info("yt-dlp not installed — skipping (not required)")

        if result.get("success"):
            # Last chance: follow outbound t.co / expanded_url.
            result = self._enrich_thin_via_outbound_links(result)
            return self._refuse_if_thin(result)

        LOGGER.error("All methods failed for: %s", url)
        return self._error_result("X content extraction blocked - manual review needed")

    def _fetch_with_public_apis(self, url: str) -> dict:
        """Try syndication → oEmbed → fxtwitter without any X cookies.

        Thin link-only successes do not short-circuit the chain — fxtwitter
        often carries the full X Articles body that syndication only previews.
        """
        parts = extract_status_parts(url)
        if not parts:
            return self._error_result("Not an X/Twitter status URL")
        user, status_id = parts

        thin_fallback = None
        for name, fetcher in (
            ("syndication", lambda: self._fetch_with_syndication(status_id, user)),
            ("oembed", lambda: self._fetch_with_oembed(url, user)),
            ("fxtwitter", lambda: self._fetch_with_fxtwitter(status_id, user)),
        ):
            try:
                result = fetcher()
            except Exception as e:
                LOGGER.warning("%s fetch raised: %s", name, e)
                continue
            if not result.get("success"):
                LOGGER.info("%s unavailable: %s", name, result.get("error"))
                continue
            # Preview-only X Articles are usable but incomplete — keep
            # trying fxtwitter which often has full content.blocks.
            preview_only = result.get("article_enrichment") == "preview"
            if not is_thin_x_result(result) and not preview_only:
                LOGGER.info("Fetched via %s (%s chars)", name, len(result.get("text") or ""))
                out = dict(result)
                out.pop("article_enrichment", None)
                out.pop("quote_enrichment", None)
                out.pop("outbound_urls", None)
                return out
            LOGGER.info(
                "%s returned thin/preview content (%s chars, enrichment=%s); trying next source",
                name,
                len(result.get("text") or ""),
                result.get("article_enrichment"),
            )
            thin_fallback = self._better_thin_fallback(thin_fallback, result)

        if thin_fallback:
            enriched = self._enrich_thin_via_outbound_links(thin_fallback)
            if enriched.get("success") and not is_thin_x_result(enriched):
                LOGGER.info(
                    "Thin X post enriched via outbound link (%s chars)",
                    len(enriched.get("text") or ""),
                )
                out = dict(enriched)
                out.pop("article_enrichment", None)
                out.pop("quote_enrichment", None)
                out.pop("outbound_urls", None)
                return out
            # Keep a usable preview even if outbound follow failed.
            if thin_fallback.get("success") and not is_thin_x_result(thin_fallback):
                out = dict(thin_fallback)
                out.pop("article_enrichment", None)
                out.pop("quote_enrichment", None)
                out.pop("outbound_urls", None)
                return out
            return enriched
        return self._error_result("Public X APIs returned no usable content")

    def _http_get_json(self, api_url: str) -> Optional[dict]:
        """GET *api_url* as JSON after url_safety check. None on failure."""
        try:
            assert_safe_fetch_url(api_url)
        except UnsafeURLError as e:
            LOGGER.error("Refusing unsafe API URL %s: %s", api_url, e)
            return None
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as response:
                body = response.read().decode("utf-8", errors="replace")
            if not body.strip() or body.strip() == "{}":
                return None
            data = json.loads(body)
            return data if isinstance(data, dict) else None
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as e:
            LOGGER.warning("HTTP JSON fetch failed for %s: %s", api_url, e)
            return None

    def _fetch_with_syndication(self, status_id: str, user: Optional[str]) -> dict:
        """Twitter CDN syndication JSON (no auth)."""
        tokens = [_syndication_token(status_id), "0"]
        data = None
        for token in tokens:
            api_url = (
                "https://cdn.syndication.twimg.com/tweet-result"
                f"?id={urllib.parse.quote(status_id)}&lang=en&token={urllib.parse.quote(token)}"
            )
            data = self._http_get_json(api_url)
            if data and (data.get("text") or data.get("full_text")):
                break
        if not data:
            return self._error_result("syndication empty")

        text = (data.get("text") or data.get("full_text") or "").strip()
        if not text:
            return self._error_result("syndication no text")

        q_author, q_text = _extract_quoted_tweet(data)
        if q_text:
            text = _format_with_quote(text, q_author, q_text)

        author = user
        user_obj = data.get("user")
        if isinstance(user_obj, dict):
            legacy = user_obj.get("legacy") if isinstance(user_obj.get("legacy"), dict) else {}
            author = (
                user_obj.get("screen_name")
                or legacy.get("screen_name")
                or author
            )

        result = {
            "success": True,
            "text": text,
            "author": (author or "").lstrip("@") or None,
            "title": self._generate_title(text),
            "error": None,
            "source": "syndication",
        }
        if q_text:
            result["quote_enrichment"] = True
        result = self._merge_x_article(result, data.get("article") if isinstance(data.get("article"), dict) else None)
        return self._attach_outbound_urls(result, _extract_entity_urls(data))

    def _fetch_with_oembed(self, url: str, user: Optional[str]) -> dict:
        """Official publish.twitter.com oEmbed HTML → plain text."""
        api_url = (
            "https://publish.twitter.com/oembed?"
            + urllib.parse.urlencode({"url": url, "omit_script": "true"})
        )
        data = self._http_get_json(api_url)
        if not data:
            return self._error_result("oembed empty")

        text = _text_from_oembed_html(data.get("html") or "")
        if not text:
            return self._error_result("oembed no text")

        author = user
        author_url = data.get("author_url") or ""
        if author_url:
            tail = author_url.rstrip("/").split("/")[-1]
            if tail and re.fullmatch(r"[A-Za-z0-9_]{1,15}", tail):
                author = tail

        result = {
            "success": True,
            "text": text,
            "author": (author or "").lstrip("@") or None,
            "title": self._generate_title(text),
            "error": None,
            "source": "oembed",
        }
        return self._attach_outbound_urls(result, _urls_from_text(text))

    def _fetch_with_fxtwitter(self, status_id: str, user: Optional[str]) -> dict:
        """fxtwitter / FixupX public JSON mirror."""
        path_user = user or "i"
        api_url = f"https://api.fxtwitter.com/{urllib.parse.quote(path_user)}/status/{urllib.parse.quote(status_id)}"
        data = self._http_get_json(api_url)
        if not data:
            return self._error_result("fxtwitter empty")

        tweet = data.get("tweet") if isinstance(data.get("tweet"), dict) else data
        if not isinstance(tweet, dict):
            return self._error_result("fxtwitter bad shape")

        text = (tweet.get("text") or tweet.get("full_text") or "").strip()
        if not text:
            return self._error_result("fxtwitter no text")

        q_author, q_text = _extract_quoted_tweet(data)
        if not q_text:
            q_author, q_text = _extract_quoted_tweet(tweet)
        if q_text:
            text = _format_with_quote(text, q_author, q_text)

        author = user
        author_obj = tweet.get("author")
        if isinstance(author_obj, dict):
            author = author_obj.get("screen_name") or author
        else:
            author = tweet.get("user_screen_name") or author

        result = {
            "success": True,
            "text": text,
            "author": (author or "").lstrip("@") or None,
            "title": self._generate_title(text),
            "error": None,
            "source": "fxtwitter",
        }
        if q_text:
            result["quote_enrichment"] = True
        article = tweet.get("article") if isinstance(tweet.get("article"), dict) else None
        result = self._merge_x_article(result, article)
        return self._attach_outbound_urls(
            result,
            _extract_entity_urls(data),
            _extract_entity_urls(tweet),
            _urls_from_text(text),
        )

    async def _fetch_with_playwright(self, url: str, cookies: Optional[list] = None) -> dict:
        """Playwright with stealth; call only when cookies are available."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            LOGGER.warning("Playwright not installed: %s", e)
            return self._error_result("Playwright not installed")

        browser = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-accelerated-2d-canvas",
                        "--disable-gpu",
                    ],
                )

                context = await browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="America/New_York",
                )

                if cookies:
                    LOGGER.info("Adding %d saved X cookies...", len(cookies))
                    await context.add_cookies(cookies)

                page = await context.new_page()

                await page.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    window.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['en-US', 'en']
                    });
                    Object.defineProperty(navigator, 'platform', {
                        get: () => 'Win32'
                    });
                    const originalQuery = window.navigator.permissions.query;
                    window.navigator.permissions.query = (parameters) => (
                        parameters.name === 'notifications' ?
                            Promise.resolve({ state: Notification.permission }) :
                            originalQuery(parameters)
                    );
                    """
                )

                LOGGER.info("Fetching with Playwright: %s", url)
                await asyncio.sleep(2)

                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    LOGGER.warning("Navigation error: %s", e)

                await asyncio.sleep(3)
                article = None
                try:
                    article = await page.wait_for_selector(
                        "article[data-testid='tweet']", timeout=10_000
                    )
                except Exception:
                    LOGGER.warning("tweet article did not render within 10s")

                page_text = await page.inner_text("body")

                if "log in" in page_text.lower() and "Don't miss" in page_text:
                    LOGGER.warning("X login wall — cookies may be expired")
                    return self._error_result("X requires login - cookies likely expired")

                tweet_text = (await article.inner_text()) if article else ""
                if not tweet_text.strip():
                    tweet_text = page_text
                    if "to view keyboard shortcuts" in tweet_text.lower():
                        LOGGER.warning("Only X UI chrome rendered (no article) — treating as gate")
                        return self._error_result("X rendered UI chrome only - post never appeared")

                author = None
                parts = extract_status_parts(url)
                if parts and parts[0]:
                    author = parts[0]
                else:
                    try:
                        url_parts = url.split("/")
                        if len(url_parts) > 3:
                            author = url_parts[3].replace("@", "")
                    except Exception:
                        pass

                tweet_text = tweet_text.strip()
                if tweet_text and len(tweet_text) > 100 and not any(
                    gate in tweet_text.lower()
                    for gate in [
                        "click to subscribe",
                        "subscribe to",
                        "log in",
                        "sign up",
                        "create account",
                        "join now",
                        "get started",
                    ]
                ):
                    return {
                        "success": True,
                        "text": tweet_text,
                        "author": author,
                        "title": self._generate_title(tweet_text),
                        "error": None,
                        "source": "playwright",
                    }
                LOGGER.warning(
                    "Playwright got gate/paywall text (%s chars), trying fallback...",
                    len(tweet_text),
                )
                return self._error_result("Playwright hit subscribe gate")

        except Exception as e:
            LOGGER.error("Playwright error: %s", e)
            return self._error_result(f"Playwright failed: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass

    def _fetch_with_jina(self, url: str) -> dict:
        """Try jina.ai summarizer as fallback for text extraction."""
        try:
            jina_url = f"https://r.jina.ai/http://{url.replace('https://', '').replace('http://', '')}"
            LOGGER.info("Trying jina.ai: %s", jina_url)
            try:
                assert_safe_fetch_url(jina_url)
            except UnsafeURLError as e:
                return self._error_result(f"Unsafe jina URL blocked: {e}")

            req = urllib.request.Request(
                jina_url,
                headers={"User-Agent": self.user_agent},
            )

            with urllib.request.urlopen(req, timeout=20) as response:
                content = response.read().decode("utf-8")

            if content and len(content) > 50:
                lines = content.split("\n")
                title = "X Post"
                author = None
                text_lines = []

                for line in lines:
                    line = line.strip()
                    if line.startswith("Title: "):
                        title = line.replace("Title: ", "").replace(" / X", "").strip()
                    elif line.startswith("URL Source:"):
                        continue
                    elif line.startswith("Published Time:"):
                        continue
                    elif line.startswith("Markdown Content:"):
                        continue
                    elif line and not line.startswith("![") and not line.startswith("["):
                        text_lines.append(line)

                text = "\n".join(text_lines).strip()

                if text:
                    return {
                        "success": True,
                        "text": text,
                        "author": author,
                        "title": title if title != "X Post" else self._generate_title(text),
                        "error": None,
                        "source": "jina",
                    }

            LOGGER.warning("jina.ai returned no usable content")
            return self._error_result("jina.ai failed")

        except Exception as e:
            LOGGER.warning("jina.ai error: %s", e)
            return self._error_result(f"jina.ai error: {e}")

    def _fetch_with_ytdlp(self, url: str) -> dict:
        """Try yt-dlp when the binary is present (optional, not required)."""
        try:
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--quiet",
                url,
            ]

            LOGGER.info("Trying yt-dlp: %s", url)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout.strip().split("\n")[0])

                title = data.get("title", "")
                description = data.get("description", "")
                uploader = data.get("uploader", "")

                text = description or title

                if text:
                    return {
                        "success": True,
                        "text": text.strip(),
                        "author": uploader.replace("@", ""),
                        "title": self._generate_title(text),
                        "error": None,
                        "source": "yt-dlp",
                    }

            LOGGER.warning("yt-dlp failed or returned no content")
            return self._error_result("yt-dlp failed")

        except subprocess.TimeoutExpired:
            LOGGER.warning("yt-dlp timed out")
            return self._error_result("yt-dlp timeout")
        except Exception as e:
            LOGGER.warning("yt-dlp error: %s", e)
            return self._error_result(f"yt-dlp error: {e}")

    def _generate_title(self, text: str, max_length: int = 80) -> str:
        """Generate title from tweet prose; never keep raw t.co / URLs."""
        if not text:
            return "X Post"

        first_line = ""
        for line in text.split("\n"):
            cleaned = prose_without_urls(line).strip()
            if not cleaned:
                continue
            # Skip the quote-merge header line.
            if cleaned.lower().startswith("quoting @") or cleaned.lower() == "quoted post:":
                continue
            if cleaned.startswith("http://") or cleaned.startswith("https://"):
                continue
            first_line = cleaned
            break

        if not first_line:
            return "X Post"

        for punct in [". ", "? ", "! "]:
            idx = first_line[:max_length].rfind(punct)
            if idx > 20:
                return first_line[: idx + 1].strip()

        if len(first_line) > max_length:
            truncated = first_line[:max_length]
            last_space = truncated.rfind(" ")
            if last_space > 30:
                return truncated[:last_space].strip() + "..."

        return first_line[:max_length]

    def _error_result(self, error: str) -> dict:
        return {
            "success": False,
            "text": "",
            "author": None,
            "title": "X Post",
            "error": error,
            "source": None,
        }


async def fetch_x_content(url: str) -> Optional[dict]:
    """Convenience function to fetch X content.

    Usage:
        content = await fetch_x_content("https://x.com/user/status/123")
        if content["success"]:
            print(content["text"])
    """
    scraper = XScraper()
    return await scraper.fetch_tweet(url)


def fetch_x_content_sync(url: str) -> Optional[dict]:
    """Synchronous wrapper for fetch_x_content."""
    try:
        return asyncio.run(fetch_x_content(url))
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
        return {
            "success": False,
            "error": "Interrupted by user",
            "text": "",
            "title": "X Post",
            "author": None,
            "source": None,
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        target = sys.argv[1]
        try:
            out = fetch_x_content_sync(target)
            print(json.dumps(out, indent=2))
        except KeyboardInterrupt:
            LOGGER.info("Interrupted by user")
            sys.exit(130)
    else:
        print("Usage: python x_scraper.py <x_url>")
