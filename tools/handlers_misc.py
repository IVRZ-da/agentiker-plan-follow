"""Miscellaneous plan tool handlers (session, lock, notify, decompose, simulate, sync, time, coord cleanup)."""
from __future__ import annotations

import logging

from .. import coord_state, plan_core
from .._fmt import fmt_err, fmt_ok

logger = logging.getLogger("plan_follow")


def plan_session_tool(args: dict, **kwargs) -> str:
    """Show active sessions, their plans, and lock status.

    Reads from coord_state.py — no Git required.
    If Git is active, additionally shows branch info.

    Parameters:
    - include_history (bool, optional): Show git-based plan history (default: false)
    """
    include_history = args.get("include_history", False)

    sessions = coord_state.get_sessions()
    locks = coord_state.get_locks()

    notifications = coord_state.get_notifications(plan_core.get_session_id(), mark_read=False)

    # Build lock overview per session
    lock_map = {}
    for path, lock in locks.items():
        sid = lock.get("session_id", "unknown")
        lock_map.setdefault(sid, []).append(path)

    sessions_out = {}
    for sid, s in sessions.items():
        entry = {
            "since": s.get("registered", ""),
            "plan_id": s.get("plan_id", ""),
            "goal": s.get("goal", "")[:60],
            "locks": lock_map.get(sid, []),
        }
        if include_history:
            plans_dir_git = coord_state.SHARED_DIR.parent / "plans" / ".git"
            entry["git_hint"] = (
                "Git nicht aktiv — verwende plan_git_init() für Versionierung"
                if not plans_dir_git.exists()
                else "Git aktiv — History via plan_history()"
            )
        sessions_out[sid] = entry

    result = {
        "active_sessions": len(sessions_out),
        "active_locks": len(locks),
        "pending_notifications": sum(len(n) for n in [notifications] if notifications),
        "sessions": sessions_out,
        "locks": locks,
    }
    return fmt_ok(result)


def plan_lock_tool(args: dict, **kwargs) -> str:
    """Manage resource locks for cross-session coordination.

    Parameters:
    - action (str, required): 'lock', 'unlock', 'status', 'list', or 'my'
    - path (str, required for lock/unlock/status): File or directory path
    - session_id (str, optional): Session ID (default: auto-detected)
    """
    action = args.get("action", "")
    path = args.get("path", "")
    session_id = args.get("session_id") or plan_core.get_session_id()

    if not action:
        return fmt_err("action is required (lock|unlock|status|list|my)")
    if action in ("lock", "unlock", "status") and not path:
        return fmt_err("path is required")

    if action == "lock":
        result = coord_state.acquire_lock(path, session_id)
    elif action == "unlock":
        result = coord_state.release_lock(path, session_id)
    elif action == "status":
        lock = coord_state.get_lock(path)
        if lock:
            result = {"status": "locked", "path": path, "locked_by": lock.get("session_id"), "since": lock.get("since")}
        else:
            result = {"status": "free", "path": path}
    elif action in ("list", "my"):
        all_locks = coord_state.get_locks()
        if action == "my":
            filtered = {p: lk for p, lk in all_locks.items() if lk.get("session_id") == session_id}
        else:
            filtered = all_locks
        return fmt_ok({
            "action": action,
            "count": len(filtered),
            "locks": [
                {
                    "path": p,
                    "session_id": lk.get("session_id", "?"),
                    "since": lk.get("since", "?"),
                }
                for p, lk in sorted(filtered.items())
            ],
        })
    else:
        return fmt_err(f"Unknown action: {action}. Use lock|unlock|status|list|my.")

    return fmt_ok({"action": action, "path": path, **result})


