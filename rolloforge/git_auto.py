"""Git automation for RolloForge.

Auto-commit and push bookmark changes to GitHub. Off by default — pushing to
a user's repository is an opt-in side effect (set ROLLOFORGE_AUTO_GIT=1).
"""
import os
import subprocess
import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def git_auto_push(bookmark_title: str) -> bool:
    """
    Auto-commit and push bookmark changes to GitHub.

    Requires ROLLOFORGE_AUTO_GIT=1 and a git repo with a configured remote.

    Args:
        bookmark_title: Title of the bookmark for commit message

    Returns:
        True if successful (or nothing to do), False otherwise
    """
    if os.getenv("ROLLOFORGE_AUTO_GIT") != "1":
        LOGGER.info("Auto-git disabled (set ROLLOFORGE_AUTO_GIT=1 to enable)")
        return False
    try:
        # Check if there are changes to commit
        status_result = subprocess.run(
            ['git', 'status', '--porcelain'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True
        )
        
        if not status_result.stdout.strip():
            LOGGER.info("No changes to commit")
            return True
        
        # Stage data files
        subprocess.run(
            ['git', 'add', 'data/', 'web/lib/data.json', 'web/lib/analysis.json'],
            cwd=PROJECT_ROOT,
            check=True
        )
        
        # Check if there's anything to commit after staging
        diff_result = subprocess.run(
            ['git', 'diff', '--cached', '--quiet'],
            cwd=PROJECT_ROOT
        )
        
        if diff_result.returncode == 0:
            LOGGER.info("No changes to commit after staging")
            return True
        
        # Commit
        commit_msg = f"Add bookmark: {bookmark_title[:50]}"
        subprocess.run(
            ['git', 'commit', '-m', commit_msg],
            cwd=PROJECT_ROOT,
            check=True
        )
        
        # Push current branch
        branch_result = subprocess.run(
            ['git', 'branch', '--show-current'],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True
        )
        current_branch = branch_result.stdout.strip()
        subprocess.run(
            ['git', 'push', 'origin', current_branch],
            cwd=PROJECT_ROOT,
            check=True
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
        timestamp_file = PROJECT_ROOT / 'web' / 'app' / 'page.tsx'
        if timestamp_file.exists():
            content = timestamp_file.read_text()
            # Add or update timestamp comment
            if '// Build timestamp:' in content:
                content = content.split('// Build timestamp:')[0] + f"// Build timestamp: {__import__('datetime').datetime.now().isoformat()}\n"
            else:
                content = content.rstrip() + f"\n// Build timestamp: {__import__('datetime').datetime.now().isoformat()}\n"
            timestamp_file.write_text(content)
            
            # Stage and commit
            subprocess.run(['git', 'add', 'web/app/page.tsx'], cwd=PROJECT_ROOT, check=True)
            subprocess.run(['git', 'commit', '-m', 'Force Vercel redeploy'], cwd=PROJECT_ROOT, check=True)
            branch_result = subprocess.run(['git', 'branch', '--show-current'], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
            current_branch = branch_result.stdout.strip()
            subprocess.run(['git', 'push', 'origin', current_branch], cwd=PROJECT_ROOT, check=True)
            
            LOGGER.info("Forced redeploy")
            return True
    except Exception as e:
        LOGGER.error(f"Force deploy failed: {e}")
        return False
    
    return False
