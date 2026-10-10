"""forge resolve must not let bookmark ids escape data/pending/."""
import argparse
import json
from pathlib import Path

import pytest

from forger.utils import (
    UnsafeBookmarkIdError,
    is_valid_bookmark_id,
    pending_paths_for_bookmark_id,
    stable_bookmark_id,
)


def test_stable_ids_are_valid():
    bid = stable_bookmark_id("https://example.com/a", "text")
    assert is_valid_bookmark_id(bid)
    assert bid.startswith("bookmark_")
    assert len(bid) == len("bookmark_") + 12


@pytest.mark.parametrize(
    "bad_id",
    [
        "",
        "bookmark",
        "bookmark_",
        "bookmark_short",
        "bookmark_gggggggggggg",  # not hex
        "BOOKMARK_aaaaaaaaaaaa",
        "../bookmark_aaaaaaaaaaaa",
        "bookmark_aaaaaaaaaaaa/../secrets",
        "../../etc/passwd",
        "/tmp/bookmark_aaaaaaaaaaaa",
        r"..\bookmark_aaaaaaaaaaaa",
        "bookmark_aaaaaaaaaaaa\x00",
        "bookmark_aaaaaaaaaaa!",  # 11 hex + bang
        "not_a_bookmark_id",
    ],
)
def test_rejects_malicious_or_malformed_ids(bad_id, tmp_path):
    assert not is_valid_bookmark_id(bad_id)
    with pytest.raises(UnsafeBookmarkIdError):
        pending_paths_for_bookmark_id(tmp_path / "pending", bad_id)


def test_valid_id_stays_under_pending(tmp_path):
    pending = tmp_path / "pending"
    pending.mkdir()
    bid = "bookmark_abcdef012345"
    analysis, content = pending_paths_for_bookmark_id(pending, bid)
    assert analysis.parent == pending.resolve()
    assert content.parent == pending.resolve()
    assert analysis.name == f"{bid}.analysis.json"
    assert content.name == f"{bid}.content.md"
    analysis.relative_to(pending.resolve())
    content.relative_to(pending.resolve())


def test_cmd_resolve_rejects_traversal(monkeypatch, tmp_path, capsys):
    import forge

    pending = tmp_path / "pending"
    pending.mkdir()
    # Plant a decoy outside pending that a naive join might reach.
    decoy = tmp_path / "evil.analysis.json"
    decoy.write_text('{"should":"remain"}', encoding="utf-8")
    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)

    args = argparse.Namespace(bookmark_id="../evil")
    assert forge.cmd_resolve(args) == 1
    captured = capsys.readouterr()
    assert "Invalid bookmark id" in captured.err
    assert decoy.read_text(encoding="utf-8") == '{"should":"remain"}'


def test_cmd_resolve_happy_path(monkeypatch, tmp_path, capsys):
    import forge

    pending = tmp_path / "pending"
    pending.mkdir()
    bid = "bookmark_abcdef012345"
    analysis_path = pending / f"{bid}.analysis.json"
    analysis_path.write_text(
        json.dumps(
            {
                "summary": "ok",
                "recommendation_bucket": "archive",
                "actionable_this_week": False,
                "reduces_friction": False,
                "reference_material": True,
            }
        ),
        encoding="utf-8",
    )
    (pending / f"{bid}.content.md").write_text("# content", encoding="utf-8")
    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)

    def fake_resolve(bookmark_id, payload):
        assert bookmark_id == bid
        assert payload["summary"] == "ok"
        return True, f"Resolved {bookmark_id}", object()

    monkeypatch.setattr(
        "forger.bookmark_workflow.resolve_pending_analysis",
        fake_resolve,
    )

    args = argparse.Namespace(bookmark_id=bid)
    assert forge.cmd_resolve(args) == 0
    assert not analysis_path.exists()
    assert not (pending / f"{bid}.content.md").exists()
    out = capsys.readouterr().out
    assert f"Resolved {bid}" in out
