"""
plan_tools.py — Tool implementations for plan-follow plugin.

Each function is registered as a Hermes tool via PluginContext.register_tool().
"""

import logging

from ._fmt import fmt_ok, fmt_err, fmt_info, fmt_table
from . import plan_core
from . import plan_peer_review

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
            return fmt_ok(expanded)
        tasks = expanded["tasks"]
        # Use goal from template description if no goal provided
        if not goal and expanded.get("description"):
            goal = expanded["description"]

    if not goal:
        return fmt_err("goal is required")
    if not tasks:
        return fmt_err("tasks is required (at least 1 task)")

    for t in tasks:
        if "id" not in t or "name" not in t:
            return fmt_err("Each task needs 'id' and 'name'")

    plan_id = plan_core.create_plan(goal, tasks, repo, parallel_groups)
    status = plan_core.get_plan_status()

    # ─── Auto Peer Review (immer aktiv — kein Feature-Toggle) ────────────
    # Nach plan_create() wird der Plan automatisch gegen die 8-Punkte-Checkliste
    # geprüft. Findings werden via apply_findings() eingearbeitet.
    peer_review_findings = []
    try:
        plan = plan_core._get_active_plan()
        if plan:
            findings = plan_peer_review.run_peer_review(plan)
            if findings:
                peer_review_findings = findings
                # Apply automatic fixes (safe: verify commands, files, profiles)
                updated = plan_peer_review.apply_findings(plan, findings)
                plan_core._save_plan(updated)
    except Exception as e:
        logger.warning(f"Auto peer review failed (non-blocking): {e}")

    # ─── TTS Flag: Plan Created ──────────────────────────────────────────
    try:
        plan = plan_core._get_active_plan()
        if plan:
            if "tts_flags" not in plan:
                plan["tts_flags"] = {}
            plan["tts_flags"]["plan_created"] = True
            plan_core._save_plan(plan)
    except Exception as e:
        logger.warning(f"TTS flag setting failed (non-blocking): {e}")

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

    # Auto-Verify: execute the verify command
    if auto_verify:
        verify_cmd = current.get("verify", "")
        verify_result = plan_core.auto_verify_task(verify_cmd)
        if verify_result["status"] == "failed":
            return fmt_ok({
                "error": "Auto-verify failed — task not completed.",
                "task_id": task_id,
                "verify_result": verify_result,
                "suggestion": "Fix das Problem und versuche plan_complete(task_id, auto_verify=true) erneut.",
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
            plan = plan_core._get_active_plan()
            repo = plan.get("repo", "") if plan else ""
            commit_result = plan_core.auto_commit(task_id, current.get("files", []), repo)
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
            logger.warning(f"TTS flag for task completion failed: {e}")

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
        "suggestion": "Entweder plan_update(task_id, {files: [...]}) um Dateien zum Task hinzuzufügen, oder Änderungen reverten.",
    })


def plan_status_tool(args: dict, **kwargs) -> str:
    """Show all tasks with their status."""
    status = plan_core.get_plan_status()
    if not status:
        return fmt_info("No active plan.")
    return fmt_ok(status)


def plan_update_tool(args: dict, **kwargs) -> str:
    """Update a task's properties (files, verify, depends_on, name)."""
    task_id = args.get("task_id", "")
    changes = args.get("changes", {})
    if not task_id:
        return fmt_err("task_id is required")
    if not changes:
        return fmt_err("changes is required (at least one field)")

    result = plan_core.update_task(task_id, changes)
    if not result:
        return fmt_err(f"Task '{task_id}' not found or no active plan.")

    return fmt_ok({"status": "updated", "task_id": task_id})


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

    from .plan_review import dispatch_review

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


def plan_review_profiles_tool(args: dict, **kwargs) -> str:
    """Show all available review profiles with their descriptions and checks."""
    from .review_profiles import PROFILES
    profiles = [
        {"name": name, "description": p["description"], "checks": p["checks"]}
        for name, p in PROFILES.items()
    ]
    return fmt_table(profiles, title="Review Profiles")
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
    from .plan_review import auto_review
    result = auto_review(current, plan, profile, depth)

    return fmt_ok(result)



def plan_list_tool(args: dict, **kwargs) -> str:
    """List all plans (including completed/aborted), newest first."""
    include_archived = args.get("include_archived", False)
    plans = plan_core.list_plans(include_archived=include_archived)
    return fmt_ok({
        "status": "ok",
        "count": len(plans),
        "plans": plans,
    })


