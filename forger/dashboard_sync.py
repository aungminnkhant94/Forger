"""Copy pipeline data files into the web dashboard directories.

The dashboard reads data at runtime from web/public/*.json (client fetch)
and optionally from web/lib/*.json. `forge sync` and the bookmark workflow
both call sync_dashboard_data().

Publishing real bookmarks into web/public/ is OPT-IN. Without
FORGER_PUBLISH_DASHBOARD=1 or publish=True, public JSON is written as
empty arrays so a default deploy cannot leak personal data. Local private
viewing requires an explicit publish choice (env or `forge sync --publish`).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

LOGGER = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]

_LIB_DIR = BASE_DIR / "web" / "lib"
_PUBLIC_DIR = BASE_DIR / "web" / "public"

_BOOKMARKS_SRC = BASE_DIR / "data" / "bookmarks_raw.json"
_ANALYSIS_SRC = BASE_DIR / "data" / "analysis_results.json"

_LIB_BOOKMARKS = _LIB_DIR / "data.json"
_LIB_ANALYSIS = _LIB_DIR / "analysis.json"
_PUBLIC_BOOKMARKS = _PUBLIC_DIR / "data.json"
_PUBLIC_ANALYSIS = _PUBLIC_DIR / "analysis.json"

_TRUTHY = {"1", "true", "yes", "on"}


def publish_dashboard_enabled(explicit: bool | None = None) -> bool:
    """Whether real bookmark JSON may be written to web/public/.

    Precedence: explicit argument (from CLI) > FORGER_PUBLISH_DASHBOARD env.
    Default is False (empty public JSON).
    """
    if explicit is not None:
        return bool(explicit)
    return os.getenv("FORGER_PUBLISH_DASHBOARD", "").strip().lower() in _TRUTHY


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _copy_or_empty(src: Path, dst: Path, *, publish: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if publish and src.exists():
        shutil.copy2(src, dst)
        return
    # Default / missing source: empty array so the dashboard loads cleanly
    # without personal data.
    _write_json(dst, [])


def sync_dashboard_data(*, publish: bool | None = None) -> bool:
    """Sync bookmarks + analysis JSON into web/lib and web/public.

    When publish is false (default), web/public gets empty ``[]`` files and
    web/lib still receives a private local copy when sources exist (lib is
    not served as static public assets). When publish is true, both trees
    get the real data.

    Returns True when every write succeeded.
    """
    do_publish = publish_dashboard_enabled(publish)
    ok = True

    try:
        # web/lib: local/private mirror when sources exist; empty otherwise.
        for src, dst in (
            (_BOOKMARKS_SRC, _LIB_BOOKMARKS),
            (_ANALYSIS_SRC, _LIB_ANALYSIS),
        ):
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            else:
                _write_json(dst, [])
    except Exception as exc:
        LOGGER.warning("Dashboard lib sync failed: %s", exc)
        ok = False

    try:
        _copy_or_empty(_BOOKMARKS_SRC, _PUBLIC_BOOKMARKS, publish=do_publish)
        _copy_or_empty(_ANALYSIS_SRC, _PUBLIC_ANALYSIS, publish=do_publish)
        if do_publish:
            LOGGER.info("Published real bookmark JSON to web/public/ (opt-in)")
        else:
            LOGGER.info(
                "web/public/ data.json+analysis.json left empty "
                "(set FORGER_PUBLISH_DASHBOARD=1 or forge sync --publish to publish)"
            )
    except Exception as exc:
        LOGGER.warning("Dashboard public sync failed: %s", exc)
        ok = False

    return ok
