"""plan_hooks.py — pre_llm_call hook for plan-follow plugin.

Injects into EVERY user message before the LLM processes it:
1. Current task banner (if a plan is active) — ALWAYS first
2. Drift warnings (if unplanned changes detected)
3. Review status (required / passed / failed)
4. Health check warnings (at the END, never blocks the banner)
"""

import logging
import os
import time
from typing import Any, Optional

from . import coord_state, plan_core

logger = logging.getLogger("plan_follow")

# ─── TTL Cache ─────────────────────────────────────────────────────────────────
# Cache health_check and drift results so they don't fire on EVERY LLM turn.
_hook_cache: dict = {}
_HOOK_CACHE_TTL = 60  # seconds

# ─── Banner-Frequenz-Reduzierung ────────────────────────────────────────────────
# Vermeidet Banner-Injection auf jedem Turn bei unveraendertem Task
_banner_turn_counter: int = 0
_BANNER_FULL_EVERY_N_TURNS = 4  # Voller Banner nur alle N Turns
_last_task_id: Optional[str] = None  # Task-Wechsel = sofort voller Banner

# ─── Banner-Recovery (einmal pro Session) ───────────────────────────────────────
# Nach einem Hermes-Restart ist der In-Memory-Cache leer. Der Banner kam deshalb
# erst, wenn irgendein plan_-Tool aufgerufen wurde. Recovery passiert jetzt beim
# ersten Turn einer Session — aber nur, wenn die Session den Plan besitzen darf
# (kein Cross-Session-Leak von Plaenen fremder Sessions im Gateway-Prozess).
_recovered_sessions: set[str] = set()

# ─── Cross-Session Auto-Coordination ────────────────────────────────────────────
# Track which task's files are currently locked, so we can release on task change.
_LAST_LOCKED_TASK: Optional[str] = None

# ─── TTS / Snapshot-State (v0.5.33) ───────────────────────────────────────────
# Der Renderpfad darf nichts schreiben. Angezeigte Events werden hier im Prozess
# gemerkt; den persistenten Water mark setzt post_tool_call (Observer).
_tts_announced_seq: int = 0
_tts_announced_legacy: set[str] = set()
_tts_pending_watermark: int = 0
_tts_pending_emitted: set[str] = set()
_epilogue_shown: set[str] = set()

# Git-/Drift-Snapshots: gefuellt in post_tool_call, gelesen im Renderpfad.
_git_snapshot: dict = {}
_git_snapshot_ts: float = 0.0
_drift_snapshot: list = []
_drift_snapshot_ts: float = 0.0
_drift_reported: tuple = ()
_SNAPSHOT_TTL = 120.0


def _hook_active_plan():
    """Plan fuer den Renderpfad: disk-frisch, aber OHNE Adoption.

    Tolerant gegen Monkeypatches ohne ``recover``-Parameter (Tests, Fremdcode) —
    in Produktion wird immer der adoptionsfreie Pfad benutzt, damit ein
    Lesezugriff keinen fremden Plan uebernehmen kann.
    """
    try:
        return plan_core._get_active_plan(recover=False)
    except TypeError:
        return plan_core._get_active_plan()


def _locks_enabled() -> bool:
    """Cross-Session-Locks sind opt-in (PLAN_FOLLOW_LOCKS=1), Default aus."""
    return os.environ.get("PLAN_FOLLOW_LOCKS", "").strip().lower() in ("1", "true", "yes", "on")


def _release_locks_for_plan(session_id: str, plan_id: str) -> int:
    """Alle Locks dieser Session freigeben (best-effort)."""
    try:
        return coord_state.release_all_locks(session_id)
    except Exception:
        logger.debug("release_all_locks failed", exc_info=True)
        return 0


def _do_coordination_housekeeping(current: Optional[dict], session_id: str = "") -> int:
    """Session-Heartbeat + optional Auto-Locks fuer den aktuellen Task.

    Aenderungen v0.5.33:
    * ``session_id`` kommt aus dem Hook-Payload — nicht aus dem prozessglobalen
      ``get_session_id()`` (im Gateway teilen sich sonst alle Sessions eine ID).
    * Locks nur mit ``PLAN_FOLLOW_LOCKS=1`` (Default aus): damit verschwindet die
      Fehlerklasse "Lock-Leiche" im Normalfall vollstaendig.
    * Ohne aktiven Task wird aufgeraeumt statt frueh zu returnen.
    """
    global _LAST_LOCKED_TASK

    sid = session_id or plan_core.get_session_id()
    if not sid:
        return 0

    plan = _hook_active_plan()
    plan_id = plan.get("plan_id", "") if plan else ""
    goal = plan.get("goal", "") if plan else ""

    registered = coord_state.get_session(sid)
    if registered:
        coord_state.update_session(sid, plan_id=plan_id, goal=goal)
    else:
        coord_state.register_session(sid, plan_id=plan_id, goal=goal)

    if not current:
        # Plan abgeschlossen/abgebrochen oder gar keiner: aufraeumen
        _release_locks_for_plan(sid, plan_id)
        _LAST_LOCKED_TASK = None
        if plan and _plan_finished(plan):
            # Abgeschlossener Plan darf nicht als aktiv gelten (Cross-Session)
            coord_state.update_session(sid, plan_id="", goal=goal)
        return 0

    if not _locks_enabled():
        # Kein Lock-Betrieb: nichts akquirieren (Default)
        return 0

    current_task_id = current.get("task_id", "")
    if _LAST_LOCKED_TASK and _LAST_LOCKED_TASK != current_task_id:
        coord_state.release_all_locks(sid)

    acquired_count = 0
    for f in current.get("files", []) or []:
        result = coord_state.acquire_lock(f, sid)
        if result.get("status") == "acquired":
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
        logger.debug("_cached_or_fresh: fetcher failed for key '%s'", key, exc_info=True)
        return None


