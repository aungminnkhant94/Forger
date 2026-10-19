"""Missing optional analysis text is stored as null, never the string "None"."""
from __future__ import annotations

from forger.bookmark_workflow import _build_analysis_result
from forger.models import AnalysisResult
from tests.test_digest_week_counts import _bookmark


def test_resolve_payload_without_optional_text_round_trips_as_null():
    b = _bookmark("a", bookmarked_at="2026-10-12T00:00:00Z")
    a = _build_analysis_result(b, {"summary": "s", "recommendation_bucket": "archive"})
    d = a.to_dict()
    back = AnalysisResult.from_dict(d)
    for k in ("confidence", "difficulty_reason", "next_action"):
        assert back.to_dict()[k] is None, k


def test_explicit_none_and_legacy_none_string_read_as_null():
    base = AnalysisResult.from_dict({"bookmark_id": "x", "summary": "s"}).to_dict()
    for value in (None, "None", "null", "  "):
        payload = dict(base, confidence=value, difficulty_reason=value, next_action=value)
        r = AnalysisResult.from_dict(payload)
        assert (r.confidence, r.difficulty_reason, r.next_action) == (None, None, None), value


def test_real_values_kept():
    base = AnalysisResult.from_dict({"bookmark_id": "x", "summary": "s"}).to_dict()
    r = AnalysisResult.from_dict(dict(base, confidence="high", next_action="Try it"))
    assert (r.confidence, r.next_action) == ("high", "Try it")
