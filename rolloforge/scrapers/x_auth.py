"""X cookie storage for the Playwright scraper — cookies only, never credentials.

X blocks anonymous scraping for many pages. To analyze X/Twitter links,
export the cookies of a logged-in browser session into a JSON file and point
X_COOKIES_PATH at it (default: <repo>/data/x_cookies.json). Without cookies
the scraper degrades gracefully — X links fall back to a manual-text flow.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
COOKIES_PATH = Path(os.getenv("X_COOKIES_PATH", str(BASE_DIR / "data" / "x_cookies.json")))


def load_cookies() -> Optional[list]:
    """Load saved X cookies if they exist."""
    if not COOKIES_PATH.exists():
        LOGGER.info("No saved cookies found at %s", COOKIES_PATH)
        return None

    try:
        cookies = json.loads(COOKIES_PATH.read_text())
        LOGGER.info("✅ Loaded %d cookies", len(cookies))
        return cookies
    except Exception as e:
        LOGGER.error("Failed to load cookies: %s", e)
        return None


if __name__ == "__main__":
    cookies = load_cookies()
    print("Status:")
    print(f"  Cookies: {'✅ Available' if cookies else '❌ Not available'}")
    print(f"  Path: {COOKIES_PATH}")
