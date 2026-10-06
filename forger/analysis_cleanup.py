from __future__ import annotations

import re

from forger.models import AnalysisResult, Bookmark

GENERIC_REASON_PATTERNS = [
    r"perfect for your stage[^.]*",
    r"this user should care because[^.]*",
    r"assigned '[^']+' because",
    r"directly relevant to your [^.]+ interests",
]

GENERIC_SUMMARY_PATTERNS = [
    r"this user should care because",
    r"assigned '[^']+' because",
]


def _squeeze(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def clean_reason(text: str, bookmark: Bookmark, analysis: AnalysisResult) -> str:
    reason = _squeeze(text)
    for pattern in GENERIC_REASON_PATTERNS:
        reason = re.sub(pattern, "", reason, flags=re.IGNORECASE).strip(" .-")
    if not reason:
        title = bookmark.title or bookmark.text[:80]
        bucket = analysis.recommendation_bucket
        if bucket == 'test_this_week':
            return f"Useful now because it can improve current workflows or decisions around {title[:80]}."
        if bucket == 'build_later':
            return f"Relevant enough to keep, but not urgent enough to act on immediately."
        if bucket == 'ignore':
            return f"Low-signal or already covered, so it is not worth attention right now."
        return f"Worth keeping as reference, but not strong enough to prioritize now."
    return reason[0].upper() + reason[1:]


def clean_summary(text: str, bookmark: Bookmark, analysis: AnalysisResult) -> str:
    summary = _squeeze(text)
    for pattern in GENERIC_SUMMARY_PATTERNS:
        summary = re.sub(pattern, "", summary, flags=re.IGNORECASE).strip()
    summary = summary.replace("The key takeaway is", "Key takeaway:")
    summary = summary.replace("This bookmark highlights", "This covers")
    summary = summary.replace("This is a social media post", "This post")
    summary = summary.replace("This is a Twitter/X post", "This X post")
    summary = summary.replace("This bookmark describes", "This covers")
    if len(summary) > 320:
        summary = summary[:317].rstrip() + "..."
    if not summary:
        summary = (bookmark.text or bookmark.title or "Reference item").strip()
    return summary


def clean_analysis_text(bookmark: Bookmark, analysis: AnalysisResult) -> AnalysisResult:
    analysis.summary = clean_summary(analysis.summary, bookmark, analysis)
    analysis.recommendation_reason = clean_reason(analysis.recommendation_reason, bookmark, analysis)
    return analysis