_SEPARATOR = ""


def _safe_section(name: str, builder, *args, **kwargs) -> list[str]:
    """Banner-Teil rendern. Fehler werden sichtbar gemacht, nicht geschluckt."""
    try:
        return list(builder(*args, **kwargs) or [])
    except Exception as exc:
        logger.warning("Banner-Teil '%s' fehlgeschlagen: %s", name, exc)
        return [f"║  ⚠️ Banner-Teil {name} fehlgeschlagen: {type(exc).__name__}"]


def _provenance_line() -> str:
    """Woher kommt der Banner-Stand? Ohne diese Zeile war die Falschmeldung
    't1, 1/15' von einem echten Fortschritt nicht unterscheidbar."""
    stamp = time.strftime("%H:%M:%S")
    plan = None
    try:
        plan = _hook_active_plan()
    except Exception:
        plan = None
    if not plan:
        return f"Stand: {stamp} | Quelle: Hook | Cache: leer"
    plan_id = plan.get("plan_id", "")
    tasks = plan.get("tasks", {}) or {}
    done = sum(1 for t in tasks.values() if t.get("status") in ("completed", "aborted"))
    disk = "?"
    try:
        from .tools.base import _plan_path

        disk = time.strftime("%H:%M", time.localtime(_plan_path(plan_id).stat().st_mtime))
    except Exception:
        disk = "?"
    return f"Stand: {stamp} | Quelle: Disk {disk} | Tasks {done}/{len(tasks)} | Cache: frisch"


def _commit_tts_state() -> None:
    """Water mark + Epilog-Merker schreiben — nur aus Observer-Hooks."""
    global _tts_pending_watermark

    try:
        from .tools import tts_queue
    except Exception:
        return

    if _tts_pending_watermark:
        try:
            tts_queue.commit_watermark(_tts_pending_watermark)
            _tts_pending_watermark = 0
        except Exception:
            logger.debug("tts watermark commit failed", exc_info=True)

    for key in list(_tts_pending_emitted):
        try:
            tts_queue.mark_emitted(key)
            _tts_pending_emitted.discard(key)
        except Exception:
            logger.debug("epilogue mark_emitted failed", exc_info=True)


def _plan_finished(plan: dict) -> bool:
    """Alle Tasks completed/aborted? (plan-level 'status' wird nie geschrieben)"""
    tasks = plan.get("tasks") or {}
    if not tasks:
        return False
    return all(t.get("status") in ("completed", "aborted") for t in tasks.values())