def plan_notify_tool(args: dict, **kwargs) -> str:
    """Send notifications to other sessions or manage own notifications.

    Parameters:
    - action (str, required): 'send', 'check', 'list', or 'clear'
    - to (str, optional): Target session ID (required for 'send')
    - message (str, optional): Message text (required for 'send')
    - kind (str, optional): 'info', 'warning', 'alert' (default: 'info')
    """
    action = args.get("action", "")
    to = args.get("to", "")
    message = args.get("message", "")
    kind = args.get("kind", "info")
    session_id = args.get("session_id") or plan_core.get_session_id()

    if not action:
        return fmt_err("action is required (send|check|list|clear)")

    if action == "send":
        if not to:
            return fmt_err("'to' (target session) is required for send")
        if not message:
            return fmt_err("'message' is required for send")
        result = coord_state.send_notification(session_id, to, message, kind)
        return fmt_ok({"action": "sent", "to": to, "notification": result})

    elif action == "check":
        pending = coord_state.get_notifications(session_id)
        return fmt_ok({
            "action": "check",
            "count": len(pending),
            "notifications": pending,
        })

    elif action == "list":
        all_notifs = coord_state._atomic_read(coord_state.NOTIFICATIONS_FILE)
        mine = all_notifs.get(session_id, [])
        return fmt_ok({
            "action": "list",
            "count": len(mine),
            "notifications": mine,
        })

    elif action == "clear":
        coord_state.clear_notifications(session_id)
        return fmt_ok({"action": "clear", "status": "cleared"})

    else:
        return fmt_err(f"Unknown action: {action}. Use send|check|list|clear.")


def plan_decompose_tool(args: dict, **kwargs) -> str:
    """Manage hierarchical task decomposition (compound tasks with sub-tasks).

    Subcommands:
    - expand task_id=X: Expand compound task into sub-tasks
    - collapse task_id=X: Collapse sub-tasks back to compound
    - status task_id=X: Show sub-task status breakdown
    - create name=X subtasks=Y: Create a compound task

    Parameters:
    - action (str, required): 'expand', 'collapse', 'status', or 'create'
    - task_id (str, optional): Task ID for expand/collapse/status
    - name (str, optional): Compound task name for create
    - subtasks (list, optional): Sub-task definitions for create
    """
    from ..plan_decompose import collapse_task, create_compound_task, expand_task, get_subtask_status
    action = args.get("action", "")
    if not action:
        return fmt_err("action is required (expand, collapse, status, create)")

    if action == "expand":
        task_id = args.get("task_id", "")
        if not task_id:
            return fmt_err("task_id is required for expand")
        result = expand_task(task_id)
        return fmt_ok(result)
    elif action == "collapse":
        task_id = args.get("task_id", "")
        if not task_id:
            return fmt_err("task_id is required for collapse")
        result = collapse_task(task_id)
        return fmt_ok(result)
    elif action == "status":
        task_id = args.get("task_id", "")
        if not task_id:
            return fmt_err("task_id is required for status")
        result = get_subtask_status(task_id)
        return fmt_ok(result)
    elif action == "create":
        name = args.get("name", "")
        subtasks = args.get("subtasks", [])
        if not name or not subtasks:
            return fmt_err("name and subtasks are required for create")
        task_id = args.get("task_id", "")
        result = create_compound_task(name, subtasks, task_id)
        return fmt_ok(result)
    elif action == "delegate":
        task_id = args.get("task_id", "")
        if not task_id:
            return fmt_err("task_id is required for delegate")
        # Prepare delegation prompt for a task
        plan = plan_core._get_active_plan()
        if not plan:
            return fmt_err("No active plan.")
        task = plan["tasks"].get(task_id)
        if not task:
            return fmt_err(f"Task '{task_id}' not found.")
        from ..plan_decompose import prepare_delegation
        result = prepare_delegation(task_id)
        return fmt_ok(result)
    return fmt_err(f"Unknown action '{action}'")


def plan_simulate_tool(args: dict, **kwargs) -> str:
    """Simulate a plan to find critical path and parallelization opportunities.

    Parameters:
    - plan_id (str, optional): Plan ID to simulate (defaults to active plan).
    """
    from ..plan_suggest import simulate_plan
    plan_id = args.get("plan_id", "")
    plan = None
    if plan_id:
        plan = plan_core._load_plan(plan_id)
        if not plan:
            return fmt_err(f"Plan '{plan_id}' not found.")
    else:
        plan = plan_core._get_active_plan()
        if not plan:
            return fmt_err("No active plan.")
    result = simulate_plan(plan)
    return fmt_ok(result)


