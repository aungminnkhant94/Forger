from __future__ import annotations

import logging

from forger.models import AnalysisResult, Bookmark

LOGGER = logging.getLogger(__name__)

HIGH_SIGNAL_TAGS = {
    'agents', 'multi-agent', 'automation', 'ai-tools', 'llm',
    'gpu', 'infra', 'security', 'coding', 'performance', 'research'
}

# Personalization hooks: keywords that always bump a bucket UP.
# The LLM prompt (driven by profile.md) is the primary personalization path;
# these sets exist as hard guardrails. Add YOUR topics here (or leave empty).
FORCE_UPGRADE_KEYWORDS: set[str] = set()
MINIMUM_BUILD_LATER: set[str] = set()


VALID_BUCKETS = frozenset({"test_this_week", "build_later", "archive", "ignore"})


def _derive_bucket(raw: dict) -> str | None:
    """Bucket from the binary answers. Only keys that are present count;
    a missing key is unknown, never False. Returns None if nothing to go on."""
    if raw.get("actionable_this_week") is True:
        return "test_this_week"
    if raw.get("reduces_friction") is True:
        return "build_later"
    if raw.get("reference_material") is True:
        return "archive"
    answered = [k for k in ("actionable_this_week", "reduces_friction", "reference_material") if k in raw]
    if len(answered) == 3:  # all three explicitly False
        return "ignore"
    return None


def refine_bucket(bookmark: Bookmark, analysis: AnalysisResult) -> str:
    """Return the final bucket.

    1. A valid bucket chosen by the agent / model wins. The only override is
       the user-configured keyword guardrails (FORCE_UPGRADE_KEYWORDS /
       MINIMUM_BUILD_LATER, empty by default), and it is logged.
    2. Derived bucketing from the binary answers applies only when no valid
       bucket was given; missing answers are not treated as False.
    """
    bucket = analysis.recommendation_bucket
    text = f"{bookmark.title} {bookmark.text} {analysis.summary} {analysis.recommendation_reason}".lower()
    has_force_upgrade = any(kw in text for kw in FORCE_UPGRADE_KEYWORDS)
    has_minimum_bl = any(kw in text for kw in MINIMUM_BUILD_LATER)

    if bucket in VALID_BUCKETS:
        final = bucket
        if has_force_upgrade and bucket != "test_this_week":
            final = "test_this_week"
        elif has_minimum_bl and bucket in {"archive", "ignore"}:
            final = "build_later"
        if final != bucket:
            LOGGER.warning(
                "Bucket override for %s: %s -> %s (user keyword guardrail in bucketing.py)",
                bookmark.id, bucket, final,
            )
        return final

    derived = _derive_bucket(analysis.to_dict())
    if has_force_upgrade:
        derived = "test_this_week"
    elif has_minimum_bl and derived in {None, "archive", "ignore"}:
        derived = "build_later"
    final = derived or "archive"
    LOGGER.info(
        "No valid bucket for %s (got %r); derived %s from binary answers",
        bookmark.id, bucket, final,
    )
    return final
