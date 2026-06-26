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

from . import coord_state, plan_core

logger = logging.getLogger("plan_follow")

# ─── TTL Cache ─────────────────────────────────────────────────────────────────
# Cache health_check and drift results so they don't fire on EVERY LLM turn.
_hook_cache: dict = {}
_HOOK_CACHE_TTL = 60  # seconds

# ─── Cross-Session Auto-Coordination ────────────────────────────────────────────
# Track which task's files are currently locked, so we can release on task change.
_LAST_LOCKED_TASK: Optional[str] = None


def _do_coordination_housekeeping(current: dict) -> int:
    """Register session heartbeat + auto-acquire locks for task files.

    Called once per turn from on_pre_llm_call, BEFORE the banner is built.
    Detects task changes and releases stale locks automatically.

    Returns the number of locks acquired (0 if none needed).
    """
    global _LAST_LOCKED_TASK

    session_id = plan_core.get_session_id()
    plan = plan_core._get_active_plan()
    plan_id = plan.get("plan_id", "") if plan else ""
    goal = plan.get("goal", "") if plan else ""

    # 1. Register/update session with heartbeat
    registered = coord_state.get_session(session_id)
    if registered:
        coord_state.update_session(session_id, plan_id=plan_id, goal=goal)
    else:
        coord_state.register_session(session_id, plan_id=plan_id, goal=goal)

    # 2. Detect task change → release ALL old locks for this session
    current_task_id = current.get("task_id", "")
    if _LAST_LOCKED_TASK and _LAST_LOCKED_TASK != current_task_id:
        coord_state.release_all_locks(session_id)

    # 3. Auto-acquire locks for current task files
    task_files = current.get("files", [])
    acquired_count = 0
    for f in task_files:
        result = coord_state.acquire_lock(f, session_id)
        if result["status"] == "acquired":
            acquired_count += 1

    _LAST_LOCKED_TASK = current_task_id
    return acquired_count


# ─── Circuit Breaker ──────────────────────────────────────────────────────────────
# Tracked tool failures that should stop work. Set by post_tool_call on error,
# displayed in pre_llm_call banner, auto-expires after _BREAKER_TTL seconds.
_breaker_state: dict[str, dict] = {}  # {tool_name: {"error": str, "ts": float}}
_BREAKER_TTL = 300  # 5 min auto-clear
_BREAKER_CRITICAL_PREFIXES = (
    "honcho_", "mcp_firecrawl_", "analysis_", "bug_hunt_",
    "research_", "code_", "plan_",
)


def _check_breaker() -> dict[str, dict]:
    """Return active breaker entries (auto-expired ones removed)."""
    now = time.monotonic()
    expired = [t for t, info in list(_breaker_state.items()) if now - info["ts"] > _BREAKER_TTL]
    for t in expired:
        _breaker_state.pop(t, None)
    return dict(_breaker_state)


def _set_breaker(tool_name: str, error_msg: str) -> None:
    """Record a circuit-breaker hit for a critical tool."""
    _breaker_state[tool_name] = {"error": error_msg[:80], "ts": time.monotonic()}


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


# ─── Banner-Builder ──────────────────────────────────────────────────────────


def _build_task_header(current: dict) -> list[str]:
    """Build task info header lines."""
    lines = [
        f"║  CURRENT TASK: {current['task_id']} — {current['name'][:50]}",
        f"║  Files: {', '.join(current['files'][:3])}"
        + (" ..." if len(current["files"]) > 3 else ""),
        f"║  Progress: {current['progress']}",
        "║                                       ║",
    ]
    return lines


