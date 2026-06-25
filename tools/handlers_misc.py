"""handlers_misc."""
from __future__ import annotations

import logging

from .. import plan_core
from .._fmt import fmt_err, fmt_info, fmt_ok

logger = logging.getLogger("plan_follow")
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


def plan_history_tool(args: dict, **kwargs) -> str:
    """Show git-based plan history or hint to activate Git.

    Parameters:
    - plan_id (str, optional): Plan ID. If empty, shows current plan's history.
    - lines (int, optional): Number of log lines to show (default: 10)
    """

    plan_id = args.get("plan_id", "")
    lines = args.get("lines", 10)

    # Get plan_id from active plan if not specified
    if not plan_id:
        current = plan_core.get_current_task()
        if not current:
            return fmt_err("No active plan and no plan_id provided.")
        plan_id = current["plan_id"]

    git_dir = plan_core.PLANS_DIR / ".git"
    if not git_dir.exists():
        return fmt_info(
            "Keine Git-Versionierung aktiv.\n"
            "  Verwende plan_git_init() um Git zu aktivieren.\n"
            "  Oder: cd ~/.hermes/plans && git init && git add . && git commit -m 'initial'\n"
            "  Aktuell ist nur der letzte Plan-Stand gespeichert."
        )

    import subprocess
    try:
        # Get git log for this plan
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{lines}", "--", f"{plan_id}.json"],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=10,
        )
        if not result.stdout.strip():
            return fmt_info(f"Keine Git-History für Plan '{plan_id[:50]}'.")

        # Add stats per commit
        detailed = subprocess.run(
            ["git", "log", "--oneline", f"-{lines}", "--stat", "--", f"{plan_id}.json"],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=10,
        )

        return fmt_ok({
            "status": "active",
            "plan_id": plan_id,
            "history": result.stdout.strip(),
            "details": detailed.stdout.strip(),
        })
    except Exception as e:
        return fmt_err(f"Git history failed: {e}")


def plan_lock_tool(args: dict, **kwargs) -> str:
    """Manage resource locks for cross-session coordination.

    Parameters:
    - action (str, required): 'lock', 'unlock', 'status', or 'list'
    - path (str, required for lock/unlock/status): File or directory path
    - session_id (str, optional): Session ID (default: auto-detected)

    'list' shows all locks grouped by session (no path needed).
    """
    from .. import coord_state

    action = args.get("action", "")
    path = args.get("path", "")
    session_id = args.get("session_id") or plan_core.get_session_id()

    if not action:
        return fmt_err("action is required (lock|unlock|status)")
    if not path:
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
    elif action == "list":
        all_locks = coord_state.get_locks()
        by_session = {}
        for lp, lock in all_locks.items():
            sid = lock.get("session_id", "unknown")
            by_session.setdefault(sid, []).append(lp)
        result = {
            "status": "ok",
            "total_locks": len(all_locks),
            "by_session": {sid: {"count": len(paths), "paths": paths[:10]}
                          for sid, paths in by_session.items()},
        }
    else:
        return fmt_err(f"Unknown action: {action}. Use lock|unlock|status.")

    return fmt_ok({"action": action, "path": path, **result})


def plan_notify_tool(args: dict, **kwargs) -> str:
    """Send or manage notifications between sessions.

    Parameters:
    - action (str, required): 'send', 'check', 'list', 'clear', or 'reply'
    - to (str, optional): Target session ID (required for 'send' and 'reply')
    - message (str, optional): Message text (required for 'send' and 'reply')
    - kind (str, optional): 'info', 'warning', 'alert' (default: 'info')
    - session_id (str, optional): Source session ID (default: auto-detected)
    """
    from .. import coord_state

    action = args.get("action", "")
    to = args.get("to", "")
    message = args.get("message", "")
    kind = args.get("kind", "info")
    session_id = args.get("session_id") or plan_core.get_session_id()

    if not action:
        return fmt_err("action is required (send|check|list|clear|reply)")

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
        sessions = coord_state.get_sessions()
        notif_all = {}
        for sid in sessions:
            n = coord_state.get_notifications(sid, mark_read=False)
            if n:
                notif_all[sid] = n
        return fmt_ok({
            "action": "list",
            "pending_by_session": notif_all,
        })

    elif action == "clear":
        coord_state.clear_notifications(session_id)
        return fmt_ok({"action": "cleared", "session_id": session_id})

    elif action == "reply":
        if not to:
            return fmt_err("'to' (target session) is required for reply")
        if not message:
            return fmt_err("'message' is required for reply")
        # Reply to the last notification from 'to'
        result = coord_state.send_notification(session_id, to, message, "reply")
        return fmt_ok({"action": "replied", "to": to, "notification": result})

    else:
        return fmt_err(f"Unknown action: {action}. Use send|check|list|clear|reply.")


# ─── Git-Integration Tools (OPTIONAL) ────────────────────────────────────────


def plan_session_tool(args: dict, **kwargs) -> str:
    """Show active sessions, their plans, and lock status.

    Reads from coord_state.py — no Git required.
    If Git is active, additionally shows branch info.

    Parameters:
    - include_history (bool, optional): Show git-based plan history (default: false)
    """
    from .. import coord_state

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


def plan_suggest_tool(args: dict, **kwargs) -> str:
    """Suggest a plan decomposition for a goal by analyzing the project.

    Parameters:
    - goal (str, required): The goal to generate suggestions for.
    - project_root (str, optional): Project root path (auto-detected if empty).

    Returns suggested template name, task list, and project info.
    """
    from ..plan_suggest import suggest_plan
    goal = args.get("goal", "")
    if not goal:
        return fmt_err("goal is required for plan suggestions")
    project_root = args.get("project_root", "")
    result = suggest_plan(goal, project_root)
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
