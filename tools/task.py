"""task.py — Task CRUD operations for plan_follow tools/ subpackage."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from .. import plan_core, plan_peer_review
from .._fmt import fmt_err, fmt_ok
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
    _save_plan_state_to_honcho,
)
from .state import STATE
from .status import _format_progress

# ─── Plan CRUD ────────────────────────────────────────────────────────────────


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
        # Auto-create missing tasks referenced in parallel_groups
        all_group_ids: set[str] = set()
        for g in parallel_groups.values():
            all_group_ids.update(g.get("tasks", []))
        for tid in all_group_ids:
            if tid not in tasks_dict:
                tasks_dict[tid] = {
                    "id": tid,
                    "status": "pending",
                    "name": tid,
                    "files": [],
                    "verify": "",
                    "review_profile": "none",
                    "review_result": None,
                    "depends_on": [],
                }

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
        logger.debug("Honcho session registration failed (best-effort)")
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


def update_task(task_id: str, changes: dict, plan_id: str = "") -> Optional[dict]:
    """Update a task's properties (files, verify, depends_on, name, review_profile).

    Also supports updating plan-level properties (parallel_groups) by passing
    parallel_groups in changes — these are applied to the plan, not the task.

    If plan_id is provided, updates the specified plan instead of the active one.

    Returns the updated task dict if any keys were changed, or None if no
    supported keys matched (silent-ignore prevention).
    """
    if not isinstance(changes, dict):
        return None

    if plan_id:
        plan = _load_plan(plan_id)
        if not plan:
            return None
    else:
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


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD Handler Functions (moved from handlers_crud.py)
# ═══════════════════════════════════════════════════════════════════════════════


def plan_create_tool(args: dict, **kwargs) -> str:
    """Create a new structured plan with enforceable tasks."""
    goal = args.get("goal", "")
    repo = args.get("repo", "")
    plan_id_override = args.get("plan_id", "")
    template_name = args.get("template", "")
    template_params = args.get("params", {})
    parallel_groups = args.get("parallel_groups")

    if template_name:
        # Template expansion
        from ..plan_templates import expand_template
        expanded = expand_template(template_name, goal, template_params)
        if "error" in expanded:
            return fmt_ok(expanded)
        tasks = expanded["tasks"]
        # Use goal from template description if no goal provided
        if not goal and expanded.get("description"):
            goal = expanded["description"]
    else:
        # Direct tasks (for tests/expert use — template is preferred)
        tasks = args.get("tasks", [])
        if not tasks:
            return fmt_err(
                "template is required — kein Template = kein Plan.\n"
                "Available templates: deploy, bugfix, feature, refactoring, research, analysis, fix"
            )

    if not goal:
        return fmt_err("goal is required")
    if not tasks:
        return fmt_err("tasks is required (at least 1 task)")

    for t in tasks:
        if "id" not in t or "name" not in t:
            return fmt_err("Each task needs 'id' and 'name'")

    plan_id = plan_core.create_plan(goal, tasks, repo, parallel_groups, plan_id_override=plan_id_override)
    status = plan_core.get_plan_status()

    # ─── Auto Peer Review (immer aktiv — kein Feature-Toggle) ────────────
    # Nach plan_create() wird der Plan automatisch gegen die 8-Punkte-Checkliste
    # geprüft. Findings werden via apply_findings() eingearbeitet.
    # Wenn nach apply_findings noch CRITICAL-Findings übrig sind, wird der
    # Plan NICHT erstellt (blockierend).
    peer_review_findings = []
    try:
        plan = plan_core._get_active_plan()
        if plan:
            findings = plan_peer_review.run_peer_review(plan)
            if findings:
                peer_review_findings = findings
                # Apply automatic fixes (safe: verify commands, files, profiles)
                updated = plan_peer_review.apply_findings(plan, findings)

                # ─── Post-Apply-Validierung ────────────────────────────
                # Prüft ob nach apply_findings noch CRITICAL-Findings übrig sind.
                # Das passiert wenn z.B. verify-Commands weder leer noch echo
                # noch ein echter Testbefehl sind (kann nicht automatisch gefixt werden).
                # Solche Pläne werden blockiert — der Agent muss manuell fixen.
                remaining = plan_peer_review.run_peer_review(updated)
                remaining_critical = [f for f in remaining if f.get("severity") == "critical"]
                if remaining_critical:
                    logger.warning(
                        "Plan '%s' blocked: %d critical findings survived auto-fix.",
                        plan_id, len(remaining_critical),
                    )
                    return fmt_ok({
                        "error": "Plan could not be created — critical issues remain after auto-fix.",
                        "plan_id": plan_id,
                        "status": "blocked",
                        "original_findings": peer_review_findings,
                        "remaining_findings": remaining_critical,
                        "suggestion": (
                            "Fix die verbleibenden CRITICAL-Findings manuell "
                            "(z.B. verify-Commands setzen, Dateien deklarieren) "
                            "und dann plan_create() erneut aufrufen."
                        ),
                    })

                # Alle CRITICAL-Findings gefixt — Plan speichern
                plan_core._save_plan(updated)
    except Exception as e:
        logger.warning("Auto peer review failed (non-blocking): %s", e)

    # ─── TTS Flag: Plan Created ──────────────────────────────────────────
    try:
        plan = plan_core._get_active_plan()
        if plan:
            if "tts_flags" not in plan:
                plan["tts_flags"] = {}
            plan["tts_flags"]["plan_created"] = True
            plan_core._save_plan(plan)
    except Exception as e:
        logger.warning("TTS flag setting failed (non-blocking): %s", e)

    response = {
        "status": "created",
        "plan_id": plan_id,
        "current_task": status["current_task"] if status else None,
    }
    if peer_review_findings:
        response["peer_review"] = peer_review_findings
        critical = [f for f in peer_review_findings if f.get("severity") == "critical"]
        if critical:
            response["status"] = "warning"
            response["peer_review_summary"] = f"{len(critical)} critical finding(s) — auto-fixes applied"
    if template_name:
        response["template"] = template_name
    return fmt_ok(response)


def plan_complete_tool(args: dict, **kwargs) -> str:
    """Complete the current task, verify it, advance to next."""
    task_id = args.get("task_id", "")
    skip_review = args.get("skip_review", False)
    auto_verify = args.get("auto_verify", False)
    auto_commit_enabled = args.get("auto_commit", False)
    if not task_id:
        return fmt_err("task_id is required")

    # Run verification first
    current = plan_core.get_current_task()
    if not current:
        return fmt_err("No active plan.")

    if current["task_id"] != task_id:
        return fmt_err(f"Task '{task_id}' is not the current task. Aktuell: {current['task_id']}")

    # REVIEW GATE
    if not skip_review and not plan_core.is_review_passed(current):
        review_state = plan_core.get_task_review_state(current)

        # Auto-save review result if none exists yet (auto-pass)
        if review_state == "in_review":
            plan_core.save_review_result(task_id, {
                "status": "passed",
                "issues": [],
                "summary": "Auto-review: Gate passed (kein manuelles Review angefordert).",
            })
            # Re-check after saving
            if plan_core.is_review_passed(plan_core._get_active_plan()["tasks"].get(task_id, {})):
                logger.info("Auto-review: review_result für '%s' gespeichert", task_id)
            else:
                return fmt_ok({
                    "error": "Review not passed — task cannot be completed.",
                    "task_id": task_id,
                    "review_required": current.get("review_profile", "none") != "none",
                    "review_state": review_state,
                    "suggestion": (
                        "Führe plan_review(task_id) aus um den Review zu starten. "
                        "Nach erfolgreichem Review: save_review_result() aufrufen. "
                        "Mit skip_review=true in plan_complete() überspringen (nicht empfohlen)."
                    ),
                })
        else:
            # Review exists but is not passed (failed/pending) — block
            return fmt_ok({
                "error": "Review not passed — task cannot be completed.",
                "task_id": task_id,
                "review_required": True,
                "review_state": review_state,
                "suggestion": (
                    "Review-Status: " + review_state + ". "
                    "Führe save_review_result(task_id, {'status': 'passed'}) aus "
                    "um den Review zu bestehen, oder nutze skip_review=true."
                ),
            })

    # Auto-Verify: execute the verify command
    if auto_verify:
        verify_cmd = current.get("verify", "")
        max_retries = args.get("auto_retry", 0)
        retry_count = 0
        verify_result = plan_core.auto_verify_task(verify_cmd)
        while verify_result["status"] == "failed" and retry_count < max_retries:
            retry_count += 1
            import time
            time.sleep(3)  # Kurze Pause vor Retry
            verify_result = plan_core.auto_verify_task(verify_cmd)
        if verify_result["status"] == "failed":
            return fmt_ok({
                "error": "Auto-verify failed — task not completed.",
                "task_id": task_id,
                "verify_result": verify_result,
                "retries": retry_count,
                "suggestion": "Fix das Problem und versuche plan_complete(task_id, auto_verify=true) erneut."
            })
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
            plan_obj = plan_core._get_active_plan()
            repo_single = plan_obj.get("repo", "") if plan_obj else ""
            repo_list = plan_obj.get("repos", []) if plan_obj else None
            commit_result = plan_core.auto_commit(
                task_id, current.get("files", []), repo_single, repo_list,
            )
            result["auto_commit"] = commit_result

        # ─── TTS Flag: Task Completed ────────────────────────────────────
        try:
            plan = plan_core._get_active_plan()
            if plan:
                if "tts_flags" not in plan:
                    plan["tts_flags"] = {}
                if "task_completed" not in plan["tts_flags"]:
                    plan["tts_flags"]["task_completed"] = []
                plan["tts_flags"]["task_completed"].append(task_id)
                plan_core._save_plan(plan)
        except Exception as e:
            logger.warning("TTS flag for task completion failed: %s", e)

    return fmt_ok(result)


def plan_update_tool(args: dict, **kwargs) -> str:
    """Update a task's properties (files, verify, depends_on, name, review_profile).

    Supports optional plan_id to update a different plan than the active one.
    """
    task_id = args.get("task_id", "")
    changes = args.get("changes", {})
    plan_id = args.get("plan_id", "")
    if not task_id:
        return fmt_err("task_id is required")
    if not changes:
        return fmt_err("changes is required (at least one field)")

    result = plan_core.update_task(task_id, changes, plan_id)
    if result is None:
        return fmt_err(
            f"Task '{task_id}' not found, no changes applied, "
            f"or 'changes' contains no supported keys. "
            f"Supported keys: files, verify, depends_on, name, review_profile, parallel_groups"
        )

    return fmt_ok({"status": "updated", "task_id": task_id})


def plan_select_tool(args: dict, **kwargs) -> str:
    """Switch to a different saved plan as the active one."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.select_plan(plan_id)
    return fmt_ok(result)
