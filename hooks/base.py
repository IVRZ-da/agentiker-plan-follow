"""hooks/base.py — Shared base for plan_follow hooks.

TTL Cache, banner builder, smart banner state, keyword detection.
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("plan_follow")

# ─── TTL Cache ─────────────────────────────────────────────────────────────────
_hook_cache: dict = {}
_HOOK_CACHE_TTL = 300  # seconds (5 min)
_HEALTH_CACHE_TTL = 600  # seconds (10 min)
_HEALTH_CACHE_KEY = "health_v2"

# ─── Smart Banner State ────────────────────────────────────────────────────────
_banner_turn_counter: int = 0
_BANNER_FULL_EVERY_N_TURNS = 5
_BANNER_COMPACT_EVERY_N_TURNS = 2
_last_task_id: str = ""
_banner_last_task_id: str = ""

_PLAN_KEYWORDS = {
    "plan", "task", "phase", "hook", "banner", "status", "progress",
    "complete", "completed", "abschliessen", "fertig", "done",
    "weiter", "next", "offen", "was gibt", "was steht",
    "a0", "a1", "a2", "a3", "a4", "a5", "f1", "f2", "p0",
    "roadmap", "hook-verbesserung",
}


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


def invalidate_hook_cache() -> None:
    """Invalidate all cached hook data (health, drift, git status, etc.).
    Call this when the plan changes (task completed, plan switched, etc.)
    so the next banner shows fresh data."""
    _hook_cache.clear()
    # Reset smart banner counter so next turn shows full banner
    global _banner_turn_counter
    _banner_turn_counter = 0


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


def _has_plan_keywords(text: str) -> bool:
    """Check if user message contains plan-relevant keywords."""
    if not text:
        return False
    lower = text.lower()
    for kw in _PLAN_KEYWORDS:
        if kw in lower:
            return True
    return False


def _get_last_user_message(kwargs: dict) -> str:
    """Extract the last user message from Hermes kwargs."""
    messages = kwargs.get("messages", [])
    if not messages:
        return ""
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, str):
                return content
    return ""


def _build_compact_banner(current: dict) -> str:
    """1-line compact banner for rapid turns (no changes)."""
    task_id = current.get("task_id", "?")
    task_name = current.get("name", "?")[:40]
    progress = current.get("progress", "?")
    return _build_banner([
        f"║  📋 [{task_id}] {task_name}  {progress:>20}  ║",
    ]) or ""


# ─── Banner-Builder (aus plan_hooks.py ausgelagert) ──────────────────────


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
        from ..plan_roadmap import _get_next_phases, _get_phase_progress, get_active_roadmap

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
        from .. import plan_core

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
        from .. import plan_core as _pc

        drift = _cached_or_fresh("drift", _pc.check_drift)
        if drift:
            lines.append("║  ⚠️  DRIFT DETECTED                   ║")
            for f in drift[:3]:
                lines.append(f"║    {f[:60]}")
            if len(drift) > 3:
                lines.append(f"║    ... and {len(drift) - 3} more")
            lines.append("║  → plan_update() oder revert          ║")

        drift_warnings = _pc.get_drift_warnings()
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
        from .. import plan_core as _pc

        due_info = _pc.get_task_due_info()
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
        from .. import coord_state
        from .. import plan_core as _pc

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

        current = _pc.get_current_task_cached()
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
            _pc.get_session_id(), mark_read=False
        )
        if notifs:
            lines.append(f"║  📬 {len(notifs)} Nachricht(en) von anderen    ║")
            lines.append("║    → plan_notify(action='check')          ║")

        # ─── Worker-Event-Check ────────────────────────────────────
        try:
            from ..tools.base import _kanban_available
            if _kanban_available():
                from hermes_cli import kanban_db as _kdb

                from ..tools.state import STATE
                if STATE.kanban_root_id:
                    _conn = _kdb.connect(board='plans')
                    _result = _kdb.claim_unseen_events_for_sub(
                        _conn, task_id=STATE.kanban_root_id,
                        platform="hermes", chat_id=_pc.get_session_id(),
                    )
                    if _result:
                        _old, _new, _events = _result
                        if _events:
                            crashed = [e for e in _events if e.kind == "crashed"]
                            blocked = [e for e in _events if e.kind == "blocked"]
                            completed = [e for e in _events if e.kind == "completed"]
                            if crashed:
                                lines.append(f"║  🔴 {len(crashed)} Worker-Crash(s)          ║")
                            if blocked:
                                lines.append(f"║  🚫 {len(blocked)} Task(s) blocked          ║")
                            if completed:
                                lines.append(f"║  ✅ {len(completed)} Task(s) completed       ║")
                    _conn.close()
        except Exception:
            pass
    except Exception:
        pass
    return lines


def _build_tts_banner() -> list[str]:
    """Build TTS event marker lines (best-effort, clears flags after display)."""
    lines = []
    try:
        from .. import plan_core as _pc

        active_plan = _pc._get_active_plan()
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
        _pc._save_plan(active_plan)
    except Exception as e:
        logger.warning("TTS flag save failed (non-blocking): %s", e)
    return lines


def _build_review_banner(current: dict) -> list[str]:
    """Build review status lines (best-effort)."""
    lines = []
    try:
        from .. import plan_core as _pc

        review_profile = current.get("review_profile", "none")
        if review_profile == "none":
            return lines
        review_state = _pc.get_task_review_state(current)
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
    import time

    lines = []
    try:
        from ..tools.health import health_check as _health_check

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
