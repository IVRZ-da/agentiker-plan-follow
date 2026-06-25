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
from typing import Any, Optional

from . import plan_core

# Re-Export für Test-Kompatibilität (Tests importieren _hook_cache etc. aus plan_hooks)
from .hooks import (
    _BANNER_COMPACT_EVERY_N_TURNS,
    _BANNER_FULL_EVERY_N_TURNS,
    _HEALTH_CACHE_KEY,
    _HEALTH_CACHE_TTL,
    _HOOK_CACHE_TTL,
    _banner_last_task_id,
    _banner_turn_counter,
    _build_banner,
    _build_compact_banner,
    _build_coordination_banner,
    _build_drift_banner,
    _build_due_banner,
    _build_git_banner,
    _build_health_banner,
    _build_review_banner,
    _build_roadmap_banner,
    _build_task_header,
    _build_tts_banner,
    _cached_or_fresh,
    _get_last_user_message,
    _has_plan_keywords,
    _hook_cache,
    _last_task_id,
    invalidate_hook_cache,
)
from .hooks.breaker import (  # noqa: F401 — Re-Export für Tests
    _BREAKER_CRITICAL_PREFIXES,
    _BREAKER_TTL,
    _breaker_state,
    _build_breaker_banner,
    _check_breaker,
    _set_breaker,
)

logger = logging.getLogger("plan_follow")

# Die folgenden imports sind Re-Exports für Tests (scheinbar unused, aber benötigt)
_HEALTH_CACHE_KEY  # noqa: F401
_HEALTH_CACHE_TTL  # noqa: F401
_HOOK_CACHE_TTL  # noqa: F401
_banner_last_task_id  # noqa: F401
_cached_or_fresh  # noqa: F401
_hook_cache  # noqa: F401
invalidate_hook_cache  # noqa: F401


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
