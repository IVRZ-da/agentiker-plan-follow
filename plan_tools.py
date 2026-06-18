"""
plan_tools.py — Tool implementations for plan-follow plugin.

Each function is registered as a Hermes tool via PluginContext.register_tool().
"""

import json
import logging

from . import plan_core

logger = logging.getLogger("plan_follow")


def plan_create_tool(args: dict, **kwargs) -> str:
    """Create a new structured plan with enforceable tasks."""
    goal = args.get("goal", "")
    tasks = args.get("tasks", [])
    repo = args.get("repo", "")
    if not goal:
        return json.dumps({"error": "goal ist erforderlich"})
    if not tasks:
        return json.dumps({"error": "tasks ist erforderlich (min 1 Task)"})

    for t in tasks:
        if "id" not in t or "name" not in t:
            return json.dumps({"error": "Jeder Task braucht 'id' und 'name'"})

    plan_id = plan_core.create_plan(goal, tasks, repo)
    status = plan_core.get_plan_status()
    return json.dumps({
        "status": "created",
        "plan_id": plan_id,
        "current_task": status["current_task"] if status else None,
    }, ensure_ascii=False)


def plan_current_tool(args: dict, **kwargs) -> str:
    """Show the current task. Only ONE task is visible at a time."""
    current = plan_core.get_current_task()
    if not current:
        return json.dumps({"status": "no_active_plan", "message": "Kein aktiver Plan. Nutze plan_create() um einen zu starten."})
    return json.dumps(current, ensure_ascii=False)


def plan_complete_tool(args: dict, **kwargs) -> str:
    """Complete the current task, verify it, advance to next."""
    task_id = args.get("task_id", "")
    if not task_id:
        return json.dumps({"error": "task_id ist erforderlich"})

    # Run verification first
    current = plan_core.get_current_task()
    if not current:
        return json.dumps({"error": "Kein aktiver Plan."})

    if current["task_id"] != task_id:
        return json.dumps({"error": f"Task '{task_id}' ist nicht der aktuelle Task. Aktuell: {current['task_id']}"})

    # Verify: check drift
    drift = plan_core.check_drift()
    verify_result = {}
    if drift:
        verify_result["unplanned_files"] = drift
        verify_result["drift_warning"] = "Ungeplante Änderungen gefunden. Entweder plan_update() oder revert."

    result = plan_core.complete_task(task_id)
    if result.get("status") == "completed":
        verify_result["files_changed"] = drift or []
        result["verified"] = verify_result

    return json.dumps(result, ensure_ascii=False)


def plan_verify_tool(args: dict, **kwargs) -> str:
    """Check for drift: unplanned changes compared to the current plan."""
    current = plan_core.get_current_task()
    if not current:
        return json.dumps({"status": "no_active_plan", "message": "Kein aktiver Plan."})

    drift = plan_core.check_drift()
    if not drift:
        return json.dumps({
            "status": "clean",
            "plan_id": current["plan_id"],
            "task_id": current["task_id"],
            "message": "✅ Keine ungeplanten Änderungen.",
        })

    return json.dumps({
        "status": "drift_detected",
        "plan_id": current["plan_id"],
        "task_id": current["task_id"],
        "unplanned_files": drift,
        "suggestion": "Entweder plan_update(task_id, {files: [...]}) um Dateien zum Task hinzuzufügen, oder Änderungen reverten.",
    }, ensure_ascii=False)


def plan_status_tool(args: dict, **kwargs) -> str:
    """Show all tasks with their status."""
    status = plan_core.get_plan_status()
    if not status:
        return json.dumps({"status": "no_active_plan", "message": "Kein aktiver Plan."})
    return json.dumps(status, ensure_ascii=False)


def plan_update_tool(args: dict, **kwargs) -> str:
    """Update a task's properties (files, verify, depends_on, name)."""
    task_id = args.get("task_id", "")
    changes = args.get("changes", {})
    if not task_id:
        return json.dumps({"error": "task_id ist erforderlich"})
    if not changes:
        return json.dumps({"error": "changes ist erforderlich (mindestens ein Feld)"})

    result = plan_core.update_task(task_id, changes)
    if not result:
        return json.dumps({"error": f"Task '{task_id}' nicht gefunden oder kein aktiver Plan."})

    return json.dumps({"status": "updated", "task_id": task_id, "task": result}, ensure_ascii=False)
