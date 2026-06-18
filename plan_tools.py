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
    template_name = args.get("template", "")
    parallel_groups = args.get("parallel_groups")
    template_params = args.get("params", {})

    # Template expansion
    if template_name and not tasks:
        from .plan_templates import expand_template
        expanded = expand_template(template_name, goal, template_params)
        if "error" in expanded:
            return json.dumps(expanded, ensure_ascii=False)
        tasks = expanded["tasks"]
        # Use goal from template description if no goal provided
        if not goal and expanded.get("description"):
            goal = expanded["description"]

    if not goal:
        return json.dumps({"error": "goal is required"})
    if not tasks:
        return json.dumps({"error": "tasks is required (at least 1 task)"})

    for t in tasks:
        if "id" not in t or "name" not in t:
            return json.dumps({"error": "Each task needs 'id' and 'name'"})

    plan_id = plan_core.create_plan(goal, tasks, repo, parallel_groups)
    status = plan_core.get_plan_status()
    response = {
        "status": "created",
        "plan_id": plan_id,
        "current_task": status["current_task"] if status else None,
    }
    if template_name:
        response["template"] = template_name
    return json.dumps(response, ensure_ascii=False)


def plan_current_tool(args: dict, **kwargs) -> str:
    """Show the current task. Only ONE task is visible at a time."""
    current = plan_core.get_current_task()
    if not current:
        return json.dumps({"status": "no_active_plan", "message": "No active plan. Use plan_create() to start one."})
    return json.dumps(current, ensure_ascii=False)


def plan_complete_tool(args: dict, **kwargs) -> str:
    """Complete the current task, verify it, advance to next."""
    task_id = args.get("task_id", "")
    skip_review = args.get("skip_review", False)
    auto_verify = args.get("auto_verify", False)
    auto_commit_enabled = args.get("auto_commit", False)
    if not task_id:
        return json.dumps({"error": "task_id is required"})

    # Run verification first
    current = plan_core.get_current_task()
    if not current:
        return json.dumps({"error": "No active plan."})

    if current["task_id"] != task_id:
        return json.dumps({"error": f"Task '{task_id}' is not the current task. Aktuell: {current['task_id']}"})

    # REVIEW GATE
    if not skip_review and not plan_core.is_review_passed(current):
        review_state = plan_core.get_task_review_state(current)
        return json.dumps({
            "error": "Review not passed — task cannot be completed.",
            "task_id": task_id,
            "review_required": current.get("review_profile", "none") != "none",
            "review_state": review_state,
            "suggestion": (
                "Führe plan_review(task_id) aus um den Review zu starten. "
                "Nach erfolgreichem Review: save_review_result() aufrufen. "
                "Mit skip_review=true in plan_complete() überspringen (nicht empfohlen)."
            ),
        }, ensure_ascii=False)

    # Auto-Verify: execute the verify command
    if auto_verify:
        verify_cmd = current.get("verify", "")
        verify_result = plan_core.auto_verify_task(verify_cmd)
        if verify_result["status"] == "failed":
            return json.dumps({
                "error": "Auto-verify failed — task not completed.",
                "task_id": task_id,
                "verify_result": verify_result,
                "suggestion": "Fix das Problem und versuche plan_complete(task_id, auto_verify=true) erneut.",
            }, ensure_ascii=False)
    else:
        verify_result = {"status": "skipped", "message": "auto_verify nicht aktiviert"}

    # Drift check
    drift = plan_core.check_drift()
    drift_info = {}
    if drift:
        drift_info["unplanned_files"] = drift
        drift_info["drift_warning"] = "Ungeplante Änderungen gefunden. Entweder plan_update() oder revert."

    # Complete the task
    result = plan_core.complete_task(task_id)

    if result.get("status") == "completed":
        result["auto_verify"] = verify_result
        result["drift"] = drift_info

        # Auto-Commit after completion
        if auto_commit_enabled:
            plan = plan_core._get_active_plan()
            repo = plan.get("repo", "") if plan else ""
            commit_result = plan_core.auto_commit(task_id, current.get("files", []), repo)
            result["auto_commit"] = commit_result

    return json.dumps(result, ensure_ascii=False)


def plan_verify_tool(args: dict, **kwargs) -> str:
    """Check for drift: unplanned changes compared to the current plan."""
    current = plan_core.get_current_task()
    if not current:
        return json.dumps({"status": "no_active_plan", "message": "No active plan."})

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
        return json.dumps({"status": "no_active_plan", "message": "No active plan."})
    return json.dumps(status, ensure_ascii=False)


def plan_update_tool(args: dict, **kwargs) -> str:
    """Update a task's properties (files, verify, depends_on, name)."""
    task_id = args.get("task_id", "")
    changes = args.get("changes", {})
    if not task_id:
        return json.dumps({"error": "task_id is required"})
    if not changes:
        return json.dumps({"error": "changes is required (at least one field)"})

    result = plan_core.update_task(task_id, changes)
    if not result:
        return json.dumps({"error": f"Task '{task_id}' not found or no active plan."})

    return json.dumps({"status": "updated", "task_id": task_id, "task": result}, ensure_ascii=False)


