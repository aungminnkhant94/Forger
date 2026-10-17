"""Article scraper using web_fetch - more reliable than newspaper3k."""

import logging
import re

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

from forger.url_safety import UnsafeURLError, assert_safe_fetch_url
from forger.scrape_quality import (
    is_bot_challenge_content,
    is_bot_challenge_headers,
    is_bot_challenge_html,
)
from forger.scrapers.doi_metadata import (
    extract_doi_from_url,
    is_acs_doi_url,
    is_nature_article_url,
    scrape_doi_metadata,
)
from forger.scrapers.hacker_news import is_hn_item_url, scrape_hn_item
from forger.scrapers.pubchem import is_pubchem_compound_url, scrape_pubchem_compound

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15  # seconds
MAX_TEXT_LENGTH = 5000


# Charset names that requests uses when Content-Type omits charset for text/*.
# Decoding real UTF-8 bytes with these produces classic mojibake (itâs, Â).
_LATIN1_DEFAULTS = frozenset(
    {
        "iso-8859-1",
        "latin-1",
        "latin1",
        "windows-1252",
        "cp1252",
        "ascii",
    }
)

_META_CHARSET_RE = re.compile(
    br"""<meta\b[^>]*?charset\s*=\s*["\']?([a-zA-Z0-9_\-]+)""",
    re.IGNORECASE,
)
_META_HTTP_EQUIV_RE = re.compile(
    br"""<meta\b[^>]*?content\s*=\s*["\'][^"\']*charset\s*=\s*([a-zA-Z0-9_\-]+)""",
    re.IGNORECASE,
)


def _normalize_charset(name: str | None) -> str | None:
    if not name:
        return None
    cleaned = name.strip().strip("\"'").lower().replace("_", "-")
    if cleaned == "utf8":
        return "utf-8"
    if cleaned in ("latin1", "latin-1"):
        return "iso-8859-1"
    return cleaned or None


def _charset_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    match = re.search(r"charset\s*=\s*[\"\']?([a-zA-Z0-9_\-]+)", content_type, re.I)
    return _normalize_charset(match.group(1) if match else None)


def _charset_from_html_meta(raw: bytes) -> str | None:
    """Sniff <meta charset> / http-equiv Content-Type from the HTML head."""
    head = raw[:8192]
    for pattern in (_META_CHARSET_RE, _META_HTTP_EQUIV_RE):
        match = pattern.search(head)
        if match:
            try:
                return _normalize_charset(match.group(1).decode("ascii", errors="ignore"))
            except Exception:
                continue
    return None


