"""plan_mgmt.py — Plan lifecycle (abort, delete, select, due dates, archive) for plan_follow tools/ subpackage."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .base import (
    _clear_plans_index,
    _get_active_plan,
    _plan_path,
    _save_plan,
    get_session_id,
    logger,
)
from .coordination import (
    _auto_unlock_task_files,
)
from .resolver import resolve_archive_dir
from .state import STATE
from .task import set_active_plan


def abort_plan(task_id: str = "") -> dict:
    """Abort the active plan or a specific task.

    Args:
        task_id: If provided, abort only this task. Otherwise abort entire plan.

    Returns:
        Dict with status and plan_id.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    if task_id:
        task = plan["tasks"].get(task_id)
        if not task:
            return {"status": "error", "message": f"Task '{task_id}' not found."}
        task["status"] = "aborted"
        _auto_unlock_task_files(task)
        if plan.get("current_task") == task_id:
            plan["current_task"] = None
        _save_plan(plan)
        msg = f"Task '{task_id}' aborted."
    else:
        for tid, t in plan["tasks"].items():
            if t["status"] == "in_progress":
                t["status"] = "aborted"
                _auto_unlock_task_files(t)
        plan["current_task"] = None
        _save_plan(plan)

        # Fix A: Clear cache + index so aborted plan isn't recovered
        STATE.active_plan = None
        STATE.active_plan_id = None
        try:
            _clear_plans_index()
        except Exception:
            logger.debug("Plans index clear failed (best-effort)")

        msg = "Whole plan aborted."

    # Cross-Session: Deregistrierung bei Abbruch
    try:
        from .coord_state import unregister_session
        unregister_session(get_session_id())
    except Exception:
        logger.debug("Cross-session coordination failed (best-effort)")
        pass  # Best-effort

    return {"status": "aborted", "plan_id": plan["plan_id"], "message": msg}


def delete_plan(plan_id: str) -> dict:
    """Permanently delete a plan from disk.

    Args:
        plan_id: The plan ID to delete.

    Returns:
        Dict with status and message.
    """
    path = _plan_path(plan_id)
    if not path.exists():
        return {"status": "error", "message": f"Plan '{plan_id}' not found."}

    was_active = STATE.active_plan_id == plan_id

    if was_active:
        STATE.active_plan = None
        STATE.active_plan_id = None

    path.unlink()

    # Clear index if deleted plan was the active one
    if was_active:
        try:
            _clear_plans_index()
        except Exception:
            logger.debug("Plans index clear failed (best-effort)")

    # Cross-Session: Deregistrierung bei Löschung
    try:
        from .coord_state import unregister_session
        unregister_session(get_session_id())
    except Exception:
        logger.debug("Cross-session coordination failed (best-effort)")
        pass  # Best-effort

    return {"status": "deleted", "plan_id": plan_id, "message": f"Plan '{plan_id}' deleted."}


def select_plan(plan_id: str) -> dict:
    """Switch to a different plan as the active one.

    Args:
        plan_id: The plan ID to activate.

    Returns:
        Dict with status and current_task info.
    """
    ok = set_active_plan(plan_id)
    if not ok:
        return {"status": "error", "message": f"Plan '{plan_id}' not found."}
    return {
        "status": "selected",
        "plan_id": plan_id,
        "goal": STATE.active_plan.get("goal", "")[:60],
        "current_task": STATE.active_plan.get("current_task"),
    }