def _build_roadmap_banner() -> list[str]:
    """Build roadmap progress lines (best-effort)."""
    lines = []
    try:
        from .plan_roadmap import _get_next_phases, _get_phase_progress, get_active_roadmap

        rname, rdata = get_active_roadmap()
        if not rdata:
            return lines
        prog = _get_phase_progress(rdata)
        lines.append(f"║  📋 ROADMAP: {rdata.get('name', rname or '?')}")
        lines.append(f"║     {prog['completed']}/{prog['total']} Phasen erledigt")

        next_phases = _get_next_phases(rdata)
        if next_phases:
            next_names = [p.get("name", p.get("id", "?"))[:30] for p in next_phases[:3]]
            lines.append(f"║     👉 Nächste: {', '.join(next_names)}")

        blocked = [p for p in rdata.get("phases", []) if p.get("status") == "blocked"]
        if blocked:
            blocked_names = [p.get("name", p.get("id", "?"))[:25] for p in blocked[:2]]
            lines.append(f"║     🔒 Blockiert: {', '.join(blocked_names)}")
    except Exception:
        pass
    return lines


def _build_git_banner() -> list[str]:
    """Build git status lines (branch, ahead/behind, dirty) — cached, non-blocking."""
    lines = []
    try:
        plan = plan_core._get_active_plan()
        if not plan:
            return lines

        repos = plan_core._get_repos(plan)
        if not repos:
            return lines

        for repo in repos:
            def _git_status_wrapper(r=repo):
                return plan_core.get_git_status(r)
            status = _cached_or_fresh(f"git_status:{repo}", _git_status_wrapper, ttl=120)
            if not status or status.get("status") != "ok":
                continue

            repo_name = repo.rstrip("/").split("/")[-1]
            parts = [f"{repo_name}"]
            parts.append(f"🌿{status.get('branch', '?')}")

            if status.get("dirty"):
                parts.append(f"💩+{status['dirty_files']}")

            ahead = status.get("ahead", 0)
            behind = status.get("behind", 0)
            if ahead or behind:
                if ahead and behind:
                    parts.append(f"↑{ahead}↓{behind}")
                elif ahead:
                    parts.append(f"↑{ahead}")
                elif behind:
                    parts.append(f"↓{behind}")

            lines.append(f"║  📍 {' '.join(parts)}")

    except Exception:
        pass  # Non-blocking
    return lines


def _build_drift_banner() -> list[str]:
    """Build drift detection lines (cached, best-effort)."""
    lines = []
    try:
        drift = _cached_or_fresh("drift", plan_core.check_drift)
        if drift:
            lines.append("║  ⚠️  DRIFT DETECTED                   ║")
            for f in drift[:3]:
                lines.append(f"║    {f[:60]}")
            if len(drift) > 3:
                lines.append(f"║    ... and {len(drift) - 3} more")
            lines.append("║  → plan_update() oder revert          ║")

        drift_warnings = plan_core.get_drift_warnings()
        if drift_warnings:
            lines.append("║  ⚠️  DRIFT WARNING (proaktiv)          ║")
            for w in drift_warnings[:2]:
                lines.append(f"║    • {w[:55]}")
            if len(drift_warnings) > 2:
                lines.append(f"║    ... and {len(drift_warnings) - 2} more")
            lines.append("║  → Task-Eigenschaften prüfen          ║")
    except Exception:
        pass
    return lines


def _build_due_banner() -> list[str]:
    """Build deadline/due-date warning lines (best-effort)."""
    lines = []
    try:
        due_info = plan_core.get_task_due_info()
        if not due_info:
            return lines
        if due_info.get("overdue"):
            due_days = abs(due_info.get("days_remaining", 0))
            lines.append("║  🔴 DEADLINE OVERDUE            ║")
            lines.append(
                f"║    Overdue by {due_days} Tag(en): {due_info['due']}          ║"
            )
        elif due_info.get("days_remaining", 0) <= 3:
            lines.append("║  🟡 DEADLINE SOON                     ║")
            lines.append(
                f"║    Noch {due_info['days_remaining']} Tag(e): {due_info['due']}             ║"
            )
    except Exception:
        pass
    return lines