def _epilogue_lines(session_id: str) -> list[str]:
    """Einmaliger Abschluss-Epilog: was ist fertig, was ist noch offen.

    Genau einmal pro (plan_id, session_id). Kein Dauer-Banner — der Banner ist
    bei erledigter Arbeit stumm, bis auf diese zwei Zeilen.
    """
    global _tts_pending_emitted

    plan = _hook_active_plan()
    if not plan or not _plan_finished(plan):
        return []

    plan_id = plan.get("plan_id", "")
    tasks = plan.get("tasks") or {}
    total = len(tasks)
    completed = sum(1 for t in tasks.values() if t.get("status") == "completed")
    aborted = sum(1 for t in tasks.values() if t.get("status") == "aborted")

    key = f"{plan_id}:{session_id}"
    if key in _epilogue_shown:
        return []
    try:
        from .tools import tts_queue

        if session_id and tts_queue.is_emitted(tts_queue.epilogue_key(plan_id, session_id)):
            _epilogue_shown.add(key)
            return []
        _tts_pending_emitted.add(tts_queue.epilogue_key(plan_id, session_id))
    except Exception:
        logger.debug("epilogue dedupe via tts_queue failed", exc_info=True)
    _epilogue_shown.add(key)

    if aborted:
        head = f"⛔ Plan abgebrochen: {plan_id} ({completed}/{total} erledigt, {aborted} abgebrochen)"
    else:
        head = f"✅ Plan abgeschlossen: {plan_id} ({completed}/{total})"

    offen: list[str] = []
    try:
        from .tools.base import resolve_archive_dir, resolve_plans_index

        if resolve_plans_index().exists():
            import json as _json

            try:
                index = _json.loads(resolve_plans_index().read_text(encoding="utf-8"))
            except (ValueError, OSError):
                index = {}
            if index.get("active_plan_id") == plan_id:
                offen.append("Index zeigt noch auf diesen Plan")
        if not (resolve_archive_dir() / f"{plan_id}.json").exists():
            offen.append("nicht archiviert")
    except Exception:
        logger.debug("epilogue open-items failed", exc_info=True)

    if _locks_enabled():
        try:
            own = [
                p
                for p, lock in coord_state.get_locks().items()
                if lock.get("session_id") == (session_id or plan_core.get_session_id())
            ]
            if own:
                offen.append(f"{len(own)} Lock(s) offen")
        except Exception:
            pass

    tail = "→ offen: " + " · ".join(offen) if offen else "→ offen: nichts"
    return [f"║  {head}", f"║  {tail}"]


def _build_banner(lines: list, session_id: str = "") -> Optional[str]:
    """Linien zu einer Box mit einheitlicher Breite machen.

    Bis v0.5.32 mischten die Builder Zeilen mit und ohne ``║``-Abschluss, die
    Box war sichtbar schief. Jetzt wird zentral gepolstert.
    """
    if not lines:
        return None

    footer = _provenance_line()
    body: list[str] = []
    for raw in list(lines) + [footer]:
        text = raw.strip()
        if text.startswith("║"):
            text = text[1:]
        text = text.rstrip()
        if text.endswith("║"):  # alte Builder haben den Rahmen selbst gepolstert
            text = text[:-1].rstrip()
        if text:
            body.append(text)

    width = max((len(t) for t in body), default=0)
    width = max(45, min(width, 96))
    body = [(t if len(t) <= width else t[: width - 1] + "…") for t in body]

    full = ["╔" + "═" * (width + 2) + "╗"]
    full.extend("║ " + t.ljust(width) + " ║" for t in body)
    full.append("╚" + "═" * (width + 2) + "╝")
    return "[PLAN] " + "\n[PLAN] ".join(full)


# ─── Banner-Builder ──────────────────────────────────────────────────────────


