from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config.settings import LATEST_REPORT_PATH, REPORT_HISTORY_DIR, REPORT_TEMPLATE_PATH
from rolloforge.models import AnalysisResult, Bookmark
from rolloforge.utils import ensure_parent, utc_now_iso


def _build_rows(bookmarks: list[Bookmark], analysis_map: dict[str, AnalysisResult]) -> list[dict]:
    rows: list[dict] = []
    for bookmark in bookmarks:
        analysis = analysis_map.get(bookmark.id)
        rows.append(
            {
                "id": bookmark.id,
                "url": bookmark.url,
                "title": bookmark.title or bookmark.text[:80],
                "text": bookmark.text,
                "note": bookmark.note or "",
                "author": bookmark.author or "unknown",
                "created_at": bookmark.created_at or "",
                "bookmarked_at": bookmark.bookmarked_at or "",
                "tags": bookmark.tags,
                "summary": analysis.summary if analysis else "Pending analysis",
                "recommendation_reason": analysis.recommendation_reason if analysis else "Pending analysis",
                "key_insights": analysis.key_insights if analysis else [],
                "worth_score": analysis.worth_score if analysis else 0,
                "effort_score": analysis.effort_score if analysis else 0,
                "priority_score": analysis.priority_score if analysis else 0,
                "recommendation_bucket": analysis.recommendation_bucket if analysis else "archive",
                "analysis_source": analysis.analysis_source if analysis else "pending",
            }
        )
    return sorted(rows, key=lambda item: item["priority_score"], reverse=True)


def _stats(rows: list[dict]) -> dict[str, int]:
    return summarize_recommendations_from_rows(rows)


def summarize_recommendations_from_rows(rows: list[dict]) -> dict[str, int]:
    return {
        "total": len(rows),
        "test_this_week": sum(1 for row in rows if row["recommendation_bucket"] == "test_this_week"),
        "build_later": sum(1 for row in rows if row["recommendation_bucket"] == "build_later"),
        "archive": sum(1 for row in rows if row["recommendation_bucket"] == "archive"),
        "ignore": sum(1 for row in rows if row["recommendation_bucket"] == "ignore"),
    }


def summarize_recommendations(analysis_results: list[AnalysisResult]) -> dict[str, int]:
    rows = [{"recommendation_bucket": result.recommendation_bucket} for result in analysis_results]
    return summarize_recommendations_from_rows(rows)


def generate_report(
    bookmarks: list[Bookmark],
    analysis_results: list[AnalysisResult],
    template_path: Path = REPORT_TEMPLATE_PATH,
    latest_path: Path = LATEST_REPORT_PATH,
    history_dir: Path = REPORT_HISTORY_DIR,
) -> Path:
    analysis_map = {result.bookmark_id: result for result in analysis_results}
    
    # Build rows for ALL bookmarks to get accurate stats
    all_rows = _build_rows(bookmarks, analysis_map)
    
    # Keep only last 10 bookmarks for display (most recent first)
    recent_bookmarks = sorted(bookmarks, key=lambda b: b.bookmarked_at or "", reverse=True)[:10]
    display_rows = _build_rows(recent_bookmarks, analysis_map)
    
    generated_at = utc_now_iso()

    environment = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    rendered = environment.get_template(template_path.name).render(
        generated_at=generated_at,
        rows=display_rows,
        stats=_stats(all_rows),
        showing_last_n=len(recent_bookmarks),
        total_bookmarks=len(bookmarks),
    )

    ensure_parent(latest_path)
    latest_path.write_text(rendered, encoding="utf-8")

    # Save to history
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / f"report_{generated_at.replace(':', '-')}.html"
    history_path.write_text(rendered, encoding="utf-8")
    
    # Keep only last 2 reports, delete older ones
    history_files = sorted(history_dir.glob("report_*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old_file in history_files[2:]:
        old_file.unlink()
    
    return latest_path