def _build_coordination_banner() -> list[str]:
    """Build cross-session coordination lines (best-effort)."""
    lines = []
    try:
        from . import coord_state

        _cached_or_fresh(
            "cleanup_stale",
            lambda: (
                coord_state.cleanup_stale_sessions(60),
                coord_state.cleanup_stale_locks(120),
                "ok",
            ),
        )

        sessions = coord_state.get_sessions()
        locks = coord_state.get_locks()
        my_sid = plan_core.get_session_id()
        current = plan_core.get_current_task_cached()

        if sessions:
            lines.append(f"║  👥 {len(sessions)} aktive Session(s)         ║")
            for sid, s in list(sessions.items())[:3]:
                plan_label = s.get("plan_id", "")[:25]
                last_seen = s.get("last_seen", "")[11:19] if s.get("last_seen") else "?"
                lock_count = sum(
                    1 for lock in locks.values()
                    if lock.get("session_id") == sid
                )
                my_mark = " ← du" if sid == my_sid else ""
                lines.append(
                    f"║    • {sid[:16]} {plan_label} [{last_seen}]"
                    f"{' 🔒' + str(lock_count) if lock_count else ''}{my_mark}    ║"
                )
            if len(sessions) > 3:
                lines.append(f"║    ... und {len(sessions) - 3} weitere        ║")

        # Show MY locks
        if my_sid and locks:
            my_locks = [
                p for p, lock in locks.items()
                if lock.get("session_id") == my_sid
            ]
            if my_locks:
                lines.append(f"║  🔒 Eigene Locks ({len(my_locks)})                  ║")
                for lp in my_locks[:2]:
                    fname = lp.rsplit("/", 1)[-1]
                    lines.append(f"║    • {fname[:45]}                      ║")
                if len(my_locks) > 2:
                    lines.append(f"║    ... und {len(my_locks) - 2} weitere            ║")

        # Warning for LOCKS older than 30 minutes (stale)
        if locks:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            stale = []
            for path, lock in locks.items():
                since_str = lock.get("since", "")
                try:
                    age = (now - datetime.fromisoformat(since_str)).total_seconds() / 60
                    if age > 30:
                        stale.append((path, lock, int(age)))
                except (ValueError, TypeError):
                    pass
            if stale:
                stale.sort(key=lambda x: -x[2])  # oldest first
                lines.append(f"║  ⏳ Stale-Locks ({len(stale)} >30 Min alt)      ║")
                for lpath, lock_info, age_min in stale[:2]:
                    fname = lpath.rsplit("/", 1)[-1]
                    locker_sid = lock_info.get("session_id", "?")[:16]
                    lines.append(
                        f"║    • {fname[:35]} ({locker_sid}, {age_min}m)  ║"
                    )

        # Show locks by OTHER sessions on our task files
        if current and locks:
            other_locks = []
            task_files = current.get("files", [])
            for path, lock in locks.items():
                if any(f in path for f in task_files):
                    locker = lock.get("session_id", "")
                    if locker and locker != my_sid:
                        other_locks.append((path, lock))
            if other_locks:
                lines.append("║  ⚠️  LOCKS von anderen auf Task-Files    ║")
                for lpath, lock_info in other_locks[:2]:
                    fname = lpath.rsplit("/", 1)[-1]
                    locker_sid = lock_info.get("session_id", "?")[:16]
                    lines.append(
                        f"║    • {fname[:40]} (🔒 {locker_sid})    ║"
                    )

        notifs = coord_state.get_notifications(
            plan_core.get_session_id(), mark_read=False
        )
        if notifs:
            lines.append(f"║  📬 {len(notifs)} Nachricht(en) von anderen    ║")
            # Show preview of latest notification
            latest = notifs[-1]
            from_msg = latest.get("from", "?")[:16]
            msg_preview = latest.get("message", "")[:35]
            lines.append(f"║    • {from_msg}: {msg_preview}         ║")
            lines.append("║    → plan_notify(action='check')          ║")
    except Exception:
        pass
    return lines


