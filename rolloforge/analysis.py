"""Batch bookmark analysis — the one-brain path (ADR-0001).

Every analysis goes through the LLM (deepseek_analysis), which reads the
Personal Context canon and produces summary, relates-to prose, scores, and
bucket together. The keyword auto-scorer this module used to implement was
removed; its output ('llm_auto_scored') was the source of the degenerate
backlog being re-analyzed.
"""
from __future__ import annotations

import logging

from config.settings import Settings
from rolloforge.models import AnalysisResult, Bookmark, ScoringInputs
from rolloforge.deepseek_analysis import deepseek_analyze_bookmark
from rolloforge.utils import utc_now_iso

LOGGER = logging.getLogger(__name__)


def _result_from_llm(bookmark: Bookmark, payload: dict) -> AnalysisResult:
    """Build an AnalysisResult from the LLM payload; mark quarantine on failure."""
    if payload.get("analysis_source") == "deepseek_fallback" or "deepseek-failed" in payload.get("tags", []):
        return AnalysisResult(
            bookmark_id=bookmark.id,
            summary=str(payload.get("summary", ""))[:220],
            recommendation_reason="LLM analysis failed — re-run pipeline to retry.",
            key_insights=[],
            scoring_inputs=ScoringInputs.from_dict(payload.get("scoring_inputs", {})),
            worth_score=float(payload.get("worth_score", 3.0)),
            effort_score=float(payload.get("effort_score", 5.0)),
            priority_score=float(payload.get("priority_score", 3.0)),
            recommendation_bucket="archive",
            analysis_source="llm_failed",
            analyzed_at=utc_now_iso(),
            title=payload.get("title") or bookmark.title,
            relates_to=payload.get("relates_to"),
            tags=list(payload.get("tags", [])),
        )

    return AnalysisResult(
        bookmark_id=bookmark.id,
        summary=str(payload.get("summary", "")),
        recommendation_reason=str(payload.get("recommendation_reason", "")),
        key_insights=[str(i) for i in payload.get("key_insights", [])],
        scoring_inputs=ScoringInputs.from_dict(payload.get("scoring_inputs", {})),
        worth_score=float(payload.get("worth_score", 5.0)),
        effort_score=float(payload.get("effort_score", 5.0)),
        priority_score=float(payload.get("priority_score", 5.0)),
        recommendation_bucket=str(payload.get("recommendation_bucket", "archive")),
        analysis_source="llm",
        analyzed_at=utc_now_iso(),
        title=payload.get("title") or bookmark.title,
        relates_to=payload.get("relates_to"),
        tags=list(payload.get("tags", [])),
    )


def analyze_pending_bookmarks(
    bookmarks: list[Bookmark],
    existing_ids: set[str],
    settings: Settings,
    limit: int | None = None,
    force_all: bool = False,
) -> list[AnalysisResult]:
    """Analyze pending bookmarks through the LLM (one brain; ADR-0001)."""
    pending = bookmarks if force_all else [b for b in bookmarks if b.id not in existing_ids]
    if limit is not None:
        pending = pending[:limit]
    LOGGER.info("Analyzing %s bookmark(s) through the LLM.", len(pending))
    results: list[AnalysisResult] = []
    for bookmark in pending:
        payload = deepseek_analyze_bookmark(bookmark.text, bookmark.title or "", bookmark.url)
        results.append(_result_from_llm(bookmark, payload))
    return results
