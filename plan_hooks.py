"""plan_hooks.py — pre_llm_call hook for plan-follow plugin.

Injects into EVERY user message before the LLM processes it:
1. Current task banner (if a plan is active) — ALWAYS first
2. Drift warnings (if unplanned changes detected)
3. Review status (required / passed / failed)
4. Health check warnings (at the END, never blocks the banner)
"""

import logging
import time
from typing import Any, Optional

from . import plan_core
from .plan_roadmap import get_active_roadmap, _get_phase_progress

logger = logging.getLogger("plan_follow")

# ─── TTL Cache ─────────────────────────────────────────────────────────────────
# Cache health_check and drift results so they don't fire on EVERY LLM turn.
_hook_cache: dict = {}
_HOOK_CACHE_TTL = 60  # seconds


def _cached_or_fresh(key: str, fetcher, ttl: int = _HOOK_CACHE_TTL):
    """Generic TTL cache: returns cached value or calls fetcher()."""
    cached = _hook_cache.get(key)
    if cached:
        val, ts = cached
        if time.monotonic() - ts < ttl:
            return val
        del _hook_cache[key]
    try:
        val = fetcher()
        if val is not None:
            _hook_cache[key] = (val, time.monotonic())
        return val
    except Exception:
        return None


def _build_banner(lines: list) -> Optional[str]:
    """Wrap lines in PLAN banner or return None if empty."""
    if not lines:
        return None
    full = [
        "╔═══════════════════════════════════════════╗",
    ]
    full.extend(lines)
    full.append("╚═══════════════════════════════════════════╝")
    return "[PLAN] " + "\n[PLAN] ".join(full)