def plan_abort_tool(args: dict, **kwargs) -> str:
    """Abort the active plan or a specific task."""
    task_id = args.get("task_id", "")
    result = plan_core.abort_plan(task_id)
    return fmt_ok(result)


def plan_delete_tool(args: dict, **kwargs) -> str:
    """Permanently delete a plan from disk."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.delete_plan(plan_id)
    return fmt_ok(result)


def plan_select_tool(args: dict, **kwargs) -> str:
    """Switch to a different saved plan as the active one."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.select_plan(plan_id)
    return fmt_ok(result)


def plan_validate_tool(args: dict, **kwargs) -> str:
    """Validate the integrity of a plan (deps, cycles, profiles, orphan tasks)."""
    plan_id = args.get("plan_id", "")
    result = plan_core.validate_plan(plan_id)
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


def plan_archive_tool(args: dict, **kwargs) -> str:
    """Move a plan to the archive directory."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.archive_plan(plan_id)
    return fmt_ok(result)


def plan_restore_tool(args: dict, **kwargs) -> str:
    """Restore a plan from the archive back to the plans directory."""
    plan_id = args.get("plan_id", "")
    if not plan_id:
        return fmt_err("plan_id is required.")
    result = plan_core.restore_plan(plan_id)
    return fmt_ok(result)


# ─── Cross-Session Coordination Tools ─────────────────────────────────────────


def plan_session_tool(args: dict, **kwargs) -> str:
    """Show active sessions, their plans, and lock status.

    Reads from coord_state.py — no Git required.
    If Git is active, additionally shows branch info.

    Parameters:
    - include_history (bool, optional): Show git-based plan history (default: false)
    """
    from . import coord_state

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
    - action (str, required): 'lock', 'unlock', or 'status'
    - path (str, required): File or directory path to lock/unlock
    - session_id (str, optional): Session ID (default: auto-detected)
    """
    from . import coord_state

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
    else:
        return fmt_err(f"Unknown action: {action}. Use lock|unlock|status.")

    return fmt_ok({"action": action, "path": path, **result})


def plan_notify_tool(args: dict, **kwargs) -> str:
    """Send a notification to another session or check own notifications.

    Parameters:
    - action (str, required): 'send' or 'check'
    - to (str, optional): Target session ID (required for 'send')
    - message (str, optional): Message text (required for 'send')
    - kind (str, optional): 'info', 'warning', 'alert' (default: 'info')
    """
    from . import coord_state

    action = args.get("action", "")
    to = args.get("to", "")
    message = args.get("message", "")
    kind = args.get("kind", "info")
    session_id = args.get("session_id") or plan_core.get_session_id()

    if not action:
        return fmt_err("action is required (send|check)")

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

    else:
        return fmt_err(f"Unknown action: {action}. Use send|check.")


# ─── Git-Integration Tools (OPTIONAL) ────────────────────────────────────────


def plan_history_tool(args: dict, **kwargs) -> str:
    """Show git-based plan history or hint to activate Git.

    Parameters:
    - plan_id (str, optional): Plan ID. If empty, shows current plan's history.
    - lines (int, optional): Number of log lines to show (default: 10)
    """
    from . import plan_core

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


def plan_git_init_tool(args: dict, **kwargs) -> str:
    """Initialize a Git repo in ~/.hermes/plans/ for plan versioning.

    Also creates an initial commit with all existing plans.
    This is optional — plans work fine without Git.

    Parameters:
    - commit_message (str, optional): Initial commit message (default: 'plan: initial')
    """
    from . import plan_core

    git_dir = plan_core.PLANS_DIR / ".git"
    if git_dir.exists():
        return fmt_info("Git-Versionierung bereits aktiv in ~/.hermes/plans/")

    commit_msg = args.get("commit_message", "plan: initial commit")

    import subprocess
    try:
        # git init
        init = subprocess.run(
            ["git", "init"],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=10,
        )
        if init.returncode != 0:
            return fmt_err(f"git init failed: {init.stderr[:200]}")

        # .gitignore for temp files
        gitignore = plan_core.PLANS_DIR / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*.tmp\n.session-logs/\n", encoding="utf-8")

        # git add + initial commit
        subprocess.run(
            ["git", "add", "--", "."],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=plan_core.PLANS_DIR, capture_output=True, text=True, timeout=30,
        )

        return fmt_ok({
            "status": "initialized",
            "path": str(plan_core.PLANS_DIR),
            "commits": "1 initial commit with all existing plans",
            "message": "Git-Versionierung aktiviert. Pläne werden jetzt automatisch versioniert.",
        })
    except Exception as e:
        return fmt_err(f"Git init failed: {e}")
