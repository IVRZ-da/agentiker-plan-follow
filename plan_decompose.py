"""plan_decompose.py — Hierarchical Plan Decomposition (HTN-Style).

Ermöglicht Compound Tasks mit Sub-Tasks. Ein Compound-Task ist ein Task
der mehrere Sub-Tasks enthält. Der Status des Compound-Tasks wird aus
dem Status seiner Sub-Tasks aggregiert.

Usage:
    plan_decompose expand task_id   → Zeigt Sub-Tasks eines Compound-Tasks
    plan_decompose collapse task_id → Kollabiert Sub-Tasks zurück zum Parent
    plan_decompose status task_id   → Zeigt Sub-Task-Status
"""

from __future__ import annotations


from .tools.base import _get_active_plan, _save_plan


def expand_task(task_id: str) -> dict:
    """Expand a compound task into its sub-tasks.

    Makes sub-tasks visible in the plan's task list by promoting them
    to top-level tasks with proper depends_on.

    Args:
        task_id: The compound task ID to expand.

    Returns:
        Dict with status and promoted subtasks.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    subtasks = task.get("subtasks", [])
    if not subtasks:
        return {"status": "error", "message": f"Task '{task_id}' has no sub-tasks."}

    promoted = []
    for st in subtasks:
        stid = st.get("id", "")
        if not stid:
            continue
        # Promote sub-task to top-level task
        if stid not in plan["tasks"]:
            st_entry = {
                "id": stid,
                "name": st.get("name", stid),
                "status": "pending",
                "files": st.get("files", []),
                "verify": st.get("verify", ""),
                "review_profile": st.get("review_profile", task.get("review_profile", "none")),
                "review_result": None,
                "depends_on": [task_id] + st.get("depends_on", []),
                "_parent_task": task_id,
            }
            plan["tasks"][stid] = st_entry
            promoted.append(stid)

    # Update compound task status
    task["status"] = "in_progress"
    if task["subtasks_expanded"] is False:
        task["subtasks_expanded"] = True

    # If this was the current task and it has subtasks, move to first subtask
    if plan.get("current_task") == task_id and promoted:
        plan["current_task"] = promoted[0]
        plan["tasks"][promoted[0]]["status"] = "in_progress"

    _save_plan(plan)
    return {
        "status": "expanded",
        "task_id": task_id,
        "subtasks_promoted": len(promoted),
        "subtasks": subtasks,
        "current_task": plan.get("current_task"),
    }


def collapse_task(task_id: str) -> dict:
    """Collapse sub-tasks back into their parent compound task.

    Removes promoted sub-tasks from the plan's task list and updates
    the compound task's status based on sub-task completion.

    Args:
        task_id: The compound task ID to collapse.

    Returns:
        Dict with status.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    subtasks = task.get("subtasks", [])
    if not subtasks:
        return {"status": "error", "message": f"Task '{task_id}' has no sub-tasks."}

    # Calculate aggregate status
    all_completed = True
    any_in_progress = False
    any_aborted = False

    for st in subtasks:
        stid = st.get("id", "")
        if stid in plan["tasks"]:
            st_status = plan["tasks"][stid].get("status", "pending")
            if st_status != "completed":
                all_completed = False
            if st_status == "in_progress":
                any_in_progress = True
            if st_status == "aborted":
                any_aborted = True
            # Remove promoted sub-task
            del plan["tasks"][stid]

    # Set compound task status based on sub-tasks
    if all_completed:
        task["status"] = "completed"
    elif any_aborted:
        task["status"] = "aborted"
    elif any_in_progress:
        task["status"] = "in_progress"
    else:
        task["status"] = "pending"

    task["subtasks_expanded"] = False
    plan["current_task"] = task_id

    _save_plan(plan)
    return {
        "status": "collapsed",
        "task_id": task_id,
        "aggregate_status": task["status"],
        "subtasks_collapsed": len(subtasks),
    }


