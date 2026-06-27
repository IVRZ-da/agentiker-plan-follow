"""auto.py — Auto-Verify, Auto-Commit, Auto-Advance, Review-Dispatch for plan_follow tools/ subpackage."""

from __future__ import annotations

import os
from typing import Any, Optional

from .. import plan_core
from .._fmt import fmt_info, fmt_ok
from .base import (
    _get_active_plan,
    logger,
)

# ─── Re-exports from plan_review ──────────────────────────────────────────────

def dispatch_review(
    profile_name: str, task: dict, depth: str = "normal"
) -> dict[str, Any]:
    """Prepare review data for a task.

    Delegates to plan_follow.plan_review.dispatch_review.

    Args:
        profile_name: Review profile name (unit-test, api-route, etc.)
        task: Task dict from the plan (must include 'files', 'id', 'name')
        depth: Review depth ('quick', 'normal', 'deep')

    Returns:
        Dict with 'status' key:
          - 'ready' — review can proceed
          - 'skipped' — no profile or no files
          - 'error' — invalid state
    """
    from ..plan_review import dispatch_review as _dispatch

    return _dispatch(profile_name, task, depth)


# ─── Auto-Advance ─────────────────────────────────────────────────────────────

def _find_next_linear(tasks: dict, completed_task_id: str) -> Optional[str]:
    """Find the next pending task with satisfied dependencies (linear mode).

    Returns task ID or None if all tasks are complete.
    Does NOT modify the task dicts — pure read-only logic.
    """
    ordered = list(tasks.keys())
    completed_idx = ordered.index(completed_task_id)

    for i in range(completed_idx + 1, len(ordered)):
        tid = ordered[i]
        tdef = tasks[tid]
        if tdef.get("status") != "pending":
            continue
        deps = tdef.get("depends_on", [])
        if all(tasks.get(d, {}).get("status") == "completed" for d in deps):
            return tid
    return None


def _find_next_parallel(tasks: dict, groups: dict,
                         completed_task_id: str) -> Optional[str]:
    """Find the next task in parallel group mode.

    Returns task ID or None if all groups are done.
    Does NOT modify the plan dict — pure read-only logic.
    """
    # Find which group the completed task belongs to (could be in_progress or completed)
    current_group_id = None
    for gid, group in groups.items():
        if completed_task_id in group.get("tasks", []):
            current_group_id = gid
            break

    if not current_group_id:
        return None

    current_group = groups[current_group_id]

    # Are all tasks in this group complete?
    all_done = all(
        tasks.get(tid, {}).get("status") == "completed"
        for tid in current_group.get("tasks", [])
    )

    if not all_done:
        # Find next incomplete task in this group
        for tid in current_group.get("tasks", []):
            t = tasks.get(tid)
            if t and t.get("status") != "completed":
                return tid
        return None

    # Current group fully done — find next pending group
    found_current = False
    for gid, group in groups.items():
        if gid == current_group_id:
            found_current = True
            continue
        if found_current and group.get("status") == "pending":
            # Return first task of next group
            for tid in group.get("tasks", []):
                t = tasks.get(tid)
                if t and t.get("status") == "pending":
                    return tid
            break

    return None


def auto_advance(plan: dict, completed_task_id: str) -> dict[str, Any]:
    """Determine the next task after completing the current one.

    Pure read-only function — does NOT modify the plan dict.
    Examines the plan's task structure to find the next task
    that should become 'in_progress'.

    Args:
        plan: The plan dictionary (must have 'tasks').
        completed_task_id: ID of the task that was just completed.

    Returns:
        Dict with:
          - 'status': 'advanced' | 'completed' | 'error'
          - 'next_task': task ID or None
          - 'message': human-readable message
    """
    if not plan:
        return {"status": "error", "next_task": None,
                "message": "No plan provided."}
    if not completed_task_id:
        return {"status": "error", "next_task": None,
                "message": "No completed task ID provided."}

    tasks = plan.get("tasks", {})
    if not tasks:
        return {"status": "error", "next_task": None,
                "message": "Plan has no tasks."}

    if completed_task_id not in tasks:
        return {"status": "error", "next_task": None,
                "message": f"Task '{completed_task_id}' not found in plan."}

    groups = plan.get("parallel_groups")
    if groups:
        next_task = _find_next_parallel(tasks, groups, completed_task_id)
    else:
        next_task = _find_next_linear(tasks, completed_task_id)

    if next_task:
        return {
            "status": "advanced",
            "next_task": next_task,
            "message": f"Advanced to task '{next_task}'.",
        }
    return {
        "status": "completed",
        "next_task": None,
        "message": "All tasks completed.",
    }

