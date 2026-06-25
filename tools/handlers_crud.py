"""handlers_crud."""
from __future__ import annotations

import logging

from .. import plan_core, plan_peer_review
from .._fmt import fmt_err, fmt_info, fmt_ok, fmt_table

logger = logging.getLogger("plan_follow")
def plan_abort_tool(args: dict, **kwargs) -> str:
    """Abort the active plan or a specific task."""
    task_id = args.get("task_id", "")
    result = plan_core.abort_plan(task_id)
    return fmt_ok(result)


def plan_archive_tool(args: dict, **kwargs) -> str:
    """Move a plan to the archive directory."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.archive_plan(plan_id)
    return fmt_ok(result)


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
                        f"Plan '{plan_id}' blocked: {len(remaining_critical)} "
                        f"critical findings survived auto-fix."
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


def plan_current_tool(args: dict, **kwargs) -> str:
    """Show the current task. Only ONE task is visible at a time."""
    current = plan_core.get_current_task()
    if not current:
        return fmt_info("No active plan. Use plan_create() to start one.")
    return fmt_ok(current)


def plan_delete_tool(args: dict, **kwargs) -> str:
    """Permanently delete a plan from disk."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.delete_plan(plan_id)
    return fmt_ok(result)


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
                return fmt_err("No active task and no task_id provided.")
            task_id = current["task_id"]
        result = plan_core.set_task_due(task_id, due)
        return fmt_ok(result)
    else:
        info = plan_core.get_task_due_info(task_id)
        if not info:
            return fmt_info("No due date set.")
        return fmt_ok({"status": "ok", **info})


def plan_list_tool(args: dict, **kwargs) -> str:
    """List all plans (including completed/aborted), newest first."""
    include_archived = args.get("include_archived", False)
    plans = plan_core.list_plans(include_archived=include_archived)
    return fmt_ok({
        "status": "ok",
        "count": len(plans),
        "plans": plans,
    })


def plan_restore_tool(args: dict, **kwargs) -> str:
    """Restore a plan from the archive back to the plans directory."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.restore_plan(plan_id)
    return fmt_ok(result)


# ─── Cross-Session Coordination Tools ─────────────────────────────────────────


def plan_select_tool(args: dict, **kwargs) -> str:
    """Switch to a different saved plan as the active one."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.select_plan(plan_id)
    return fmt_ok(result)


def plan_status_tool(args: dict, **kwargs) -> str:
    """Show all tasks with their status."""
    status = plan_core.get_plan_status()
    if not status:
        return fmt_info("No active plan.")
    return fmt_ok(status)


def plan_template_tool(args: dict, **kwargs) -> str:
    """Manage user-defined templates.

    Subcommands:
    - list: List all templates (built-in + user)
    - detail name=X: Show template details
    - save name=X tasks=Y: Save a user template
    - delete name=X: Delete a user template
    """
    from ..plan_templates import delete_user_template, get_template_detail, get_template_names, save_user_template
    cmd = args.get("action", "list")

    if cmd == "list":
        names = get_template_names()
        if not names:
            return fmt_ok({"templates": [], "message": "Keine Templates verfügbar."})
        details = []
        for n in names:
            d = get_template_detail(n)
            if d:
                details.append(d)
        return fmt_table(details, title="Verfügbare Templates")

    elif cmd == "detail":
        name = args.get("name", "")
        if not name:
            return fmt_err("name is required for detail action")
        d = get_template_detail(name)
        if not d:
            return fmt_err(f"Template '{name}' not found.")
        return fmt_ok(d)

    elif cmd == "save":
        name = args.get("name", "")
        tasks = args.get("tasks", [])
        if not name or not tasks:
            return fmt_err("name and tasks are required for save action")
        description = args.get("description", "")
        review_profile = args.get("review_profile", "none")
        result = save_user_template(name, tasks, description, review_profile)
        if result.get("status") == "saved":
            return fmt_ok(result)
        return fmt_err(result.get("message", "Save failed"))

    elif cmd == "delete":
        name = args.get("name", "")
        if not name:
            return fmt_err("name is required for delete action")
        result = delete_user_template(name)
        if result.get("status") == "deleted":
            return fmt_ok(result)
        return fmt_err(result.get("message", "Delete failed"))

    return fmt_err(f"Unknown action '{cmd}'. Supported: list, detail, save, delete")


def plan_update_tool(args: dict, **kwargs) -> str:
    """Update a task's properties (files, verify, depends_on, name)."""
    task_id = args.get("task_id", "")
    changes = args.get("changes", {})
    if not task_id:
        return fmt_err("task_id is required")
    if not changes:
        return fmt_err("changes is required (at least one field)")

    result = plan_core.update_task(task_id, changes)
    if result is None:
        return fmt_err(
            f"Task '{task_id}' not found, no changes applied, "
            f"or 'changes' contains no supported keys. "
            f"Supported keys: files, verify, depends_on, name, review_profile, parallel_groups"
        )

    return fmt_ok({"status": "updated", "task_id": task_id})


def plan_validate_tool(args: dict, **kwargs) -> str:
    """Validate the integrity of a plan (deps, cycles, profiles, orphan tasks)."""
    plan_id = args.get("plan_id", "")
    result = plan_core.validate_plan(plan_id)
    return fmt_ok(result)


def plan_verify_tool(args: dict, **kwargs) -> str:
    """Check for drift: unplanned changes compared to the current plan."""
    current = plan_core.get_current_task()
    if not current:
        return fmt_info("No active plan.")

    drift = plan_core.check_drift()
    if not drift:
        return fmt_ok({
            "status": "clean",
            "plan_id": current["plan_id"],
            "task_id": current["task_id"],
            "message": "Keine ungeplanten Änderungen.",
        })

    return fmt_ok({
        "status": "drift_detected",
        "plan_id": current["plan_id"],
        "task_id": current["task_id"],
        "unplanned_files": drift,
        "suggestion": "plan_update(task_id, {files: [...]}) oder Änderungen reverten.",
    })
