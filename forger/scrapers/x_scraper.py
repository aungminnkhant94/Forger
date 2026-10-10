"""X/Twitter content scraper with fallback methods.

ESSENTIAL COMPONENT - See ARCHITECTURE.md before modifying.
Fetches tweet content from X URLs using multiple methods:
1. Playwright with stealth (primary; cookies via X_COOKIES_PATH)
2. jina.ai text extraction (fallback)
3. yt-dlp (fallback for public tweets)

Free-proxy fetching was removed; fetches always use a direct connection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import urllib.request
from typing import Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from forger.scrapers.x_auth import load_cookies
from forger.url_safety import UnsafeURLError, assert_safe_fetch_url

LOGGER = logging.getLogger(__name__)


class XScraperError(Exception):
    """Base exception for XScraper errors."""
    pass


class XScraperTimeoutError(XScraperError):
    """Raised when scraping times out."""
    pass


class XScraperPlaywrightError(XScraperError):
    """Raised when Playwright encounters an error."""
    pass


class XScraper:
    """Scrape X/Twitter content using multiple methods."""
    
    def __init__(self):
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    
    async def fetch_tweet(self, url: str) -> dict:
        """Fetch tweet content from X URL using multiple methods.
        
        Returns:
            dict with keys: text, author, title, success, error
        """
        try:
            assert_safe_fetch_url(url)
        except UnsafeURLError as e:
            LOGGER.error("Refusing unsafe X URL %s: %s", url, e)
            return self._error_result(f"Unsafe URL blocked: {e}")

        # Method 1: Playwright with stealth (no proxy)
        result = await self._fetch_with_playwright(url)
        if result.get("success"):
            return result
        
        # Method 2: jina.ai text extraction (free, no auth)
        LOGGER.info("Playwright failed, trying jina.ai...")
        result = self._fetch_with_jina(url)
        if result.get("success"):
            return result
        
        # Method 3: yt-dlp
        LOGGER.info("jina.ai failed, trying yt-dlp...")
        result = self._fetch_with_ytdlp(url)
        if result.get("success"):
            return result
        
        # Method 4: Return error with details
        LOGGER.error(f"All methods failed for: {url}")
        return self._error_result("X content extraction blocked - manual review needed")
    
    async def _fetch_with_playwright(self, url: str) -> dict:
        """Try Playwright with stealth options (direct connection, no proxy)."""
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            LOGGER.warning(f"Playwright not installed: {e}")
            return self._error_result("Playwright not installed")
        
        browser = None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-accelerated-2d-canvas',
                        '--disable-gpu',
                    ]
                )
                
                # Direct browser context — no proxy.
                context = await browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                    timezone_id="America/New_York",
                )
                
                # Load and add cookies (auth_token is critical)
                cookies = load_cookies()
                if cookies:
                    LOGGER.info(f"Adding {len(cookies)} saved X cookies...")
                    await context.add_cookies(cookies)
                else:
                    LOGGER.warning("No X cookies found — will hit login wall")
                
                page = await context.new_page()
                
                # Inject stealth script to hide Playwright
                await page.add_init_script("""
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
                """)
                
                LOGGER.info(f"Fetching with Playwright: {url}")
                
                # Add delay to seem human
                await asyncio.sleep(2)
                
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    LOGGER.warning(f"Navigation error: {e}")
                
                # Brief wait for JS render, then wait for the tweet article itself.
                # (Blind 3s sleep captured X's UI chrome before the post rendered —
                #  the "keyboard shortcuts" garbage-bookmark bug.)
                await asyncio.sleep(3)
                article = None
                try:
                    article = await page.wait_for_selector(
                        "article[data-testid='tweet']", timeout=10_000
                    )
                except Exception:
                    LOGGER.warning("tweet article did not render within 10s")
                
                # Get page text
                page_text = await page.inner_text("body")
                
                # Check for login wall
                if "log in" in page_text.lower() and "Don't miss" in page_text:
                    LOGGER.warning("X login wall — cookies may be expired")
                    return self._error_result("X requires login - cookies likely expired")
                
                # Prefer the article text; fall back to body only if the article
                # never rendered. Body text alone is UI chrome, not the post.
                tweet_text = (await article.inner_text()) if article else ""
                if not tweet_text.strip():
                    tweet_text = page_text
                    if "to view keyboard shortcuts" in tweet_text.lower():
                        LOGGER.warning("Only X UI chrome rendered (no article) — treating as gate")
                        return self._error_result("X rendered UI chrome only - post never appeared")
                
                # Extract author from URL path
                author = None
                try:
                    parts = url.split('/')
                    if len(parts) > 3:
                        author = parts[3].replace('@', '')
                except:
                    pass
                
                tweet_text = tweet_text.strip()
                if tweet_text and len(tweet_text) > 100 and not any(
                    gate in tweet_text.lower() for gate in [
                        "click to subscribe", "subscribe to", "log in", "sign up",
                        "create account", "join now", "get started"
                    ]
                ):
                    return {
                        "success": True,
                        "text": tweet_text,
                        "author": author,
                        "title": self._generate_title(tweet_text),
                        "error": None
                    }
                LOGGER.warning(f"Playwright got gate/paywall text ({len(tweet_text)} chars), trying fallback...")
                return self._error_result("Playwright hit subscribe gate")
                    
        except Exception as e:
            LOGGER.error(f"Playwright error: {e}")
            return self._error_result(f"Playwright failed: {e}")
        finally:
            if browser:
                try:
                    await browser.close()
                except:
                    pass
    
    def _fetch_with_jina(self, url: str) -> dict:
        """Try jina.ai summarizer as fallback for text extraction."""
        try:
            jina_url = f"https://r.jina.ai/http://{url.replace('https://', '').replace('http://', '')}"
            LOGGER.info(f"Trying jina.ai: {jina_url}")
            
            req = urllib.request.Request(
                jina_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )
            
            with urllib.request.urlopen(req, timeout=20) as response:
                content = response.read().decode('utf-8')
            
            if content and len(content) > 50:
                # Parse jina.ai output format
                lines = content.split('\n')
                title = "X Post"
                author = None
                text_lines = []
                
                for line in lines:
                    line = line.strip()
                    if line.startswith('Title: '):
                        title = line.replace('Title: ', '').replace(' / X', '').strip()
                    elif line.startswith('URL Source:'):
                        continue
                    elif line.startswith('Published Time:'):
                        continue
                    elif line.startswith('Markdown Content:'):
                        continue
                    elif line and not line.startswith('![') and not line.startswith('['):
                        text_lines.append(line)
                
                text = '\n'.join(text_lines).strip()
                
                if text:
                    return {
                        "success": True,
                        "text": text,
                        "author": author,
                        "title": title if title != "X Post" else self._generate_title(text),
                        "error": None
                    }
            
            LOGGER.warning("jina.ai returned no usable content")
            return self._error_result("jina.ai failed")
            
        except Exception as e:
            LOGGER.warning(f"jina.ai error: {e}")
            return self._error_result(f"jina.ai error: {e}")

    def _fetch_with_ytdlp(self, url: str) -> dict:
        """Try yt-dlp as fallback for public tweets."""
        try:
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-download",
                "--quiet",
                url
            ]
            
            LOGGER.info(f"Trying yt-dlp: {url}")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout.strip().split('\n')[0])
                
                # Extract tweet text from yt-dlp data
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
                        "error": None
                    }
            
            LOGGER.warning(f"yt-dlp failed or returned no content")
            return self._error_result("yt-dlp failed")
            
        except subprocess.TimeoutExpired:
            LOGGER.warning("yt-dlp timed out")
            return self._error_result("yt-dlp timeout")
        except Exception as e:
            LOGGER.warning(f"yt-dlp error: {e}")
            return self._error_result(f"yt-dlp error: {e}")
    
    def _generate_title(self, text: str, max_length: int = 80) -> str:
        """Generate title from tweet text."""
        if not text:
            return "X Post"
        
        # If text is just a URL or starts with http, return generic title
        text_stripped = text.strip()
        if text_stripped.startswith('http://') or text_stripped.startswith('https://'):
            return "X Post"
        
        first_line = text.split('\n')[0].strip()
        
        # If first line is a URL, use generic title
        if first_line.startswith('http://') or first_line.startswith('https://'):
            return "X Post"
        
        # Look for sentence end
        for punct in ['. ', '? ', '! ']:
            idx = first_line[:max_length].rfind(punct)
            if idx > 20:
                return first_line[:idx + 1].strip()
        
        # Word boundary
        if len(first_line) > max_length:
            truncated = first_line[:max_length]
            last_space = truncated.rfind(' ')
            if last_space > 30:
                return truncated[:last_space].strip() + "..."
        
        return first_line[:max_length]
    
    def _error_result(self, error: str) -> dict:
        return {
            "success": False,
            "text": "",
            "author": None,
            "title": "X Post",
            "error": error
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
    import asyncio
    try:
        return asyncio.run(fetch_x_content(url))
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")
        return {"success": False, "error": "Interrupted by user", "text": "", "title": "X Post", "author": None}

if __name__ == "__main__":
    import sys
    import json
    if len(sys.argv) > 1:
        url = sys.argv[1]
        try:
            result = fetch_x_content_sync(url)
            print(json.dumps(result, indent=2))
        except KeyboardInterrupt:
            LOGGER.info("Interrupted by user")
            sys.exit(130)
    else:
        print("Usage: python x_scraper.py <x_url>")