def on_pre_llm_call(**kwargs: Any) -> Optional[str]:
    """Pre-LLM-call hook: inject plan context into user message.

    ALWAYS builds the task banner first, then appends health warnings
    at the end. Health degradation does NOT block the task banner.

    Registered via PluginContext.register_hook("pre_llm_call", ...).
    The return value is appended to the user message before it reaches the LLM.
    """

    # ─── 1. Active Plan → Task Banner (ALWAYS first) ──────────────────────
    # NOTE: Nur In-Memory Cache, kein Disk-Recovery. So werden keine Pläne
    # aus anderen Sessions angezeigt. Plans bleiben auf Disk und sind via
    # plan_list() + plan_select() manuell wiederherstellbar.
    try:
        current = plan_core.get_current_task_cached()
        if current:
            lines = [
                f"║  CURRENT TASK: {current['task_id']} — {current['name'][:50]}",
                f"║  Files: {', '.join(current['files'][:3])}" +
                (" ..." if len(current['files']) > 3 else ""),
                f"║  Progress: {current['progress']}",
                "║                                       ║",
            ]

            # ─── 1b. Roadmap Banner (if a roadmap is active) ───────────────
            try:
                rname, rdata = get_active_roadmap()
                if rdata:
                    prog = _get_phase_progress(rdata)
                    lines.append(f"║  📋 ROADMAP: {rdata.get('name', rname or '?')}")
                    lines.append(f"║     {prog['completed']}/{prog['total']} Phasen erledigt")

                    # Show next unblocked phases (max 3)
                    from .plan_roadmap import _get_next_phases
                    next_phases = _get_next_phases(rdata)
                    if next_phases:
                        next_names = [p.get("name", p.get("id", "?"))[:30] for p in next_phases[:3]]
                        lines.append(f"║     👉 Nächste: {', '.join(next_names)}")

                    # Show blocked phases
                    blocked = [p for p in rdata.get("phases", []) if p.get("status") == "blocked"]
                    if blocked:
                        blocked_names = [p.get("name", p.get("id", "?"))[:25] for p in blocked[:2]]
                        lines.append(f"║     🔒 Blockiert: {', '.join(blocked_names)}")
            except Exception:
                pass  # Roadmap banner is best-effort

            # ─── 2. Drift Check (cached) ──────────────────────────────────
            try:
                drift = _cached_or_fresh("drift", plan_core.check_drift)
                if drift:
                    lines.append("║                                       ║")
                    lines.append("║  ⚠️  DRIFT DETECTED                   ║")
                    for f in drift[:3]:
                        lines.append(f"║    {f[:60]}")
                    if len(drift) > 3:
                        lines.append(f"║    ... and {len(drift)-3} more")
                    lines.append("║                                       ║")
                    lines.append("║  → plan_update() oder revert          ║")

                # Proactive drift warnings from post_tool_call hook
                drift_warnings = plan_core.get_drift_warnings()
                if drift_warnings:
                    lines.append("║                                       ║")
                    lines.append("║  ⚠️  DRIFT WARNING (proaktiv)          ║")
                    for w in drift_warnings[:2]:
                        lines.append(f"║    • {w[:55]}")
                    if len(drift_warnings) > 2:
                        lines.append(f"║    ... and {len(drift_warnings)-2} more")
                    lines.append("║                                       ║")
                    lines.append("║  → Task-Eigenschaften prüfen          ║")
            except Exception:
                pass  # Drift check is best-effort

            # ─── 3. Due Date / Deadline Warning ──────────────────────────
            try:
                due_info = plan_core.get_task_due_info()
                if due_info:
                    if due_info.get("overdue"):
                        due_days = abs(due_info.get("days_remaining", 0))
                        lines.append("║                                       ║")
                        lines.append("║  🔴 DEADLINE OVERDUE            ║")
                        lines.append(f"║    Overdue by {due_days} Tag(en): {due_info['due']}          ║")
                    elif due_info.get("days_remaining", 0) <= 3:
                        lines.append("║                                       ║")
                        lines.append("║  🟡 DEADLINE SOON                     ║")
                        lines.append(f"║    Noch {due_info['days_remaining']} Tag(e): {due_info['due']}             ║")
            except Exception:
                pass  # Deadline display is best-effort

            # ─── 3b. Cross-Session Info ─────────────────────────────────────
            try:
                from . import coord_state

                # Silent cleanup: stale sessions/locks (TTL-geschützt via _cached_or_fresh)
                _cached_or_fresh("cleanup_stale", lambda: (
                    coord_state.cleanup_stale_sessions(60),
                    coord_state.cleanup_stale_locks(120),
                    "ok"
                ))

                sessions = coord_state.get_sessions()
                locks = coord_state.get_locks()

                # Show active sessions count (excluding current)
                if sessions:
                    lines.append("║                                       ║")
                    lines.append(f"║  👥 {len(sessions)} aktive Session(s)         ║")
                    for sid, s in list(sessions.items())[:3]:
                        goal_preview = s.get("goal", "")[:35]
                        lines.append(f"║    • {sid[:20]}: {goal_preview}    ║")
                    if len(sessions) > 3:
                        lines.append(f"║    ... und {len(sessions)-3} weitere        ║")

                # Check if current files are locked by other sessions
                current = plan_core.get_current_task_cached()
                if current and locks:
                    other_locks = []
                    task_files = current.get("files", [])
                    for path, lock in locks.items():
                        if any(f in path for f in task_files):
                            other_locks.append(path)

                    if other_locks:
                        lines.append("║                                       ║")
                        lines.append("║  🔒 LOCKS: Dateien von anderer Session  ║")
                        for lpath in other_locks[:2]:
                            lock_info = locks.get(lpath, {})
                            lines.append(f"║    • {lpath[:45]} ({lock_info.get('session_id','?')[:15]})    ║")

                # Check pending notifications
                from . import plan_core as _plan_core
                notifs = coord_state.get_notifications(_plan_core.get_session_id(), mark_read=False)
                if notifs:
                    lines.append("║                                       ║")
                    lines.append(f"║  📬 {len(notifs)} Nachricht(en) von anderen    ║")
                    lines.append("║    → plan_notify(action='check')          ║")
            except Exception:
                pass  # Cross-session info is best-effort

            # ─── 3c. TTS Event Markers ───────────────────────────────────────
            # Inject [TTS:event=...:message=...] markers for the Agent to pick up.
            # Markers are shown EXACTLY ONCE and cleared after display.
            try:
                active_plan = plan_core._get_active_plan()
                if active_plan and active_plan.get("tts_flags"):
                    tts_flags = active_plan["tts_flags"]
                    tts_messages_to_clear = []

                    # Plan created → announce plan goal
                    if tts_flags.get("plan_created"):
                        goal_text = active_plan.get("goal", "Plan created")[:80]
                        task_count = len(active_plan.get("tasks", {}))
                        lines.append("║                                       ║")
                        lines.append("║  [TTS:event=plan_created:message=Plan erstellt:             ║")
                        lines.append(f"║   {goal_text} ({task_count} Tasks)]  ║")
                        tts_messages_to_clear.append("plan_created")

                    # Task completed → announce task name
                    completed_tasks = tts_flags.get("task_completed", [])
                    for ctid in list(completed_tasks):
                        task = active_plan.get("tasks", {}).get(ctid, {})
                        task_name = task.get("name", ctid)[:50]
                        lines.append("║                                       ║")
                        lines.append("║  [TTS:event=task_completed:message=Aufgabe abgeschlossen:  ║")
                        lines.append(f"║   {task_name}]          ║")
                        tts_messages_to_clear.append(ctid)  # mark individual task as shown

                    # Review failed → announce critical issues
                    failed_reviews = tts_flags.get("review_failed", [])
                    for rfid in list(failed_reviews):
                        task = active_plan.get("tasks", {}).get(rfid, {})
                        review_result = task.get("review_result", {})
                        issues = review_result.get("issues", []) if isinstance(review_result, dict) else []
                        error_issues = [i for i in issues if i.get("severity") == "error"] if issues else []
                        issue_summary = f"{len(error_issues)} kritische(s) Problem(e)" if error_issues else "Review fehlgeschlagen"
                        lines.append("║                                       ║")
                        lines.append(f"║  [TTS:event=review_failed:message={issue_summary}  ║")
                        task_name = task.get("name", rfid)[:40]
                        lines.append(f"║   in {task_name}]                            ║")
                        tts_messages_to_clear.append(rfid)

                    # Clear shown flags after display
                    if "plan_created" in tts_messages_to_clear:
                        tts_flags.pop("plan_created", None)
                    for ctid in tts_messages_to_clear:
                        if ctid in tts_flags.get("task_completed", []):
                            tts_flags["task_completed"].remove(ctid)
                        if ctid in tts_flags.get("review_failed", []):
                            tts_flags["review_failed"].remove(ctid)

                    # If all flags consumed, remove the key entirely
                    if not tts_flags:
                        active_plan.pop("tts_flags", None)

                    # Persist cleared flags back to disk
                    plan_core._save_plan(active_plan)

            except Exception:
                pass  # TTS markers are best-effort

            # ─── 4. Review Status Banner ──────────────────────────────────
            try:
                review_profile = current.get("review_profile", "none")
                if review_profile != "none":
                    review_state = plan_core.get_task_review_state(current)
                    if review_state == "in_review":
                        lines.append("║                                       ║")
                        lines.append("║  ⚠️  REVIEW REQUIRED                  ║")
                        lines.append(f"║    Profil: {review_profile}                    ║")
                        lines.append(f"║    → plan_review(\"{current['task_id']}\")     ║")
                        lines.append("║      vor plan_complete()             ║")
                        lines.append("║                                       ║")
                        lines.append(f"║  [REVIEW_PENDING:task_id={current['task_id']}  ║")
                        lines.append(f"║   :profile={review_profile}]         ║")
                    elif review_state == "failed":
                        lines.append("║                                       ║")
                        lines.append("║  ❌ REVIEW FAILED                    ║")
                        result_issues = current.get("review_result", {}).get("issues", [])
                        for issue in result_issues[:2]:
                            msg = issue.get("check", "?")[:50]
                            lines.append(f"║    • {msg}")
                        if len(result_issues) > 2:
                            lines.append(f"║    ... and {len(result_issues)-2} more")
                        lines.append("║                                       ║")
                        lines.append("║  → Issues fixen + erneut reviewen    ║")
                    elif review_state == "passed":
                        lines.append("║                                       ║")
                        lines.append("║  ✅ REVIEW PASSED                 ║")
                        lines.append("║  → plan_complete() möglich           ║")
            except Exception:
                pass  # Review banner is best-effort

            # ─── 4. Health Check (at the END, non-blocking) ───────────────
            try:
                health = _cached_or_fresh("health", lambda: plan_core.health_check())
                if health and health.get("status") == "degraded":
                    issues = health.get("issues", [])
                    if issues:
                        lines.append("║                                       ║")
                        lines.append("║  ⚠️  SYSTEM HEALTH DEGRADED           ║")
                        for issue in issues[:3]:
                            lines.append(f"║    • {issue[:55]}")
                        if len(issues) > 3:
                            lines.append(f"║    ... and {len(issues)-3} more")
                        lines.append("║  (Arbeit trotzdem möglich)           ║")
            except Exception:
                pass  # Health check is best-effort

            return _build_banner(lines)
    except Exception as e:
        logger.warning(f"Task banner injection failed: {e}")

    return None  # Nothing to inject


