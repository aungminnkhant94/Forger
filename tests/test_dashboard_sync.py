"""Dashboard sync publish opt-in."""
import json
from pathlib import Path

import pytest

from forger import dashboard_sync


@pytest.fixture
def fake_tree(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    web_lib = tmp_path / "web" / "lib"
    web_public = tmp_path / "web" / "public"
    web_lib.mkdir(parents=True)
    web_public.mkdir(parents=True)

    bookmarks = [{"id": "bookmark_abc", "url": "https://example.com", "title": "T"}]
    analysis = [{"bookmark_id": "bookmark_abc", "summary": "s"}]
    (data / "bookmarks_raw.json").write_text(json.dumps(bookmarks), encoding="utf-8")
    (data / "analysis_results.json").write_text(json.dumps(analysis), encoding="utf-8")

    monkeypatch.setattr(dashboard_sync, "BASE_DIR", tmp_path)
    monkeypatch.setattr(dashboard_sync, "_LIB_DIR", web_lib)
    monkeypatch.setattr(dashboard_sync, "_PUBLIC_DIR", web_public)
    monkeypatch.setattr(dashboard_sync, "_BOOKMARKS_SRC", data / "bookmarks_raw.json")
    monkeypatch.setattr(dashboard_sync, "_ANALYSIS_SRC", data / "analysis_results.json")
    monkeypatch.setattr(dashboard_sync, "_LIB_BOOKMARKS", web_lib / "data.json")
    monkeypatch.setattr(dashboard_sync, "_LIB_ANALYSIS", web_lib / "analysis.json")
    monkeypatch.setattr(dashboard_sync, "_PUBLIC_BOOKMARKS", web_public / "data.json")
    monkeypatch.setattr(dashboard_sync, "_PUBLIC_ANALYSIS", web_public / "analysis.json")
    return tmp_path


def test_default_public_is_empty(fake_tree, monkeypatch):
    monkeypatch.delenv("FORGER_PUBLISH_DASHBOARD", raising=False)
    assert dashboard_sync.sync_dashboard_data() is True

    public_bookmarks = json.loads((fake_tree / "web/public/data.json").read_text())
    public_analysis = json.loads((fake_tree / "web/public/analysis.json").read_text())
    assert public_bookmarks == []
    assert public_analysis == []

    lib_bookmarks = json.loads((fake_tree / "web/lib/data.json").read_text())
    assert lib_bookmarks[0]["id"] == "bookmark_abc"


def test_publish_flag_copies_real_data(fake_tree, monkeypatch):
    monkeypatch.delenv("FORGER_PUBLISH_DASHBOARD", raising=False)
    assert dashboard_sync.sync_dashboard_data(publish=True) is True

    public_bookmarks = json.loads((fake_tree / "web/public/data.json").read_text())
    assert public_bookmarks[0]["url"] == "https://example.com"


def test_publish_env_enables(fake_tree, monkeypatch):
    monkeypatch.setenv("FORGER_PUBLISH_DASHBOARD", "1")
    assert dashboard_sync.publish_dashboard_enabled() is True
    assert dashboard_sync.sync_dashboard_data() is True
    public_bookmarks = json.loads((fake_tree / "web/public/data.json").read_text())
    assert len(public_bookmarks) == 1


def test_explicit_false_overrides_env(fake_tree, monkeypatch):
    monkeypatch.setenv("FORGER_PUBLISH_DASHBOARD", "1")
    assert dashboard_sync.sync_dashboard_data(publish=False) is True
    public_bookmarks = json.loads((fake_tree / "web/public/data.json").read_text())
    assert public_bookmarks == []
