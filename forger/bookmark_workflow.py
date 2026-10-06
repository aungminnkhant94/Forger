"""Complete bookmark workflow with auto-push.

This module combines scraping, analysis, saving, and git push into one workflow.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from forger.deepseek_analysis import deepseek_analyze_bookmark
from forger.similarity import check_duplicate_topic
from forger.git_auto import git_auto_push
from forger.models import Bookmark, AnalysisResult, ScoringInputs
from forger.tagging import clean_tags
from forger.bucketing import refine_bucket
from forger.analysis_cleanup import clean_analysis_text
from forger.scrapers import fetch_x_content_sync
from forger.storage import (
    load_bookmarks,
    load_analysis_results,
    merge_bookmarks,
    save_bookmarks,
    upsert_analysis_results,
)
from forger.utils import stable_bookmark_id

LOGGER = logging.getLogger(__name__)


class IngestionInvariantError(RuntimeError):
    """Raised when bookmark ingestion breaks required data invariants."""

def check_duplicate(url: str) -> Optional[Bookmark]:
    """Check if URL already exists in bookmarks."""
    bookmarks = load_bookmarks()
    for b in bookmarks:
        if b.url == url:
            return b
    return None


def find_similar_duplicate(bookmark: Bookmark) -> tuple[Optional[Bookmark], Optional[str]]:
    """Check if a near-duplicate topic already exists."""
    bookmarks = load_bookmarks()
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
    """Scrape URL and create bookmark."""
    # Determine source
    url_lower = url.lower()
    if "x.com/" in url_lower or "twitter.com/" in url_lower:
        source = "x"
        # Try to scrape X
        try:
            scraped = fetch_x_content_sync(url)
            if scraped and scraped.get("success"):
                text = scraped["text"]
                author = scraped.get("author", "unknown")
                title = scraped.get("title", text[:80] + "..." if len(text) > 80 else text)
                note = f"Auto-captured from X. Author: @{author}"
                scraped_via = "playwright"
            else:
                # Fallback
                handle = _extract_x_handle(url)
                text = f"Twitter/X post from @{handle}. View on X for full content."
                title = f"Twitter/X post from @{handle}"
                note = "Auto-captured from URL-only message (scraping failed)"
                scraped_via = None
        except Exception as e:
            LOGGER.warning(f"X scraping failed: {e}")
            handle = _extract_x_handle(url)
            text = f"Twitter/X post from @{handle}. View on X for full content."
            title = f"Twitter/X post from @{handle}"
            note = "Auto-captured from URL-only message"
            scraped_via = None
    else:
        source = "article"
        scraped = None
        try:
            from forger.scrapers.article_scraper import scrape_article

            scraped = scrape_article(url)
        except Exception as e:
            LOGGER.warning(f"Article scraping failed: {e}")
        if scraped and scraped.get("success"):
            text = scraped["text"]
            title = scraped.get("title") or f"Article from {url.split('/')[2]}"
            author = scraped.get("author")
            note = f"Auto-captured article. Author: {author}" if author else "Auto-captured from URL"
            scraped_via = scraped.get("source")
        else:
            text = f"[URL content not available] {url}"
            title = f"Article from {url.split('/')[2]}"
            note = "Captured from URL only (scraping failed)"
            scraped_via = None
    
    bookmark_id = stable_bookmark_id(url, text)
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    bookmark = Bookmark(
        id=bookmark_id,
        source=source,
        url=url,
        text=text,
        title=title,
        note=note,
        created_at=timestamp,
        bookmarked_at=timestamp,
        tags=clean_tags([], title, text, url, note),
        raw_payload={
            "ingestion_channel": "url",
            "capture_mode": "url_only",
            "scraped_via": scraped_via,
        },
    )
    
    return bookmark


def _extract_x_handle(url: str) -> str:
    """Extract X handle from URL."""
    try:
        parts = url.split("/")
        if "x.com" in url or "twitter.com" in url:
            for i, part in enumerate(parts):
                if part in ("x.com", "twitter.com") and i + 1 < len(parts):
                    return parts[i + 1]
    except (IndexError, ValueError):
        pass
    return "unknown"


def _build_analysis_result(bookmark: Bookmark, analysis_dict: dict) -> AnalysisResult:
    # Bucket & scores come straight from the LLM (one brain; see ADR-0001).
    final_bucket = analysis_dict.get("recommendation_bucket", "archive")

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
    )
    return result


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
        analysis_source="pending_agent",
        analyzed_at=bookmark.bookmarked_at,
        title=bookmark.title,
    )


VALID_BUCKETS = {"test_this_week", "build_later", "archive", "ignore"}


def resolve_pending_analysis(bookmark_id: str, analysis_dict: dict) -> Tuple[bool, str, Optional[AnalysisResult]]:
    """Ingest an agent-written analysis for a bookmark (agent mode step 2).

    The analysis dict must contain: summary, recommendation_bucket (one of
    test_this_week|build_later|archive|ignore), and the three booleans
    actionable_this_week / reduces_friction / reference_material. Optional:
    title, recommendation_reason, relates_to, key_insights, tags, novelty,
    excitement.
    """
    from forger.deepseek_analysis import derive_legacy_scores

    bookmark = next((b for b in load_bookmarks() if b.id == bookmark_id), None)
    if not bookmark:
        return False, f"Bookmark {bookmark_id} not found", None

    bucket = analysis_dict.get("recommendation_bucket")
    if bucket not in VALID_BUCKETS:
        return False, "recommendation_bucket must be one of: " + "|".join(sorted(VALID_BUCKETS)), None
    if not analysis_dict.get("summary"):
        return False, "summary is required", None

    derive_legacy_scores(analysis_dict)
    analysis_dict.setdefault("analysis_source", "agent")

    analysis = _build_analysis_result(bookmark, analysis_dict)
    analysis.recommendation_bucket = refine_bucket(bookmark, analysis)
    analysis = clean_analysis_text(bookmark, analysis)

    bookmark.tags = clean_tags(analysis_dict.get("tags"), bookmark.title, bookmark.text, bookmark.url, bookmark.note)
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


def process_bookmark_url(url: str, analyze: bool = True, note: str | None = None) -> Tuple[bool, str, Optional[Bookmark], Optional[AnalysisResult]]:
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

    Returns:
        (success, message, bookmark, analysis)
    """
    # Check for duplicate
    existing = check_duplicate(url)
    if existing:
        return False, f"DUPLICATE: Already saved - {existing.title[:50]}...", existing, None

    # Scrape and create bookmark
    bookmark = scrape_and_create_bookmark(url)
    if not bookmark:
        return False, "Failed to scrape URL", None, None

    if note and note.strip():
        bookmark.note = note.strip()
        bookmark.raw_payload["capture_mode"] = "url_with_note"

    similar_existing, similar_message = find_similar_duplicate(bookmark)
    if similar_existing:
        return False, f"DUPLICATE_TOPIC: {similar_message}", similar_existing, None

    if analyze:
        # Run LLM analysis
        LOGGER.info(f"Running LLM analysis for: {bookmark.title[:50]}...")
        analysis_dict = deepseek_analyze_bookmark(
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
        analysis = _build_pending_result(bookmark)

    before_bookmarks = load_bookmarks()
    before_analyses = load_analysis_results()

    merged_bookmarks = merge_bookmarks(before_bookmarks, [bookmark])
    save_bookmarks(merged_bookmarks)
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
    if push_success:
        message = f"✓ Saved: {bookmark.title}\n✓ Bucket: {analysis.recommendation_bucket}\n✓ Priority: {analysis.priority_score}\n✓ Why: {why}\n✓ Pushed to GitHub"
    else:
        message = f"✓ Saved: {bookmark.title}\n✓ Bucket: {analysis.recommendation_bucket}\n✓ Priority: {analysis.priority_score}\n✓ Why: {why}\n✓ Saved locally"
    
    return True, message, bookmark, analysis
