from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from config.settings import Settings
from forger.models import AnalysisResult, Bookmark, ScoringInputs
from forger.storage import (
    load_analysis_results,
    load_bookmarks,
    load_known_bookmark_ids,
    load_seen_bookmark_ids,
    merge_bookmarks,
    save_bookmarks,
    save_known_bookmark_ids,
    save_seen_bookmark_ids,
    upsert_analysis_results,
)
from forger.utils import compact_text, stable_bookmark_id, utc_now_iso
from forger.tagging import clean_tags


# URL detection patterns
URL_PATTERN = re.compile(r"https?://[^\s<>\[\]]+", re.IGNORECASE)
FIELD_PATTERN = re.compile(r"^(url|text|note|tag|source)\s*:\s*(.*)$", re.IGNORECASE)
VALID_SOURCES = {"x", "article", "github", "manual"}
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ParsedTelegramBookmark:
    url: str
    text: str
    note: Optional[str]
    tag: str
    source: str
    raw_message: str
    capture_mode: str  # "manual", "url_only", "url_plus_note"


def detect_url(message: str) -> Optional[str]:
    """Extract first URL from message."""
    match = URL_PATTERN.search(message.strip())
    return match.group(0) if match else None


def infer_source_from_url(url: str) -> str:
    lowered = url.lower()
    if "x.com/" in lowered or "twitter.com/" in lowered:
        return "x"
    if "github.com/" in lowered:
        return "github"
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return "article"
    return "manual"


def normalize_tag(tag: str | None) -> str:
    value = (tag or "").strip().lower()
    if not value:
        return "research"
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^a-z0-9_-]", "", value)
    return value or "research"


def normalize_source(source: str | None, url: str) -> str:
    value = (source or "").strip().lower()
    if value in VALID_SOURCES:
        return value
    return infer_source_from_url(url)


def parse_frictionless_url(message: str) -> ParsedTelegramBookmark:
    """Parse a frictionless URL message (plain URL with optional note)."""
    url = detect_url(message)
    if not url:
        raise ValueError("No URL found in message.")

    # Remove the URL from the message to get any additional text
    remaining = message.replace(url, "").strip()
    
    # Check if there's additional text (note)
    text_content = remaining.strip() if remaining.strip() else ""
    
    # Determine capture mode based on whether there's extra content
    if text_content:
        capture_mode = "url_plus_note"
        # Use the additional text as both text and note
        text = text_content
        note = text_content
        scraped_via = None
    else:
        capture_mode = "url_only"
        
        # For X URLs, try to scrape content
        source = infer_source_from_url(url)
        if source == "x":
            try:
                from forger.scrapers import fetch_x_content_sync
                LOGGER.info(f"Attempting to scrape X content: {url}")
                scraped = fetch_x_content_sync(url)
                
                if scraped and scraped.get("success"):
                    text = scraped["text"]
                    note = f"Auto-captured from X. Author: @{scraped.get('author', 'unknown')}"
                    scraped_via = "playwright"
                    LOGGER.info(f"Successfully scraped X content: {len(text)} chars")
                else:
                    # Fallback to placeholder
                    text = f"Twitter/X post from @{_extract_x_handle(url)}. View on X for full content."
                    note = "Auto-captured from URL-only message (scraping failed)"
                    scraped_via = None
            except Exception as e:
                LOGGER.warning(f"X scraping failed: {e}")
                text = f"Twitter/X post from @{_extract_x_handle(url)}. View on X for full content."
                note = "Auto-captured from URL-only message"
                scraped_via = None
        else:
            # For non-X URLs, use placeholder
            text = f"[URL content not available] {url}"
            note = "Auto-captured from URL-only message"
            scraped_via = None

    parsed = ParsedTelegramBookmark(
        url=url,
        text=text,
        note=note,
        tag="research",
        source=infer_source_from_url(url),
        raw_message=message.strip(),
        capture_mode=capture_mode,
    )
    
    # Attach scraping metadata
    if scraped_via:
        parsed.raw_payload = getattr(parsed, 'raw_payload', {})
        if isinstance(parsed.raw_payload, dict):
            parsed.raw_payload["scraped_via"] = scraped_via
    
    return parsed


def _extract_x_handle(url: str) -> str:
    """Extract X handle from URL."""
    try:
        # https://x.com/username/status/...
        parts = url.split("/")
        if "x.com" in url or "twitter.com" in url:
            for i, part in enumerate(parts):
                if part in ("x.com", "twitter.com") and i + 1 < len(parts):
                    return parts[i + 1]
    except (IndexError, ValueError):
        pass
    return "unknown"


