"""handlers_review."""
from __future__ import annotations

import logging

from .. import plan_core
from .._fmt import fmt_err, fmt_ok, fmt_table

logger = logging.getLogger("plan_follow")
def plan_auto_review_tool(args: dict, **kwargs) -> str:
    """Prepare a complete review in one call — files, coverage, prompt.

    Bundles the entire review preparation:
    1. Reads task files
    2. Measures test coverage (if profile has coverage checks)
    3. Builds the delegate_task prompt
    4. Returns everything ready for use

    Parameters:
    - task_id (str, required): The task ID to review
    - profile (str, optional): Review profile (auto|none|unit-test|api-route|ui-component|security|full). Default: auto
    - depth (str, optional): Review depth (quick|normal|deep). Default: normal

    Returns:
    - status: 'ready' → run delegate_task with the prompt
    - status: 'coverage_failed' → coverage too low, write more tests first
    - status: 'skipped' → no review needed
    - status: 'error' → something went wrong
    """
    task_id = args.get("task_id", "")
    profile = args.get("profile", "auto")
    depth = args.get("depth", "normal")

    if not task_id:
        return fmt_err("task_id is required")

    current = plan_core.get_current_task()
    if not current:
        return fmt_err("No active plan.")

    if current["task_id"] != task_id:
        return fmt_err(f"Task '{task_id}' is not the current task. Aktuell: {current['task_id']}")

    # Get full plan for coverage path resolution
    plan = plan_core._get_active_plan()

    # Use auto_review() from plan_review
    from ..plan_review import auto_review
    result = auto_review(current, plan, profile, depth)

    return fmt_ok(result)


def plan_review_profiles_tool(args: dict, **kwargs) -> str:
    """Show all available review profiles with their descriptions and checks."""
    from ..review_profiles import PROFILES
    profiles = [
        {"name": name, "description": p["description"], "checks": p["checks"]}
        for name, p in PROFILES.items()
    ]
    return fmt_table(profiles, title="Review Profiles")


def plan_review_save_result_tool(args: dict, **kwargs) -> str:
    """Save a review result for a task. Persists the result so plan_complete can pass the review gate.

    Parameters:
    - task_id (str, required): The task ID
    - status (str, required): 'passed' or 'failed'
    - issues (list, optional): List of issue dicts
    - summary (str, optional): Review summary
    """
    task_id = args.get("task_id", "")
    status = args.get("status", "passed")
    issues = args.get("issues", [])
    summary = args.get("summary", "")
    if not task_id:
        return fmt_err("task_id is required")
    ok = plan_core.save_review_result(task_id, {
        "status": status,
        "issues": issues,
        "summary": summary,
    })
    if not ok:
        return fmt_err(f"Task '{task_id}' not found or no active plan.")
    return fmt_ok({"status": "saved", "task_id": task_id, "review_status": status})


def plan_review_tool(args: dict, **kwargs) -> str:
    """Review a task's files using an independent reviewer subagent.

    Prepares review data based on the task's review_profile and current state.
    The Agent should use build_review_prompt() to get the prompt for delegate_task.
    """
    task_id = args.get("task_id", "")
    profile = args.get("profile", "auto")
    depth = args.get("depth", "normal")

    if not task_id:
        return fmt_err("task_id is required")

    from ..plan_review import dispatch_review

    current = plan_core.get_current_task()
    if not current:
        return fmt_err("No active plan.")

    if current["task_id"] != task_id:
        return fmt_err(f"Task '{task_id}' is not the current task. Aktuell: {current['task_id']}")

    # Profile resolution
    profile_name = profile
    if profile_name == "auto":
        profile_name = current.get("review_profile", "none")

    # Dispatch
    result = dispatch_review(profile_name, current, depth)
    if result.get("status") == "ready":
        return fmt_ok({
            "status": "ready",
            "task_id": task_id,
            "profile": profile_name,
            "message": "Review bereit → delegate_task ausführen.",
            "checks": result.get("checks", []),
            "checks_count": len(result.get("checks", [])),
            "description": result.get("description", ""),
            "suggestion": (
                "Nutze plan_review_profiles() für eine Übersicht aller Profile. "
                "Nach dem Review: save_review_result() aufrufen."
            ),
        })

    return fmt_ok(result)
