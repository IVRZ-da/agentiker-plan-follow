"""plan_hooks.py — pre_llm_call hook for plan-follow plugin (Facade).

Injects into EVERY user message before the LLM processes it:
1. Current task banner (if a plan is active) — ALWAYS first
2. Drift warnings (if unplanned changes detected)
3. Review status (required / passed / failed)
4. Health check warnings (at the END, never blocks the banner)

Core logic lives in hooks/ subpackage. This module re-exports everything
from hooks/ and adds the banner-builders that haven't been split out yet.
"""

import logging
import time
from typing import Any, Optional

from . import plan_core
from .hooks.base import (
    _BANNER_COMPACT_EVERY_N_TURNS,
    _BANNER_FULL_EVERY_N_TURNS,
    _HEALTH_CACHE_KEY,
    _HEALTH_CACHE_TTL,
    _banner_turn_counter,
    _build_banner,
    _build_compact_banner,
    _cached_or_fresh,
    _get_last_user_message,
    _has_plan_keywords,
    _hook_cache,
    _last_task_id,
)
from .hooks.breaker import (
    _BREAKER_CRITICAL_PREFIXES,
    _BREAKER_TTL,  # noqa: F401 — Re-Export für Tests
    _breaker_state,  # noqa: F401 — Re-Export für Tests
    _build_breaker_banner,
    _check_breaker,  # noqa: F401 — Re-Export für Tests
    _set_breaker,
)
from .plan_roadmap import _get_phase_progress

logger = logging.getLogger("plan_follow")


# ─── Banner-Builder (noch nicht in hooks/ ausgelagert) ─────────────────────


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
        from .plan_roadmap import _get_next_phases, get_active_roadmap

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

        if sessions:
            lines.append(f"║  👥 {len(sessions)} aktive Session(s)         ║")
            for sid, s in list(sessions.items())[:3]:
                goal_preview = s.get("goal", "")[:35]
                lines.append(f"║    • {sid[:20]}: {goal_preview}    ║")
            if len(sessions) > 3:
                lines.append(f"║    ... und {len(sessions) - 3} weitere        ║")

        current = plan_core.get_current_task_cached()
        if current and locks:
            other_locks = []
            task_files = current.get("files", [])
            for path, lock in locks.items():
                if any(f in path for f in task_files):
                    other_locks.append(path)
            if other_locks:
                lines.append("║  🔒 LOCKS: Dateien von anderer Session  ║")
                for lpath in other_locks[:2]:
                    lock_info = locks.get(lpath, {})
                    lines.append(
                        f"║    • {lpath[:45]} ({lock_info.get('session_id', '?')[:15]})    ║"
                    )

        notifs = coord_state.get_notifications(
            plan_core.get_session_id(), mark_read=False
        )
        if notifs:
            lines.append(f"║  📬 {len(notifs)} Nachricht(en) von anderen    ║")
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


def _build_health_banner() -> list[str]:
    """Build health check lines (cached, non-blocking, at end)."""
    lines = []
    try:
        from .tools.health import health_check as _health_check

        health = _cached_or_fresh(_HEALTH_CACHE_KEY, _health_check, ttl=_HEALTH_CACHE_TTL)
        if health and health.get("status") == "degraded":
            issues = health.get("issues", [])
            if issues:
                age_str = ""
                cached = _hook_cache.get(_HEALTH_CACHE_KEY)
                if cached:
                    _, ts = cached
                    age_sec = int(time.monotonic() - ts)
                    if age_sec > 60:
                        age_str = f" (Stand: vor {age_sec // 60} Min)"
                    elif age_sec > 10:
                        age_str = f" (Stand: vor {age_sec} Sek)"
                lines.append(f"║  ⚠️  SYSTEM HEALTH DEGRADED{age_str:46s}║")
                for issue in issues[:3]:
                    lines.append(f"║    • {issue[:55]}")
                if len(issues) > 3:
                    lines.append(f"║    ... and {len(issues) - 3} more")
                lines.append("║  (Arbeit trotzdem möglich)           ║")
    except Exception:
        pass
    return lines


def on_pre_llm_call(**kwargs: Any) -> Optional[str]:
    """Pre-LLM-call hook: inject plan context into user message.

    Uses Smart Banner logic:
    - Full banner: on plan changes, plan keywords, or every N turns
    - Compact banner: every N turns even without changes
    - None: rapid turns with no plan relevance
    """
    global _banner_turn_counter, _last_task_id, _banner_last_task_id

    try:
        current = plan_core.get_current_task_cached()
        if not current:
            return None

        _banner_turn_counter += 1
        task_id = current.get("task_id", "")

        task_changed = (task_id != _last_task_id)
        keywords_found = _has_plan_keywords(_get_last_user_message(kwargs))
        force_refresh = (_banner_turn_counter % _BANNER_FULL_EVERY_N_TURNS == 0)
        compact_turn = (_banner_turn_counter % _BANNER_COMPACT_EVERY_N_TURNS == 0)

        needs_full_banner = task_changed or keywords_found or force_refresh
        _last_task_id = task_id

        if needs_full_banner:
            _banner_last_task_id = task_id
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

        if compact_turn:
            return _build_compact_banner(current)

        return None

    except Exception as e:
        logger.warning("Task banner injection failed: %s", e)
        return None


# ─── post_tool_call Hook (Observability) ───────────────────────────────────────


def on_post_tool_call(**kwargs: Any) -> None:
    """Observe tool calls for metrics and auto-drift-tracking.

    Records:
    - Per-task tool call counters (category, duration, count)
    - Drift warnings when code_*/patch tools operate outside task.files
    """
    tool_name = kwargs.get("tool_name", "")
    duration = kwargs.get("duration_ms", 0)
    status = kwargs.get("status", "")
    error = kwargs.get("error", "")

    # Circuit Breaker: catch errors on critical tools
    if status == "error" and tool_name.startswith(_BREAKER_CRITICAL_PREFIXES):
        error_msg = str(error or kwargs.get("result", "Unknown error"))[:80]
        _set_breaker(tool_name, error_msg)

    if not tool_name.startswith(("plan_", "code_", "patch", "terminal")):
        return

    from .plan_core import (
        get_current_task_cached,
        record_drift_warning,
        record_tool_call,
    )

    record_tool_call(tool_name, duration, status)

    # Auto-Drift-Tracking
    if tool_name in (
        "code_refactor", "patch", "code_replace_body",
        "code_safe_delete", "code_insert_before", "code_insert_after",
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

            # Lock Enforcement
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
                    pass

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


# ─── on_session_end Hook ────────────────────────────────────────────────────────


def on_session_end(**kwargs: Any) -> None:
    """Session end: persist plan state, release locks, write final log entry."""
    try:
        # 1. Persist current plan state
        plan = plan_core._get_active_plan()
        if plan:
            plan["_last_session_end"] = __import__("datetime").datetime.now(
                __import__("zoneinfo").ZoneInfo("UTC")
            ).isoformat()
            plan_core._save_plan(plan)
            logger.info("Plan '%s' state persisted at session end", plan.get("plan_id"))

        # 2. Release all locks held by this session
        try:
            from . import coord_state
            session_id = plan_core.get_session_id()
            owned = [p for p, lock in coord_state.get_locks().items()
                     if lock.get("session_id") == session_id]
            for path in owned:
                coord_state.release_lock(path)
            if owned:
                logger.info("Released %d lock(s) at session end", len(owned))
        except Exception:
            pass

        # 3. Finalize session log
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
