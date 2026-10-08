"""Article scraper using web_fetch - more reliable than newspaper3k."""

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.exceptions import (
    ConnectionError,
    HTTPError,
    RequestException,
    Timeout,
)
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15  # seconds
MAX_TEXT_LENGTH = 5000

# Normal browser UA. Some sites reject the python-requests default.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Hacker News answers HTTP 419 "Sorry" to browser-like user agents and
# 200 to a plain client UA (curl and python-requests both succeed).
PLAIN_USER_AGENT = "Forger/1.0 (+https://github.com/aungminnkhant94/Forger)"

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


class ArticleScraperError(Exception):
    """Base exception for article scraper errors."""
    pass


class ArticleScraperTimeoutError(ArticleScraperError):
    """Raised when scraping times out."""
    pass


class ArticleScraperHTTPError(ArticleScraperError):
    """Raised when HTTP request fails."""
    pass


def _content_type(response: requests.Response) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    try:
        value = headers.get("Content-Type") or headers.get("content-type") or ""
    except Exception:
        return ""
    return value if isinstance(value, str) else ""


def response_text(response: requests.Response) -> str:
    """Decode a response, honoring an explicit charset else apparent encoding.

    requests treats text/* with no charset as ISO-8859-1. Pages such as
    docs.python.org send UTF-8 without a charset header, so response.text
    turns punctuation into mojibake ("thereâs"). apparent_encoding is the
    charset guessed from the body when the header does not name one.
    """
    if "charset=" not in _content_type(response).lower():
        apparent = getattr(response, "apparent_encoding", None)
        if isinstance(apparent, str) and apparent:
            response.encoding = apparent
    text = response.text
    return text if isinstance(text, str) else str(text)


