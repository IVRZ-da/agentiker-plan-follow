"""task.py — Task CRUD operations for plan_follow tools/ subpackage."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from .base import (
    _get_active_plan,
    _get_cached_plan,
    _load_plan,
    _save_plan,
    get_session_id,
    logger,
    reset_tool_metrics,
)
from .coordination import (
    _auto_lock_task_files,
    _auto_unlock_task_files,
    _create_review_task,
    _save_plan_state_to_honcho,
)
from .state import STATE
from .status import _format_progress

# ─── Plan CRUD ────────────────────────────────────────────────────────────────


def _kanban_available() -> bool:
    try:
        import sys
        _p = "/home/jo/.hermes/hermes-agent"
        if _p not in sys.path:
            sys.path.insert(0, _p)
        from hermes_cli import kanban_db  # noqa: F401
        return True
    except ImportError:
        return False


def _kanban_db():
    try:
        from hermes_cli import kanban_db
        return kanban_db
    except ImportError:
        return None


def _kanban_profile() -> str:
    import os
    return os.environ.get("HERMES_PROFILE", "default")


def _profile_for_review(review_profile: str) -> str:
    """Map review_profile to Kanban worker profile name."""
    mapping = {
        "full": "plan-reviewer",
        "security": "plan-reviewer",
        "api-route": "plan-reviewer",
        "unit-test": "plan-reviewer",
        "ui-component": "plan-reviewer",
    }
    return mapping.get(review_profile, "plan-worker")


def _skill_for_review(review_profile: str) -> list[str]:
    """Map review_profile to Kanban skills."""
    mapping = {
        "full": ["review:full"],
        "security": ["review:security"],
        "api-route": ["review:api-route"],
        "unit-test": ["review:unit-test"],
        "ui-component": ["review:ui-component"],
    }
    return mapping.get(review_profile, ["plan:default"])


# ─── Kanban Plan Creation ─────────────────────────────────────────────────────


def _create_kanban_plan(
    goal: str, tasks: list, plan_id: str, repo: str = "",
    repos: Optional[list[str]] = None,
    parallel_groups: Optional[dict] = None,
) -> str:
    """Create a plan as a Kanban task graph.

    Creates one root task (type='plan') + N child tasks (type='plan_task')
    with dependencies via link_tasks().

    Returns plan_id.
    """
    import json
    import uuid
    from datetime import datetime, timezone

    kdb = _kanban_db()
    if not kdb:
        raise RuntimeError("Kanban-DB not available")

    conn = kdb.connect(board='plans')
    try:
        profile = _kanban_profile()
        now = datetime.now(timezone.utc).isoformat()

        # Session-ID + Workspace-Pfad ermitteln
        try:
            from .base import get_session_id
            session_id = get_session_id()
        except Exception:
            session_id = str(uuid.uuid4())

        workspace_path = ""
        if repos:
            workspace_path = str(repos[0])
        elif repo:
            workspace_path = repo
        else:
            import os
            workspace_path = os.getcwd()

        # 1. Create root plan task
        root_body_str = json.dumps({
            "type": "plan",
            "plan_id": plan_id,
            "goal": goal,
            "created": now,
            "repo": repo,
            "repos": repos or [],
            "parallel_groups": parallel_groups or {},
            "current_task": None,
            "template": "kanban",
            "version": "2",
            "session_id": session_id,
            "workspace_path": workspace_path,
        })

        root_id = None
        try:
            root_id = kdb.create_task(
                conn,
                title=goal[:80],
                body=root_body_str,
                assignee=profile,
                initial_status="running",
                priority=5,
                workspace_kind="dir",
                workspace_path=workspace_path,
                skills=[],
                max_runtime_seconds=7200,
                max_retries=2,
                session_id=session_id,
            )
            if root_id:
                from .state import STATE
                STATE.kanban_root_id = root_id
                try:
                    kdb.add_notify_sub(conn, task_id=root_id, platform="hermes",
                                       chat_id=session_id, notifier_profile=profile)
                except Exception:
                    logger.debug("Notify sub for root failed (non-fatal)")
        except Exception as root_err:
            logger.debug("Root task creation failed (non-fatal): %s", root_err)

        # 2. Create child tasks
        kanban_child_ids = {}
        for t in tasks:
            tid = t.get("id", "unknown")
            t_name = t.get("name", tid)
            t_verify = t.get("verify", "")
            t_files = t.get("files", [])
            t_review = t.get("review_profile", "none")
            depends_on = t.get("depends_on", [])

            task_body = json.dumps({
                "type": "plan_task",
                "plan_id": plan_id,
                "task_id": tid,
                "name": t_name,
                "verify": t_verify,
                "files": t_files,
                "review_profile": t_review,
                "depends_on": depends_on,
            })

            # Determine assignee + skills from review_profile
            assignee = _profile_for_review(t_review) if t_review != "none" else profile
            child_skills = _skill_for_review(t_review)
            if not child_skills:
                child_skills = ["plan:default"]

            kanban_child_id = kdb.create_task(
                conn,
                title=f"{plan_id[:30]}:{tid} — {t_name[:40]}",
                body=task_body,
                assignee=assignee,
                initial_status="blocked",
                skills=child_skills,
                priority=5,
                workspace_kind="dir",
                workspace_path=workspace_path,
                parents=[root_id] if root_id else [],
                max_runtime_seconds=3600,
                max_retries=2,
                session_id=session_id,
            )
            if kanban_child_id:
                kanban_child_ids[tid] = kanban_child_id
                try:
                    kdb.add_notify_sub(conn, task_id=kanban_child_id, platform="hermes",
                                       chat_id=session_id, notifier_profile=assignee)
                except Exception:
                    pass

        # 3. Link dependencies (via kanban-IDs, nicht plan_follow-IDs)
        for t in tasks:
            tid = t.get("id", "")
            child_kid = kanban_child_ids.get(tid)
            if not child_kid:
                continue
            for dep in t.get("depends_on", []):
                parent_kid = kanban_child_ids.get(dep) or root_id
                if parent_kid and child_kid:
                    try:
                        kdb.link_tasks(conn, parent_kid, child_kid)
                    except Exception:
                        logger.debug("Kanban link %s → %s failed (non-fatal)", dep, tid)

        # 4. Start first task — update root task's current_task via comment
        if tasks:
            first_tid = tasks[0].get("id", "")
            try:
                root_body_dict = json.loads(root_body_str)
                root_body_dict["current_task"] = first_tid
                kdb.add_comment(conn, plan_id, author="system", body=json.dumps(root_body_dict))
            except Exception:
                pass
    finally:
        conn.close()

    logger.info("✅ Plan '%s' als Kanban-Task-Graph erstellt (%d Tasks)", plan_id, len(tasks))

    # Save JSON plan as backup (für STATE-Konsistenz + Fallback)
    try:
        from datetime import datetime, timezone
        plan_dict = {
            "plan_id": plan_id,
            "goal": goal,
            "created": now,
            "current_task": tasks[0].get("id", "") if tasks else None,
            "tasks": {t["id"]: {
                "id": t["id"],
                "status": "in_progress" if t.get("id") == (tasks[0].get("id", "") if tasks else None) else "pending",
                "name": t.get("name", ""),
                "files": t.get("files", []),
                "verify": t.get("verify", ""),
                "review_profile": t.get("review_profile", "none"),
                "depends_on": t.get("depends_on", []),
            } for t in tasks},
            "repo": repo,
            "repos": repos or [],
            "parallel_groups": parallel_groups or {},
        }
        from .base import _save_plan
        _save_plan(plan_dict)
        logger.debug("JSON-Backup für Plan %s gespeichert", plan_id)
    except Exception as plan_save_err:
        logger.warning("JSON-Backup fehlgeschlagen (non-fatal): %s", plan_save_err)

    return plan_id


def create_plan(goal: str, tasks: list, repo: str = "", parallel_groups: Optional[dict] = None,
                repos: Optional[list[str]] = None, plan_id_override: str = "") -> str:
    """Create a new plan and persist it. Returns plan_id.

    Args:
        goal: The plan goal.
        tasks: List of task dicts with id, name, files, verify, depends_on.
        repo: Optional single git repo path (legacy, use repos instead).
        parallel_groups: Optional dict of groups.
        repos: Optional list of git repo paths for drift detection across
            multiple repositories.
        plan_id_override: Optional custom plan_id. If provided, used instead
            of auto-generated from goal.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    if plan_id_override:
        plan_id = plan_id_override
    else:
        plan_id = f"{now[:10]}-{goal.lower().replace(' ', '-')[:40]}"


    # --- Kanban-DB: Create Task-Graph ---
    if _kanban_available():
        try:
            return _create_kanban_plan(
                goal=goal, tasks=tasks, plan_id=plan_id,
                repo=repo, repos=repos,
                parallel_groups=parallel_groups,
            )
        except Exception as e:
            logger.warning("Kanban plan creation failed, fallback to JSON: %s", e)

    # --- JSON-Fallback: Existing logic ---
    tasks_dict = {}
    for t in tasks:
        tasks_dict[t["id"]] = {
            "id": t["id"],  # preserve for peer review identification
            "status": "pending",
            "name": t.get("name", ""),
            "files": t.get("files", []),
            "verify": t.get("verify", ""),
            "review_profile": t.get("review_profile", "none"),
            "review_result": None,
            "depends_on": t.get("depends_on", []),
        }

    plan = {
        "plan_id": plan_id,
        "goal": goal,
        "created": now,
        "plan_version": "1",
        "repo": repo,
        "current_task": None,
        "tasks": tasks_dict,
    }

    if repos:
        plan["repos"] = repos

    # Parallel groups
    if parallel_groups:
        plan["parallel_groups"] = {}
        ordered = sorted(parallel_groups.keys())
        for i, gid in enumerate(ordered):
            g = parallel_groups[gid]
            plan["parallel_groups"][gid] = {
                "tasks": g.get("tasks", []),
                "status": "in_progress" if i == 0 else "pending",
            }
        # Set first task of first group as current_task
        first_group = plan["parallel_groups"][ordered[0]]
        if first_group["tasks"]:
            first_tid = first_group["tasks"][0]
            plan["current_task"] = first_tid
            tasks_dict[first_tid]["status"] = "in_progress"
            for t_parallel in first_group["tasks"][1:]:
                tasks_dict[t_parallel]["status"] = "in_progress"
    else:
        # Linear mode: first task without dependencies becomes current
        for tid, tdef in tasks_dict.items():
            if not tdef["depends_on"]:
                plan["current_task"] = tid
                tdef["status"] = "in_progress"
                break

    reset_tool_metrics()
    _save_plan(plan)

    # Cross-Session: Session registrieren
    try:
        from .coord_state import register_session
        register_session(
            get_session_id(),
            plan_id=plan_id,
            goal=goal[:80],
            cwd=os.getcwd(),
        )
    except Exception:
        logger.debug("Honcho session registration failed (best-effort)")
        pass  # Best-effort

    # Honcho persistence (save plan state for cross-session recovery)
    _save_plan_state_to_honcho(plan_id, "active", "true")

    return plan_id