def _build_tts_banner() -> list[str]:
    """Build TTS event marker lines (best-effort, clears flags after display)."""
    lines = []
    try:
        active_plan = plan_core._get_active_plan()
        if not active_plan or not active_plan.get("tts_flags"):
            return lines

        tts_flags = active_plan["tts_flags"]
        to_clear = []

        if tts_flags.get("plan_created"):
            goal_text = active_plan.get("goal", "Plan created")[:80]
            task_count = len(active_plan.get("tasks", {}))
            lines.append(
                "║  [TTS:event=plan_created:message=Plan erstellt:             ║"
            )
            lines.append(f"║   {goal_text} ({task_count} Tasks]  ║")
            to_clear.append("plan_created")

        completed_tasks = tts_flags.get("task_completed", [])
        for ctid in list(completed_tasks):
            task = active_plan.get("tasks", {}).get(ctid, {})
            task_name = task.get("name", ctid)[:50]
            lines.append(
                "║  [TTS:event=task_completed:message=Aufgabe abgeschlossen:  ║"
            )
            lines.append(f"║   {task_name}]          ║")
            to_clear.append(ctid)

        failed_reviews = tts_flags.get("review_failed", [])
        for rfid in list(failed_reviews):
            task = active_plan.get("tasks", {}).get(rfid, {})
            review_result = task.get("review_result", {})
            issues = (
                review_result.get("issues", [])
                if isinstance(review_result, dict)
                else []
            )
            error_issues = (
                [i for i in issues if i.get("severity") == "error"] if issues else []
            )
            issue_summary = (
                f"{len(error_issues)} kritische(s) Problem(e)"
                if error_issues
                else "Review fehlgeschlagen"
            )
            lines.append(f"║  [TTS:event=review_failed:message={issue_summary}  ║")
            task_name = task.get("name", rfid)[:40]
            lines.append(f"║   in {task_name}]                            ║")
            to_clear.append(rfid)

        if "plan_created" in to_clear:
            tts_flags.pop("plan_created", None)
        for item in to_clear:
            if item in tts_flags.get("task_completed", []):
                tts_flags["task_completed"].remove(item)
            if item in tts_flags.get("review_failed", []):
                tts_flags["review_failed"].remove(item)

        if not tts_flags:
            active_plan.pop("tts_flags", None)
        plan_core._save_plan(active_plan)
    except Exception as e:
        logger.warning("TTS flag save failed (non-blocking): %s", e)
    return lines


def _build_review_banner(current: dict) -> list[str]:
    """Build review status lines (best-effort)."""
    lines = []
    try:
        review_profile = current.get("review_profile", "none")
        if review_profile == "none":
            return lines
        review_state = plan_core.get_task_review_state(current)
        if review_state == "in_review":
            lines.append("║  ⚠️  REVIEW REQUIRED                  ║")
            lines.append(f"║    Profil: {review_profile}                    ║")
            lines.append(f'║    → plan_review("{current["task_id"]}")     ║')
            lines.append("║      vor plan_complete()             ║")
            lines.append("║                                       ║")
            lines.append(f"║  [REVIEW_PENDING:task_id={current['task_id']}  ║")
            lines.append(f"║   :profile={review_profile}]         ║")
        elif review_state == "failed":
            lines.append("║  ❌ REVIEW FAILED                    ║")
            result_issues = current.get("review_result", {}).get("issues", [])
            for issue in result_issues[:2]:
                msg = issue.get("check", "?")[:50]
                lines.append(f"║    • {msg}")
            if len(result_issues) > 2:
                lines.append(f"║    ... and {len(result_issues) - 2} more")
            lines.append("║  → Issues fixen + erneut reviewen    ║")
        elif review_state == "passed":
            lines.append("║  ✅ REVIEW PASSED                 ║")
            lines.append("║  → plan_complete() möglich           ║")
    except Exception:
        pass
    return lines


