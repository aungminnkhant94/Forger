"""refine_bucket must not override the agent from page-text substrings."""
import pytest

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


def test_valid_agent_bucket_wins_over_conflicting_boolean():
    """Previously archive+actionable=True was silently rewritten. Now the
    agent's valid bucket is the product."""
    bookmark = _bookmark("duplicate Docker layers")
    analysis = _analysis("archive", actionable_this_week=True, reduces_friction=False, reference_material=True)

    assert analysis.to_dict()["actionable_this_week"] is True
    assert refine_bucket(bookmark, analysis) == "archive"


def test_monte_carlo_test_this_week_with_reduces_friction_only_is_kept():
    """Reported bug: test_this_week + reduces_friction=True, no
    actionable_this_week, came back as build_later."""
    bookmark = _bookmark("Monte Carlo tree search notes for the solver.")
    analysis = _analysis("test_this_week", reduces_friction=True)

    assert "actionable_this_week" not in analysis.to_dict()
    assert refine_bucket(bookmark, analysis) == "test_this_week"


def test_low_scores_no_longer_demote_valid_bucket():
    bookmark = _bookmark("notes")
    analysis = _analysis("test_this_week")
    analysis.priority_score = 1.0
    analysis.worth_score = 2.0
    assert refine_bucket(bookmark, analysis) == "test_this_week"


@pytest.mark.parametrize(
    "flags,expected",
    [
        ({"actionable_this_week": True}, "test_this_week"),
        ({"reduces_friction": True}, "build_later"),
        ({"reference_material": True}, "archive"),
        ({"actionable_this_week": False, "reduces_friction": False, "reference_material": False}, "ignore"),
        ({"reduces_friction": False}, "archive"),  # missing != False: no ignore
        ({}, "archive"),
    ],
)
def test_derived_bucket_only_when_bucket_invalid(flags, expected):
    bookmark = _bookmark("notes")
    analysis = _analysis("not-a-bucket", **flags)
    assert refine_bucket(bookmark, analysis) == expected


def test_keyword_guardrail_override_is_logged(monkeypatch, caplog):
    import forger.bucketing as bucketing

    monkeypatch.setattr(bucketing, "FORCE_UPGRADE_KEYWORDS", {"docker"})
    bookmark = _bookmark("docker notes")
    analysis = _analysis("archive")
    with caplog.at_level("WARNING", logger="forger.bucketing"):
        assert refine_bucket(bookmark, analysis) == "test_this_week"
    assert "archive -> test_this_week" in caplog.text