def parse_telegram_bookmark_message(message: str) -> ParsedTelegramBookmark:
    lines = [line.rstrip() for line in message.strip().splitlines()]
    if not lines:
        raise ValueError("Message is empty.")
    if lines[0].strip().lower() != "/bookmark":
        raise ValueError("Message must start with /bookmark.")

    collected: dict[str, list[str]] = {}
    current_field: str | None = None

    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        match = FIELD_PATTERN.match(line)
        if match:
            current_field = match.group(1).lower()
            collected.setdefault(current_field, []).append(match.group(2).strip())
            continue
        if current_field is None:
            raise ValueError(f"Unexpected content before any field: {raw_line}")
        collected.setdefault(current_field, []).append(line)

    url = " ".join(collected.get("url", [])).strip()
    text = "\n".join(collected.get("text", [])).strip()
    note = "\n".join(collected.get("note", [])).strip() or None
    tag = normalize_tag(" ".join(collected.get("tag", [])).strip())
    source = normalize_source(" ".join(collected.get("source", [])).strip() or None, url)

    if not url:
        raise ValueError("URL is required.")
    if not text:
        raise ValueError("Text is required.")

    return ParsedTelegramBookmark(
        url=url,
        text=text,
        note=note,
        tag=tag,
        source=source,
        raw_message=message.strip(),
        capture_mode="manual",
    )


def bookmark_from_parsed_message(parsed: ParsedTelegramBookmark) -> Bookmark:
    bookmark_id = stable_bookmark_id(parsed.url, parsed.text)
    timestamp = utc_now_iso()
    
    # Generate title from first line or first sentence of text (max 80 chars)
    title = _generate_title(parsed.text)
    
    return Bookmark(
        id=bookmark_id,
        source=parsed.source,
        url=parsed.url,
        text=parsed.text,
        title=title,
        note=parsed.note,
        created_at=timestamp,
        bookmarked_at=timestamp,
        tags=clean_tags([parsed.tag], parsed.text, parsed.url, parsed.note),
        raw_payload={
            "ingestion_channel": "telegram",
            "telegram_message": parsed.raw_message,
            "note": parsed.note,
            "capture_mode": parsed.capture_mode,
        },
    )


def _generate_title(text: str, max_length: int = 80) -> str:
    """Generate a clean, concise title from text.
    
    - Takes first sentence or first complete thought
    - Removes hashtags for cleaner reading
    - No trailing ellipsis
    - Ends with proper punctuation
    """
    if not text:
        return "Untitled"
    
    # Get first line and clean it up
    first_line = text.split('\n')[0].strip()
    
    # Remove hashtags for cleaner title (keep the words, lose the #)
    import re
    first_line = re.sub(r'#(\w+)', r'\1', first_line)
    
    # If it's short enough, use it as-is (add period if needed)
    if len(first_line) <= max_length:
        if first_line[-1] in '.?!':
            return first_line
        return first_line + '.'
    
    # Look for sentence-ending punctuation within limit
    for punct in ['. ', '? ', '! ']:
        idx = first_line[:max_length].rfind(punct)
        if idx > 20:
            return first_line[:idx + 1].strip()
    
    # Try colon as alternative
    colon_idx = first_line[:max_length].rfind(': ')
    if colon_idx > 30:
        return first_line[:colon_idx + 1].strip()
    
    # No good break found - truncate at word boundary
    idx = first_line[:max_length].rfind(' ')
    if idx > 20:
        title = first_line[:idx].strip()
    else:
        title = first_line[:max_length].strip()
    
    # Ensure it ends with period (NOT ellipsis)
    if title and title[-1] not in '.?!':
        title += '.'
    elif title.endswith('...'):
        # Replace ellipsis with single period
        title = title.rstrip('.') + '.'
    
    return title if title else "Untitled"


def next_action_for_bucket(bucket: str) -> str:
    mapping = {
        "test_this_week": "Run a concrete experiment this week.",
        "build_later": "Keep it in the backlog and revisit after current priorities.",
        "archive": "Store it for reference without active follow-up.",
        "ignore": "Drop it and move on.",
    }
    return mapping.get(bucket, "Review manually.")


def build_failed_analysis_result(bookmark: Bookmark) -> AnalysisResult:
    return AnalysisResult(
        bookmark_id=bookmark.id,
        summary=compact_text(bookmark.text, limit=220),
        recommendation_reason="Analysis failed; bookmark was still saved for later review.",
        key_insights=[
            "Bookmark persisted successfully.",
            "Analysis failed during ingest.",
            "Retry analysis later.",
        ],
        scoring_inputs=ScoringInputs(
            relevance=0,
            practical_value=0,
            actionability=0,
            stage_fit=0,
            novelty=0,
            excitement=0,
            difficulty=0,
            time_cost=0,
        ),
        worth_score=0,
        effort_score=0,
        priority_score=0,
        recommendation_bucket="archive",
        analysis_source="failed",
        confidence="low",
        difficulty_reason="analysis failed",
        next_action="retry analysis later",
        analyzed_at=utc_now_iso(),
    )


def fallback_analysis(bookmark: Bookmark, pipeline_stage: str) -> dict:
    """Generate fallback analysis payload for URL-only bookmarks."""
    return {
        "summary": bookmark.text[:200] if bookmark.text else "URL-only bookmark with limited context.",
        "recommendation_reason": f"Low-confidence analysis for {pipeline_stage} stage. Limited context available.",
        "key_insights": ["Captured from URL only", "Consider re-saving with full context"],
        "scoring_inputs": {
            "relevance": 5.0,
            "practical_value": 4.0,
            "actionability": 3.0,
            "stage_fit": 5.0,
            "novelty": 5.0,
            "excitement": 4.0,
            "difficulty": 5.0,
            "time_cost": 4.0,
        },
    }