# ─── Auto-Verify & Auto-Commit ─────────────────────────────────────────────────


def auto_verify_task(verify_cmd: str, timeout: int = 120) -> dict:
    """Run a verify command as a subprocess and return results."""
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
    """Git-add + commit in a single repo."""
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


def _warn_other_sessions(repos: list[str]) -> list[str]:
    """Warn if other sessions work in overlapping repos. Returns warnings."""
    try:
        from .. import coord_state

        my_sid = plan_core.get_session_id()
        if not my_sid:
            return []
        sessions = coord_state.get_sessions()
        others = {sid: s for sid, s in sessions.items() if sid != my_sid}
        if not others:
            return []

        warnings = []

        plans_dir = plan_core.PLANS_DIR
        for sid, s in others.items():
            plan_id = s.get("plan_id", "")
            if not plan_id:
                continue
            plan_file = plans_dir / f"{plan_id}.json"
            if not plan_file.exists():
                continue
            try:
                import json

                other_plan = json.loads(plan_file.read_text())
                other_repos = other_plan.get("repos", other_plan.get("repo", []))
                if isinstance(other_repos, str):
                    other_repos = [other_repos]
                overlap = [r for r in repos if r in other_repos]
                if overlap:
                    label = plan_id[:25]
                    warnings.append(
                        f"⚠️ Session '{label}' arbeitet in {', '.join(overlap)}. "
                        f"Git-Operation kann Konflikte verursachen!"
                    )
            except Exception:
                continue
        return warnings
    except Exception:
        return []


def auto_commit(task_id: str, files: list[str], repo: str = "",
                repos: list[str] | None = None) -> dict:
    """Git-commit task files across one or more repositories."""
    if not files:
        return {"status": "skipped", "message": "No files to commit."}

    target_repos: list[str] = []
    if repos:
        target_repos = list(repos)
    elif repo:
        target_repos = [repo]

    if not target_repos:
        return {"status": "skipped", "message": "No git repo configured."}

    # Cross-Session Check
    conflicts = _warn_other_sessions(target_repos)
    if conflicts:
        return {"status": "cancelled", "message": "\n".join(conflicts) +
                " — Auto-Commit abgebrochen, andere Session aktiv in diesem Repo."}

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
    """Git-push to remote for one or more repos."""
    # Cross-Session Check
    conflicts = _warn_other_sessions(repos)
    if conflicts:
        return {"results": [{"status": "cancelled", "message": "\n".join(conflicts) +
                            " — Push abgebrochen, andere Session aktiv in diesem Repo."}]}

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


