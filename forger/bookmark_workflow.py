"""Complete bookmark workflow with auto-push.

This module combines scraping, analysis, saving, and git push into one workflow.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from forger.analysis import analyze_bookmark
from forger.relates_to import validate_relates_to
from forger.scrape_quality import is_usable_scrape_text
from forger.similarity import check_duplicate_topic
from forger.git_auto import git_auto_push
from forger.models import Bookmark, AnalysisResult, ScoringInputs, PENDING_AGENT_SOURCE, is_pending_analysis
from forger.tagging import clean_tags
from forger.bucketing import VALID_BUCKETS, refine_bucket
from forger.analysis_cleanup import clean_analysis_text
from forger.scrape_result import Refused, scrape_url
from forger.storage import (
    data_lock,
    invalidate_cache,
    load_bookmarks,
    load_analysis_results,
    merge_bookmarks,
    save_bookmarks,
    upsert_analysis_results,
)
from forger.utils import _canonical_bookmark_identity, stable_bookmark_id

LOGGER = logging.getLogger(__name__)


class IngestionInvariantError(RuntimeError):
    """Raised when bookmark ingestion breaks required data invariants."""

def check_duplicate(url: str) -> Optional[Bookmark]:
    """Check if URL already exists, using the canonical bookmark identity.

    Raw string equality misses the same video with a different tracking
    param, and used to let a later merge overwrite a different resource
    that collided on a query-less id.
    """
    bookmarks = load_bookmarks()
    target = _canonical_bookmark_identity(url, "")
    if not target:
        return None
    for b in bookmarks:
        if _canonical_bookmark_identity(b.url, "") == target:
            return b
    return None


def find_similar_duplicate(
    bookmark: Bookmark,
    exclude_ids: set[str] | None = None,
) -> tuple[Optional[Bookmark], Optional[str]]:
    """Check if a near-duplicate topic already exists.

    Skips the check when the new bookmark text is empty/thin — comparing
    stubs produces false DUPLICATE_TOPIC hits (e.g. against "Article from …").
    Pass *exclude_ids* (e.g. the bookmark being replaced) so self-matches
    do not trip DUPLICATE_TOPIC / exact-URL hits during --replace.
    """
    if not is_usable_scrape_text(
        bookmark.text, source=bookmark.source, title=bookmark.title
    ):
        return None, None
    skip = exclude_ids or set()
    bookmarks = [b for b in load_bookmarks() if b.id not in skip]
    payload = [b.to_dict() for b in bookmarks]
    result = check_duplicate_topic(bookmark.url, bookmark.title, bookmark.tags, bookmark.text, payload)
    if result.get("is_duplicate"):
        top = result.get("similar", [{}])[0].get("bookmark")
        if top:
            return Bookmark.from_dict(top), result.get("message")
    similar = result.get("similar") or []
    if similar and similar[0].get("score", 0) >= 0.82:
        return Bookmark.from_dict(similar[0]["bookmark"]), result.get("message")
    return None, None


def scrape_and_create_bookmark(url: str) -> Optional[Bookmark]:
    """Scrape URL and create bookmark, or None when the scrape is refused.

    All scraping goes through ``forger.scrape_result.scrape_url``; only a
    ``Saved`` outcome (usable text, URL-free title) can become a bookmark.
    """
    outcome = scrape_url(url)
    if isinstance(outcome, Refused):
        return None
    source = outcome.source
    body = outcome.text
    title = outcome.title
    if source == "x":
        note = f"Auto-captured from X. Author: @{outcome.author or 'unknown'}"
        scraped_via = outcome.via or "playwright"
    else:
        note = f"Auto-captured article. Author: {outcome.author}" if outcome.author else "Auto-captured from URL"
        scraped_via = outcome.via

    bookmark_id = stable_bookmark_id(url, body)
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')

    # Defer tags until analysis (API analyze or agent resolve). Heuristic
    # auto-tags at scrape time invent junk ("research", "ai-tools") that
    # pollutes the bookmark while agent mode is still pending.
    return Bookmark(
        id=bookmark_id,
        source=source,
        url=url,
        text=body,
        title=title,
        note=note,
        created_at=timestamp,
        bookmarked_at=timestamp,
        tags=[],
        raw_payload={
            "ingestion_channel": "url",
            "capture_mode": "url_only",
            "scraped_via": scraped_via,
        },
    )



def _build_analysis_result(bookmark: Bookmark, analysis_dict: dict) -> AnalysisResult:
    # Bucket & scores come straight from the LLM (one brain; see ADR-0001).
    final_bucket = analysis_dict.get("recommendation_bucket", "archive")

    relates_raw = analysis_dict.get("relates_to")
    relates_to = None
    if relates_raw is not None and str(relates_raw).strip():
        relates_to = str(relates_raw).strip()

    result = AnalysisResult(
        bookmark_id=bookmark.id,
        summary=analysis_dict.get("summary", ""),
        recommendation_reason=analysis_dict.get("recommendation_reason", ""),
        key_insights=analysis_dict.get("key_insights", []),
        scoring_inputs=ScoringInputs.from_dict(analysis_dict.get("scoring_inputs", {})),
        worth_score=analysis_dict.get("worth_score", 0),
        effort_score=analysis_dict.get("effort_score", 0),
        priority_score=analysis_dict.get("priority_score", 0),
        recommendation_bucket=final_bucket,
        analysis_source=analysis_dict.get("analysis_source", "deepseek"),
        analyzed_at=bookmark.bookmarked_at,
        title=analysis_dict.get("title") or bookmark.title,
        relates_to=relates_to,
        actionable_this_week=_bool_if_provided(analysis_dict, "actionable_this_week"),
        reduces_friction=_bool_if_provided(analysis_dict, "reduces_friction"),
        reference_material=_bool_if_provided(analysis_dict, "reference_material"),
    )
    return result


def _bool_if_provided(payload: dict, key: str) -> bool | None:
    if key not in payload or not isinstance(payload[key], bool):
        return None
    return payload[key]


def _build_pending_result(bookmark: Bookmark) -> AnalysisResult:
    """Placeholder analysis for agent mode — resolved later by the agent."""
    return AnalysisResult(
        bookmark_id=bookmark.id,
        summary="[PENDING ANALYSIS] " + bookmark.text[:180],
        recommendation_reason="Awaiting agent analysis.",
        key_insights=[],
        scoring_inputs=ScoringInputs.from_dict({}),
        worth_score=0.0,
        effort_score=0.0,
        priority_score=0.0,
        recommendation_bucket="archive",
        analysis_source=PENDING_AGENT_SOURCE,
        analyzed_at=bookmark.bookmarked_at,
        title=bookmark.title,
    )




def resolve_pending_analysis(bookmark_id: str, analysis_dict: dict) -> Tuple[bool, str, Optional[AnalysisResult]]:
    """Ingest an agent-written analysis for a bookmark (agent mode step 2).

    Required: summary, recommendation_bucket (test_this_week|build_later|
    archive|ignore), relates_to (2+ sentences, >=40 chars, no None/N/A),
    and the three booleans actionable_this_week / reduces_friction /
    reference_material. Optional: title, recommendation_reason, key_insights,
    tags, novelty, excitement.
    """
    from forger.analysis import derive_legacy_scores

    bookmark = next((b for b in load_bookmarks() if b.id == bookmark_id), None)
    if not bookmark:
        return False, f"Bookmark {bookmark_id} not found", None

    bucket = analysis_dict.get("recommendation_bucket")
    if bucket not in VALID_BUCKETS:
        return False, "recommendation_bucket must be one of: " + "|".join(sorted(VALID_BUCKETS)), None
    if not analysis_dict.get("summary"):
        return False, "summary is required", None

    try:
        analysis_dict["relates_to"] = validate_relates_to(analysis_dict.get("relates_to"))
    except ValueError as exc:
        return False, str(exc), None

    derive_legacy_scores(analysis_dict)
    analysis_dict.setdefault("analysis_source", "agent")

    analysis = _build_analysis_result(bookmark, analysis_dict)
    analysis.recommendation_bucket = refine_bucket(bookmark, analysis)
    analysis = clean_analysis_text(bookmark, analysis)

    bookmark.tags = clean_tags(analysis_dict.get("tags"), bookmark.title, bookmark.text, bookmark.url, bookmark.note)
    # Re-read and write under the data lock (see process_bookmark_url).
    with data_lock():
        invalidate_cache()
        save_bookmarks(merge_bookmarks(load_bookmarks(), [bookmark]))
        upsert_analysis_results(load_analysis_results(), [analysis])

    try:
        _sync_dashboard()
    except Exception as e:
        LOGGER.warning(f"Failed to sync dashboard after resolve: {e}")

    return True, f"Resolved {bookmark_id}: bucket={analysis.recommendation_bucket} priority={analysis.priority_score}", analysis


def _sync_dashboard() -> None:
    from forger.dashboard_sync import sync_dashboard_data

    if not sync_dashboard_data():
        raise RuntimeError("Dashboard sync failed")


def _verify_ingestion_invariants(before_bookmarks: list[Bookmark], before_analyses: list[AnalysisResult], bookmark: Bookmark) -> tuple[list[Bookmark], list[AnalysisResult]]:
    invalidate_cache()
    after_bookmarks = load_bookmarks()
    after_analyses = load_analysis_results()

    bookmark_ids = {b.id for b in after_bookmarks}
    analysis_ids = {a.bookmark_id for a in after_analyses}

    if bookmark.id not in bookmark_ids:
        raise IngestionInvariantError(f"Bookmark {bookmark.id} missing after save")
    if bookmark.id not in analysis_ids:
        raise IngestionInvariantError(f"Analysis {bookmark.id} missing after save")
    if len(after_bookmarks) < len(before_bookmarks):
        raise IngestionInvariantError("Bookmark count dropped during ingestion")
    if len(after_analyses) < len(before_analyses):
        raise IngestionInvariantError("Analysis count dropped during ingestion")
    if len(after_analyses) - len(after_bookmarks) > 0:
        LOGGER.warning(
            "Analysis/bookmark mismatch after ingestion: %s analyses vs %s bookmarks",
            len(after_analyses),
            len(after_bookmarks),
        )

    return after_bookmarks, after_analyses


def find_bookmark_by_id(bookmark_id: str) -> Optional[Bookmark]:
    """Return a stored bookmark by id, or None."""
    target = (bookmark_id or "").strip()
    if not target:
        return None
    for b in load_bookmarks():
        if b.id == target:
            return b
    return None


def process_bookmark_url(
    url: str,
    analyze: bool = True,
    note: str | None = None,
    replace: bool = False,
) -> Tuple[bool, str, Optional[Bookmark], Optional[AnalysisResult]]:
    """
    Complete workflow: scrape, analyze, save, push.

    Args:
        url: the bookmark URL
        analyze: run LLM analysis now. When False (agent mode), a pending
            placeholder analysis is stored; the calling agent writes its own
            analysis later and resolves it via resolve_pending_analysis().
        note: the user's own words accompanying the URL (a URL+text message).
            Stored on the bookmark and passed to the analysis as the
            strongest signal of why they saved it.
        replace: when True, re-scrape and overwrite an existing bookmark for
            the same canonical URL instead of returning DUPLICATE. Default
            False keeps DUPLICATE as the safe default for `forge add`.

    Returns:
        (success, message, bookmark, analysis)
    """
    # Check for duplicate (default) or locate the row to replace
    existing = check_duplicate(url)
    if existing and not replace:
        return False, f"DUPLICATE: Already saved - {existing.title[:50]}...", existing, None

    # Scrape and create bookmark. On replace failure the existing row is left
    # untouched — never wipe a stub only to save nothing.
    bookmark = scrape_and_create_bookmark(url)
    if not bookmark:
        return (
            False,
            "SCRAPE_FAILED: No usable content (refusing to save empty/thin/challenge trash)",
            None,
            None,
        )

    if existing and replace:
        # Same URL → same stable id; keep original created_at, mark replace.
        bookmark.created_at = existing.created_at or bookmark.created_at
        bookmark.raw_payload = {
            **(existing.raw_payload or {}),
            **(bookmark.raw_payload or {}),
            "replaced": True,
            "replaced_at": bookmark.bookmarked_at,
        }
        if existing.note and not (note and note.strip()):
            # Keep prior user note unless a new --note was supplied
            bookmark.note = existing.note

    if note and note.strip():
        bookmark.note = note.strip()
        bookmark.raw_payload["capture_mode"] = "url_with_note"

    exclude_ids = {existing.id} if (existing and replace) else None
    similar_existing, similar_message = find_similar_duplicate(
        bookmark, exclude_ids=exclude_ids
    )
    if similar_existing:
        return False, f"DUPLICATE_TOPIC: {similar_message}", similar_existing, None

    if analyze:
        # Run LLM analysis
        LOGGER.info(f"Running LLM analysis for: {bookmark.title[:50]}...")
        analysis_dict = analyze_bookmark(
            text=bookmark.text,
            title=bookmark.title,
            url=bookmark.url,
            user_note=bookmark.note if (note and note.strip()) else None
        )

        # Update bookmark tags from the analysis
        bookmark.tags = clean_tags(analysis_dict.get("tags"), bookmark.title, bookmark.text, bookmark.url, bookmark.note)
        LOGGER.info(f"Final tags: {bookmark.tags}")

        analysis = _build_analysis_result(bookmark, analysis_dict)
        analysis.recommendation_bucket = refine_bucket(bookmark, analysis)
        analysis = clean_analysis_text(bookmark, analysis)
    else:
        # Agent mode: no API call — the calling agent analyzes and resolves.
        # Keep tags empty until resolve writes real analysis tags.
        bookmark.tags = []
        analysis = _build_pending_result(bookmark)

    # Legacy / odd identity on replace: drop the old row so replace does not
    # leave two bookmarks for the same URL.
    drop_ids = {existing.id} if (existing and replace and existing.id != bookmark.id) else set()

    # Read-merge-write under the cross-process data lock so a concurrent
    # `forge add` cannot overwrite this bookmark with a stale list.
    with data_lock():
        invalidate_cache()  # another process may have written since we started
        before_bookmarks = [b for b in load_bookmarks() if b.id not in drop_ids]
        before_analyses = [a for a in load_analysis_results() if a.bookmark_id not in drop_ids]
        save_bookmarks(merge_bookmarks(before_bookmarks, [bookmark]))
        LOGGER.info(f"Saved bookmark: {bookmark.id}")
        upsert_analysis_results(before_analyses, [analysis])
        LOGGER.info(f"Saved analysis: {analysis.bookmark_id}")

    try:
        _verify_ingestion_invariants(before_bookmarks, before_analyses, bookmark)
    except IngestionInvariantError as exc:
        return False, f"Ingestion invariant failed: {exc}", bookmark, analysis

    try:
        _sync_dashboard()
        LOGGER.info("Synced dashboard data")
    except Exception as e:
        LOGGER.warning(f"Failed to sync dashboard: {e}")
        return False, f"Saved but dashboard sync failed: {e}", bookmark, analysis

    # Git auto-push (opt-in: FORGER_AUTO_GIT=1)
    push_success = git_auto_push(bookmark.title)
    why = analysis.recommendation_reason or ""
    if len(why) > 120:
        why = why[:117] + "..."
    verb = "Replaced" if (existing and replace) else "Saved"
    where = "✓ Pushed to GitHub" if push_success else "✓ Saved locally"
    if is_pending_analysis(analysis):
        # Agent mode: no analysis yet, so no bucket or priority to report.
        message = f"✓ {verb}: {bookmark.title}\n✓ Analysis: pending (run forge resolve)\n{where}"
    else:
        message = f"✓ {verb}: {bookmark.title}\n✓ Bucket: {analysis.recommendation_bucket}\n✓ Priority: {analysis.priority_score}\n✓ Why: {why}\n{where}"
    
    return True, message, bookmark, analysis
