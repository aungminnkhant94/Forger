"""Article scraper using web_fetch - more reliable than newspaper3k."""

import logging

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
        LOGGER.info(f"Fetching article: {url}")
        response = _fetch_url(url, headers, timeout)
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
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
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=timeout)
        soup = BeautifulSoup(response.text, 'html.parser')
        
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