def get_subtask_status(task_id: str) -> dict:
    """Get the status of all sub-tasks for a compound task.

    Args:
        task_id: The compound task ID.

    Returns:
        Dict with subtask status breakdown.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    subtasks = task.get("subtasks", [])
    if not subtasks:
        return {"status": "error", "message": f"Task '{task_id}' has no sub-tasks."}

    results = []
    for st in subtasks:
        stid = st.get("id", "")
        if stid in plan["tasks"]:
            st_data = plan["tasks"][stid]
            results.append({
                "id": stid,
                "name": st_data.get("name", ""),
                "status": st_data.get("status", "pending"),
                "files": st_data.get("files", []),
            })
        else:
            results.append({
                "id": stid,
                "name": st.get("name", ""),
                "status": "not_expanded",
            })

    return {
        "status": "ok",
        "task_id": task_id,
        "task_name": task.get("name", ""),
        "subtasks": results,
        "expanded": task.get("subtasks_expanded", False),
        "count": len(subtasks),
        "completed": sum(1 for r in results if r["status"] == "completed"),
    }


def create_compound_task(name: str, subtasks: list[dict], task_id: str = "") -> dict:
    """Create a compound task with sub-tasks in the active plan.

    Args:
        name: Compound task name.
        subtasks: List of sub-task dicts (id, name, files, verify, depends_on required).
        task_id: Optional task ID (auto-generated if empty).

    Returns:
        Dict with created task info.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    tid = task_id or f"ct{len(plan['tasks']) + 1}"
    if tid in plan["tasks"]:
        return {"status": "error", "message": f"Task '{tid}' already exists."}

    compound_task = {
        "id": tid,
        "name": name,
        "status": "pending",
        "files": [],
        "verify": "echo '✅ Compound task completed'",
        "review_profile": "none",
        "review_result": None,
        "depends_on": [],
        "subtasks": subtasks,
        "subtasks_expanded": False,
        "_is_compound": True,
    }
    plan["tasks"][tid] = compound_task

    # First sub-task should depend on this task's dependencies
    if subtasks:
        first_st = subtasks[0]
        first_st["depends_on"] = first_st.get("depends_on", [])
        if plan.get("current_task"):
            first_st["depends_on"].insert(0, plan["current_task"])

    _save_plan(plan)
    return {
        "status": "created",
        "task_id": tid,
        "name": name,
        "subtasks": len(subtasks),
    }


def prepare_delegation(task_id: str) -> dict:
    """Prepare a task for delegation to a subagent.

    Returns a structured prompt that can be used with delegate_task
    to have a subagent execute the task autonomously.

    Args:
        task_id: Task ID to delegate.

    Returns:
        Dict with delegation prompt and task context.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    plan_id = plan.get("plan_id", "unknown")
    plan_goal = plan.get("goal", "")
    task_name = task.get("name", task_id)
    task_files = task.get("files", [])
    task_verify = task.get("verify", "")
    task_profile = task.get("review_profile", "none")

    prompt_lines = [
        f"## Delegated Task: {task_name} (ID: {task_id})",
        "",
        f"**Plan:** {plan_goal}",
        f"**Plan ID:** {plan_id}",
        "",
        "### Task Files",
    ]

    if task_files:
        for f in task_files:
            prompt_lines.append(f"- `{f}`")
    else:
        prompt_lines.append("(no specific files declared — check the plan goal)")

    prompt_lines.extend([
        "",
        "### Verify Command",
        "```bash",
        f"{task_verify}",
        "```",
        "",
        "### Review Profile",
        task_profile,
        "",
        "### Instructions",
        "1. Implement the necessary changes",
        "2. Run the verify command to confirm success",
        "3. Report back with a summary of what was done",
    ])

    return {
        "status": "ready",
        "task_id": task_id,
        "task_name": task_name,
        "plan_id": plan_id,
        "delegation_prompt": "\n".join(prompt_lines),
        "toolsets": ["terminal", "file"],
        "suggestion": f"Nutze delegate_task(goal='{task_name}', context=delegation_prompt)",
    }
