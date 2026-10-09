"""Git automation for Forger.

Auto-commit and push bookmark changes to GitHub. OFF BY DEFAULT — pushing
personal bookmark data to a remote is an opt-in side effect
(set FORGER_AUTO_GIT=1). When enabled, Forger logs a hard warning: this can
commit URLs, page text, notes, and analysis from `data/` into git history.
"""
from __future__ import annotations

import logging
import os
import subprocess
import warnings
from pathlib import Path

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_AUTO_GIT_WARNED = False

_AUTO_GIT_WARNING = (
    "FORGER_AUTO_GIT=1 is enabled. Forger will attempt to commit and push "
    "personal bookmark data (data/, dashboard JSON). Only use this with a "
    "PRIVATE remote you control. Prefer forge sync --publish for local "
    "dashboard data and never force-add gitignored personal files to a "
    "public repo."
)


def auto_git_enabled() -> bool:
    return os.getenv("FORGER_AUTO_GIT", "").strip() == "1"


def _warn_auto_git_enabled() -> None:
    global _AUTO_GIT_WARNED
    LOGGER.warning(_AUTO_GIT_WARNING)
    warnings.warn(_AUTO_GIT_WARNING, UserWarning, stacklevel=3)
    if not _AUTO_GIT_WARNED:
        # One loud stderr line so CLI users notice without digging logs.
        print(f"WARNING: {_AUTO_GIT_WARNING}", flush=True)
        _AUTO_GIT_WARNED = True


def git_auto_push(bookmark_title: str) -> bool:
    """
    Auto-commit and push bookmark changes to GitHub.

    Requires FORGER_AUTO_GIT=1 and a git repo with a configured remote.
    Off by default. When enabled, emits a hard warning about personal data.

    Args:
        bookmark_title: Title of the bookmark for commit message

    Returns:
        True if successful (or nothing to do), False otherwise
    """
    if not auto_git_enabled():
        LOGGER.info("Auto-git disabled (default). Set FORGER_AUTO_GIT=1 to enable — not recommended for public repos.")
        return False

    _warn_auto_git_enabled()

    try:
        # Check if there are changes to commit
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )

        if not status_result.stdout.strip():
            LOGGER.info("No changes to commit")
            return True

        # Stage data files. Respect .gitignore — do not force-add personal
        # JSON that is intentionally ignored on public Forger.
        add_result = subprocess.run(
            ["git", "add", "--", "data/", "web/lib/data.json", "web/lib/analysis.json"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if add_result.returncode != 0:
            # Ignored paths make `git add` exit non-zero when named explicitly.
            LOGGER.warning(
                "Auto-git staging skipped or partial (gitignore may block personal "
                "data paths — this is intentional on public Forger): %s",
                (add_result.stderr or add_result.stdout).strip(),
            )

        # Check if there's anything to commit after staging
        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=PROJECT_ROOT,
        )

        if diff_result.returncode == 0:
            LOGGER.info("No changes to commit after staging")
            return True

        # Commit
        commit_msg = f"Add bookmark: {bookmark_title[:50]}"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=PROJECT_ROOT,
            check=True,
        )

        # Push current branch
        branch_result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        current_branch = branch_result.stdout.strip()
        subprocess.run(
            ["git", "push", "origin", current_branch],
            cwd=PROJECT_ROOT,
            check=True,
        )

        LOGGER.info(f"Successfully pushed: {bookmark_title[:50]}")
        return True

    except subprocess.CalledProcessError as e:
        LOGGER.error(f"Git operation failed: {e}")
        return False
    except Exception as e:
        LOGGER.error(f"Unexpected error in git_auto_push: {e}")
        return False


def git_force_deploy() -> bool:
    """
    Force a Vercel redeploy by making a trivial change.
    Use this if the regular push doesn't trigger a rebuild.
    """
    try:
        # Update a timestamp file
        timestamp_file = PROJECT_ROOT / "web" / "app" / "page.tsx"
        if timestamp_file.exists():
            content = timestamp_file.read_text()
            # Add or update timestamp comment
            if "// Build timestamp:" in content:
                content = content.split("// Build timestamp:")[0] + f"// Build timestamp: {__import__('datetime').datetime.now().isoformat()}\n"
            else:
                content = content.rstrip() + f"\n// Build timestamp: {__import__('datetime').datetime.now().isoformat()}\n"
            timestamp_file.write_text(content)

            # Stage and commit
            subprocess.run(["git", "add", "web/app/page.tsx"], cwd=PROJECT_ROOT, check=True)
            subprocess.run(["git", "commit", "-m", "Force Vercel redeploy"], cwd=PROJECT_ROOT, check=True)
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            current_branch = branch_result.stdout.strip()
            subprocess.run(["git", "push", "origin", current_branch], cwd=PROJECT_ROOT, check=True)

            LOGGER.info("Forced redeploy")
            return True
    except Exception as e:
        LOGGER.error(f"Force deploy failed: {e}")
        return False

    return False
