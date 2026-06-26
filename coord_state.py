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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("plan_follow")

SHARED_DIR = Path.home() / ".hermes" / "shared"
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
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        _SHARED_DIR_INIT = True


def _atomic_write(path: Path, data: dict) -> None:
    """Atomic write: tempfile → rename. Verhindert corrupted reads.

    Uses fcntl flock on a .lock file for cross-session coordination.
    """
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


# ─── Lock Management ──────────────────────────────────────────────────────────


def acquire_lock(path: str, session_id: str) -> dict:
    """Acquire a lock on a file/path for a session.

    Auto-sends notification to the current holder if lock is taken.
    Returns:
        {"status": "acquired" | "exists" | "error",
         "locked_by": session_id or current holder}
    """
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
        locks[path]["since"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(LOCKS_FILE, locks)
        return {"status": "acquired", "locked_by": session_id}

    locks[path] = {
        "session_id": session_id,
        "since": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write(LOCKS_FILE, locks)
    return {"status": "acquired", "locked_by": session_id}


def release_lock(path: str, session_id: str) -> dict:
    """Release a lock. Only the holder can release.

    Returns:
        {"status": "released" | "not_locked" | "not_holder"}
    """
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
    return locks.get(path)


def release_all_locks(session_id: str) -> int:
    """Release ALL locks held by a session. Returns count released.

    Called when a session ends or on task completion.
    """
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
    """Remove locks older than max_age_minutes. Returns count removed."""
    locks = _atomic_read(LOCKS_FILE)
    now = datetime.now(timezone.utc)
    stale = []
    for p, lock in locks.items():
        since = lock.get("since", "")
        try:
            age = (now - datetime.fromisoformat(since)).total_seconds() / 60
            if age > max_age_minutes:
                stale.append(p)
        except (ValueError, TypeError):
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
