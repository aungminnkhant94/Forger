"""Agent-mode relates_to must be real profile-grounded prose."""
import pytest

from forger.bookmark_workflow import resolve_pending_analysis
from forger.models import Bookmark
from forger.relates_to import (
    RELATES_TO_MIN_CHARS,
    is_meaningful_relates_to,
    is_placeholder_relates_to,
    validate_relates_to,
)


GOOD = (
    "This maps to your Docker networking work in profile.md. "
    "It also helps the deploy friction you called out for the forge dashboard."
)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "",
        "   ",
        "None",
        "none",
        "NONE",
        "N/A",
        "n/a",
        "null",
        "NULL",
        "-",
        "--",
        "nothing",
        "Nothing connects",
        "no connection",
        "short.",  # too short / one sentence fragment
        "Only one sentence without enough length or a second beat",
    ],
)
def test_placeholders_and_thin_rejected(bad):
    assert not is_meaningful_relates_to(bad)
    with pytest.raises(ValueError):
        validate_relates_to(bad)


def test_good_relates_to_accepted():
    assert len(GOOD) >= RELATES_TO_MIN_CHARS
    assert is_meaningful_relates_to(GOOD)
    assert validate_relates_to(GOOD) == GOOD
    assert validate_relates_to(f"  {GOOD}  ") == GOOD


def test_two_short_sentences_still_need_min_chars():
    # Two sentences but under the char floor.
    text = "A. B."
    assert is_placeholder_relates_to(text) is False
    assert not is_meaningful_relates_to(text)
    with pytest.raises(ValueError, match="too short"):
        validate_relates_to(text)


def _bookmark():
    return Bookmark(
        id="bookmark_abcdef012345",
        source="article",
        url="https://example.com/post",
        text="x" * 250,
        title="Example",
    )


def _base_payload(**overrides):
    payload = {
        "summary": "A solid summary of the link for this user.",
        "recommendation_bucket": "archive",
        "actionable_this_week": False,
        "reduces_friction": False,
        "reference_material": True,
        "relates_to": GOOD,
        "recommendation_reason": "Worth keeping as reference.",
        "key_insights": ["one", "two", "three"],
        "tags": ["docker"],
    }
    payload.update(overrides)
    return payload


def test_resolve_rejects_none_relates_to(monkeypatch):
    from forger import bookmark_workflow as bw

    monkeypatch.setattr(bw, "load_bookmarks", lambda: [_bookmark()])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: None)
    monkeypatch.setattr(bw, "upsert_analysis_results", lambda *a, **k: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)

    ok, message, analysis = resolve_pending_analysis(
        "bookmark_abcdef012345", _base_payload(relates_to="None")
    )
    assert not ok
    assert "relates_to" in message.lower()
    assert analysis is None


def test_resolve_persists_meaningful_relates_to(monkeypatch):
    from forger import bookmark_workflow as bw

    stored = {}

    def capture_upsert(existing, incoming):
        stored["analysis"] = list(incoming)[0]
        return list(incoming)

    monkeypatch.setattr(bw, "load_bookmarks", lambda: [_bookmark()])
    monkeypatch.setattr(bw, "load_analysis_results", lambda: [])
    monkeypatch.setattr(bw, "save_bookmarks", lambda bookmarks: None)
    monkeypatch.setattr(bw, "merge_bookmarks", lambda existing, incoming: list(incoming))
    monkeypatch.setattr(bw, "upsert_analysis_results", capture_upsert)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)
    monkeypatch.setattr(bw, "refine_bucket", lambda bookmark, analysis: analysis.recommendation_bucket)
    monkeypatch.setattr(bw, "clean_analysis_text", lambda bookmark, analysis: analysis)
    monkeypatch.setattr(bw, "clean_tags", lambda *a, **k: ["docker"])

    ok, message, analysis = resolve_pending_analysis(
        "bookmark_abcdef012345", _base_payload()
    )
    assert ok, message
    assert analysis is not None
    assert analysis.relates_to == GOOD
    assert stored["analysis"].relates_to == GOOD