def _build_breaker_banner() -> list[str]:
    """Build circuit-breaker warning lines (shown BEFORE health banner)."""
    active = _check_breaker()
    if not active:
        return []
    lines = [
        "║  🚫 CIRCUIT BREAKER ACTIVE                ║",
    ]
    for tool, info in list(active.items())[:3]:
        lines.append(f"║    • {tool}: {info['error'][:50]}")
    if len(active) > 3:
        lines.append(f"║    ... und {len(active) - 3} weitere")
    lines.append("║  → Nur lesende Analyse                 ║")
    lines.append("║  → Johannes entscheiden lassen          ║")
    return lines


def _build_health_banner() -> list[str]:
    """Build health check lines (cached, non-blocking, at end)."""
    lines = []
    try:
        from .tools.health import health_check as _health_check

        health = _cached_or_fresh("health", _health_check)
        if health and health.get("status") == "degraded":
            issues = health.get("issues", [])
            if issues:
                lines.append("║  ⚠️  SYSTEM HEALTH DEGRADED           ║")
                for issue in issues[:3]:
                    lines.append(f"║    • {issue[:55]}")
                if len(issues) > 3:
                    lines.append(f"║    ... and {len(issues) - 3} more")
                lines.append("║  (Arbeit trotzdem möglich)           ║")
    except Exception:
        pass
    return lines


# ─── pre_llm_call Hook ──────────────────────────────────────────────────────


def on_pre_llm_call(**kwargs: Any) -> Optional[str]:
    """Pre-LLM-call hook: inject plan context into user message.

    Registered via PluginContext.register_hook("pre_llm_call", ...).
    Builds banner from sub-functions, then returns formatted string.
    ALWAYS returns None if no active plan (nothing to inject).
    """
    try:
        current = plan_core.get_current_task_cached()
        if not current:
            return None

        # ─── Auto-Coordination Housekeeping ─────────────────────────────
        # Session heartbeat + auto-lock task files
        try:
            _do_coordination_housekeeping(current)
        except Exception:
            pass  # Best-effort

        # Build banner sections sequentially
        lines = _build_task_header(current)
        git_lines = _build_git_banner()
        if git_lines:
            lines.append("║                                       ║")
            lines.extend(git_lines)
        lines.extend(_build_roadmap_banner())
        drift_lines = _build_drift_banner()
        if drift_lines:
            lines.append("║                                       ║")
            lines.extend(drift_lines)
        lines.extend(_build_due_banner())
        coord_lines = _build_coordination_banner()
        if coord_lines:
            lines.append("║                                       ║")
            lines.extend(coord_lines)
        lines.extend(_build_tts_banner())
        review_lines = _build_review_banner(current)
        if review_lines:
            lines.append("║                                       ║")
            lines.extend(review_lines)
        health_lines = _build_health_banner()
        if health_lines:
            lines.append("║                                       ║")
            lines.extend(health_lines)
        breaker_lines = _build_breaker_banner()
        if breaker_lines:
            lines.append("║                                       ║")
            lines.extend(breaker_lines)

        return _build_banner(lines)
    except Exception as e:
        logger.warning("Task banner injection failed: %s", e)

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
    error = kwargs.get("error", "")

    # ─── Circuit Breaker ────────────────────────────────────────────────────
    # Check BEFORE the early-return filter so firecrawl/honcho failures are caught
    if status == "error" and tool_name.startswith(_BREAKER_CRITICAL_PREFIXES):
        error_msg = str(error or kwargs.get("result", "Unknown error"))[:80]
        _set_breaker(tool_name, error_msg)

    # Only track plan_follow and code_* tools to avoid noise
    if not tool_name.startswith(("plan_", "code_", "patch", "terminal")):
        return

    # Record metrics (if a plan is active)
    from .plan_core import (
        get_current_task_cached,
        record_drift_warning,
        record_tool_call,
    )

    record_tool_call(tool_name, duration, status)

    # ─── Auto-Drift-Tracking ──────────────────────────────────────────────
    # When code_*/patch writes to files outside the current task's allowed files,
    # record a proactive drift warning.
    if tool_name in (
        "code_refactor",
        "patch",
        "code_replace_body",
        "code_safe_delete",
        "code_insert_before",
        "code_insert_after",
        "code_rename",
    ):
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

            # ─── Lock Enforcement + Auto-Lock ─────────────────────────────────
            if file_path:
                try:
                    from . import coord_state

                    my_sid = plan_core.get_session_id()

                    # Check if file is locked by another session
                    lock_info = coord_state.get_lock(file_path)
                    if lock_info:
                        locker_sid = lock_info.get("session_id", "unknown")
                        if locker_sid and my_sid and locker_sid != my_sid:
                            since = lock_info.get("since", "?")
                            record_drift_warning(
                                f"🔒 '{file_path}' ist von Session '{locker_sid[:20]}' "
                                f"gelockt seit {since[:19]}. Konflikt vermeiden!"
                            )
                            # Auto-notify the locking session
                            try:
                                coord_state.send_notification(
                                    my_sid, locker_sid,
                                    f"⚠️ Versuche '{file_path.rsplit('/', 1)[-1]}' zu editieren, "
                                    f"das du seit {since[:19]} gelockt hast.",
                                    kind="warning",
                                )
                            except Exception:
                                pass

                    # Auto-Lock: Acquire lock on the file being edited
                    if my_sid:
                        lock_result = coord_state.acquire_lock(file_path, my_sid)
                        if lock_result.get("status") == "acquired":
                            logger.debug(
                                "Auto-Lock: '%s' für Session '%s' erworben",
                                file_path, my_sid[:20]
                            )
                except Exception:
                    pass  # Best-effort

    # Append to session log file
    try:
        log_dir = plan_core.PLANS_DIR / ".session-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "tool-calls.log"
        iso = (
            __import__("datetime")
            .datetime.now(__import__("zoneinfo").ZoneInfo("UTC"))
            .isoformat()
        )
        entry = f"[{iso}] {tool_name} | {status} | {duration}ms\n"
        with open(log_file, "a") as f:
            f.write(entry)
    except Exception as e:
        logger.warning("Session log write failed: %s", e)


