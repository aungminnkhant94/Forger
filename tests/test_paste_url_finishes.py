"""A pasted URL runs to the end: add --agent prints the exact finish steps."""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import forge
from forger.models import Bookmark


def test_agent_add_prints_finish_steps_with_id(tmp_path, monkeypatch, capsys):
    bm = Bookmark(id="abc123", url="https://example.com/x", title="X", text="body", source="web")
    monkeypatch.setattr(forge, "DATA_DIR", tmp_path)
    with patch(
        "forger.bookmark_workflow.process_bookmark_url",
        return_value=(True, "saved", bm, None),
    ):
        rc = forge.cmd_add(argparse.Namespace(url=bm.url, agent=True, note=None, replace=False))
    out = capsys.readouterr().out
    assert rc == 0
    assert "NOT DONE YET: bookmark abc123 is pending" in out
    assert str(tmp_path / "pending" / "abc123.content.md") in out
    assert str(tmp_path / "pending" / "abc123.analysis.json") in out
    assert "python3 forge resolve abc123" in out


def test_agents_md_has_pasted_url_rule():
    text = (Path(__file__).resolve().parents[1] / "AGENTS.md").read_text(encoding="utf-8")
    top = text[:800]
    assert "pasted URL" in top
    assert "forge add <url> --agent" in top
    assert "forge resolve <id>" in top
