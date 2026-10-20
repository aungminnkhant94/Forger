"""Copy pipeline data files into the web dashboard directories.

The dashboard reads data at runtime from web/public/*.json (client fetch)
and optionally from web/lib/*.json. `forge sync` and the bookmark workflow
both call sync_dashboard_data().

Export goes through Bookmark / AnalysisResult so tags are kebab-normalized,
summaries are word-boundary truncated for cards, and each bookmark carries
display_title (analysis title when finished, else scraped title). The
dashboard can trust those fields instead of re-normalizing in TypeScript.

Publishing real bookmarks into web/public/ is OPT-IN. Without
FORGER_PUBLISH_DASHBOARD=1 or publish=True, public JSON is written as
empty arrays so a default deploy cannot leak personal data. Local private
viewing requires an explicit publish choice (env or `forge sync --publish`).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from forger.analysis_cleanup import truncate_at_word_boundary
from forger.models import AnalysisResult, Bookmark, display_title

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

# Match web/lib/truncate.ts CARD_SUMMARY_MAX_LENGTH + default ellipsis so the
# exported summary is already card-ready (TS need not re-truncate).
DASHBOARD_SUMMARY_MAX_LENGTH = 280
DASHBOARD_SUMMARY_ELLIPSIS = "…"


def publish_dashboard_enabled(explicit: bool | None = None) -> bool:
    """Whether real bookmark JSON may be written to web/public/.

    Precedence: explicit argument (from CLI) > FORGER_PUBLISH_DASHBOARD env.
    Default is False (empty public JSON).
    """
    if explicit is not None:
        return bool(explicit)
    return os.getenv("FORGER_PUBLISH_DASHBOARD", "").strip().lower() in _TRUTHY


def _atomic_replace(dst: Path, write) -> None:
    """Write via a temp file in the same dir + os.replace, so a concurrent
    reader or a second sync never sees a half-written dashboard file."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dst.parent, prefix=f".{dst.name}.", suffix=".tmp")
    os.close(fd)
    try:
        write(Path(tmp))
        os.replace(tmp, dst)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _write_json(path: Path, payload: object) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    _atomic_replace(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))


def _load_json_list(path: Path) -> list[Any]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def export_dashboard_payloads(
    bookmarks_raw: list[Any] | None = None,
    analysis_raw: list[Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Normalize bookmarks + analysis for the dashboard via models.

    Tags come back kebab-case (Bookmark/AnalysisResult.from_dict). Each
    bookmark gains ``display_title``. Analysis summaries are truncated to
    ``DASHBOARD_SUMMARY_MAX_LENGTH`` at a word boundary.
    """
    if bookmarks_raw is None:
        bookmarks_raw = _load_json_list(_BOOKMARKS_SRC)
    if analysis_raw is None:
        analysis_raw = _load_json_list(_ANALYSIS_SRC)

    bookmarks = [
        Bookmark.from_dict(item) for item in bookmarks_raw if isinstance(item, dict)
    ]
    analyses = [
        AnalysisResult.from_dict(item) for item in analysis_raw if isinstance(item, dict)
    ]
    by_id = {item.bookmark_id: item for item in analyses}

    bookmark_payloads: list[dict[str, Any]] = []
    for bookmark in bookmarks:
        payload = bookmark.to_dict()
        payload["display_title"] = display_title(bookmark, by_id.get(bookmark.id))
        bookmark_payloads.append(payload)

    analysis_payloads: list[dict[str, Any]] = []
    for analysis in analyses:
        payload = analysis.to_dict()
        payload["summary"] = truncate_at_word_boundary(
            str(payload.get("summary") or ""),
            DASHBOARD_SUMMARY_MAX_LENGTH,
            DASHBOARD_SUMMARY_ELLIPSIS,
        )
        analysis_payloads.append(payload)

    return bookmark_payloads, analysis_payloads


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
    has_source = _BOOKMARKS_SRC.exists() or _ANALYSIS_SRC.exists()
    bookmarks: list[dict[str, Any]] = []
    analyses: list[dict[str, Any]] = []

    try:
        if has_source:
            bookmarks, analyses = export_dashboard_payloads()
        _write_json(_LIB_BOOKMARKS, bookmarks)
        _write_json(_LIB_ANALYSIS, analyses)
    except Exception as exc:
        LOGGER.warning("Dashboard lib sync failed: %s", exc)
        ok = False

    try:
        if do_publish and has_source and ok:
            _write_json(_PUBLIC_BOOKMARKS, bookmarks)
            _write_json(_PUBLIC_ANALYSIS, analyses)
            LOGGER.info("Published real bookmark JSON to web/public/ (opt-in)")
        else:
            _write_json(_PUBLIC_BOOKMARKS, [])
            _write_json(_PUBLIC_ANALYSIS, [])
            LOGGER.info(
                "web/public/ data.json+analysis.json left empty "
                "(set FORGER_PUBLISH_DASHBOARD=1 or forge sync --publish to publish)"
            )
    except Exception as exc:
        LOGGER.warning("Dashboard public sync failed: %s", exc)
        ok = False

    return ok
