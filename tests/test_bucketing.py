"""refine_bucket must not override the agent from page-text substrings."""
from forger.bucketing import refine_bucket
from forger.models import AnalysisResult, Bookmark, ScoringInputs


def _bookmark(text: str) -> Bookmark:
    return Bookmark(
        id="bookmark_test",
        source="article",
        url="https://example.com/docker",
        text=text,
        title="Docker notes",
        tags=[],
    )


def _analysis(bucket: str, **flags) -> AnalysisResult:
    return AnalysisResult(
        bookmark_id="bookmark_test",
        summary="How image layers are stored.",
        recommendation_reason="Useful reference for the registry work.",
        key_insights=["Layers are content-addressed."],
        scoring_inputs=ScoringInputs(
            relevance=5.0,
            practical_value=5.0,
            actionability=5.0,
            stage_fit=5.0,
            novelty=5.0,
            excitement=5.0,
            difficulty=5.0,
            time_cost=5.0,
        ),
        worth_score=5.0,
        effort_score=5.0,
        priority_score=5.0,
        recommendation_bucket=bucket,
        analysis_source="agent",
        analyzed_at="2026-10-08T00:00:00Z",
        **flags,
    )


def test_duplicate_docker_layers_is_not_forced_to_ignore():
    bookmark = _bookmark("This page explains duplicate Docker layers in a registry.")
    analysis = _analysis("archive")

    assert refine_bucket(bookmark, analysis) != "ignore"
    assert refine_bucket(bookmark, analysis) == "archive"


def test_explicit_agent_bucket_is_kept():
    bookmark = _bookmark(
        "Already covered elsewhere, but this write-up is the one to keep. "
        "Not identical content to the other note."
    )
    analysis = _analysis("build_later")

    assert refine_bucket(bookmark, analysis) == "build_later"
    assert "actionable_this_week" not in analysis.to_dict()


def test_real_boolean_can_upgrade_bucket():
    bookmark = _bookmark("duplicate Docker layers")
    analysis = _analysis("archive", actionable_this_week=True, reduces_friction=False, reference_material=True)

    assert analysis.to_dict()["actionable_this_week"] is True
    assert refine_bucket(bookmark, analysis) == "test_this_week"
