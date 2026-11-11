"""coord_state.py — Shared State File-Layer für Cross-Session-Koordination.

Verwaltet:
  - sessions.json (aktive Sessions mit Plan-ID + Metadaten)
  - locks.json (Ressourcen-Locks für Dateien/Pfade)

Atomic Writes via tempfile + rename. KEINE Git-Abhängigkeit.
Fehlertolerant — Einzelfehler blockieren nicht die gesamte Koordination.
"""

import fcntl
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .tools.paths import assert_writable

logger = logging.getLogger("plan_follow")

SHARED_DIR = Path(
    os.environ.get("PLAN_FOLLOW_SHARED_DIR") or (Path.home() / ".hermes" / "shared")
)
SESSIONS_FILE = SHARED_DIR / "sessions.json"
LOCKS_FILE = SHARED_DIR / "locks.json"

_SHARED_DIR_INIT = False


def set_shared_dir(path: Path) -> None:
    """Set a custom shared directory (for testing). Updates all file paths."""
    global SHARED_DIR, SESSIONS_FILE, LOCKS_FILE, NOTIFICATIONS_FILE, _SHARED_DIR_INIT
    SHARED_DIR = path
    SESSIONS_FILE = path / "sessions.json"
    LOCKS_FILE = path / "locks.json"
    NOTIFICATIONS_FILE = path / "notifications.json"
    _SHARED_DIR_INIT = False


def _acquire_file_lock(path: Path, shared: bool = False) -> int:
    """Acquire fcntl flock on a .lock file for the given path.

    Creates/open a .lock file next to the target and acquires:
    - exclusive lock (shared=False, default) for writes
    - shared lock (shared=True) for reads

    Returns the fd (caller MUST close it or use contextmanager).
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not lock_path.exists():
        lock_path.touch()
    flag = fcntl.LOCK_SH if shared else fcntl.LOCK_EX
    fd = os.open(str(lock_path), os.O_RDONLY)
    try:
        fcntl.flock(fd, flag)
    except Exception:
        os.close(fd)
        raise
    return fd


def _release_file_lock(fd: int) -> None:
    """Release a flock and close the fd."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _ensure_shared_dir():
    """Einmalige Initialisierung des shared-Verzeichnisses."""
    global _SHARED_DIR_INIT
    if not _SHARED_DIR_INIT:
        assert_writable(SHARED_DIR)
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        _SHARED_DIR_INIT = True


