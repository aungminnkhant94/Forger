"""Auto-git stays off by default and warns when enabled."""
import warnings

from forger import git_auto


def test_auto_git_off_by_default(monkeypatch):
    monkeypatch.delenv("FORGER_AUTO_GIT", raising=False)
    assert git_auto.auto_git_enabled() is False
    assert git_auto.git_auto_push("title") is False


def test_auto_git_warns_when_enabled(monkeypatch):
    monkeypatch.setenv("FORGER_AUTO_GIT", "1")
    git_auto._AUTO_GIT_WARNED = False

    # Avoid real git: stop after the warning by making status empty.
    def fake_run(*args, **kwargs):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(git_auto.subprocess, "run", fake_run)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert git_auto.git_auto_push("some bookmark") is True
        assert any("FORGER_AUTO_GIT=1" in str(w.message) for w in caught)
