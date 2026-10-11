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

# Soft cap for stored summaries. Truncation must stop at a word boundary so
# cards never show fragments like "catalys...".
SUMMARY_MAX_LENGTH = 320


def _squeeze(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def truncate_at_word_boundary(
    text: str,
    max_length: int = SUMMARY_MAX_LENGTH,
    ellipsis: str = "...",
) -> str:
    """Truncate ``text`` to ``max_length`` without splitting a word.

    If the text already fits, it is returned unchanged. Otherwise the cut is
    made at the last whitespace before the budget (leaving room for
    ``ellipsis``). A single oversized token is hard-cut as a last resort.
    """
    text = (text or "").strip()
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text

    budget = max_length - len(ellipsis)
    if budget <= 0:
        return ellipsis[:max_length]

    cut = text[:budget].rstrip()
    last_space = cut.rfind(" ")
    # Only back up when we still keep a meaningful prefix.
    if last_space > max(0, budget // 2):
        cut = cut[:last_space].rstrip()
    cut = cut.rstrip(".,;:!?-")
    if not cut:
        # Pathological: first token longer than budget.
        cut = text[:budget].rstrip()
    return cut + ellipsis


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
    if len(summary) > SUMMARY_MAX_LENGTH:
        summary = truncate_at_word_boundary(summary, SUMMARY_MAX_LENGTH)
    if not summary:
        summary = (bookmark.text or bookmark.title or "Reference item").strip()
    return summary


def clean_analysis_text(bookmark: Bookmark, analysis: AnalysisResult) -> AnalysisResult:
    analysis.summary = clean_summary(analysis.summary, bookmark, analysis)
    analysis.recommendation_reason = clean_reason(analysis.recommendation_reason, bookmark, analysis)
    return analysis