def _build_task_header(current: dict) -> list[str]:
    """Build task info header lines."""
    progress = current.get("progress", "")
    if len(progress) > 80:
        progress = progress[:77] + "…"
    lines = [
        f"║  CURRENT TASK: {current['task_id']} — {current['name'][:50]}",
        f"║  Files: {', '.join(current['files'][:3])}"
        + (" ..." if len(current["files"]) > 3 else ""),
        f"║  Progress: {progress}",
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
        logger.debug("_build_roadmap_banner failed (non-blocking)", exc_info=True)
    return lines


def _refresh_snapshots(force: bool = False) -> None:
    """Git-/Drift-Snapshots aktualisieren — nur aus Observer-Hooks aufrufen.

    Der Renderpfad darf keine Subprozesse starten: ``check_drift`` und
    ``get_git_status`` rufen ``git`` mit 10 s Timeout pro Repo. Im pre_llm_call
    war das ein Latenzpfad in jedem Cache-Miss-Turn.
    """
    global _git_snapshot, _git_snapshot_ts, _drift_snapshot, _drift_snapshot_ts

    now = time.monotonic()
    if not force and (now - _git_snapshot_ts) < _SNAPSHOT_TTL:
        return
    try:
        plan = _hook_active_plan()
        if not plan:
            return
        repos = plan_core._get_repos(plan) or []
        snapshot = {}
        for repo in repos[:3]:
            try:
                status = plan_core.get_git_status(repo)
            except Exception:
                continue
            if status and status.get("status") == "ok":
                snapshot[repo] = status
        _git_snapshot = snapshot
        _git_snapshot_ts = now

        try:
            _drift_snapshot = plan_core.check_drift() or []
        except Exception:
            _drift_snapshot = []
        _drift_snapshot_ts = now
    except Exception:
        logger.debug("_refresh_snapshots failed (non-blocking)", exc_info=True)


def _build_git_banner() -> list[str]:
    """Git-Status aus dem Snapshot — kein subprocess im Renderpfad."""
    lines = []
    try:
        if not _git_snapshot:
            return lines
        for repo, status in list(_git_snapshot.items())[:3]:
            repo_name = repo.rstrip("/").split("/")[-1]
            parts = [f"{repo_name}", f"🌿{status.get('branch', '?')}"]
            if status.get("dirty"):
                parts.append(f"💩+{status['dirty_files']}")
            ahead = status.get("ahead", 0)
            behind = status.get("behind", 0)
            if ahead and behind:
                parts.append(f"↑{ahead}↓{behind}")
            elif ahead:
                parts.append(f"↑{ahead}")
            elif behind:
                parts.append(f"↓{behind}")
            lines.append(f"║  📍 {' '.join(parts)}")
    except Exception as exc:
        logger.debug("git-banner failed", exc_info=True)
        lines.append(f"║  ⚠️ Banner-Teil git fehlgeschlagen: {type(exc).__name__}")
    return lines


def _build_drift_banner() -> list[str]:
    """Drift aus dem Snapshot + proaktive Warnungen — je Aenderung nur einmal."""
    global _drift_reported
    lines = []
    try:
        drift = list(_drift_snapshot)
        drift_warnings = plan_core.get_drift_warnings()

        signature = (tuple(drift), tuple(drift_warnings))
        if signature == _drift_reported:
            return lines
        _drift_reported = signature

        if drift:
            lines.append("║  ⚠️  DRIFT DETECTED")
            for f in drift[:3]:
                lines.append(f"║    {f[:60]}")
            if len(drift) > 3:
                lines.append(f"║    ... and {len(drift) - 3} more")
            lines.append("║  → plan_update() oder revert")

        if drift_warnings:
            lines.append("║  ⚠️  DRIFT WARNING (proaktiv)")
            for w in drift_warnings[:2]:
                lines.append(f"║    • {w[:55]}")
            if len(drift_warnings) > 2:
                lines.append(f"║    ... and {len(drift_warnings) - 2} more")
            lines.append("║  → Task-Eigenschaften prüfen")
    except Exception as exc:
        logger.debug("_build_drift_banner failed", exc_info=True)
        lines.append(f"║  ⚠️ Banner-Teil drift fehlgeschlagen: {type(exc).__name__}")
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
        logger.debug('_build_due_banner failed (non-blocking)', exc_info=True)
    return lines


# ─── Coordination Cache ──────────────────────────────────────────────────────
_coord_cache: dict = {}  # {key: (value, timestamp)}
_COORD_CACHE_TTL = 30  # Sekunden
_prev_coord_sig: str = ""  # Vorherige Signatur für Change-Detection


def _get_coord_snapshot() -> dict:
    """Hole gecachte coord_state-Snapshots (Sessions, Locks, Notifs)."""
    global _coord_cache
    now = time.monotonic()

    cached = _coord_cache.get("snapshot")
    if cached:
        val, ts = cached
        if now - ts < _COORD_CACHE_TTL:
            return val

    try:
        from . import coord_state

        val = {
            "sessions": coord_state.get_sessions(),
            "locks": coord_state.get_locks(),
            "my_sid": plan_core.get_session_id(),
            "notifs": coord_state.get_notifications(
                plan_core.get_session_id(), mark_read=False
            ),
        }
        _coord_cache["snapshot"] = (val, now)
        return val
    except Exception:
        logger.debug("_get_coord_snapshot failed", exc_info=True)
        return {}


def _coord_signature(data: dict) -> str:
    """Signatur: session_ids+lock_count+notif_count → Change-Detection."""
    sessions = data.get("sessions", {})
    locks = data.get("locks", {})
    notifs = data.get("notifs", [])
    sig = (
        f"{sorted(sessions.keys())}|{len(locks)}|{len(notifs)}"
        f"|{sum(1 for lk in locks.values() if lk.get('session_id') != data.get('my_sid'))}"
    )
    return sig


def _build_coordination_banner() -> list[str]:
    """Build cross-session coordination lines (best-effort, cached, compact-mode).

    Nutzt TTL-Cache (30s) + Change-Detection:
    - Unverändert → kompakter 1-Zeiler: "👥 3 Sessions, 🔒 2 Locks, 📬 1 Nachricht"
    - Geändert → voller Banner mit Details
    """
    global _prev_coord_sig

    data = _get_coord_snapshot()
    if not data:
        return []

    sessions = data.get("sessions", {})
    locks = data.get("locks", {})
    notifs = data.get("notifs", [])
    my_sid = data.get("my_sid")

    # Cleanup stale entries (cached, 60s TTL)
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
    except Exception:
        pass

    new_sig = _coord_signature(data)

    # ─── Compact-Mode: Nichts geändert → nur 1 Zeile ────────────────────────
    if new_sig == _prev_coord_sig:
        parts = []
        if sessions:
            parts.append(f"👥 {len(sessions)} Session(s)")
        if locks:
            parts.append(f"🔒 {len(locks)} Lock(s)")
        if notifs:
            parts.append(f"📬 {len(notifs)} Nachricht(en)")
        if parts:
            return [f"║  {'  '.join(parts)}                ║"]
        return []

    # ─── Full Mode: Etwas hat sich geändert → voller Banner ─────────────────
    _prev_coord_sig = new_sig
    lines = []

    # Session-Liste
    if sessions:
        lines.append(f"║  👥 {len(sessions)} aktive Session(s)                  ║")
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
            lines.append(f"║    ... und {len(sessions) - 3} weitere           ║")

    # Eigene Locks
    if my_sid and locks:
        my_locks = [
            p for p, lock in locks.items()
            if lock.get("session_id") == my_sid
        ]
        if my_locks:
            lines.append(f"║  🔒 Eigene Locks ({len(my_locks)})                 ║")
            for lp in my_locks[:2]:
                fname = lp.rstrip("/").rsplit("/", 1)[-1]
                lines.append(f"║    • {fname[:45]}                       ║")
            if len(my_locks) > 2:
                lines.append(f"║    ... und {len(my_locks) - 2} weitere           ║")

    # Stale-Locks (>30 Min)
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
            stale.sort(key=lambda x: -x[2])
            lines.append(f"║  ⏳ Stale-Locks ({len(stale)} >30 Min)             ║")
            for lpath, lock_info, age_min in stale[:2]:
                fname = lpath.rsplit("/", 1)[-1]
                locker_sid = lock_info.get("session_id", "?")[:16]
                lines.append(f"║    • {fname[:35]} ({locker_sid}, {age_min}m)    ║")

    # Locks von anderen auf unseren Task-Files
    current = plan_core.get_current_task_cached()
    if current and locks:
        task_files = current.get("files", [])
        other_locks = [
            (path, lock) for path, lock in locks.items()
            if any(f in path for f in task_files)
            and lock.get("session_id", "") != my_sid
        ]
        if other_locks:
            lines.append("║  ⚠️  LOCKS von anderen auf Task-Files    ║")
            for lpath, lock_info in other_locks[:2]:
                fname = lpath.rsplit("/", 1)[-1]
                locker_sid = lock_info.get("session_id", "?")[:16]
                lines.append(f"║    • {fname[:40]} (🔒 {locker_sid})    ║")

    # Notifications
    if notifs:
        lines.append(f"║  📬 {len(notifs)} Nachricht(en) von anderen       ║")
        latest = notifs[-1]
        from_msg = latest.get("from", "?")[:16]
        msg_preview = latest.get("message", "")[:35]
        lines.append(f"║    • {from_msg}: {msg_preview}            ║")
        lines.append("║    → plan_notify(action='check')            ║")

    # Repo-Konflikt
    current_plan = _hook_active_plan()
    if current_plan and len(sessions) > 1:
        my_repos = plan_core._get_repos(current_plan)
        if my_repos:
            plans_dir = plan_core.PLANS_DIR
            other_repo_sessions = set()
            for sid, s in sessions.items():
                if sid == my_sid:
                    continue
                other_pid = s.get("plan_id", "")
                if not other_pid:
                    continue
                other_file = plans_dir / f"{other_pid}.json"
                if not other_file.exists():
                    continue
                try:
                    import json
                    other_plan = json.loads(other_file.read_text())
                    other_repos = other_plan.get("repos", other_plan.get("repo", []))
                    if isinstance(other_repos, str):
                        other_repos = [other_repos]
                    overlap = set(other_repos) & set(my_repos)
                    other_repo_sessions.update(overlap)
                except Exception:
                    continue
            if other_repo_sessions:
                lines.append("║  ⚠️  Repo-Konflikt mit anderen Sessions!  ║")
                for r in list(other_repo_sessions)[:2]:
                    short = r.rsplit("/", 1)[-1] if "/" in r else r
                    lines.append(f"║    • {short[:45]}                    ║")
                lines.append("║    Git-Operationen können kollidieren   ║")

    return lines


def _build_tts_banner(session_id: str = "") -> list[str]:
    """TTS-Marker anzeigen — rein lesend.

    Quelle 1: ``tools/tts_queue.py`` (neue Events, seit dem letzten Water mark).
    Quelle 2: ``plan["tts_flags"]`` (Altbestand aus v0.5.32 und davor). Diese
    Flags werden nur noch gelesen und im Prozess als "schon angesagt" gemerkt —
    der Renderpfad schreibt die Plan-Datei nicht mehr.
    """
    global _tts_announced_seq, _tts_pending_watermark

    lines: list[str] = []
    try:
        from .tools import tts_queue

        active_plan = _hook_active_plan()
        if not active_plan:
            return lines
        plan_id = active_plan.get("plan_id", "")

        # ─── Neue Events aus der Queue ────────────────────────────────────
        if plan_id:
            try:
                events = tts_queue.read_events(plan_id, session_id, _tts_announced_seq)
            except Exception as exc:
                logger.warning("tts_queue nicht lesbar: %s", exc)
                events = []

            for event in events:
                kind = event.get("kind", "")
                if kind == "plan_created":
                    goal = (event.get("message") or active_plan.get("goal", ""))[:42]
                    lines.append(
                        f"║  [TTS:event=plan_created:message=Plan erstellt: {goal}]"
                    )
                elif kind == "task_completed":
                    name = (event.get("name") or event.get("task_id") or "")[:38]
                    lines.append(
                        f"║  [TTS:event=task_completed:message=Aufgabe abgeschlossen: {name}]"
                    )

            if events:
                _tts_announced_seq = max(
                    _tts_announced_seq, max(int(e.get("seq") or 0) for e in events)
                )
                _tts_pending_watermark = _tts_announced_seq

        # ─── Legacy-Flags im Plan (nur lesen) ─────────────────────────────
        flags = active_plan.get("tts_flags") or {}
        if isinstance(flags, dict):
            if flags.get("plan_created") and "plan_created" not in _tts_announced_legacy:
                goal_text = active_plan.get("goal", "Plan created")[:42]
                task_count = len(active_plan.get("tasks", {}))
                lines.append(
                    f"║  [TTS:event=plan_created:message=Plan erstellt: {goal_text}]"
                    f" ({task_count} Tasks)"
                )
                _tts_announced_legacy.add("plan_created")

            for completed_id in list(flags.get("task_completed") or []):
                key = f"task_completed:{completed_id}"
                if key in _tts_announced_legacy:
                    continue
                task = active_plan.get("tasks", {}).get(completed_id, {})
                name = (task.get("name") or completed_id)[:38]
                lines.append(
                    f"║  [TTS:event=task_completed:message=Aufgabe abgeschlossen: {name}]"
                )
                _tts_announced_legacy.add(key)

            # review_failed wird nicht mehr unterstuetzt: es gab nie einen Writer.
    except Exception as exc:  # nie still schlucken
        logger.warning("TTS-Banner fehlgeschlagen: %s", exc)
        lines.append(f"║  ⚠️ Banner-Teil tts fehlgeschlagen: {type(exc).__name__}")
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
    """Health-Zustand mit Zeitstempel — DEGRADED erst nach 2 Fehlschlaegen."""
    lines = []
    try:
        from .tools import health as health_mod

        # Kein Cache: der Check ist jetzt billig (keine HTTP-Calls ohne
        # PLAN_FOLLOW_VERBOSE_HEALTH) und muss Fehler sichtbar machen koennen.
        result = health_mod.health_check() or {}
        age = health_mod.health_age_seconds()
        age_txt = f"geprüft vor {int(age)}s" if age is not None else "ungeprüft"

        if result.get("status") == "degraded":
            lines.append(f"║  ⚠️ SYSTEM HEALTH DEGRADED ({age_txt})")
            for issue in (result.get("issues") or [])[:3]:
                lines.append(f"║    • {str(issue)[:55]}")
            lines.append("║  (Arbeit trotzdem möglich)")
        elif result.get("pending"):
            lines.append(f"║  ℹ️ Health: 1 Fehlschlag ({age_txt}) — noch nicht DEGRADED")
    except Exception as exc:
        logger.warning("health-banner failed: %s", exc)
        lines.append(f"║  ⚠️ Banner-Teil health fehlgeschlagen: {type(exc).__name__}")
    return lines


def _build_tool_check_banner() -> list[str]:
    """Tool-Verfuegbarkeit aus dem geladenen Zustand — eine Zeile, keine Imports.

    Fruehere Version importierte ``code_intel``/``scout``/``plan_follow`` live und
    zeigte "❌", weil das Plugin-Verzeichnis nicht in ``sys.path`` liegt. Die
    Tools liefen trotzdem. Ausserdem stand hier eine projektspezifische
    Tool-Hierarchie in einem generischen Plugin.
    """
    lines = []
    try:
        from .tools import health as health_mod

        state = health_mod.loaded_plugins()
        parts = [f"{name} {'✓' if ok else '?'}" for name, ok in state.items()]
        lines.append("║  🛠️  " + " · ".join(parts))
    except Exception as exc:
        logger.debug("tool-check-banner failed", exc_info=True)
        lines.append(f"║  ⚠️ Banner-Teil tools fehlgeschlagen: {type(exc).__name__}")
    return lines


# ─── pre_llm_call Hook ──────────────────────────────────────────────────────


def _try_session_recovery(kwargs: dict) -> None:
    """Adoptiert beim ersten Turn einer Session einen Plan von Disk — mit Besitzpruefung.

    Ohne diese Recovery blieb der Banner nach einem Hermes-Restart stumm, bis
    irgendein plan_-Tool lief. Ohne Besitzpruefung wuerde ein Gateway-Prozess,
    der mehrere Sessions bedient, den Plan von Session A in Session B anzeigen
    (STATE ist prozessglobal) und zusaetzlich fremde Task-Dateien locken.
    """
    if not kwargs.get("is_first_turn"):
        return

    session_id = str(kwargs.get("session_id") or "")
    if not session_id or session_id in _recovered_sessions:
        return
    _recovered_sessions.add(session_id)

    from .tools.state import STATE

    if STATE.active_plan is not None:
        return

    # Wichtig: NICHT _get_active_plan() benutzen — das adoptiert den Plan bereits
    # in STATE, bevor die Besitzpruefung greifen kann. _recover_plan_from_disk()
    # liefert nur die plan_id und laesst STATE unangetastet.
    try:
        from .tools.base import _recover_plan_from_disk

        plan_id = _recover_plan_from_disk()
    except Exception as exc:  # Recovery ist best-effort
        logger.debug("plan_follow: Banner-Recovery fehlgeschlagen: %s", exc)
        return

    if not plan_id:
        return

    owner = ""
    try:
        from . import coord_state

        owner = (coord_state.get_session(session_id) or {}).get("plan_id") or ""
    except Exception:  # Koordinations-State optional
        owner = ""

    if owner and owner != plan_id:
        logger.info(
            "plan_follow: Banner-Recovery uebersprungen — Session %s gehoert zu Plan %s (nicht %s)",
            session_id[:8], owner, plan_id,
        )
        return

    try:
        from .tools.task import set_active_plan

        if not set_active_plan(plan_id):
            return
    except Exception as exc:
        logger.debug("plan_follow: Banner-Recovery (Adoption) fehlgeschlagen: %s", exc)
        return

    logger.info(
        "plan_follow: Banner-Recovery fuer Session %s -> Plan %s", session_id[:8], plan_id
    )


def on_pre_llm_call(**kwargs: Any) -> Optional[str]:
    """Pre-LLM-call hook: inject plan context into user message.

    Registered via PluginContext.register_hook("pre_llm_call", ...).
    Baut Banner mit reduzierter Frequenz (alle N Turns, es sei denn Task wechselt).
    ALWAYS returns None if no active plan (nothing to inject).
    """
    global _banner_turn_counter, _last_task_id

    try:
        _try_session_recovery(kwargs)

        # Session-Identitaet aus dem Hook-Payload. Sie ist prozessglobal NICHT
        # ableitbar (get_session_id() cached den ersten Wert) — im Gateway wuerde
        # sonst jede Session den Plan der ersten sehen.
        session_id = str(kwargs.get("session_id") or "")
        if session_id:
            # Disk-frisch + Besitzpruefung: der Banner zeigt nur, was diese
            # Session besitzt und was auf der Platte steht.
            current = plan_core.get_current_task_fresh(session_id)
        else:
            current = plan_core.get_current_task_cached()
        if not current:
            # Kein aktiver Task: aufraeumen und ggf. den Abschluss einmal melden.
            try:
                _do_coordination_housekeeping(None, session_id=session_id)
            except Exception:
                logger.debug("housekeeping ohne Task fehlgeschlagen", exc_info=True)

            epilogue = _safe_section("epilogue", _epilogue_lines, session_id)
            if epilogue:
                return _build_banner(epilogue, session_id=session_id)
            return None

        # ─── Banner-Frequenz-Check ─────────────────────────────────────────
        # Task gewechselt? → sofort voller Banner + Counter reset
        task_id = current.get("task_id", "")
        if task_id != _last_task_id:
            _last_task_id = task_id
            _banner_turn_counter = 0
        else:
            _banner_turn_counter += 1
            if _banner_turn_counter < _BANNER_FULL_EVERY_N_TURNS:
                # Bei gleichem Task: Banner nur alle _BANNER_FULL_EVERY_N_TURNS Turns
                return None

        # Counter reset fuer naechste Runde
        _banner_turn_counter = 0

        # ─── Auto-Coordination Housekeeping ─────────────────────────────
        # Session heartbeat + auto-lock task files (Lock nur mit Flag)
        try:
            _do_coordination_housekeeping(current, session_id=session_id)
        except Exception:
            pass  # Best-effort

        # Build banner sections — jeder Teil einzeln abgesichert, damit ein
        # defekter Builder sichtbar wird statt den ganzen Banner zu verschlucken.
        lines = _build_task_header(current)
        sections = [
            _safe_section("tools", _build_tool_check_banner),
            _safe_section("git", _build_git_banner),
            _safe_section("roadmap", _build_roadmap_banner),
            _safe_section("drift", _build_drift_banner),
            _safe_section("due", _build_due_banner),
            _safe_section("coord", _build_coordination_banner),
            _safe_section("tts", _build_tts_banner, session_id),
            _safe_section("review", _build_review_banner, current),
            _safe_section("health", _build_health_banner),
            _safe_section("breaker", _build_breaker_banner),
        ]
        for produced in sections:
            if produced:
                lines.append(_SEPARATOR)
                lines.extend(produced)

        return _build_banner(lines, session_id=session_id)
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
    # Hermes sendet seit v0.23.1 error_type/error_message, NICHT 'error'.
    # Vorher las der Hook kwargs['error'] (immer leer) und fiel auf kwargs['result']
    # zurueck -> der Breaker-Banner zeigte rohe Tool-Ausgabe statt der Ursache.
    error_type = kwargs.get("error_type", "") or ""
    error_message = kwargs.get("error_message", "") or kwargs.get("error", "") or ""

    # ─── Circuit Breaker ────────────────────────────────────────────────────
    # Check BEFORE the early-return filter so firecrawl/honcho failures are caught
    if status == "error" and tool_name.startswith(_BREAKER_CRITICAL_PREFIXES):
        detail = str(error_message).strip() or "(no error message)"
        if error_type:
            detail = f"{error_type}: {detail}"
        _set_breaker(tool_name, detail)

    # ─── TTS-Watermark + Epilog-Merker persistieren ─────────────────────────
    # Der Renderpfad ist rein lesend; hier (Observer) wird der Fortschritt
    # festgeschrieben, damit nach einem Restart nichts doppelt angesagt wird.
    _commit_tts_state()

    # ─── Git-/Drift-Snapshots aktualisieren ─────────────────────────────────
    # Subprozesse gehoeren hierher, nicht in pre_llm_call.
    _refresh_snapshots()

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

    # ─── Cross-Session Warning für Tests/Builds/Git ────────────────────────
    # Wenn terminal() mit pytest/build/git-commit aufgerufen wird und andere
    # Sessions aktiv sind, warnen — unabhängig von Git-Repos.
    if tool_name == "terminal":
        args = kwargs.get("args", {}) or {}
        cmd = (args.get("command", "") if isinstance(args, dict) else "")[:200]
        if cmd and any(
            cmd.startswith(p) or f" {p}" in cmd
            for p in ("pytest", "medusa build", "next build", "npm run build",
                      "yarn build", "git commit", "git push", "git merge", "git rebase")
        ):
            try:
                from . import coord_state

                my_sid = plan_core.get_session_id()
                sessions = coord_state.get_sessions()
                other_sessions = {
                    sid: s for sid, s in sessions.items()
                    if sid != my_sid
                }
                if other_sessions:
                    other_names = []
                    for sid, s in list(other_sessions.items())[:3]:
                        label = s.get("plan_id", "")[:25] or sid[:16]
                        other_names.append(label)
                    msg = (
                        f"⚠️ Cross-Session Konflikt: '{cmd[:50]}' ausgeführt, "
                        f"während {len(other_sessions)} andere Session(s) aktiv sind: "
                        f"{', '.join(other_names)}. Ergebnisse können inkonsistent sein!"
                    )
                    record_drift_warning(msg)

                    # Auto-notify the other sessions
                    for sid in other_sessions:
                        try:
                            coord_state.send_notification(
                                from_session=my_sid,
                                to_session=sid,
                                message=f"⚠️ Führe '{cmd[:60]}' aus — bin in deinem Projekt aktiv!",
                                kind="warning",
                            )
                        except Exception:
                            logger.debug(
                                "cross-session notify to %s failed", sid[:16]
                            )
            except Exception:
                logger.debug(
                    "cross-session terminal check failed", exc_info=True
                )

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
                                logger.debug('on_post_tool_call: auto-notify failed', exc_info=True)

                    # Auto-Lock: Acquire lock on the file being edited
                    if my_sid:
                        lock_result = coord_state.acquire_lock(file_path, my_sid)
                        if lock_result.get("status") == "acquired":
                            logger.debug(
                                "Auto-Lock: '%s' für Session '%s' erworben",
                                file_path, my_sid[:20]
                            )
                except Exception:
                    logger.debug('on_post_tool_call: auto-lock/check failed', exc_info=True)

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
        session_id_for_recovery = str(kwargs.get("session_id") or "")
        if session_id_for_recovery:
            _recovered_sessions.discard(session_id_for_recovery)
        # 1. Persist current plan state
        plan = _hook_active_plan()
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
            logger.debug('on_session_end: lock release failed', exc_info=True)

        # 3. Unregister session
        try:
            from . import coord_state

            session_id = plan_core.get_session_id()
            if session_id:
                coord_state.unregister_session(session_id)
                logger.info("Session '%s' unregistered at session end", session_id[:20])
        except Exception:
            logger.debug('on_session_end: unregister failed', exc_info=True)

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
            logger.debug('on_session_end: log finalize failed', exc_info=True)

    except Exception as e:
        logger.warning("on_session_end failed (non-blocking): %s", e)