def get_current_task() -> Optional[dict]:
    """Return the current task dict, or None if no active plan.

    Uses full recovery chain (cache → disk → Honcho).
    For session-local check, use get_current_task_cached().
    """
    plan = _get_active_plan()
    return _task_from_plan(plan)


def get_current_task_cached() -> Optional[dict]:
    """Return current task from in-memory cache ONLY.

    No disk or Honcho recovery — prevents plan leaks across sessions.
    """
    plan = _get_cached_plan()
    return _task_from_plan(plan)


def _task_from_plan(plan: Optional[dict]) -> Optional[dict]:
    """Extract current task dict from a plan, or None."""
    if not plan or not plan.get("current_task"):
        return None
    tid = plan["current_task"]
    task = plan["tasks"].get(tid)
    if not task:
        return None
    return {
        "plan_id": plan["plan_id"],
        "goal": plan["goal"],
        "task_id": tid,
        "name": task["name"],
        "status": task["status"],
        "files": task["files"],
        "verify": task["verify"],
        "review_profile": task.get("review_profile", "none"),
        "review_result": task.get("review_result"),
        "depends_on": task["depends_on"],
        "progress": _format_progress(plan),
    }


def get_current_tasks() -> list[dict]:
    """Return ALL current tasks (supports parallel groups).

    In linear mode (no parallel_groups), returns a list with one task.
    In group mode, returns all tasks in the active group that are
    still in_progress or pending.

    Uses full recovery chain (cache → disk → Honcho).
    For session-local check, use get_current_tasks_cached().
    """
    plan = _get_active_plan()
    return _tasks_from_plan(plan)


