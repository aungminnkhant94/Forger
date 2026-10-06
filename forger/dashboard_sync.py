"""Copy pipeline data files into the web dashboard directories.

The dashboard reads data at runtime from web/public/*.json (client fetch)
and at build time from web/lib/*.json. `forge sync` and the bookmark
workflow both call sync_dashboard_data().
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]

_SYNC_PAIRS = [
    (
        BASE_DIR / "data" / "bookmarks_raw.json",
        (
            BASE_DIR / "web" / "lib" / "data.json",
            BASE_DIR / "web" / "public" / "data.json",
        ),
    ),
    (
        BASE_DIR / "data" / "analysis_results.json",
        (
            BASE_DIR / "web" / "lib" / "analysis.json",
            BASE_DIR / "web" / "public" / "analysis.json",
        ),
    ),
]


def sync_dashboard_data() -> bool:
    """Copy bookmarks + analysis JSON into web/lib and web/public.

    Returns True when every available source was copied successfully.
    Missing sources are skipped quietly (fresh installs, empty forges).
    """
    ok = True
    for src, destinations in _SYNC_PAIRS:
        if not src.exists():
            continue
        for dst in destinations:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            except Exception as exc:
                LOGGER.warning("Dashboard sync failed %s -> %s: %s", src.name, dst, exc)
                ok = False
    return ok