def build_low_confidence_analysis_result(bookmark: Bookmark, settings: Settings) -> AnalysisResult:
    """Build analysis result for URL-only bookmarks with low confidence."""
    # Use fallback analysis but mark as low confidence
    payload = fallback_analysis(bookmark, settings.pipeline_stage)
    inputs = ScoringInputs.from_dict(payload.get("scoring_inputs", {}))
    
    # Adjust scores down slightly for low-confidence items.
    # Scores/bucket come from the LLM payload (one brain; see ADR-0001) —
    # keyword-based score_analysis is gone.
    worth_score = float(payload.get("worth_score", 3.0))
    effort_score = float(payload.get("effort_score", 5.0))
    priority_score = max(0, float(payload.get("priority_score", 3.0)) * 0.7)  # Reduce priority for low-confidence
    bucket = str(payload.get("recommendation_bucket", "archive"))

    return AnalysisResult(
        bookmark_id=bookmark.id,
        summary=compact_text(str(payload.get("summary", bookmark.text)), limit=220),
        recommendation_reason=compact_text(
            str(payload.get("recommendation_reason", "Low-confidence analysis due to incomplete input.")),
            limit=260,
        ),
        key_insights=payload.get("key_insights", []) + ["Low-confidence: captured from URL only, limited context available."],
        scoring_inputs=inputs,
        worth_score=worth_score,
        effort_score=effort_score,
        priority_score=priority_score,
        recommendation_bucket=bucket,
        analysis_source="fallback_low_confidence",
        confidence="low",
        difficulty_reason="incomplete input",
        next_action="Add more context or re-save with /bookmark for better analysis",
        analyzed_at=utc_now_iso(),
    )


def ingest_telegram_bookmark_message(message: str, settings: Settings) -> tuple[Bookmark, AnalysisResult, dict[str, str | float]]:
    # Try to detect if it's a /bookmark command first
    lines = [line.strip() for line in message.strip().splitlines()]
    is_manual = lines and lines[0].strip().lower() == "/bookmark"
    
    # Try to find a URL in the message
    url = detect_url(message)
    
    if not url:
        raise ValueError("No URL found in message.")
    
    # Parse based on mode
    if is_manual:
        # Full /bookmark format
        parsed = parse_telegram_bookmark_message(message)
    else:
        # Frictionless mode - plain URL with optional note
        parsed = parse_frictionless_url(message)
    
    bookmark = bookmark_from_parsed_message(parsed)

    existing_bookmarks = load_bookmarks()
    merged_bookmarks = merge_bookmarks(existing_bookmarks, [bookmark])
    save_bookmarks(merged_bookmarks)
    save_known_bookmark_ids(load_known_bookmark_ids() | {bookmark.id})
    
    # Auto-sync dashboard data
    try:
        import subprocess
        import sys
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]
        subprocess.run(
            [sys.executable, str(project_root / "forge"), "sync"],
            cwd=str(project_root),
            capture_output=True,
            timeout=60,
        )
    except Exception:
        pass  # Non-critical, don't fail ingestion if sync fails

    # Skip auto-analysis here - run the analysis step or forge add to analyze
    # Create placeholder result indicating pending LLM analysis
    result = AnalysisResult(
        bookmark_id=bookmark.id,
        summary="[PENDING LLM ANALYSIS] " + compact_text(bookmark.text, limit=180),
        recommendation_reason="Bookmark captured. Awaiting analysis.",
        key_insights=[
            f"Source: {bookmark.source}",
            f"Capture mode: {parsed.capture_mode}",
            "Status: Pending LLM analysis",
            "Action: run analysis to score this bookmark"
        ],
        scoring_inputs=ScoringInputs(
            relevance=0, practical_value=0, actionability=0, stage_fit=0,
            novelty=0, excitement=0, difficulty=0, time_cost=0
        ),
        worth_score=0.0,
        effort_score=0.0,
        priority_score=0.0,
        recommendation_bucket="pending",
        analysis_source="pending_llm",
        analyzed_at=utc_now_iso(),
        confidence="pending",
        difficulty_reason="awaiting LLM analysis",
        next_action="Run analysis to update scores",
    )
    
    existing_results = load_analysis_results()
    upsert_analysis_results(existing_results, [result])
    save_seen_bookmark_ids(load_seen_bookmark_ids() | {bookmark.id})

    confirmation = {
        "status": "pending_llm",
        "source": bookmark.source,
        "capture_mode": parsed.capture_mode,
        "tag": bookmark.tags[0] if bookmark.tags else "general",
        "recommendation": "pending",
        "priority": 0.0,
        "next_action": "Run analysis for this bookmark",
    }
    return bookmark, result, confirmation