def get_current_tasks_cached() -> list[dict]:
    """Return ALL current tasks from in-memory cache ONLY.

    No disk or Honcho recovery.
    """
    plan = _get_cached_plan()
    return _tasks_from_plan(plan)


def _tasks_from_plan(plan: Optional[dict]) -> list[dict]:
    """Extract current tasks list from a plan."""
    if not plan or not plan.get("current_task"):
        return []

    groups = plan.get("parallel_groups")
    if groups:
        for gid, group in groups.items():
            if group["status"] == "in_progress":
                result = []
                for tid in group["tasks"]:
                    t = plan["tasks"].get(tid)
                    if t and t["status"] in ("in_progress", "pending"):
                        result.append(_format_task(tid, t, plan))
                return result
        return []

    # Linear mode: return single current task
    t = get_current_task()
    return [t] if t else []


def _format_task(tid: str, task: dict, plan: dict) -> dict:
    """Format a task dict for API responses."""
    return {
        "plan_id": plan["plan_id"],
        "goal": plan["goal"],
        "task_id": tid,
        "name": task["name"],
        "status": task["status"],
        "files": task["files"],
        "verify": task["verify"],
        "review_profile": task.get("review_profile", "none"),
        "review_result": task.get("review_result"),
        "depends_on": task["depends_on"],
        "progress": _format_progress(plan),
    }


