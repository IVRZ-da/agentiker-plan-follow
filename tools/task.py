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
    reset_tool_metrics,
)
from .coordination import (
    _auto_lock_task_files,
    _auto_unlock_task_files,
    _save_plan_state_to_honcho,
)
from .state import STATE
from .status import _format_progress

# ─── Plan CRUD ────────────────────────────────────────────────────────────────


def create_plan(goal: str, tasks: list, repo: str = "", parallel_groups: Optional[dict] = None,
                repos: Optional[list[str]] = None) -> str:
    """Create a new plan and persist it. Returns plan_id.

    Args:
        goal: The plan goal.
        tasks: List of task dicts with id, name, files, verify, depends_on.
        repo: Optional single git repo path (legacy, use repos instead).
        parallel_groups: Optional dict of groups.
        repos: Optional list of git repo paths for drift detection across
            multiple repositories.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    plan_id = f"{now[:10]}-{goal.lower().replace(' ', '-')[:40]}"

    tasks_dict = {}
    for t in tasks:
        tasks_dict[t["id"]] = {
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


def complete_task(task_id: str) -> dict:
    """Mark a task as completed, advance to next. Returns result dict.

    Supports parallel groups: when all tasks in a group are completed,
    the next group is activated (all tasks set to in_progress).
    In linear mode, advances to the next task with satisfied dependencies.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    if plan.get("current_task") != task_id:
        return {"status": "error", "message": f"Task '{task_id}' is not the current task."}

    # Mark as completed
    task["status"] = "completed"
    _save_plan_state_to_honcho(plan["plan_id"], task_id, "completed")
    # Release locks for completed task
    _auto_unlock_task_files(task)

    # Handle parallel groups
    groups = plan.get("parallel_groups")
    if groups:
        _advance_parallel_group(plan, task_id, groups)
    else:
        # Linear mode: find next pending task with completed dependencies
        _advance_linear(plan)

    _save_plan(plan)

    # Cross-Session: Session-Update bei Task-Abschluss
    try:
        from .coord_state import update_session
        update_session(get_session_id(), plan_id=plan["plan_id"])
    except Exception:
        pass  # Best-effort

    result = {
        "status": "completed",
        "task_id": task_id,
        "next_task": plan.get("current_task"),
    }
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
    for key in ("files", "verify", "depends_on", "name", "review_profile"):
        if key in changes:
            task[key] = changes[key]
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
