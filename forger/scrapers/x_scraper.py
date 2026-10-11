"""X/Twitter content scraper with cookie-free public APIs first.

ESSENTIAL COMPONENT - See ARCHITECTURE.md before modifying.

Fetch order for status URLs:
1. Twitter syndication JSON (cdn.syndication.twimg.com) — no login
2. Twitter oEmbed (publish.twitter.com) — no login
3. fxtwitter JSON API — no login, third-party mirror
4. Playwright + cookies — optional upgrade when X_COOKIES_PATH has cookies
5. jina.ai text extraction — soft fallback
6. yt-dlp — only if the binary is already installed (not required)

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
from forger.url_safety import UnsafeURLError, assert_safe_fetch_url

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


class XScraper:
    """Scrape X/Twitter content using public APIs, then optional cookie Playwright."""

    def __init__(self):
        self.user_agent = _DEFAULT_UA

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
        if result.get("success"):
            return result

        # Method 4: Playwright only when cookies exist (optional upgrade)
        cookies = load_cookies()
        if cookies:
            LOGGER.info("Public APIs missed; trying Playwright with %d cookies...", len(cookies))
            result = await self._fetch_with_playwright(url, cookies=cookies)
            if result.get("success"):
                return result
        else:
            LOGGER.info("No X cookies — skipping Playwright (login wall without cookies)")

        # Method 5: jina.ai
        LOGGER.info("Trying jina.ai fallback...")
        result = self._fetch_with_jina(url)
        if result.get("success"):
            return result

        # Method 6: yt-dlp only if already installed
        if shutil.which("yt-dlp"):
            LOGGER.info("Trying yt-dlp fallback...")
            result = self._fetch_with_ytdlp(url)
            if result.get("success"):
                return result
        else:
            LOGGER.info("yt-dlp not installed — skipping (not required)")

        LOGGER.error("All methods failed for: %s", url)
        return self._error_result("X content extraction blocked - manual review needed")

    def _fetch_with_public_apis(self, url: str) -> dict:
        """Try syndication → oEmbed → fxtwitter without any X cookies."""
        parts = extract_status_parts(url)
        if not parts:
            return self._error_result("Not an X/Twitter status URL")
        user, status_id = parts

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
            if result.get("success"):
                LOGGER.info("Fetched via %s (%s chars)", name, len(result.get("text") or ""))
                return result
            LOGGER.info("%s unavailable: %s", name, result.get("error"))
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

        author = user
        user_obj = data.get("user")
        if isinstance(user_obj, dict):
            legacy = user_obj.get("legacy") if isinstance(user_obj.get("legacy"), dict) else {}
            author = (
                user_obj.get("screen_name")
                or legacy.get("screen_name")
                or author
            )

        return {
            "success": True,
            "text": text,
            "author": (author or "").lstrip("@") or None,
            "title": self._generate_title(text),
            "error": None,
            "source": "syndication",
        }

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

        return {
            "success": True,
            "text": text,
            "author": (author or "").lstrip("@") or None,
            "title": self._generate_title(text),
            "error": None,
            "source": "oembed",
        }

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

        author = user
        author_obj = tweet.get("author")
        if isinstance(author_obj, dict):
            author = author_obj.get("screen_name") or author
        else:
            author = tweet.get("user_screen_name") or author

        return {
            "success": True,
            "text": text,
            "author": (author or "").lstrip("@") or None,
            "title": self._generate_title(text),
            "error": None,
            "source": "fxtwitter",
        }

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
        """Generate title from tweet text."""
        if not text:
            return "X Post"

        text_stripped = text.strip()
        if text_stripped.startswith("http://") or text_stripped.startswith("https://"):
            return "X Post"

        first_line = text.split("\n")[0].strip()

        if first_line.startswith("http://") or first_line.startswith("https://"):
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