def set_task_due(task_id: str, due_date: str) -> dict:
    """Set a due date for a task.

    Args:
        task_id: Task ID.
        due_date: ISO-8601 date string (e.g. '2026-06-25') or empty string to clear.

    Returns:
        Dict with status and task info, or error dict.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}
    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    if due_date:
        # Basic ISO-8601 validation
        if not (len(due_date) >= 10 and due_date[4] == "-" and due_date[7] == "-"):
            return {"status": "error", "message": f"Invalid date format '{due_date}'. Expected: ISO-8601 (e.g. 2026-06-25)."}
        plan["tasks"][task_id]["due"] = due_date
    else:
        plan["tasks"][task_id].pop("due", None)

    _save_plan(plan)
    return {"status": "ok", "task_id": task_id, "due": due_date or None}


def get_task_due_info(task_id: str = "") -> Optional[dict]:
    """Get due date info for a task. Returns None if no due date or no active plan.

    Args:
        task_id: Task ID. If empty, uses current task.

    Returns:
        Dict with task_id, due (ISO date string), overdue (bool), days_remaining (int), or None.
    """
    plan = _get_active_plan()
    if not plan:
        return None
    if not task_id:
        task_id = plan.get("current_task", "")
    if not task_id or task_id not in plan["tasks"]:
        return None

    task = plan["tasks"][task_id]
    due = task.get("due", "")
    if not due:
        return None

    from datetime import datetime, timezone

    days_remaining = 0
    overdue = False
    try:
        due_dt = datetime.fromisoformat(due)
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (due_dt - now).days
        days_remaining = max(delta, 0) if delta >= 0 else delta
        overdue = delta < 0
    except (ValueError, TypeError):
        return {"task_id": task_id, "due": due, "error": "Cannot parse date"}

    return {
        "task_id": task_id,
        "due": due,
        "overdue": overdue,
        "days_remaining": days_remaining,
        "status": "overdue" if overdue else "pending",
    }


def archive_plan(plan_id: str) -> dict:
    """Move a plan to the archive directory.

    Args:
        plan_id: The plan ID to archive.

    Returns:
        Dict with status and message.
    """
    path = _plan_path(plan_id)
    if not path.exists():
        return {"status": "error", "message": f"Plan '{plan_id}' not found."}

    resolve_archive_dir().mkdir(parents=True, exist_ok=True)
    dest = resolve_archive_dir() / f"{plan_id}.json"

    import shutil
    try:
        shutil.move(str(path), str(dest))
    except OSError as e:
        return {"status": "error", "message": f"Archiving failed: {e}"}

    # Clear from active cache if it was the active plan
    if STATE.active_plan_id == plan_id:
        STATE.active_plan = None
        STATE.active_plan_id = None
        try:
            _clear_plans_index()
        except Exception:
            logger.debug("Plans index clear failed (best-effort)")

    return {
        "status": "archived", "plan_id": plan_id,
        "message": f"Plan '{plan_id}' archived (→ {resolve_archive_dir().relative_to(Path.home()) if Path.home() in resolve_archive_dir().parents else resolve_archive_dir()}/).",
    }


def restore_plan(plan_id: str) -> dict:
    """Restore a plan from the archive back to the plans directory.

    Args:
        plan_id: The plan ID to restore.

    Returns:
        Dict with status and message.
    """
    archived = resolve_archive_dir() / f"{plan_id}.json"
    if not archived.exists():
        return {"status": "error", "message": f"Archived plan '{plan_id}' not found. Use plan_list(include_archived=true) to search."}

    dest = _plan_path(plan_id)
    import shutil
    try:
        shutil.move(str(archived), str(dest))
    except OSError as e:
        return {"status": "error", "message": f"Restore failed: {e}"}

    return {
        "status": "restored", "plan_id": plan_id,
        "message": f"Plan '{plan_id}' restored from archive.",
    }

def retry_task(task_id: str) -> dict:
    """Reset a crashed/blocked task to pending for retry."""
    from .base import _get_active_plan, _save_plan
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan"}
    tasks = plan.get("tasks", {})
    if task_id not in tasks:
        return {"status": "error", "message": f"Task '{task_id}' not found"}
    t = tasks[task_id]
    old_status = t.get("status", "unknown")
    t["status"] = "pending"
    t["review_result"] = None
    _save_plan(plan)
    return {"status": "retried", "task_id": task_id, "from": old_status, "to": "pending"}