def _atomic_write(path: Path, data: dict) -> None:
    """Atomic write: tempfile → rename. Verhindert corrupted reads.

    Uses fcntl flock on a .lock file for cross-session coordination.
    """
    assert_writable(path)
    _ensure_shared_dir()
    lock_fd = _acquire_file_lock(path, shared=False)
    try:
        fd, tmp = tempfile.mkstemp(dir=str(SHARED_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, str(path))
        except Exception as e:
            logger.warning("atomic_write failed for %s: %s", path, e)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        _release_file_lock(lock_fd)


def _atomic_read(path: Path) -> dict:
    """Read JSON with flock guard and fallback auf leeres Dict.

    Uses shared fcntl flock to prevent reading stale/corrupted data
    while another session is writing.
    """
    if not path.exists():
        return {}
    lock_fd = _acquire_file_lock(path, shared=True)
    try:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    finally:
        _release_file_lock(lock_fd)


# ─── Serialisierung von Read-modify-write ────────────────────────────────────
# ``_atomic_read`` und ``_atomic_write`` sichern je EINEN Zugriff. Zwischen
# Lesen und Schreiben konnte eine andere Session dazwischenfunken — dann
# ueberschrieb der zweite Write die Aenderung des ersten (verlorener Lock).
# Alle mutierenden Funktionen halten deshalb eine gemeinsame State-Lock ueber
# den kompletten Zyklus. Reihenfolge ist ueberall: State-Lock → Datei-Lock.

@contextmanager
def _state_lock():
    """Exklusive Lock ueber einen Read-modify-write-Zyklus."""
    _ensure_shared_dir()
    lock_file = SHARED_DIR / ".state.lock"
    fd = None
    try:
        fd = os.open(str(lock_file), os.O_CREAT | os.O_RDONLY, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _normalize_path(path: str) -> str:
    """Lock-Pfad kanonisieren.

    Bisher standen relative ("tests/conftest.py") und absolute Pfade
    nebeneinander, was Zuordnung und Anzeige unzuverlaessig machte.
    Repo-relative Aufloesung braucht ``plan.repo`` und passiert im Aufrufer;
    hier wird nur die Schreibweise vereinheitlicht.
    """
    if not path:
        return path
    return os.path.normpath(path)


# ─── Session Management ───────────────────────────────────────────────────────


def register_session(
    session_id: str,
    plan_id: str = "",
    goal: str = "",
    cwd: str = "",
) -> dict:
    """Register a session in shared state. Returns the sessions dict."""
    now = datetime.now(timezone.utc).isoformat()
    sessions = _atomic_read(SESSIONS_FILE)
    sessions[session_id] = {
        "registered": now,
        "last_seen": now,
        "plan_id": plan_id,
        "goal": goal,
        "cwd": cwd,
    }
    _atomic_write(SESSIONS_FILE, sessions)
    return sessions


def unregister_session(session_id: str) -> dict:
    """Remove a session from shared state. Returns updated sessions dict."""
    sessions = _atomic_read(SESSIONS_FILE)
    sessions.pop(session_id, None)
    _atomic_write(SESSIONS_FILE, sessions)
    return sessions


def update_session(session_id: str, **kwargs) -> dict:
    """Update session fields (plan_id, goal, cwd, last_seen)."""
    sessions = _atomic_read(SESSIONS_FILE)
    if session_id not in sessions:
        return sessions
    now = datetime.now(timezone.utc).isoformat()
    sessions[session_id]["last_seen"] = now
    for key in ("plan_id", "goal", "cwd"):
        if key in kwargs:
            sessions[session_id][key] = kwargs[key]
    _atomic_write(SESSIONS_FILE, sessions)
    return sessions


def get_sessions() -> dict:
    """Get all active sessions."""
    return _atomic_read(SESSIONS_FILE)


def get_session(session_id: str) -> Optional[dict]:
    """Get a single session by ID."""
    sessions = _atomic_read(SESSIONS_FILE)
    return sessions.get(session_id)


def cleanup_stale_sessions(max_age_minutes: int = 60) -> int:
    """Remove sessions older than max_age_minutes. Returns count removed."""
    with _state_lock():
        return _cleanup_stale_sessions_locked(max_age_minutes)


def _cleanup_stale_sessions_locked(max_age_minutes: int) -> int:
    sessions = _atomic_read(SESSIONS_FILE)
    now = datetime.now(timezone.utc)
    stale = []
    for sid, s in sessions.items():
        last = s.get("last_seen", s.get("registered", ""))
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds() / 60
            if age > max_age_minutes:
                stale.append(sid)
        except (ValueError, TypeError):
            stale.append(sid)
    for sid in stale:
        sessions.pop(sid, None)
    if stale:
        _atomic_write(SESSIONS_FILE, sessions)
    return len(stale)


# Einheitliche Schwellen: Anzeige und Cleanup benutzen dieselben Werte.
# Vorher zeigte der Banner ">30 Min" als stale, waehrend cleanup 120 Min wartete.
LOCK_STALE_MIN = 30
SESSION_STALE_MIN = 60


# ─── Lock Management ──────────────────────────────────────────────────────────


def acquire_lock(path: str, session_id: str) -> dict:
    """Acquire a lock on a file/path for a session.

    Auto-sends notification to the current holder if lock is taken.
    Returns:
        {"status": "acquired" | "exists" | "error",
         "locked_by": session_id or current holder}
    """
    path = _normalize_path(path)
    with _state_lock():
        return _acquire_lock_locked(path, session_id)


def _acquire_lock_locked(path: str, session_id: str) -> dict:
    locks = _atomic_read(LOCKS_FILE)
    if path in locks:
        holder = locks[path].get("session_id", "unknown")
        if holder != session_id:
            # Auto-Notify the current holder about the conflict
            try:
                send_notification(
                    from_session=session_id,
                    to_session=holder,
                    message=f"Lock-Konflikt: {path}",
                    kind="warning",
                )
            except Exception:
                logger.debug("acquire_lock: notification to %s failed", holder)
            return {"status": "exists", "locked_by": holder}
        # Same session — renew
        now_iso = datetime.now(timezone.utc).isoformat()
        locks[path]["since"] = now_iso
        locks[path]["heartbeat"] = now_iso
        _atomic_write(LOCKS_FILE, locks)
        return {"status": "acquired", "locked_by": session_id}

    now_iso = datetime.now(timezone.utc).isoformat()
    locks[path] = {
        "session_id": session_id,
        "since": now_iso,
        "heartbeat": now_iso,
    }
    _atomic_write(LOCKS_FILE, locks)
    return {"status": "acquired", "locked_by": session_id}


def release_lock(path: str, session_id: str) -> dict:
    """Release a lock. Only the holder can release.

    Returns:
        {"status": "released" | "not_locked" | "not_holder"}
    """
    path = _normalize_path(path)
    with _state_lock():
        return _release_lock_locked(path, session_id)


def _release_lock_locked(path: str, session_id: str) -> dict:
    locks = _atomic_read(LOCKS_FILE)
    if path not in locks:
        return {"status": "not_locked", "locked_by": None}
    if locks[path].get("session_id") != session_id:
        return {"status": "not_holder", "locked_by": locks[path].get("session_id")}
    locks.pop(path, None)
    _atomic_write(LOCKS_FILE, locks)
    return {"status": "released", "locked_by": None}


def get_locks() -> dict:
    """Get all active locks."""
    return _atomic_read(LOCKS_FILE)


def get_lock(path: str) -> Optional[dict]:
    """Get lock info for a specific path."""
    locks = _atomic_read(LOCKS_FILE)
    return locks.get(_normalize_path(path))


def release_all_locks(session_id: str) -> int:
    """Release ALL locks held by a session. Returns count released.

    Called when a session ends or on task completion.
    """
    with _state_lock():
        return _release_all_locks_locked(session_id)


def _release_all_locks_locked(session_id: str) -> int:
    locks = _atomic_read(LOCKS_FILE)
    to_release = [p for p, lock in locks.items()
                  if lock.get("session_id") == session_id]
    for p in to_release:
        locks.pop(p, None)
    if to_release:
        _atomic_write(LOCKS_FILE, locks)
    return len(to_release)


def get_locks_by_session(session_id: str) -> dict:
    """Get all locks held by a specific session."""
    locks = _atomic_read(LOCKS_FILE)
    return {p: lock for p, lock in locks.items()
            if lock.get("session_id") == session_id}


def cleanup_stale_locks(max_age_minutes: int = 120) -> int:
    """Locks freigeben — aber nur, wenn der Besitzer wirklich weg ist.

    v0.5.33: Ein Lock wird nicht mehr allein nach Alter freigegeben. Sonst gibt
    eine fremde Session den Lock einer Session frei, die gerade nur lange in
    einem Tool-Call (Build, Testsuite, Subagent) steckt und deshalb keinen
    Heartbeat schreibt. Freigabe nur, wenn zusaetzlich die Besitzer-Session
    fehlt oder selbst stale ist.
    """
    with _state_lock():
        return _cleanup_stale_locks_locked(max_age_minutes)


def _cleanup_stale_locks_locked(max_age_minutes: int) -> int:
    locks = _atomic_read(LOCKS_FILE)
    sessions = _atomic_read(SESSIONS_FILE)
    now = datetime.now(timezone.utc)

    def _owner_alive(session_id: str) -> bool:
        entry = sessions.get(session_id)
        if not entry:
            return False
        last = entry.get("last_seen") or entry.get("registered") or ""
        try:
            age = (now - datetime.fromisoformat(last)).total_seconds() / 60
        except (ValueError, TypeError):
            return False
        return age <= SESSION_STALE_MIN

    stale = []
    for p, lock in locks.items():
        since = lock.get("heartbeat") or lock.get("since", "")
        try:
            age = (now - datetime.fromisoformat(since)).total_seconds() / 60
        except (ValueError, TypeError):
            stale.append(p)
            continue
        if age <= max_age_minutes:
            continue
        if _owner_alive(lock.get("session_id", "")):
            continue
        stale.append(p)

    for p in stale:
        locks.pop(p, None)
    if stale:
        _atomic_write(LOCKS_FILE, locks)
    return len(stale)


# ─── Notification Management ──────────────────────────────────────────────────


NOTIFICATIONS_FILE = SHARED_DIR / "notifications.json"


def send_notification(
    from_session: str,
    to_session: str,
    message: str,
    kind: str = "info",
) -> dict:
    """Send a notification to another session.

    Returns the notification dict with id.
    """
    notifs = _atomic_read(NOTIFICATIONS_FILE)
    notif_id = f"{from_session}-{len(notifs) + 1}"
    entry = {
        "id": notif_id,
        "from": from_session,
        "to": to_session,
        "message": message,
        "kind": kind,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "read": False,
    }
    if to_session not in notifs:
        notifs[to_session] = []
    notifs[to_session].append(entry)
    _atomic_write(NOTIFICATIONS_FILE, notifs)
    return entry


def get_notifications(session_id: str, mark_read: bool = True) -> list:
    """Get pending notifications for a session."""
    notifs = _atomic_read(NOTIFICATIONS_FILE)
    pending = notifs.pop(session_id, [])
    if mark_read and pending:
        _atomic_write(NOTIFICATIONS_FILE, notifs)
    return pending


def clear_notifications(session_id: str) -> None:
    """Clear all notifications for a session."""
    notifs = _atomic_read(NOTIFICATIONS_FILE)
    notifs.pop(session_id, None)
    _atomic_write(NOTIFICATIONS_FILE, notifs)


# ─── Init beim Laden ──────────────────────────────────────────────────────────

_ensure_shared_dir()


# ─── Tool Handlers (moved from tools/handlers_misc.py) ──────────────────────

from . import plan_core  # noqa: E402
from ._fmt import fmt_err, fmt_ok  # noqa: E402


def plan_session_tool(args: dict, **kwargs) -> str:
    """Show active sessions, their plans, and lock status.

    Reads from coord_state.py — no Git required.
    If Git is active, additionally shows branch info.

    Parameters:
    - include_history (bool, optional): Show git-based plan history (default: false)
    """
    include_history = args.get("include_history", False)

    sessions = get_sessions()
    locks = get_locks()

    notifications = get_notifications(plan_core.get_session_id(), mark_read=False)

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
            plans_dir_git = SHARED_DIR.parent / "plans" / ".git"
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
    - action (str, required): 'lock', 'unlock', 'status', 'list', or 'my'
    - path (str, required for lock/unlock/status): File or directory path
    - session_id (str, optional): Session ID (default: auto-detected)
    """
    action = args.get("action", "")
    path = args.get("path", "")
    session_id = args.get("session_id") or plan_core.get_session_id()

    if not action:
        return fmt_err("action is required (lock|unlock|status|list|my)")
    if action in ("lock", "unlock", "status") and not path:
        return fmt_err("path is required")

    if action == "lock":
        result = acquire_lock(path, session_id)
    elif action == "unlock":
        result = release_lock(path, session_id)
    elif action == "status":
        lock = get_lock(path)
        if lock:
            result = {"status": "locked", "path": path, "locked_by": lock.get("session_id"), "since": lock.get("since")}
        else:
            result = {"status": "free", "path": path}
    elif action in ("list", "my"):
        all_locks = get_locks()
        if action == "my":
            filtered = {p: lk for p, lk in all_locks.items() if lk.get("session_id") == session_id}
        else:
            filtered = all_locks
        return fmt_ok({
            "action": action,
            "count": len(filtered),
            "locks": [
                {
                    "path": p,
                    "session_id": lk.get("session_id", "?"),
                    "since": lk.get("since", "?"),
                }
                for p, lk in sorted(filtered.items())
            ],
        })
    else:
        return fmt_err(f"Unknown action: {action}. Use lock|unlock|status|list|my.")

    return fmt_ok({"action": action, "path": path, **result})


def plan_notify_tool(args: dict, **kwargs) -> str:
    """Send notifications to other sessions or manage own notifications.

    Parameters:
    - action (str, required): 'send', 'check', 'list', or 'clear'
    - to (str, optional): Target session ID (required for 'send')
    - message (str, optional): Message text (required for 'send')
    - kind (str, optional): 'info', 'warning', 'alert' (default: 'info')
    """
    action = args.get("action", "")
    to = args.get("to", "")
    message = args.get("message", "")
    kind = args.get("kind", "info")
    session_id = args.get("session_id") or plan_core.get_session_id()

    if not action:
        return fmt_err("action is required (send|check|list|clear)")

    if action == "send":
        if not to:
            return fmt_err("'to' (target session) is required for send")
        if not message:
            return fmt_err("'message' is required for send")
        result = send_notification(session_id, to, message, kind)
        return fmt_ok({"action": "sent", "to": to, "notification": result})

    elif action == "check":
        pending = get_notifications(session_id)
        return fmt_ok({
            "action": "check",
            "count": len(pending),
            "notifications": pending,
        })

    elif action == "list":
        all_notifs = _atomic_read(NOTIFICATIONS_FILE)
        mine = all_notifs.get(session_id, [])
        return fmt_ok({
            "action": "list",
            "count": len(mine),
            "notifications": mine,
        })

    elif action == "clear":
        clear_notifications(session_id)
        return fmt_ok({"action": "clear", "status": "cleared"})

    else:
        return fmt_err(f"Unknown action: {action}. Use send|check|list|clear.")


def plan_coord_cleanup_tool(args: dict, **kwargs) -> str:
    """Clean up stale sessions and locks from shared coordination state.

    Parameters:
    - session_max_age (int, optional): Session max age in minutes (default: 60)
    - lock_max_age (int, optional): Lock max age in minutes (default: 120)
    - dry_run (bool, optional): If true, only report what would be removed (default: false)
    """
    session_max_age = args.get("session_max_age", 60)
    lock_max_age = args.get("lock_max_age", 120)
    dry_run = args.get("dry_run", False)

    if dry_run:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        stale_sessions = 0
        for s in get_sessions().values():
            last = s.get("last_seen", s.get("registered", ""))
            try:
                age = (now - datetime.fromisoformat(last)).total_seconds() / 60
                if age > session_max_age:
                    stale_sessions += 1
            except (ValueError, TypeError):
                stale_sessions += 1
        stale_locks = 0
        for lock in get_locks().values():
            since = lock.get("since", "")
            try:
                age = (now - datetime.fromisoformat(since)).total_seconds() / 60
                if age > lock_max_age:
                    stale_locks += 1
            except (ValueError, TypeError):
                stale_locks += 1
        return fmt_ok({
            "action": "dry_run",
            "stale_sessions": stale_sessions,
            "stale_locks": stale_locks,
            "session_max_age": session_max_age,
            "lock_max_age": lock_max_age,
        })

    removed_sessions = cleanup_stale_sessions(session_max_age)
    removed_locks = cleanup_stale_locks(lock_max_age)
    return fmt_ok({
        "action": "cleanup",
        "removed_sessions": removed_sessions,
        "removed_locks": removed_locks,
        "session_max_age": session_max_age,
        "lock_max_age": lock_max_age,
    })
