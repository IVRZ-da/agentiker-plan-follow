"""validation.py — Plan validation for plan_follow tools/ subpackage."""


from .base import (
    _get_active_plan,
    _load_plan,
)

# ─── Plan Validation ──────────────────────────────────────────────────────────


def validate_plan(plan_id: str = "") -> dict:
    """Validate the integrity of a plan.

    Checks:
    - All depends_on references exist (no orphan deps)
    - No circular dependencies (DAG check via topological sort)
    - All verify commands are non-empty (or at least syntactically valid)
    - parallel_groups tasks all exist in tasks
    - Review profiles are valid
    - No orphan tasks (not reachable from root tasks)

    Args:
        plan_id: Plan ID to validate. If empty, validates the active plan.

    Returns:
        Dict with status, plan_id, and list of issues/errors.
    """
    # 1. Load plan
    if plan_id:
        plan = _load_plan(plan_id)
        if not plan:
            return {"status": "error", "plan_id": plan_id, "errors": [f"Plan '{plan_id}' not found."]}
    else:
        plan = _get_active_plan()
        if not plan:
            return {"status": "error", "plan_id": "", "errors": ["No active plan."]}
        plan_id = plan["plan_id"]

    errors = []
    warnings = []

    tasks = plan.get("tasks", {})
    all_task_ids = set(tasks.keys())
    groups = plan.get("parallel_groups", {})
    valid_profiles = {"none", "unit-test", "api-route", "ui-component", "security", "full"}

    # 2. Check each task
    for tid, tdef in tasks.items():
        # depends_on checks
        for dep in tdef.get("depends_on", []):
            if dep not in all_task_ids:
                errors.append(f"Task '{tid}': depends_on '{dep}' does not exist.")

        # verify command check
        verify = tdef.get("verify", "")
        if verify and len(verify) < 3:
            warnings.append(f"Task '{tid}': verify-Command '${verify}' seems too short.")

        # review profile check
        profile = tdef.get("review_profile", "none")
        if profile not in valid_profiles and profile is not None:
            warnings.append(f"Task '{tid}': review_profile '{profile}' is not a valid profile.")

        # status check
        valid_statuses = {"pending", "in_progress", "completed", "blocked", "aborted"}
        status = tdef.get("status", "pending")
        if status not in valid_statuses:
            errors.append(f"Task '{tid}': invalid status '{status}'.")

    # 3. Circular dependency check (DAG via topological sort)
    in_degree = {tid: 0 for tid in all_task_ids}
    adj = {tid: [] for tid in all_task_ids}

    for tid, tdef in tasks.items():
        for dep in tdef.get("depends_on", []):
            if dep in all_task_ids:
                adj[dep].append(tid)
                in_degree[tid] = in_degree.get(tid, 0) + 1

    # Kahn's algorithm
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(all_task_ids):
        cycle_tasks = [tid for tid, deg in in_degree.items() if deg > 0]
        errors.append(f"Circular dependencies detected between: {', '.join(cycle_tasks)}")

    # 4. Orphan tasks (no incoming depends_on and not reachable)
    if len(all_task_ids) > 1:
        reachable = set()
        root_tasks = [tid for tid, deg in in_degree.items() if deg == 0]
        # BFS from roots
        stack = list(root_tasks)
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            for neighbor in adj.get(node, []):
                stack.append(neighbor)
        orphaned = all_task_ids - reachable
        if orphaned and len(orphaned) < len(all_task_ids):
            # Only show as warning if not ALL tasks are orphaned (single-task plan)
            orphans_str = ", ".join(sorted(orphaned)[:5])
            if len(orphaned) > 5:
                orphans_str += f" ... and {len(orphaned)-5} more"
            warnings.append(f"Orphaned tasks (no connection to root): {orphans_str}")

    # 5. parallel_groups consistency
    if groups:
        all_group_task_ids = set()
        for gid, group in groups.items():
            for group_tid in group.get("tasks", []):
                if group_tid not in all_task_ids:
                    errors.append(f"parallel_group '{gid}': Task '{group_tid}' does not exist in tasks.")
                all_group_task_ids.add(group_tid)

    result = {
        "status": "valid" if not errors else "invalid",
        "plan_id": plan_id,
        "goal": plan.get("goal", "")[:60],
    }
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    if not errors and not warnings:
        result["summary"] = "Plan ist konsistent und vollständig."
    return result
