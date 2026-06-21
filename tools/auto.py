"""auto.py — Auto-Verify, Auto-Commit, Drift for plan_follow tools/ subpackage."""

from __future__ import annotations

import os
from typing import Any

from .base import (
    logger,
    _get_active_plan,
)


# ─── Auto-Verify & Auto-Commit ─────────────────────────────────────────────────


def auto_verify_task(verify_cmd: str, timeout: int = 120) -> dict:
    """Run a verify command as a subprocess and return results.

    Args:
        verify_cmd: Shell command to execute.
        timeout: Max seconds to wait (default 120).

    Returns:
        Dict with status (passed/failed/skipped), exit_code, stdout, stderr.
    """
    if not verify_cmd or not verify_cmd.strip():
        return {"status": "skipped", "message": "No verify command configured."}

    import subprocess
    try:
        result = subprocess.run(
            verify_cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        std_out = result.stdout[-1000:] if result.stdout else ""
        std_err = result.stderr[-1000:] if result.stderr else ""
        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "stdout": std_out,
            "stderr": std_err,
        }
    except subprocess.TimeoutExpired:
        return {"status": "failed", "message": f"verify-Command timeout ({timeout}s)"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


def auto_commit(task_id: str, files: list[str], repo: str = "") -> dict:
    """Git-commit only the task's files.

    Args:
        task_id: Task identifier for the commit message.
        files: List of file paths to add.
        repo: Git repository path.

    Returns:
        Dict with status (committed/skipped/failed) and output.
    """
    if not repo or not os.path.isdir(os.path.join(repo, ".git")):
        return {"status": "skipped", "message": "No git repo configured."}
    if not files:
        return {"status": "skipped", "message": "No files to commit."}

    import subprocess
    try:
        # Add files
        for f in files:
            subprocess.run(
                ["git", "add", "--", f],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )

        # Check if anything changed
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if not diff.stdout.strip():
            return {"status": "skipped", "message": "No changes to commit."}

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", f"plan: {task_id} — auto-commit"],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
        return {
            "status": "committed" if result.returncode == 0 else "failed",
            "output": (result.stdout[:300] + result.stderr[:300]),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Drift Detection ─────────────────────────────────────────────────────────


def _get_repos(plan: dict) -> list[str]:
    """Normalize repo/repos to a list. Supports legacy single 'repo' and new 'repos' array."""
    repos = plan.get("repos", [])
    if isinstance(repos, list) and repos:
        return repos
    single = plan.get("repo", "")
    if single:
        return [single]
    return []


def check_drift() -> list:
    """Compare git diff against current task's files. Returns list of unplanned files.
    Supports multiple repos — checks all configured repositories."""
    plan = _get_active_plan()
    if not plan or not plan.get("current_task"):
        return []

    tid = plan["current_task"]
    task = plan["tasks"].get(tid)
    if not task:
        return []

    allowed_files = set(task.get("files", []))
    repos = _get_repos(plan)
    if not repos:
        return []

    import subprocess
    unplanned = []
    for repo in repos:
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                changed = [f.strip() for f in result.stdout.split("\n") if f.strip()]
                unplanned.extend(f for f in changed if f not in allowed_files)
        except Exception as e:
            logger.warning(f"Drift check failed for repo {repo}: {e}")
            continue

    return unplanned