def plan_review_tool(args: dict, **kwargs) -> str:
    """Review a task's files using an independent reviewer subagent.

    Prepares review data based on the task's review_profile and current state.
    The Agent should use build_review_prompt() to get the prompt for delegate_task.
    """
    task_id = args.get("task_id", "")
    profile = args.get("profile", "auto")
    depth = args.get("depth", "normal")

    if not task_id:
        return json.dumps({"error": "task_id is required"})

    from .plan_review import dispatch_review

    current = plan_core.get_current_task()
    if not current:
        return json.dumps({"error": "No active plan."})

    if current["task_id"] != task_id:
        return json.dumps({
            "error": f"Task '{task_id}' is not the current task. Aktuell: {current['task_id']}"
        })

    # Profile resolution
    profile_name = profile
    if profile_name == "auto":
        profile_name = current.get("review_profile", "none")

    # Dispatch
    result = dispatch_review(profile_name, current, depth)
    if result.get("status") == "ready":
        return json.dumps({
            "status": "ready",
            "task_id": task_id,
            "profile": profile_name,
            "message": "Review bereit. Führe delegate_task mit dem Prompt aus build_review_prompt() aus.",
            "checks": result.get("checks", []),
            "checks_count": len(result.get("checks", [])),
            "description": result.get("description", ""),
            "suggestion": (
                "Nutze plan_review_profiles() für eine Übersicht aller Profile. "
                "Nach dem Review: save_review_result() aufrufen."
            ),
        }, ensure_ascii=False)

    return json.dumps(result, ensure_ascii=False)


def plan_review_profiles_tool(args: dict, **kwargs) -> str:
    """Show all available review profiles with their descriptions and checks."""
    from .review_profiles import PROFILES
    profiles = [
        {"name": name, "description": p["description"], "checks": p["checks"]}
        for name, p in PROFILES.items()
    ]
    return json.dumps(profiles, ensure_ascii=False)


def plan_list_tool(args: dict, **kwargs) -> str:
    """List all plans (including completed/aborted), newest first."""
    include_archived = args.get("include_archived", False)
    plans = plan_core.list_plans(include_archived=include_archived)
    return json.dumps({
        "status": "ok",
        "count": len(plans),
        "plans": plans,
    }, ensure_ascii=False)


def plan_abort_tool(args: dict, **kwargs) -> str:
    """Abort the active plan or a specific task."""
    task_id = args.get("task_id", "")
    result = plan_core.abort_plan(task_id)
    return json.dumps(result, ensure_ascii=False)


def plan_delete_tool(args: dict, **kwargs) -> str:
    """Permanently delete a plan from disk."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return json.dumps({"status": "error", "message": "plan_id is required."})
    result = plan_core.delete_plan(plan_id)
    return json.dumps(result, ensure_ascii=False)


def plan_select_tool(args: dict, **kwargs) -> str:
    """Switch to a different saved plan as the active one."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return json.dumps({"status": "error", "message": "plan_id is required."})
    result = plan_core.select_plan(plan_id)
    return json.dumps(result, ensure_ascii=False)


def plan_validate_tool(args: dict, **kwargs) -> str:
    """Validate the integrity of a plan (deps, cycles, profiles, orphan tasks)."""
    plan_id = args.get("plan_id", "")
    result = plan_core.validate_plan(plan_id)
    return json.dumps(result, ensure_ascii=False)


def plan_duedate_tool(args: dict, **kwargs) -> str:
    """Set or view the due date for a task.

    Parameters:
    - task_id (str, optional): Task ID. If empty, shows current task's due date.
    - due (str, optional): ISO-8601 date string (e.g. '2026-06-25'). Omit to view.
      Pass empty string to clear the due date.
    """
    task_id = args.get("task_id", "")
    due = args.get("due")

    if due is not None:
        # Set/clear due date
        if not task_id:
            # If no task_id specified, use current task
            current = plan_core.get_current_task()
            if not current:
                return json.dumps({"status": "error", "message": "No active task and no task_id provided."})
            task_id = current["task_id"]
        result = plan_core.set_task_due(task_id, due)
        return json.dumps(result, ensure_ascii=False)
    else:
        info = plan_core.get_task_due_info(task_id)
        if not info:
            return json.dumps({"status": "ok", "task_id": task_id or "current", "due": None, "message": "No due date set."})
        return json.dumps({"status": "ok", **info}, ensure_ascii=False)


def plan_archive_tool(args: dict, **kwargs) -> str:
    """Move a plan to the archive directory."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return json.dumps({"status": "error", "message": "plan_id is required."})
    result = plan_core.archive_plan(plan_id)
    return json.dumps(result, ensure_ascii=False)


def plan_restore_tool(args: dict, **kwargs) -> str:
    """Restore a plan from the archive back to the plans directory."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return json.dumps({"status": "error", "message": "plan_id is required."})
    result = plan_core.restore_plan(plan_id)
    return json.dumps(result, ensure_ascii=False)