# ─── on_session_end Hook ────────────────────────────────────────────────────


def on_session_end(**kwargs: Any) -> None:
    """Session end: persist plan state, release locks, unregister session."""
    try:
        # 1. Persist current plan state
        plan = plan_core._get_active_plan()
        if plan:
            plan["_last_session_end"] = (
                __import__("datetime")
                .datetime.now(__import__("zoneinfo").ZoneInfo("UTC"))
                .isoformat()
            )
            plan_core._save_plan(plan)
            logger.info("Plan '%s' state persisted at session end", plan.get("plan_id"))

        # 2. Release all locks held by this session
        try:
            from . import coord_state

            session_id = plan_core.get_session_id()
            if session_id:
                released = coord_state.release_all_locks(session_id)
                if released:
                    logger.info("Released %d lock(s) at session end", released)
        except Exception:
            pass  # Best-effort

        # 3. Unregister session
        try:
            from . import coord_state

            session_id = plan_core.get_session_id()
            if session_id:
                coord_state.unregister_session(session_id)
                logger.info("Session '%s' unregistered at session end", session_id[:20])
        except Exception:
            pass  # Best-effort

        # 4. Finalize session log
        try:
            log_dir = plan_core.PLANS_DIR / ".session-logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "tool-calls.log"
            iso = __import__("datetime").datetime.now(
                __import__("zoneinfo").ZoneInfo("UTC")
            ).isoformat()
            with open(log_file, "a") as f:
                f.write(f"[{iso}] SESSION_END\n")
        except Exception:
            pass

    except Exception as e:
        logger.warning("on_session_end failed (non-blocking): %s", e)