def _run_verify(verify_cmd: str, timeout: int = 120) -> dict:
    """Run a verify command and return results."""
    if not verify_cmd or not verify_cmd.strip():
        return {"status": "skipped", "message": "No verify command configured."}
    import subprocess
    try:
        result = subprocess.run(
            ["bash", "-c", verify_cmd], capture_output=True, text=True, timeout=timeout,
        )
        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[-500:],
        }
    except subprocess.TimeoutExpired:
        return {"status": "failed", "message": f"Timeout ({timeout}s)"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


def _check_drift(repos: list[str]) -> list[str]:
    """Check for unplanned changes in git repos."""
    import subprocess
    drift = []
    for repo in repos:
        if not repo:
            continue
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )
            if result.stdout.strip():
                drift.append(
                    f"{repo}: {len([_line for _line in result.stdout.splitlines() if _line.strip()])} uncommitted changes"
                )
        except Exception:
            pass
    return drift


def _kanban_complete(plan_id: str, task_id: str, verify_result: dict) -> None:
    """Complete a task in Kanban DB (best-effort)."""
    kdb = _kanban_db()
    if not kdb:
        return
    try:
        import json
        import os
        summary = verify_result.get("status", "completed")
        metadata = {
            "plan_id": plan_id,
            "task_id": task_id,
            "verify": verify_result,
            "profile": os.environ.get("HERMES_PROFILE", "default"),
        }
        conn = kdb.connect(board='plans')
        try:
            kdb.complete_task(
                conn,
                f"{plan_id}:{task_id}",
                summary=summary,
                metadata=json.dumps(metadata),
            )
        finally:
            conn.close()
        logger.debug("Kanban complete: %s/%s → %s", plan_id, task_id, summary)
    except Exception as e:
        logger.debug("Kanban complete failed (non-fatal): %s", e)