def decode_html_bytes(
    raw: bytes,
    *,
    header_encoding: str | None = None,
    content_type: str | None = None,
) -> str:
    """Decode HTML body bytes to str without Latin-1 mojibake.

    Classic failure: UTF-8 pages (curly apostrophes, NBSP) served without a
    Content-Type charset. ``requests`` then sets encoding to ISO-8859-1, so
    ``response.text`` yields ``itâs`` / stray ``Â``. Prefer an explicit header
    or HTML meta charset, then UTF-8 when the bytes are valid, and only then
    fall back to Windows-1252 / Latin-1.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError(f"expected bytes, got {type(raw)!r}")
    raw = bytes(raw)

    ct_enc = _charset_from_content_type(content_type)
    meta_enc = _charset_from_html_meta(raw)
    req_enc = _normalize_charset(header_encoding)

    # Explicit declarations (Content-Type charset or <meta>) always win —
    # including legacy windows-1252 when the server truly meant it.
    candidates: list[str] = []
    for enc in (ct_enc, meta_enc):
        if enc and enc not in candidates:
            candidates.append(enc)

    # requests sets encoding=ISO-8859-1 whenever Content-Type is text/* with no
    # charset. That is not an explicit declaration — skip it so UTF-8 pages
    # are not mojibaked. Trust response.encoding only when it is non-Latin-1
    # or when Content-Type already named the same charset.
    if req_enc and req_enc not in candidates:
        if req_enc not in _LATIN1_DEFAULTS or req_enc == ct_enc:
            candidates.append(req_enc)

    for enc in ("utf-8", "utf-8-sig"):
        if enc not in candidates:
            candidates.append(enc)

    for enc in candidates:
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue

    for enc in ("windows-1252", "iso-8859-1"):
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def html_text_from_response(response) -> str:
    """Return Unicode HTML from a requests-like response.

    Uses ``response.content`` when present so we can re-decode correctly.
    Falls back to ``response.text`` for test doubles that only set text.
    """
    raw = getattr(response, "content", None)
    if isinstance(raw, (bytes, bytearray)) and len(raw) > 0:
        headers = getattr(response, "headers", None) or {}
        try:
            content_type = headers.get("Content-Type") or headers.get("content-type")
        except Exception:
            content_type = None
        header_encoding = getattr(response, "encoding", None)
        if not isinstance(header_encoding, str):
            header_encoding = None
        return decode_html_bytes(
            bytes(raw),
            header_encoding=header_encoding,
            content_type=content_type if isinstance(content_type, str) else None,
        )

    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(raw, (bytes, bytearray)):
        return decode_html_bytes(bytes(raw))
    return ""


class ArticleScraperError(Exception):
    """Base exception for article scraper errors."""
    pass


class ArticleScraperTimeoutError(ArticleScraperError):
    """Raised when scraping times out."""
    pass


class ArticleScraperHTTPError(ArticleScraperError):
    """Raised when HTTP request fails."""
    pass


@retry(
    retry=retry_if_exception_type((ConnectionError, Timeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True
)
def _fetch_url(url: str, headers: dict, timeout: int) -> requests.Response:
    """Fetch URL with retry logic for transient errors."""
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response



def _challenge_failure(url: str, *, title=None, text=None, detail: str = "bot challenge") -> dict:
    """Uniform failure payload for anti-bot interstitials."""
    LOGGER.warning("Refusing bot-challenge / trash scrape for %s (%s)", url, detail)
    return {
        "success": False,
        "title": title,
        "text": text,
        "author": None,
        "source": None,
        "error": f"Bot challenge / anti-bot interstitial ({detail})",
    }


def _challenge_or_doi_recovery(
    url: str,
    *,
    title=None,
    text=None,
    detail: str = "bot challenge",
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Refuse challenge HTML, but try Crossref when the URL carries a DOI."""
    if extract_doi_from_url(url):
        doi_meta = scrape_doi_metadata(url, timeout=timeout)
        if doi_meta.get("success"):
            LOGGER.info("Recovered from challenge via DOI metadata for %s", url)
            return doi_meta
        LOGGER.warning(
            "DOI recovery after challenge failed for %s (%s)",
            url,
            doi_meta.get("error") or "unknown",
        )
    return _challenge_failure(url, title=title, text=text, detail=detail)


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
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    try:
        assert_safe_fetch_url(url)
    except UnsafeURLError as e:
        LOGGER.error("Refusing unsafe article URL %s: %s", url, e)
        return {
            'success': False,
            'title': None,
            'text': None,
            'author': None,
            'source': None,
            'error': f'Unsafe URL blocked: {e}',
        }

    # HN item HTML is often HTTP 419 from datacenter IPs; use Firebase API.
    # Do not fall back to HTML — the Firebase miss is the real answer.
    if is_hn_item_url(url):
        return scrape_hn_item(url, timeout=timeout)

    # PubChem compound pages are JS-heavy / bot-challenged; use PUG REST first.
    if is_pubchem_compound_url(url):
        pubchem = scrape_pubchem_compound(url, timeout=timeout)
        if pubchem.get("success"):
            return pubchem
        LOGGER.warning(
            "PubChem API scrape failed for %s (%s); falling back to HTML",
            url,
            pubchem.get("error") or "unknown",
        )

    # ACS/JACS 403 and Nature Client Challenge: prefer Crossref metadata first.
    if is_acs_doi_url(url) or is_nature_article_url(url):
        doi_meta = scrape_doi_metadata(url, timeout=timeout)
        if doi_meta.get("success"):
            return doi_meta
        LOGGER.warning(
            "DOI metadata scrape failed for %s (%s); falling back to HTML",
            url,
            doi_meta.get("error") or "unknown",
        )

    try:
        LOGGER.info(f"Fetching article: {url}")
        response = _fetch_url(url, headers, timeout)
        html = html_text_from_response(response)

        # Cloudflare advertises challenges via cf-mitigated; Nature/Fastly and
        # others serve HTTP 200 Client Challenge HTML that still looks "long".
        if is_bot_challenge_headers(getattr(response, "headers", None)):
            return _challenge_or_doi_recovery(
                url, detail="cf-mitigated: challenge", timeout=timeout
            )
        if is_bot_challenge_html(html):
            # Prefer title from HTML for logging; do not save the body.
            rough_title = None
            try:
                rough_soup = BeautifulSoup(html, "html.parser")
                if rough_soup.find("title"):
                    rough_title = rough_soup.find("title").get_text().strip()
            except Exception:
                rough_title = None
            return _challenge_or_doi_recovery(
                url,
                title=rough_title,
                detail="challenge HTML markers",
                timeout=timeout,
            )

        soup = BeautifulSoup(html, 'html.parser')
        
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
        
        # Challenge pages can clear HTML markers after script stripping but
        # still leave interstitial titles / enable-JS copy — refuse those too.
        if is_bot_challenge_content(title=title, text=text, html=html):
            return _challenge_or_doi_recovery(
                url,
                title=title,
                text=text,
                detail="challenge title/body",
                timeout=timeout,
            )

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
            if extract_doi_from_url(url):
                doi_meta = scrape_doi_metadata(url, timeout=timeout)
                if doi_meta.get("success"):
                    LOGGER.info(
                        "Recovered thin HTML scrape via DOI metadata for %s",
                        url,
                    )
                    return doi_meta
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
        # Publisher 403/paywall: if the URL carries a DOI, try Crossref title+abstract.
        if extract_doi_from_url(url):
            doi_meta = scrape_doi_metadata(url, timeout=timeout)
            if doi_meta.get("success"):
                LOGGER.info(
                    "Recovered from HTTP error via DOI metadata for %s",
                    url,
                )
                return doi_meta
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        html = html_text_from_response(response)
        soup = BeautifulSoup(html, 'html.parser')
        
        title = None
        if soup.find('title'):
            title = soup.find('title').get_text().strip()
        
        # Get all paragraphs
        paragraphs = soup.find_all('p')
        text = '\n'.join(p.get_text().strip() for p in paragraphs if p.get_text().strip())
        text = text[:MAX_TEXT_LENGTH]
        
        if is_bot_challenge_content(title=title, text=text, html=html):
            return _challenge_failure(
                url,
                title=title,
                text=text,
                detail="challenge in fallback scrape",
            )

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