def get_git_status(repo: str) -> dict:
    """Get comprehensive git status for a single repo."""
    import subprocess

    result: dict = {"repo": repo}
    if not os.path.isdir(os.path.join(repo, ".git")):
        result["status"] = "no_git"
        return result

    try:
        br = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        result["branch"] = br.stdout.strip()

        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        result["dirty"] = bool(dirty.stdout.strip())
        result["dirty_files"] = len([ln for ln in dirty.stdout.splitlines() if ln.strip()])

        ab = subprocess.run(
            ["git", "rev-list", "--left-right", "--count",
             "HEAD...@{upstream}"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if ab.returncode == 0 and ab.stdout.strip():
            parts = ab.stdout.strip().split()
            result["ahead"] = int(parts[0]) if parts else 0
            result["behind"] = int(parts[1]) if len(parts) > 1 else 0
        else:
            result["ahead"] = 0
            result["behind"] = 0

        lc = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        result["last_commit"] = lc.stdout.strip() if lc.returncode == 0 else ""

        result["status"] = "ok"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def git_sync(repo: str, task_id: str, files: list[str],
             remote: str = "origin", branch: str | None = None,
             push_flag: bool = True) -> dict:
    """Pull to add to commit to push in one step."""
    import subprocess

    out: dict = {"repo": repo, "steps": []}

    if not os.path.isdir(os.path.join(repo, ".git")):
        out["status"] = "skipped"
        out["message"] = "No .git in repo."
        return out

    try:
        pull = subprocess.run(
            ["git", "pull", "--ff-only", remote],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
        out["steps"].append({
            "step": "pull",
            "status": "ok" if pull.returncode == 0 else "failed",
            "output": pull.stdout[:200] + pull.stderr[:200],
        })

        for f in files:
            subprocess.run(
                ["git", "add", "--", f],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )
        out["steps"].append({"step": "add", "status": "ok"})

        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if diff.stdout.strip():
            commit = subprocess.run(
                ["git", "commit", "-m", f"plan: {task_id} — auto-sync"],
                cwd=repo, capture_output=True, text=True, timeout=30,
            )
            out["steps"].append({
                "step": "commit",
                "status": "ok" if commit.returncode == 0 else "failed",
                "output": commit.stdout[:200] + commit.stderr[:200],
            })
        else:
            out["steps"].append({"step": "commit", "status": "skipped",
                                 "message": "No changes to commit."})

        if push_flag:
            br = branch or subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo, capture_output=True, text=True, timeout=10,
            ).stdout.strip() or "main"
            push_result = subprocess.run(
                ["git", "push", remote, br],
                cwd=repo, capture_output=True, text=True, timeout=60,
            )
            out["steps"].append({
                "step": "push",
                "status": "ok" if push_result.returncode == 0 else "failed",
                "output": push_result.stdout[:200] + push_result.stderr[:200],
            })

        out["status"] = "ok" if all(
            s["status"] == "ok" or s["status"] == "skipped"
            for s in out["steps"]
        ) else "failed"

    except Exception as e:
        out["status"] = "error"
        out["error"] = str(e)

    return out


# ─── Git Stash / Branch / Tag ──────────────────────────────────────────────────


def git_stash(repo: str, action: str = "push", message: str = "") -> dict:
    """Stash or unstash changes in a repo.

    Args:
        repo: Git repo path.
        action: 'push' (stash), 'pop' (restore), 'list' (show).
        message: Optional stash message for push.
    """
    import subprocess
    result: dict = {"repo": repo, "action": action}
    if not os.path.isdir(os.path.join(repo, ".git")):
        result["status"] = "skipped"
        result["message"] = "No .git in repo."
        return result

    try:
        if action == "push":
            cmd = ["git", "stash", "push", "-u"]
            if message:
                cmd.extend(["-m", message])
            out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=30)
            result["status"] = "ok" if out.returncode == 0 else "failed"
            result["output"] = (out.stdout[:300] + out.stderr[:300])
            result["stashed"] = "No local changes" not in out.stdout
        elif action == "pop":
            out = subprocess.run(["git", "stash", "pop"], cwd=repo, capture_output=True, text=True, timeout=30)
            result["status"] = "ok" if out.returncode == 0 else "failed"
            result["output"] = (out.stdout[:300] + out.stderr[:300])
        elif action == "list":
            out = subprocess.run(["git", "stash", "list"], cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok"
            result["stashes"] = out.stdout.strip()
        else:
            result["status"] = "error"
            result["message"] = f"Unknown action: {action}"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    return result


def git_branch(repo: str, action: str = "current", name: str = "",
               start_point: str = "") -> dict:
    """Manage branches in a repo.

    Args:
        repo: Git repo path.
        action: 'current', 'list', 'create', 'switch', 'delete'.
        name: Branch name (for create/switch/delete).
        start_point: Start point for branch creation.
    """
    import subprocess
    result: dict = {"repo": repo, "action": action}
    if not os.path.isdir(os.path.join(repo, ".git")):
        result["status"] = "skipped"
        result["message"] = "No .git in repo."
        return result

    try:
        if action == "current":
            out = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                 cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok"
            result["branch"] = out.stdout.strip()
        elif action == "list":
            out = subprocess.run(["git", "branch", "-a"],
                                 cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok"
            result["branches"] = out.stdout.strip()
        elif action == "create":
            cmd = ["git", "branch", name]
            if start_point:
                cmd.append(start_point)
            out = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok" if out.returncode == 0 else "failed"
            result["output"] = (out.stdout[:300] + out.stderr[:300])
        elif action == "switch":
            git_stash(repo, "push", "auto-stash before branch switch")
            out = subprocess.run(["git", "checkout", name],
                                 cwd=repo, capture_output=True, text=True, timeout=30)
            result["status"] = "ok" if out.returncode == 0 else "failed"
            result["output"] = (out.stdout[:300] + out.stderr[:300])
        elif action == "delete":
            out = subprocess.run(["git", "branch", "-d", name],
                                 cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok" if out.returncode == 0 else "failed"
            result["output"] = (out.stdout[:300] + out.stderr[:300])
        else:
            result["status"] = "error"
            result["message"] = f"Unknown action: {action}"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    return result


def git_tag(repo: str, tag_name: str, message: str = "", action: str = "create") -> dict:
    """Create or manage git tags.

    Args:
        repo: Git repo path.
        tag_name: Tag name.
        message: Tag annotation message.
        action: 'create', 'list', 'delete'.
    """
    import subprocess
    result: dict = {"repo": repo, "tag": tag_name, "action": action}
    if not os.path.isdir(os.path.join(repo, ".git")):
        result["status"] = "skipped"
        result["message"] = "No .git in repo."
        return result

    try:
        if action == "create":
            if message:
                out = subprocess.run(["git", "tag", "-a", tag_name, "-m", message],
                                     cwd=repo, capture_output=True, text=True, timeout=10)
            else:
                out = subprocess.run(["git", "tag", tag_name],
                                     cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok" if out.returncode == 0 else "failed"
            result["output"] = (out.stdout[:300] + out.stderr[:300])
        elif action == "list":
            out = subprocess.run(["git", "tag", "-l", "--sort=-creatordate"],
                                 cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok"
            result["tags"] = out.stdout.strip()
        elif action == "delete":
            out = subprocess.run(["git", "tag", "-d", tag_name],
                                 cwd=repo, capture_output=True, text=True, timeout=10)
            result["status"] = "ok" if out.returncode == 0 else "failed"
            result["output"] = (out.stdout[:300] + out.stderr[:300])
        else:
            result["status"] = "error"
            result["message"] = f"Unknown action: {action}"
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    return result


# ─── Drift Detection ─────────────────────────────────────────────────────────


def _get_repos(plan: dict, fallback_repo: str | None = None) -> list[str]:
    """Normalize repo/repos to a list.

    Fallback chain:
      1. plan['repos'] (list)
      2. plan['repo'] (single string)
      3. fallback_repo parameter (from tool args or env)
      4. Current working directory if it has a .git
      5. Empty list
    """
    repos = plan.get("repos", [])
    if isinstance(repos, list) and repos:
        return repos
    single = plan.get("repo", "")
    if single:
        return [single]
    if fallback_repo is not None:
        if fallback_repo:
            return [fallback_repo]
        return []
    cwd = os.getcwd()
    if os.path.isdir(os.path.join(cwd, ".git")):
        return [cwd]
    return []


def check_drift() -> list:
    """Compare git diff against current task's files."""
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


# ─── Alias ─────────────────────────────────────────────────────────────────────

auto_commit_task = auto_commit


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD Handler Functions (moved from handlers_crud.py)
# ═══════════════════════════════════════════════════════════════════════════════


def plan_verify_tool(args: dict, **kwargs) -> str:
    """Check for drift: unplanned changes compared to the current plan."""
    current = plan_core.get_current_task()
    if not current:
        return fmt_info("No active plan.")

    drift = plan_core.check_drift()
    if not drift:
        return fmt_ok({
            "status": "clean",
            "plan_id": current["plan_id"],
            "task_id": current["task_id"],
            "message": "Keine ungeplanten Änderungen.",
        })

    return fmt_ok({
        "status": "drift_detected",
        "plan_id": current["plan_id"],
        "task_id": current["task_id"],
        "unplanned_files": drift,
        "suggestion": "plan_update(task_id, {files: [...]}) oder Änderungen reverten.",
    })