# ─── post_tool_call Hook (Observability) ───────────────────────────────────────


def on_post_tool_call(**kwargs: Any) -> None:
    """Observe tool calls for metrics and auto-drift-tracking.

    Registered via PluginContext.register_hook("post_tool_call", ...).
    Return value is ignored (observer pattern).

    Records:
    - Per-task tool call counters (category, duration, count)
    - Drift warnings when code_*/patch tools operate outside task.files
    """
    tool_name = kwargs.get("tool_name", "")
    duration = kwargs.get("duration_ms", 0)
    status = kwargs.get("status", "")

    # Only track plan_follow and code_* tools to avoid noise
    if not tool_name.startswith(("plan_", "code_", "patch", "terminal")):
        return

    # Record metrics (if a plan is active)
    from .plan_core import record_tool_call, record_drift_warning, get_current_task_cached
    record_tool_call(tool_name, duration, status)

    # ─── Auto-Drift-Tracking ──────────────────────────────────────────────
    # When code_*/patch writes to files outside the current task's allowed files,
    # record a proactive drift warning.
    if tool_name in ("code_refactor", "patch", "code_replace_body", "code_safe_delete",
                     "code_insert_before", "code_insert_after", "code_rename"):
        args = kwargs.get("args", {}) or {}
        file_path = args.get("path", "") if isinstance(args, dict) else ""
        if file_path:
            current = get_current_task_cached()
            if current:
                allowed = current.get("files", [])
                if allowed and not any(f in file_path for f in allowed):
                    record_drift_warning(
                        f"Tool '{tool_name}' operated on '{file_path}', "
                        f"which is outside task.files: {allowed}"
                    )

            # ─── Lock Enforcement ───────────────────────────────────────────
            # Check if file is locked by another session
            if file_path:
                try:
                    from . import coord_state
                    lock_info = coord_state.get_lock(file_path)
                    if lock_info:
                        locker_sid = lock_info.get("session_id", "unknown")
                        my_sid = __import__("os").environ.get("HERMES_SESSION_ID", "")
                        if locker_sid and my_sid and locker_sid != my_sid:
                            since = lock_info.get("since", "?")
                            record_drift_warning(
                                f"🔒 '{file_path}' ist von Session '{locker_sid[:20]}' "
                                f"gelockt seit {since[:19]}. Konflikt vermeiden!"
                            )
                except Exception:
                    pass  # Best-effort

    # Append to session log file
    try:
        log_dir = plan_core.PLANS_DIR / ".session-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "tool-calls.log"
        iso = __import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("UTC")).isoformat()
        entry = f"[{iso}] {tool_name} | {status} | {duration}ms\n"
        with open(log_file, "a") as f:
            f.write(entry)
    except Exception:
        pass  # Best-effort logging only
