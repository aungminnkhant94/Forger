"""End-to-end: resolve and API paths keep a valid agent/model bucket."""
import forger.bookmark_workflow as bw
from forger.analysis import derive_legacy_scores
from tests.test_workflow import _make_bookmark

RELATES = (
    "Connects to the solver project because Monte Carlo rollouts are the "
    "planned search method. Worth testing against the current baseline."
)


def _wire(monkeypatch, pending, stored):
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [pending])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", lambda b: None)
    monkeypatch.setattr(bw, "merge_bookmarks", lambda existing, incoming: list(incoming))

    def upsert(existing, incoming):
        stored["analysis"] = list(incoming)[0]
        return list(incoming)

    monkeypatch.setattr(bw, "upsert_analysis_results", upsert)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    # real refine_bucket on purpose (not mocked)


def test_resolve_monte_carlo_keeps_test_this_week(monkeypatch):
    stored = {}
    pending = _make_bookmark()
    _wire(monkeypatch, pending, stored)
    ok, message, analysis = bw.resolve_pending_analysis(
        pending.id,
        {
            "summary": "Monte Carlo tree search walkthrough to try on the solver.",
            "recommendation_bucket": "test_this_week",
            "reduces_friction": True,
            "relates_to": RELATES,
        },
    )
    assert ok, message
    assert "bucket=test_this_week" in message
    assert analysis.recommendation_bucket == "test_this_week"
    assert stored["analysis"].recommendation_bucket == "test_this_week"


def test_api_derive_keeps_model_bucket_and_missing_is_not_false():
    kept = {"recommendation_bucket": "test_this_week", "reduces_friction": True}
    derive_legacy_scores(kept)
    assert kept["recommendation_bucket"] == "test_this_week"

    unknown = {"reduces_friction": False}  # others missing
    derive_legacy_scores(unknown)
    assert "recommendation_bucket" not in unknown  # not forced to ignore

    invalid = {"recommendation_bucket": "Maybe", "reduces_friction": True}
    derive_legacy_scores(invalid)
    assert invalid["recommendation_bucket"] == "build_later"
