from __future__ import annotations

from forger.models import AnalysisResult, Bookmark

HIGH_SIGNAL_TAGS = {
    'agents', 'multi-agent', 'automation', 'ai-tools', 'llm',
    'gpu', 'infra', 'security', 'coding', 'performance', 'research'
}

# Personalization hooks: keywords that always bump a bucket UP.
# The LLM prompt (driven by profile.md) is the primary personalization path;
# these sets exist as hard guardrails. Add YOUR topics here (or leave empty).
FORCE_UPGRADE_KEYWORDS: set[str] = set()
MINIMUM_BUILD_LATER: set[str] = set()


def refine_bucket(bookmark: Bookmark, analysis: AnalysisResult) -> str:
    bucket = analysis.recommendation_bucket
    tags = set(bookmark.tags or [])
    worth = float(analysis.worth_score or 0)
    priority = float(analysis.priority_score or 0)
    text = f"{bookmark.title} {bookmark.text} {analysis.summary} {analysis.recommendation_reason}".lower()

    is_duplicate = 'duplicate' in text or 'identical content' in text or 'already covered' in text
    if is_duplicate:
        return 'ignore'

    has_high_signal = bool(tags & HIGH_SIGNAL_TAGS)
    has_force_upgrade = any(kw in text for kw in FORCE_UPGRADE_KEYWORDS)
    has_minimum_bl = any(kw in text for kw in MINIMUM_BUILD_LATER)

    # NEW: Use binary answers from DeepSeek if available (Option 2)
    # These take precedence over the computed bucket when present
    raw_analysis = analysis.to_dict()
    if 'actionable_this_week' in raw_analysis or 'reduces_friction' in raw_analysis or 'reference_material' in raw_analysis:
        actionable = raw_analysis.get('actionable_this_week', False)
        reduces_friction = raw_analysis.get('reduces_friction', False)
        reference = raw_analysis.get('reference_material', False)
        
        # Override based on binary answers + force-upgrade keywords
        if actionable or has_force_upgrade:
            return 'test_this_week'
        if reduces_friction or has_minimum_bl:
            return 'build_later'
        if reference:
            return 'archive'
        return 'ignore'

    # LEGACY: Fallback to old rules if binary answers not present
    # RULE 1: Force upgrade high-signal content from archive/ignore
    if bucket in {'archive', 'ignore'} and has_force_upgrade:
        return 'test_this_week' if has_high_signal or worth >= 6 else 'build_later'

    # RULE 2: Infrastructure/coding tools should never be archived
    if bucket == 'archive' and has_minimum_bl:
        return 'build_later'

    # RULE 3: Worth-based overrides (existing)
    if bucket in {'archive', 'ignore'} and worth >= 8 and has_high_signal:
        return 'test_this_week' if priority >= 5 else 'build_later'

    if bucket == 'archive' and worth >= 7 and has_high_signal:
        return 'build_later'

    if bucket == 'ignore' and worth >= 6 and not is_duplicate:
        return 'build_later'

    # RULE 4: Demote low-priority test_this_week
    if bucket == 'test_this_week' and priority < 4 and worth < 7:
        return 'build_later'

    return bucket