def complete_task(task_id: str, auto_verify: bool = False) -> dict:
    """Mark a task as completed, advance to next. Returns result dict.

    Supports:
    - Auto-Verify: runs verify command before completing
    - Kanban: calls kanban_db.complete_task() when available
    - Drift detection: warns about unplanned changes
    - Parallel groups and linear mode
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    if plan.get("current_task") != task_id:
        return {"status": "error", "message": f"Task '{task_id}' is not the current task."}

    # 1. Drift Detection
    repos = plan.get("repos", [])
    if plan.get("repo"):
        repos = [plan["repo"]] + repos
    drift = _check_drift(repos) if repos else []

    # 2. Auto-Verify
    verify_result = {"status": "skipped"}
    if auto_verify:
        verify_cmd = task.get("verify", "")
        if verify_cmd and verify_cmd != "echo '✅ Plan reviewed and accepted'":
            verify_result = _run_verify(verify_cmd)
            if verify_result.get("status") == "failed":
                return {
                    "status": "verify_failed",
                    "task_id": task_id,
                    "message": f"Verify command failed: {verify_cmd}",
                    "verify_result": verify_result,
                    "drift": drift,
                }

    # 3. Kanban: complete task
    _kanban_complete(plan["plan_id"], task_id, verify_result)

    # Review-Gate: create review task if applicable
    review_profile = task.get("review_profile", "none")
    if review_profile and review_profile != "none":
        _create_review_task(
            plan_id=plan["plan_id"],
            task_id=task_id,
            review_profile=review_profile,
            files=task.get("files", []),
        )

    # 4. Mark as completed (JSON fallback)
    task["status"] = "completed"
    task["verify_result"] = verify_result
    if drift:
        task["drift_warnings"] = drift
    _save_plan_state_to_honcho(plan["plan_id"], task_id, "completed")
    _auto_unlock_task_files(task)

    # 5. Advance
    groups = plan.get("parallel_groups")
    if groups:
        _advance_parallel_group(plan, task_id, groups)
    else:
        _advance_linear(plan)

    _save_plan(plan)

    # 6. Cross-Session: Session-Update
    try:
        from .coord_state import update_session
        update_session(get_session_id(), plan_id=plan["plan_id"])
    except Exception:
        pass

    result = {
        "status": "completed",
        "task_id": task_id,
        "next_task": plan.get("current_task"),
        "verify": verify_result,
    }
    if drift:
        result["drift"] = drift
    return result


def _advance_parallel_group(plan: dict, task_id: str, groups: dict) -> None:
    """Advance to next group when all tasks in current group are done."""
    current_group_id = None
    for gid, group in groups.items():
        if group["status"] == "in_progress":
            current_group_id = gid
            break

    if not current_group_id:
        plan["current_task"] = None
        return

    current_group = groups[current_group_id]

    # Check if ALL tasks in current group are completed
    all_done = all(
        plan["tasks"].get(tid, {}).get("status") == "completed"
        for tid in current_group["tasks"]
    )

    if not all_done:
        # Keep current group, set current_task to next incomplete task
        next_task = _find_next_in_group(plan, current_group)
        plan["current_task"] = next_task
        return

    # Current group is fully done → mark as completed
    current_group["status"] = "completed"

    # Find next pending group
    next_group_id = None
    found_current = False
    for gid in groups:
        if gid == current_group_id:
            found_current = True
            continue
        if found_current and groups[gid]["status"] == "pending":
            next_group_id = gid
            break

    if next_group_id:
        next_group = groups[next_group_id]
        next_group["status"] = "in_progress"
        reset_tool_metrics()
        # Activate all tasks in next group
        for tid in next_group["tasks"]:
            t = plan["tasks"].get(tid)
            if t:
                t["status"] = "in_progress"
                _save_plan_state_to_honcho(plan["plan_id"], tid, "in_progress")
                _auto_lock_task_files(t)
        # Set current_task to first task in new group
        plan["current_task"] = next_group["tasks"][0] if next_group["tasks"] else None
    else:
        plan["current_task"] = None
        _save_plan_state_to_honcho(plan["plan_id"], "active", "false")


def _find_next_in_group(plan: dict, group: dict) -> Optional[str]:
    """Find the next incomplete task in a group (for progress within group)."""
    for tid in group["tasks"]:
        t = plan["tasks"].get(tid)
        if t and t["status"] != "completed":
            return tid
    return None


def _advance_linear(plan: dict) -> None:
    """Find next task in linear mode (first pending with satisfied deps)."""
    next_task = None
    for tid, tdef in plan["tasks"].items():
        if tdef["status"] != "pending":
            continue
        deps = tdef.get("depends_on", [])
        if all(plan["tasks"].get(d, {}).get("status") == "completed" for d in deps):
            next_task = tid
            break

    if next_task:
        reset_tool_metrics()
        plan["current_task"] = next_task
        plan["tasks"][next_task]["status"] = "in_progress"
        _save_plan_state_to_honcho(plan["plan_id"], next_task, "in_progress")
        _auto_lock_task_files(plan["tasks"][next_task])
    else:
        plan["current_task"] = None
        _save_plan_state_to_honcho(plan["plan_id"], "active", "false")


def update_task(task_id: str, changes: dict) -> Optional[dict]:
    """Update a task's properties (files, verify, depends_on, name, review_profile).

    Also supports updating plan-level properties (parallel_groups) by passing
    parallel_groups in changes — these are applied to the plan, not the task.

    Returns the updated task dict if any keys were changed, or None if no
    supported keys matched (silent-ignore prevention).
    """
    if not isinstance(changes, dict):
        return None
    plan = _get_active_plan()
    if not plan:
        return None
    task = plan["tasks"].get(task_id)
    if not task:
        return None
    updated = False

    # Task-level updates
    for key in ("files", "verify", "depends_on", "name", "review_profile"):
        if key in changes:
            task[key] = changes[key]
            updated = True

    # Plan-level updates (applied to plan, not task)
    for key in ("parallel_groups",):
        if key in changes:
            plan[key] = changes[key]
            updated = True

    if not updated:
        return None
    _save_plan(plan)
    return task


def set_active_plan(plan_id: str) -> bool:
    """Load a plan from disk and set it as active. Returns True on success."""
    plan = _load_plan(plan_id)
    if not plan:
        return False
    STATE.active_plan = plan
    STATE.active_plan_id = plan_id
    # Auto-lock current task's files when activating a plan
    current_task_id = plan.get("current_task")
    if current_task_id:
        current_task = plan["tasks"].get(current_task_id)
        if current_task:
            _auto_lock_task_files(current_task)
    return True
