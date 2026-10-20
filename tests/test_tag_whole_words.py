"""Tag inference matches whole words; agent tags are not padded; retag cleans."""
from __future__ import annotations

import argparse
from unittest.mock import patch

import forge
from forger.models import Bookmark
from forger.tagging import clean_tags, infer_tags, retag


def test_substrings_do_not_infer_tags():
    text = "Our marketing agency decoded the encoder settings for client reports"
    assert infer_tags(text) == []  # was trading, agents, coding


def test_whole_words_still_infer():
    tags = infer_tags("An AI agent writes code to automate trading on a market of bitcoin")
    assert {"agents", "coding", "automation", "trading"} <= set(tags)


def test_market_alone_is_not_trading():
    assert "trading" not in infer_tags("Grow your market share with better reports")


def test_agent_tags_are_not_padded_with_inference():
    got = clean_tags(["ppc", "google-ads"], "A coding agent for GPU trading")
    assert got == ["ppc", "google-ads"]


def test_empty_agent_tags_still_get_whole_word_inference():
    assert clean_tags([], "Deploy with Docker on an NVIDIA GPU") == ["gpu", "infra"]


def test_retag_legacy_missing_agent_tags_is_noop():
    """Old bookmarks without agent_tags: safer default — do not wipe."""
    tags = ["ppc", "agents", "trading", "coding", "gpu"]
    text = "Marketing guide: reagents, codeine and Google Ads bidding on an NVIDIA GPU dashboard"
    assert retag(tags, "Guide", text) == tags
    assert retag(tags, "Guide", text, agent_tags=None) == tags


def test_retag_inferred_only_drops_substring_leftovers():
    """Empty agent_tags means tags are inferred-only: substring→whole-word cleanup."""
    tags = ["ppc", "agents", "trading", "coding", "gpu"]
    text = "Marketing guide: reagents, codeine and Google Ads bidding on an NVIDIA GPU dashboard"
    assert retag(tags, "Guide", text, agent_tags=[]) == ["ppc", "gpu"]


def _bm(tags, text, agent_tags=None):
    payload = {
        "id": "bookmark_aaaaaaaaaaaa", "url": "https://example.com/a", "title": "HubSpot reports",
        "text": text, "source": "article", "bookmarked_at": "2026-10-12T00:00:00Z", "tags": tags,
    }
    if agent_tags is not None:
        payload["agent_tags"] = agent_tags
    return Bookmark.from_dict(payload)


def test_forge_retag_dry_run_does_not_write(capsys):
    # Inferred-only (empty agent_tags): substring junk is reported, not written.
    bms = [_bm(
        ["marketing", "agents", "trading"],
        "Marketing reports for reagents suppliers",
        agent_tags=[],
    )]
    with patch.object(forge, "load_bookmarks", return_value=bms), \
            patch("forger.storage.save_bookmarks") as save:
        assert forge.cmd_retag(argparse.Namespace(apply=False)) == 0
    save.assert_not_called()
    out = capsys.readouterr().out
    assert "before: marketing, agents, trading" in out and "after:  marketing" in out


def test_forge_retag_apply_writes(capsys):
    bms = [_bm(
        ["marketing", "agents"],
        "Marketing reports for reagents suppliers",
        agent_tags=[],
    )]
    with patch.object(forge, "load_bookmarks", return_value=bms), \
            patch("forger.storage.save_bookmarks") as save, \
            patch("forger.dashboard_sync.sync_dashboard_data"):
        forge.cmd_retag(argparse.Namespace(apply=True))
    (saved,), _ = save.call_args
    assert saved[0].tags == ["marketing"]


def test_forge_retag_legacy_without_agent_tags_changes_nothing(capsys):
    bms = [_bm(["marketing", "agents", "trading"], "Marketing reports for reagents suppliers")]
    assert bms[0].agent_tags is None
    with patch.object(forge, "load_bookmarks", return_value=bms), \
            patch("forger.storage.save_bookmarks") as save:
        assert forge.cmd_retag(argparse.Namespace(apply=False)) == 0
    save.assert_not_called()
    out = capsys.readouterr().out
    assert "0 of 1 bookmarks would change" in out


def test_reagents_is_not_agents():
    # Chemistry library: "reagents" was tagged #agents by substring match.
    assert "agents" not in infer_tags("Grignard reagents and the codeine synthesis route")
    assert infer_tags("Grignard reagents and the codeine synthesis route") == []


def test_retag_keeps_agent_rule_tag_without_substring_evidence():
    # "research" with no keyword in the text was chosen by the agent: keep it.
    assert retag(
        ["biomed", "research"],
        "Dementia risk",
        "Women are more likely to develop it",
        agent_tags=["biomed", "research"],
    ) == ["biomed", "research"]


def test_retag_keeps_agent_agents_despite_leavening_agent_body():
    """Prove-it: agent #agents stays when body says 'leavening agent'."""
    text = "Bake bread with a leavening agent; old marketing copy about reagents"
    tags = ["agents", "trading", "baking"]
    assert retag(tags, "Sourdough notes", text, agent_tags=["agents", "baking"]) == [
        "agents",
        "baking",
    ]


def test_retag_removes_inferred_only_agents_false_friend():
    """Prove-it: inferred-only #agents (not in agent_tags) is stripped even when
    the body still whole-word-matches 'agent' (semantic false friend)."""
    text = "Using a leavening agent in sourdough starter"
    # Body would still infer #agents; SoT says agent chose only baking.
    assert "agents" in infer_tags(text)
    assert retag(
        ["baking", "agents"],
        "Sourdough",
        text,
        agent_tags=["baking"],
    ) == ["baking"]


def test_bookmark_roundtrip_omits_missing_agent_tags():
    b = Bookmark.from_dict({
        "id": "bookmark_bbbbbbbbbbbb",
        "url": "https://example.com/b",
        "text": "hi",
        "source": "article",
        "tags": ["gpu"],
    })
    assert b.agent_tags is None
    payload = b.to_dict()
    assert "agent_tags" not in payload
    again = Bookmark.from_dict(payload)
    assert again.agent_tags is None


def test_bookmark_roundtrip_keeps_empty_agent_tags():
    b = Bookmark.from_dict({
        "id": "bookmark_cccccccccccc",
        "url": "https://example.com/c",
        "text": "hi",
        "source": "article",
        "tags": ["gpu"],
        "agent_tags": [],
    })
    assert b.agent_tags == []
    again = Bookmark.from_dict(b.to_dict())
    assert again.agent_tags == []
