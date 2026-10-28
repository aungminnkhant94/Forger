"""forge retag --agent: queue existing bookmarks so the agent re-picks tags."""
import contextlib

import forger.bookmark_workflow as bw
from tests.test_workflow import _make_bookmark


def _paper():
    b = _make_bookmark()
    b.id = "bookmark_5c1b9abf2cb4"
    b.title = "Band-Resolved Superconducting Gaps via the Thermal Hall Effect"
    b.text = "We resolve superconducting gaps band by band; analysis coding scheme..."
    b.tags = ["arxiv", "superconductivity", "coding"]
    b.agent_tags = None
    return b


def _wire(monkeypatch, bookmark, saved):
    monkeypatch.setattr(bw, "load_bookmarks", lambda: [bookmark])
    monkeypatch.setattr(bw, "save_bookmarks", lambda bs: saved.extend(bs))
    monkeypatch.setattr(bw, "data_lock", contextlib.nullcontext)
    monkeypatch.setattr(bw, "invalidate_cache", lambda: None)
    monkeypatch.setattr(bw, "_sync_dashboard", lambda: None)


def test_write_retag_pending_is_idempotent_and_marked(tmp_path):
    b = _paper()
    ok, path = bw.write_retag_pending(tmp_path, b, "Thermal Hall gaps paper.")
    assert ok
    first = (tmp_path / f"{b.id}.content.md").read_text(encoding="utf-8")
    assert first.startswith(bw.RETAG_MARKER)
    assert "CURRENT TAGS: arxiv, superconductivity, coding" in first
    assert "Thermal Hall gaps paper." in first
    ok2, _ = bw.write_retag_pending(tmp_path, b, "Thermal Hall gaps paper.")
    assert ok2
    assert (tmp_path / f"{b.id}.content.md").read_text(encoding="utf-8") == first
    assert len(list(tmp_path.iterdir())) == 1


def test_write_retag_pending_never_clobbers_add_agent_file(tmp_path):
    b = _paper()
    pending = tmp_path / f"{b.id}.content.md"
    pending.write_text("# full analysis pending\n", encoding="utf-8")
    ok, msg = bw.write_retag_pending(tmp_path, b)
    assert not ok and "skipped" in msg
    assert pending.read_text(encoding="utf-8") == "# full analysis pending\n"


def test_resolve_retag_agent_tags_replace_inferred(monkeypatch):
    b = _paper()
    saved = []
    _wire(monkeypatch, b, saved)
    ok, msg = bw.resolve_retag(b.id, {"tags": ["arxiv", "superconductivity", "thermal-hall"]})
    assert ok, msg
    # "coding" still appears in the text, but the agent's pick wins.
    assert saved[0].tags == ["arxiv", "superconductivity", "thermal-hall"]
    assert saved[0].agent_tags == ["arxiv", "superconductivity", "thermal-hall"]
    assert "coding" in msg and "->" in msg
    # Re-running with the same tags is a stable no-op in effect.
    saved.clear()
    ok, _ = bw.resolve_retag(b.id, {"tags": ["arxiv", "superconductivity", "thermal-hall"]})
    assert ok and saved[0].tags == ["arxiv", "superconductivity", "thermal-hall"]


def test_resolve_retag_rejects_empty_tags(monkeypatch):
    b = _paper()
    saved = []
    _wire(monkeypatch, b, saved)
    for payload in ({}, {"tags": []}, {"tags": ["general"]}, {"tags": "coding"}):
        ok, _ = bw.resolve_retag(b.id, payload)
        assert not ok
    assert saved == [] and b.tags == ["arxiv", "superconductivity", "coding"]


def test_retag_agent_requires_scope(capsys):
    import argparse
    import forge

    rc = forge._cmd_retag_agent(argparse.Namespace(agent=True, apply=False, tag=None, all=False))
    assert rc == 1