def plan_sync_tool(args: dict, **kwargs) -> str:
    """Sync plans with external systems.

    Subcommands:
    - github: Sync plan tasks to GitHub Issues
    - export: Export plan as Markdown
    - import: Import plan from Markdown

    Parameters:
    - action (str, required): 'github', 'export', or 'import'
    - plan_id (str, optional): Plan ID (defaults to active plan)
    - repo (str, optional): GitHub repo (owner/repo, for github action)
    - markdown (str, optional): Markdown content (for import action)
    """
    from ..plan_sync import export_to_markdown, import_from_markdown, sync_to_github
    action = args.get("action", "")
    if not action:
        return fmt_err("action is required (github, export, import)")

    # Load plan
    plan_id = args.get("plan_id", "")
    plan = None
    if plan_id:
        plan = plan_core._load_plan(plan_id)
        if not plan:
            return fmt_err(f"Plan '{plan_id}' not found.")
    else:
        plan = plan_core._get_active_plan()

    if action == "github":
        if not plan:
            return fmt_err("No plan to sync (specify plan_id or have an active plan)")
        repo = args.get("repo", "")
        result = sync_to_github(plan, repo)
        return fmt_ok(result)

    elif action == "export":
        if not plan:
            return fmt_err("No plan to export")
        markdown = export_to_markdown(plan)
        return fmt_ok({"format": "markdown", "plan_id": plan.get("plan_id"), "content": markdown,
                       "lines": len(markdown.split("\n"))})

    elif action == "import":
        markdown = args.get("markdown", "")
        if not markdown:
            return fmt_err("markdown content is required for import")
        result = import_from_markdown(markdown)
        if not result:
            return fmt_err("Could not parse plan from markdown")
        return fmt_ok({"status": "parsed", "plan_id": result.get("plan_id"),
                       "goal": result.get("goal"), "task_count": len(result.get("tasks", {}))})

    return fmt_err(f"Unknown action '{action}'")


def plan_time_tool(args: dict, **kwargs) -> str:
    """Track time for tasks (start/stop/status/history).

    Parameters:
    - action (str, required): 'start', 'stop', 'status', or 'history'
    - task_id (str, optional): Task ID
    - plan_id (str, optional): Plan ID
    """
    from ..plan_suggest import time_track
    action = args.get("action", "")
    if not action:
        return fmt_err("action is required (start, stop, status, history)")
    task_id = args.get("task_id", "")
    plan_id = args.get("plan_id", "")
    result = time_track(action, task_id, plan_id)
    return fmt_ok(result)


def plan_coord_cleanup_tool(args: dict, **kwargs) -> str:
    """Clean up stale sessions and locks from shared coordination state.

    Parameters:
    - session_max_age (int, optional): Session max age in minutes (default: 60)
    - lock_max_age (int, optional): Lock max age in minutes (default: 120)
    - dry_run (bool, optional): If true, only report what would be removed (default: false)
    """
    session_max_age = args.get("session_max_age", 60)
    lock_max_age = args.get("lock_max_age", 120)
    dry_run = args.get("dry_run", False)

    if dry_run:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        stale_sessions = 0
        for s in coord_state.get_sessions().values():
            last = s.get("last_seen", s.get("registered", ""))
            try:
                age = (now - datetime.fromisoformat(last)).total_seconds() / 60
                if age > session_max_age:
                    stale_sessions += 1
            except (ValueError, TypeError):
                stale_sessions += 1
        stale_locks = 0
        for lock in coord_state.get_locks().values():
            since = lock.get("since", "")
            try:
                age = (now - datetime.fromisoformat(since)).total_seconds() / 60
                if age > lock_max_age:
                    stale_locks += 1
            except (ValueError, TypeError):
                stale_locks += 1
        return fmt_ok({
            "action": "dry_run",
            "stale_sessions": stale_sessions,
            "stale_locks": stale_locks,
            "session_max_age": session_max_age,
            "lock_max_age": lock_max_age,
        })

    removed_sessions = coord_state.cleanup_stale_sessions(session_max_age)
    removed_locks = coord_state.cleanup_stale_locks(lock_max_age)
    return fmt_ok({
        "action": "cleanup",
        "removed_sessions": removed_sessions,
        "removed_locks": removed_locks,
        "session_max_age": session_max_age,
        "lock_max_age": lock_max_age,
    })
