"""Tests for agent-mode score derivation."""
import pytest

from forger.deepseek_analysis import derive_legacy_scores


class TestDeriveLegacyScores:
    def test_all_false_is_ignore(self):
        a = derive_legacy_scores({
            "actionable_this_week": False,
            "reduces_friction": False,
            "reference_material": False,
        })
        assert a["recommendation_bucket"] == "ignore"
        assert a["scoring_inputs"]["relevance"] == 2.0
        assert a["priority_score"] == 0.0  # worth 1.5 - 0.3*7 effort clamps to 0

    def test_actionable_is_test_this_week(self):
        a = derive_legacy_scores({"actionable_this_week": True})
        assert a["recommendation_bucket"] == "test_this_week"
        assert a["scoring_inputs"]["relevance"] == 8.0
        assert a["priority_score"] == pytest.approx(8.0 - 0.3 * 2.0)

    def test_reduces_friction_is_build_later(self):
        a = derive_legacy_scores({
            "actionable_this_week": False,
            "reduces_friction": True,
        })
        assert a["recommendation_bucket"] == "build_later"

    def test_reference_only_is_archive(self):
        a = derive_legacy_scores({
            "actionable_this_week": False,
            "reduces_friction": False,
            "reference_material": True,
        })
        assert a["recommendation_bucket"] == "archive"
        assert a["worth_score"] == 4.0

    def test_explicit_bucket_preserved(self):
        a = derive_legacy_scores({
            "actionable_this_week": True,
            "recommendation_bucket": "archive",
        })
        assert a["recommendation_bucket"] == "archive"

    def test_explicit_scores_not_overwritten(self):
        a = derive_legacy_scores({
            "actionable_this_week": True,
            "worth_score": 9.5,
            "priority_score": 9.0,
            "scoring_inputs": {"relevance": 10.0},
        })
        assert a["worth_score"] == 9.5
        assert a["priority_score"] == 9.0
        assert a["scoring_inputs"]["relevance"] == 10.0
