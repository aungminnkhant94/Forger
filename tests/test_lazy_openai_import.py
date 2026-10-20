"""Agent mode must not require the openai package at import time.

Root cause this guards: forger.analysis eagerly imported openai, and
bookmark_workflow imported analysis at module level, so `forge add --agent`
crashed with ModuleNotFoundError even when no API key was needed.
"""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager


@contextmanager
def _openai_blocked():
    """Simulate openai not being installed via sys.modules.

    Restores sys.modules AND forger.* package attributes so later tests keep
    the original module object identity (needed for patch.object).
    """
    import forger

    saved_openai = {
        name: mod
        for name, mod in list(sys.modules.items())
        if name == "openai" or name.startswith("openai.")
    }
    targets = (
        "forger.analysis",
        "forger.bookmark_workflow",
    )
    saved_forger = {
        name: sys.modules[name]
        for name in targets
        if name in sys.modules
    }
    saved_pkg_attrs = {
        name: getattr(forger, name.split(".", 1)[1], None)
        for name in targets
    }

    for name in saved_openai:
        del sys.modules[name]
    for name in list(sys.modules):
        if name in targets or name.startswith("forger.analysis."):
            del sys.modules[name]
    # Halt any import of openai (importlib convention: None → ModuleNotFoundError).
    sys.modules["openai"] = None

    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == "openai" or name.startswith("openai."):
                del sys.modules[name]
            if (
                name in targets
                or name.startswith("forger.analysis.")
                or name.startswith("forger.bookmark_workflow.")
            ):
                del sys.modules[name]
        sys.modules.update(saved_openai)
        sys.modules.update(saved_forger)
        for fqname, mod in saved_forger.items():
            attr = fqname.split(".", 1)[1]
            setattr(forger, attr, mod)
        for fqname, mod in saved_pkg_attrs.items():
            if fqname not in saved_forger and mod is not None:
                setattr(forger, fqname.split(".", 1)[1], mod)


def test_analysis_module_imports_without_openai():
    """forger.analysis must load when openai is absent (derive_legacy_scores / resolve)."""
    with _openai_blocked():
        analysis = importlib.import_module("forger.analysis")
        # Eager `from openai import OpenAI` would have crashed before this.
        assert not hasattr(analysis, "OpenAI")
        result = analysis.derive_legacy_scores(
            {
                "actionable_this_week": True,
                "reduces_friction": False,
                "reference_material": False,
            }
        )
        assert result["recommendation_bucket"] == "test_this_week"


def test_bookmark_workflow_imports_without_openai():
    """Agent-mode import chain (bookmark_workflow) must not pull openai."""
    with _openai_blocked():
        bw = importlib.import_module("forger.bookmark_workflow")
        assert hasattr(bw, "process_bookmark_url")
        assert hasattr(bw, "resolve_pending_analysis")


def test_agent_mode_entry_does_not_need_openai():
    """process_bookmark_url(..., analyze=False) must not import openai.

    Short-circuits on duplicate so we exercise agent-mode entry without network.
    """
    with _openai_blocked():
        bw = importlib.import_module("forger.bookmark_workflow")

        class _Existing:
            title = "already saved example title for duplicate path"
            id = "dup-id"

        original = bw.check_duplicate
        bw.check_duplicate = lambda _url: _Existing()  # type: ignore[method-assign]
        try:
            ok, msg, _bookmark, analysis = bw.process_bookmark_url(
                "https://example.com/agent-mode-no-openai",
                analyze=False,
            )
        finally:
            bw.check_duplicate = original
        assert ok is False
        assert msg.startswith("DUPLICATE:")
        assert analysis is None
