"""Optional analysis text is real null — never the string "None" (#12, #47).

Shared ingest (``ingest_optional_analysis_text`` / ``_build_analysis_result``)
is the single write path for agent resolve and API scoring.
"""
from __future__ import annotations

import pytest

from forger.bookmark_workflow import _build_analysis_result
from forger.models import (
    OPTIONAL_ANALYSIS_TEXT_FIELDS,
    AnalysisResult,
    ingest_optional_analysis_text,
)
from tests.test_digest_week_counts import _bookmark

# Bad payloads that previously became stored literals (replay #12 / #47).
STRING_NULLS = (None, "None", "null", "NULL", "  ", "")

# Fields that must never persist str(None) / "None" / "null".
STORE_AS_NULL = (
    "confidence",
    "difficulty_reason",
    "next_action",
    "relates_to",
    "personalized_why",
)


def test_resolve_payload_without_optional_text_round_trips_as_null():
    b = _bookmark("a", bookmarked_at="2026-10-12T00:00:00Z")
    a = _build_analysis_result(b, {"summary": "s", "recommendation_bucket": "archive"})
    d = a.to_dict()
    back = AnalysisResult.from_dict(d)
    for k in ("confidence", "difficulty_reason", "next_action"):
        assert back.to_dict()[k] is None, k


@pytest.mark.parametrize("value", STRING_NULLS)
def test_explicit_none_and_legacy_none_string_read_as_null(value):
    base = AnalysisResult.from_dict({"bookmark_id": "x", "summary": "s"}).to_dict()
    payload = dict(base, **{k: value for k in STORE_AS_NULL})
    payload["title"] = value
    r = AnalysisResult.from_dict(payload)
    for k in STORE_AS_NULL:
        assert getattr(r, k) is None, (k, value)
    assert r.title is None


def test_real_values_kept():
    base = AnalysisResult.from_dict({"bookmark_id": "x", "summary": "s"}).to_dict()
    r = AnalysisResult.from_dict(
        dict(
            base,
            confidence="high",
            next_action="Try it",
            relates_to="Fits the current study plan. Worth a weekend spike.",
            title="Real title",
            personalized_why="Because profile says so",
        )
    )
    assert r.confidence == "high"
    assert r.next_action == "Try it"
    assert r.relates_to.startswith("Fits the current")
    assert r.title == "Real title"
    assert r.personalized_why == "Because profile says so"


@pytest.mark.parametrize("value", STRING_NULLS)
def test_build_analysis_result_stores_string_nulls_as_real_null(value):
    """API scoring + resolve share ``_build_analysis_result`` — neither may store \"None\"."""
    b = _bookmark("a", bookmarked_at="2026-10-12T00:00:00Z", title="Scraped title")
    a = _build_analysis_result(
        b,
        {
            "summary": "s",
            "recommendation_bucket": "archive",
            "confidence": value,
            "difficulty_reason": value,
            "next_action": value,
            "relates_to": value,
            "title": value,
            "personalized_why": value,
        },
    )
    for k in ("confidence", "difficulty_reason", "next_action", "relates_to"):
        assert getattr(a, k) is None, (k, value)
    # Null analysis title falls back to scraped bookmark title (not the string "None").
    assert a.title == "Scraped title"
    d = a.to_dict()
    back = AnalysisResult.from_dict(d)
    for k in ("confidence", "difficulty_reason", "next_action", "relates_to"):
        assert back.to_dict()[k] is None, (k, value)
    assert "None" not in {back.confidence, back.difficulty_reason, back.next_action, back.relates_to, back.title}


def test_from_dict_round_trip_never_resurrects_none_string():
    """The #47 bug: to_dict writes null, from_dict used to str(None) -> \"None\"."""
    b = _bookmark("a", bookmarked_at="2026-10-12T00:00:00Z")
    a = _build_analysis_result(b, {"summary": "s", "recommendation_bucket": "archive"})
    assert a.relates_to is None and a.confidence is None
    once = AnalysisResult.from_dict(a.to_dict())
    twice = AnalysisResult.from_dict(once.to_dict())
    for k in STORE_AS_NULL:
        assert getattr(twice, k) is None, k
        assert twice.to_dict()[k] is None, k


def test_ingest_helper_is_shared_sot_for_optional_fields():
    """Fail if someone reintroduces str(value) for these fields outside the helper."""
    for value in STRING_NULLS:
        got = ingest_optional_analysis_text({k: value for k in OPTIONAL_ANALYSIS_TEXT_FIELDS})
        for k in OPTIONAL_ANALYSIS_TEXT_FIELDS:
            assert got[k] is None, (k, value)
    good = ingest_optional_analysis_text(
        {
            "confidence": "medium",
            "difficulty_reason": "needs GPU",
            "next_action": "skim paper",
            "relates_to": "Ties to Forger trust work. Ship the ingest PR.",
            "title": "Shared ingest",
            "personalized_why": "matches profile",
        }
    )
    assert good["confidence"] == "medium"
    assert good["title"] == "Shared ingest"
    assert "None" not in good.values()
