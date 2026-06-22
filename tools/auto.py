"""auto.py — Auto-Verify, Auto-Commit, Drift for plan_follow tools/ subpackage."""

from __future__ import annotations

import os

from .base import (
    _get_active_plan,
    logger,
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
            ["bash", "-c", verify_cmd], capture_output=True, text=True, timeout=timeout,
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


def _commit_in_repo(repo: str, task_id: str, files: list[str]) -> dict:
    """Git-add + commit in a single repo.

    Returns dict with status (committed/skipped/failed/error).
    """
    if not os.path.isdir(os.path.join(repo, ".git")):
        return {"status": "skipped", "repo": repo, "message": "No .git in repo."}

    import subprocess
    try:
        for f in files:
            subprocess.run(
                ["git", "add", "--", f],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if not diff.stdout.strip():
            return {"status": "skipped", "repo": repo, "message": "No changes to commit."}

        result = subprocess.run(
            ["git", "commit", "-m", f"plan: {task_id} — auto-commit"],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
        return {
            "status": "committed" if result.returncode == 0 else "failed",
            "repo": repo,
            "output": (result.stdout[:300] + result.stderr[:300]),
        }
    except Exception as e:
        return {"status": "error", "repo": repo, "message": str(e)}


def auto_commit(task_id: str, files: list[str], repo: str = "",
                repos: list[str] | None = None) -> dict:
    """Git-commit task files across one or more repositories.

    Supports multi-repo via ``repos`` list. Falls back to single ``repo``
    for backward compatibility.

    Args:
        task_id: Task identifier for the commit message.
        files: List of file paths to add.
        repo: Single git repo path (legacy).
        repos: Multiple git repo paths.

    Returns:
        Dict with results per repo.
    """
    if not files:
        return {"status": "skipped", "message": "No files to commit."}

    target_repos: list[str] = []
    if repos:
        target_repos = list(repos)
    elif repo:
        target_repos = [repo]

    if not target_repos:
        return {"status": "skipped", "message": "No git repo configured."}

    results = []
    for r in target_repos:
        results.append(_commit_in_repo(r, task_id, files))

    failed = [r for r in results if r.get("status") in ("failed", "error")]
    committed = [r for r in results if r.get("status") == "committed"]
    skipped = [r for r in results if r.get("status") == "skipped"]

    if not results:
        return {"status": "skipped", "message": "No repos configured."}
    if committed:
        return {
            "status": "committed",
            "committed": len(committed),
            "skipped": len(skipped),
            "failed": len(failed),
            "results": results,
        }
    if failed:
        return {
            "status": "failed",
            "message": f"{len(failed)} repo(s) failed",
            "results": results,
        }
    return {"status": "skipped", "results": results}


def auto_push(repos: list[str], remote: str = "origin",
              branch: str | None = None) -> dict:
    """Git-push to remote for one or more repos.

    Args:
        repos: List of git repo paths.
        remote: Remote name (default: origin).
        branch: Branch to push (default: current branch).

    Returns:
        Dict with results per repo.
    """
    import subprocess
    results = []
    for repo in repos:
        if not os.path.isdir(os.path.join(repo, ".git")):
            results.append({"status": "skipped", "repo": repo,
                            "message": "No .git in repo."})
            continue
        try:
            if branch is None:
                br = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=repo, capture_output=True, text=True, timeout=10,
                )
                branch = br.stdout.strip() or "main"

            result = subprocess.run(
                ["git", "push", remote, branch],
                cwd=repo, capture_output=True, text=True, timeout=60,
            )
            results.append({
                "status": "pushed" if result.returncode == 0 else "failed",
                "repo": repo,
                "remote": remote,
                "branch": branch,
                "output": (result.stdout[:300] + result.stderr[:300]),
            })
        except Exception as e:
            results.append({"status": "error", "repo": repo, "message": str(e)})
    return {"results": results}


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
            logger.warning("Drift check failed for repo %s: %s", repo, e)
            continue

    return unplanned