def _request_headers(user_agent: str) -> dict:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def youtube_video_id(url: str) -> str | None:
    """Return the video id for a YouTube watch (or youtu.be) URL."""
    raw = (url or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return None
    if host.endswith("youtu.be"):
        video_id = parts.path.strip("/").split("/")[0]
        return video_id or None
    if parts.path.rstrip("/") == "/watch":
        for key, value in parse_qsl(parts.query):
            if key == "v" and value:
                return value
    return None


def _empty_article(error: str, title: str | None = None, text: str | None = None) -> dict:
    return {
        "success": False,
        "title": title,
        "text": text,
        "author": None,
        "source": None,
        "error": error,
    }


def fetch_youtube(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Bookmark a YouTube watch URL without treating it as an article.

    oEmbed is public and needs no API key. The text always includes the
    video id and URL. If oEmbed and the watch page both fail, the title
    still contains the video id so two failures cannot look identical.
    """
    video_id = youtube_video_id(url)
    if not video_id:
        return _empty_article("Not a YouTube watch URL")

    oembed_url = "https://www.youtube.com/oembed?" + urlencode({"url": url, "format": "json"})
    try:
        LOGGER.info("Fetching YouTube oEmbed: %s", video_id)
        response = requests.get(oembed_url, headers=_request_headers(BROWSER_USER_AGENT), timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                title = (data.get("title") or "").strip()
                author = (data.get("author_name") or "").strip() or None
                description = (data.get("description") or "").strip()
                if title:
                    parts = []
                    if description:
                        parts.append(description)
                    if author:
                        parts.append(f"Channel: {author}")
                    parts.append(f"Video id: {video_id}")
                    parts.append(f"URL: {url}")
                    return {
                        "success": True,
                        "title": title,
                        "text": "\n".join(parts),
                        "author": author,
                        "source": "youtube-oembed",
                        "error": None,
                        "video_id": video_id,
                    }
        LOGGER.warning("YouTube oEmbed failed for %s: HTTP %s", video_id, response.status_code)
    except Exception as exc:
        LOGGER.warning("YouTube oEmbed failed for %s: %s", video_id, exc)

    page_title = _youtube_page_title(url, timeout)
    if page_title:
        return {
            "success": True,
            "title": page_title,
            "text": f"{page_title}\nVideo id: {video_id}\nURL: {url}",
            "author": None,
            "source": "youtube-page",
            "error": None,
            "video_id": video_id,
        }

    return {
        "success": False,
        "title": f"YouTube video {video_id}",
        "text": f"[URL content not available] {url}\nVideo id: {video_id}",
        "author": None,
        "source": None,
        "error": "YouTube oEmbed failed",
        "video_id": video_id,
    }


def _youtube_page_title(url: str, timeout: int) -> str | None:
    """Last resort: <title> or og:title from the watch page."""
    try:
        response = requests.get(url, headers=_request_headers(BROWSER_USER_AGENT), timeout=timeout)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response_text(response), "html.parser")
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = str(og.get("content")).strip()
            if title:
                return title
        if soup.title and soup.title.get_text(strip=True):
            return soup.title.get_text(strip=True)
    except Exception as exc:
        LOGGER.debug("YouTube watch page title failed: %s", exc)
    return None


@retry(
    retry=retry_if_exception_type((ConnectionError, Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True
)
def _fetch_url(url: str, headers: dict, timeout: int) -> requests.Response:
    """Fetch URL with retry logic for transient errors.

    Sends a browser User-Agent. If the host answers 419 (Hacker News does
    this for browser UAs and returns "Sorry"), retry once with a plain UA.
    """
    response = requests.get(url, headers=headers, timeout=timeout)
    if getattr(response, "status_code", None) == 419:
        LOGGER.info("HTTP 419 from %s; retrying with a non-browser User-Agent", url)
        alt_headers = dict(headers)
        alt_headers["User-Agent"] = PLAIN_USER_AGENT
        response = requests.get(url, headers=alt_headers, timeout=timeout)
    response.raise_for_status()
    return response


def scrape_article(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Scrape article content using requests + BeautifulSoup.
    Falls back to basic extraction if web_fetch fails.
    
    Args:
        url: The URL to scrape
        timeout: Request timeout in seconds
        
    Returns:
        {
            'success': bool,
            'title': str or None,
            'text': str or None,
            'author': str or None,
            'source': str or None,
            'error': str or None
        }
    """
    headers = _request_headers(BROWSER_USER_AGENT)
    
    try:
        LOGGER.info(f"Fetching article: {url}")
        response = _fetch_url(url, headers, timeout)
        
        soup = BeautifulSoup(response_text(response), 'html.parser')
        
        # Extract title
        title = None
        try:
            if soup.find('title'):
                title = soup.find('title').get_text().strip()
            elif soup.find('h1'):
                title = soup.find('h1').get_text().strip()
        except Exception as e:
            LOGGER.debug(f"Could not extract title: {e}")
        
        # Extract main content
        # Try common article containers
        article = None
        for selector in ['article', 'main', '[role="main"]', '.article-content', '.post-content', '.entry-content', '#content']:
            try:
                article = soup.select_one(selector)
                if article:
                    LOGGER.debug(f"Found article container: {selector}")
                    break
            except Exception as e:
                LOGGER.debug(f"Selector {selector} failed: {e}")
                continue
        
        # Fallback to body if no article container
        if not article:
            article = soup.find('body')
            LOGGER.debug("Using body as article container")
        
        # Clean up the text
        text = None
        if article:
            # Remove script and style elements
            try:
                for script in article(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                    script.decompose()
                
                text = article.get_text(separator='\n', strip=True)
                # Clean up excessive whitespace
                lines = [line.strip() for line in text.split('\n') if line.strip()]
                text = '\n'.join(lines)
                text = text[:MAX_TEXT_LENGTH]  # Limit text length
            except Exception as e:
                LOGGER.warning(f"Error cleaning article text: {e}")
        
        # Extract author
        author = None
        try:
            for meta in soup.find_all('meta'):
                if meta.get('name') in ['author', 'twitter:creator', 'article:author']:
                    author = meta.get('content')
                    if author:
                        break
        except Exception as e:
            LOGGER.debug(f"Could not extract author: {e}")
        
        # Check if we got meaningful content
        if title and text and len(text) > 200:
            LOGGER.info(f"Successfully scraped article: {title[:80]}...")
            return {
                'success': True,
                'title': title,
                'text': text,
                'author': author,
                'source': 'requests+bs4',
                'error': None
            }
        else:
            LOGGER.warning(f"Insufficient content extracted from {url}")
            return {
                'success': False,
                'title': title,
                'text': text,
                'author': author,
                'source': None,
                'error': 'Insufficient content extracted'
            }
            
    except Timeout as e:
        LOGGER.error(f"Request timed out for {url}: {e}")
        return {
            'success': False,
            'title': None,
            'text': None,
            'author': None,
            'source': None,
            'error': f'Request timeout: {e}'
        }
    except ConnectionError as e:
        LOGGER.error(f"Connection error for {url}: {e}")
        return {
            'success': False,
            'title': None,
            'text': None,
            'author': None,
            'source': None,
            'error': f'Connection error: {e}'
        }
    except HTTPError as e:
        LOGGER.error(f"HTTP error for {url}: {e}")
        return {
            'success': False,
            'title': None,
            'text': None,
            'author': None,
            'source': None,
            'error': f'HTTP error: {e}'
        }
    except RequestException as e:
        LOGGER.error(f"Request failed for {url}: {e}")
        return {
            'success': False,
            'title': None,
            'text': None,
            'author': None,
            'source': None,
            'error': f'Request failed: {e}'
        }
    except Exception as e:
        LOGGER.exception(f"Unexpected error scraping {url}")
        return {
            'success': False,
            'title': None,
            'text': None,
            'author': None,
            'source': None,
            'error': f'Unexpected error: {e}'
        }


def scrape_article_with_fallback(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Scrape article with fallback to simpler extraction if full scrape fails.
    
    Args:
        url: The URL to scrape
        timeout: Request timeout in seconds
        
    Returns:
        Article dict with at least partial content if possible
    """
    # Try full scrape first
    result = scrape_article(url, timeout)
    if result['success']:
        return result
    
    LOGGER.warning(f"Full scrape failed, trying fallback for {url}")
    
    # Fallback: try to get at least the title and some text
    try:
        headers = _request_headers(BROWSER_USER_AGENT)
        response = _fetch_url(url, headers, timeout)
        soup = BeautifulSoup(response_text(response), 'html.parser')
        
        title = None
        if soup.find('title'):
            title = soup.find('title').get_text().strip()
        
        # Get all paragraphs
        paragraphs = soup.find_all('p')
        text = '\n'.join(p.get_text().strip() for p in paragraphs if p.get_text().strip())
        text = text[:MAX_TEXT_LENGTH]
        
        if title or text:
            LOGGER.info(f"Fallback scrape successful for {url}")
            return {
                'success': True,
                'title': title or "Untitled",
                'text': text or "[No content extracted]",
                'author': None,
                'source': 'fallback+bs4',
                'error': None
            }
    except Exception as e:
        LOGGER.error(f"Fallback scrape also failed: {e}")
    
    # Return original failure if fallback also fails
    return result