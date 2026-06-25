"""coord_state.py — Cross-Session Koordination via Kanban-DB + JSON-Locks.

Verwaltet:
  - sessions.json → KANBAN-DB: Sessions werden als Kanban-Tasks mit status='running'
    und body.type='session' abgebildet. Heartbeat via kanban_db.heartbeat_worker().
  - locks.json (bleibt): Datei-Locks via fcntl.flock (passen nicht ins Task-Modell).
  - notifications.json → KANBAN-DB: Notifications als Kanban-Comments + Events.

Migration: Altlasten (JSON-Dateien) werden beim ersten Zugriff automatisch gelöscht
wenn Kanban-DB verfügbar ist.
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
NOTIFICATIONS_FILE = SHARED_DIR / "notifications.json"

_COORD_LOCK = SHARED_DIR / ".coord.lock"
_SHARED_DIR_INIT = False

# ─── Kanban-DB Verfügbarkeit ─────────────────────────────────────────────────

_KANBAN_AVAILABLE: Optional[bool] = None


def _kanban_available() -> bool:
    global _KANBAN_AVAILABLE
    if _KANBAN_AVAILABLE is not None:
        return _KANBAN_AVAILABLE
    try:
        import sys
        _p = "/home/jo/.hermes/hermes-agent"
        if _p not in sys.path:
            sys.path.insert(0, _p)
        from hermes_cli import kanban_db  # noqa: F401
        _KANBAN_AVAILABLE = True
        logger.debug("Kanban-DB verfügbar — Sessions/Notifications via Kanban")
    except ImportError:
        _KANBAN_AVAILABLE = False
        logger.info("Kanban-DB nicht verfügbar — Sessions/Notifications via JSON")
    return _KANBAN_AVAILABLE


def _get_kanban_db():
    """Get kanban_db module. Returns None if not available."""
    try:
        from hermes_cli import kanban_db
        return kanban_db
    except ImportError:
        return None


def _get_profile_name() -> str:
    """Get current Hermes profile name from env."""
    return os.environ.get("HERMES_PROFILE", "default")


# ─── File-Locks (bleiben JSON+fcntl) ─────────────────────────────────────────


def set_shared_dir(path: Path) -> None:
    """Set a custom shared directory (for testing). Updates all file paths."""
    global SHARED_DIR, SESSIONS_FILE, LOCKS_FILE, NOTIFICATIONS_FILE, _COORD_LOCK, _SHARED_DIR_INIT
    SHARED_DIR = path
    SESSIONS_FILE = path / "sessions.json"
    LOCKS_FILE = path / "locks.json"
    NOTIFICATIONS_FILE = path / "notifications.json"
    _COORD_LOCK = path / ".coord.lock"
    _SHARED_DIR_INIT = False


def _ensure_shared_dir():
    """Einmalige Initialisierung des shared-Verzeichnisses."""
    global _SHARED_DIR_INIT
    if not _SHARED_DIR_INIT:
        SHARED_DIR.mkdir(parents=True, exist_ok=True)
        _SHARED_DIR_INIT = True


def _acquire_coord_lock():
    """Acquire an exclusive fcntl.flock() on the coord lock file."""
    _ensure_shared_dir()
    fd = os.open(str(_COORD_LOCK), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _release_coord_lock(fd: int) -> None:
    """Release the coord lock and close the fd."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError as e:
        logger.warning("coord_state: failed to unlock fd %d: %s", fd, e)
    try:
        os.close(fd)
    except OSError as e:
        logger.warning("coord_state: failed to close fd %d: %s", fd, e)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Atomic JSON write: tempfile → rename. fcntl.flock() schützt vor TOCTOU."""
    lock_fd = _acquire_coord_lock()
    try:
        _ensure_shared_dir()
        fd, tmp = tempfile.mkstemp(dir=str(SHARED_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, str(path))
        except Exception:
            try:
                os.unlink(tmp)
            except OSError as e:
                logger.warning("coord_state: cleanup of temp file %s failed: %s", tmp, e)
            raise
    finally:
        _release_coord_lock(lock_fd)


def _atomic_read_json(path: Path) -> dict:
    """Read JSON with fallback auf leeres Dict. fcntl.flock() für Konsistenz."""
    lock_fd = _acquire_coord_lock()
    try:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    finally:
        _release_coord_lock(lock_fd)


# ─── Session Management (KANBAN-DB, Fallback JSON) ───────────────────────────


def register_session(
    session_id: str,
    plan_id: str = "",
    goal: str = "",
    cwd: str = "",
) -> dict:
    """Register a session via Kanban-DB (oder JSON-Fallback)."""
    kdb = _get_kanban_db()
    if kdb:
        try:
            profile = _get_profile_name()
            now = datetime.now(timezone.utc).isoformat()
            body = json.dumps({
                "type": "session",
                "session_id": session_id,
                "plan_id": plan_id,
                "goal": goal[:80],
                "cwd": cwd,
                "registered": now,
            })
            # Create a lightweight session-marker task
            conn = kdb.connect(board='plans')
            try:
                kdb.create_task(
                    conn,
                    title=f"session:{session_id[:20]}",
                    body=body,
                    assignee=profile,
                    initial_status="running",
                    workspace_kind="scratch",
                    skills=[],
                    max_runtime_seconds=300,
                    max_retries=0,
                    session_id=session_id,
                )
            finally:
                conn.close()
            logger.debug("Session %s via Kanban registriert", session_id[:20])
            return {"session_id": session_id, "status": "registered", "backend": "kanban"}
        except Exception as e:
            logger.warning("Kanban session reg failed (fallback to JSON): %s", e)

    # JSON-Fallback
    now = datetime.now(timezone.utc).isoformat()
    sessions = _atomic_read_json(SESSIONS_FILE)
    sessions[session_id] = {
        "registered": now,
        "last_seen": now,
        "plan_id": plan_id,
        "goal": goal,
        "cwd": cwd,
    }
    _atomic_write_json(SESSIONS_FILE, sessions)
    return sessions


def unregister_session(session_id: str) -> dict:
    """Remove a session from Kanban-DB (oder JSON-Fallback)."""
    kdb = _get_kanban_db()
    if kdb:
        try:
            # Find and complete the session task
            tid = f"session:{session_id[:20]}"
            conn = kdb.connect(board='plans')
            try:
                kdb.complete_task(conn, tid, summary="session ended")
            finally:
                conn.close()
            logger.debug("Session %s via Kanban beendet", session_id[:20])
            return {"status": "unregistered", "backend": "kanban"}
        except Exception as e:
            logger.debug("Kanban session unreg failed (fallback): %s", e)

    sessions = _atomic_read_json(SESSIONS_FILE)
    sessions.pop(session_id, None)
    _atomic_write_json(SESSIONS_FILE, sessions)
    return sessions


def update_session(session_id: str, **kwargs) -> dict:
    """Update session fields + Heartbeat via Kanban."""
    kdb = _get_kanban_db()
    if kdb:
        try:
            tid = f"session:{session_id[:20]}"
            # Update task body with new metadata
            conn = kdb.connect(board='plans')
            try:
                task = kdb.get_task(conn, tid)
                if task:
                    body = json.loads(task.body) if task.body else {}
                    for key in ("plan_id", "goal", "cwd"):
                        if key in kwargs:
                            body[key] = kwargs[key]
                    kdb.add_comment(conn, tid, author="system", body=json.dumps({"event": "heartbeat", "ts": datetime.now(timezone.utc).isoformat()}))
            finally:
                conn.close()
            return {"status": "updated", "backend": "kanban"}
        except Exception as e:
            logger.debug("Kanban session update failed (fallback): %s", e)

    sessions = _atomic_read_json(SESSIONS_FILE)
    if session_id not in sessions:
        return sessions
    now = datetime.now(timezone.utc).isoformat()
    sessions[session_id]["last_seen"] = now
    for key in ("plan_id", "goal", "cwd"):
        if key in kwargs:
            sessions[session_id][key] = kwargs[key]
    _atomic_write_json(SESSIONS_FILE, sessions)
    return sessions


def get_sessions() -> dict:
    """Get all active sessions from Kanban-DB (oder JSON-Fallback)."""
    kdb = _get_kanban_db()
    if kdb:
        try:
            conn = kdb.connect()
            rows = conn.execute(
                "SELECT id, body FROM tasks WHERE "
                "body LIKE '%\"type\":\"session\"%' "
                "AND status IN ('running', 'in_progress') "
                "ORDER BY created_at DESC"
            ).fetchall()
            sessions = {}
            for row in rows:
                body = {}
                try:
                    body = json.loads(row[1]) if row[1] else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                sid = body.get("session_id", row[0])
                sessions[sid] = {
                    "session_id": sid,
                    "plan_id": body.get("plan_id", ""),
                    "goal": body.get("goal", ""),
                    "registered": body.get("registered", ""),
                    "last_seen": body.get("last_seen", body.get("registered", "")),
                    "cwd": body.get("cwd", ""),
                }
            return sessions
        except Exception as e:
            logger.debug("Kanban sessions query failed (fallback): %s", e)

    return _atomic_read_json(SESSIONS_FILE)


def get_session(session_id: str) -> Optional[dict]:
    """Get a single session by ID."""
    sessions = get_sessions()
    return sessions.get(session_id)


def cleanup_stale_sessions(max_age_minutes: int = 60) -> int:
    """Remove stale sessions via Kanban oder JSON."""
    kdb = _get_kanban_db()
    if kdb:
        try:
            # Kanban's built-in stale detection
            conn = kdb.connect(board='plans')
            try:
                result = kdb.release_stale_claims(conn)
            finally:
                conn.close()
            return len(result.get("reclaimed", [])) if result else 0
        except Exception as e:
            logger.debug("Kanban stale cleanup failed (fallback): %s", e)

    # JSON-Fallback
    sessions = _atomic_read_json(SESSIONS_FILE)
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
        _atomic_write_json(SESSIONS_FILE, sessions)
    return len(stale)


# ─── Lock Management (bleibt JSON+fcntl) ─────────────────────────────────────


def acquire_lock(path: str, session_id: str) -> dict:
    """Acquire a lock on a file/path for a session."""
    locks = _atomic_read_json(LOCKS_FILE)
    if path in locks:
        holder = locks[path].get("session_id", "unknown")
        if holder != session_id:
            return {"status": "exists", "locked_by": holder}
        locks[path]["since"] = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(LOCKS_FILE, locks)
        return {"status": "acquired", "locked_by": session_id}
    locks[path] = {
        "session_id": session_id,
        "since": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(LOCKS_FILE, locks)
    return {"status": "acquired", "locked_by": session_id}


def release_lock(path: str, session_id: str) -> dict:
    """Release a lock. Only the holder can release."""
    locks = _atomic_read_json(LOCKS_FILE)
    if path not in locks:
        return {"status": "not_locked", "locked_by": None}
    if locks[path].get("session_id") != session_id:
        return {"status": "not_holder", "locked_by": locks[path].get("session_id")}
    locks.pop(path, None)
    _atomic_write_json(LOCKS_FILE, locks)
    return {"status": "released", "locked_by": None}


def get_locks() -> dict:
    """Get all active locks."""
    return _atomic_read_json(LOCKS_FILE)


def get_lock(path: str) -> Optional[dict]:
    """Get lock info for a specific path."""
    locks = _atomic_read_json(LOCKS_FILE)
    return locks.get(path)


def cleanup_stale_locks(max_age_minutes: int = 120) -> int:
    """Remove locks older than max_age_minutes. Returns count removed."""
    locks = _atomic_read_json(LOCKS_FILE)
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
        _atomic_write_json(LOCKS_FILE, locks)
    return len(stale)


# ─── Notification Management (KANBAN-DB, Fallback JSON) ──────────────────────


def send_notification(
    from_session: str,
    to_session: str,
    message: str,
    kind: str = "info",
) -> dict:
    """Send a notification via Kanban-Comment (oder JSON-Fallback)."""
    kdb = _get_kanban_db()
    if kdb:
        try:
            # Kanban uses comments on session tasks for notifications
            tid = f"session:{to_session[:20]}"
            comment_body = json.dumps({
                "from": from_session,
                "message": message,
                "kind": kind,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
            conn = kdb.connect(board='plans')
            try:
                kdb.add_comment(conn, tid, author="system", body=comment_body)
            finally:
                conn.close()
            return {"id": tid, "from": from_session, "to": to_session, "message": message, "kind": kind}
        except Exception as e:
            logger.debug("Kanban notification failed (fallback): %s", e)

    # JSON-Fallback
    notifs = _atomic_read_json(NOTIFICATIONS_FILE)
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
    _atomic_write_json(NOTIFICATIONS_FILE, notifs)
    return entry


def get_notifications(session_id: str, mark_read: bool = True) -> list:
    """Get pending notifications via Kanban-Comments (oder JSON)."""
    kdb = _get_kanban_db()
    if kdb:
        try:
            tid = f"session:{session_id[:20]}"
            conn = kdb.connect(board='plans')
            try:
                comments = kdb.list_comments(conn, tid)
            finally:
                conn.close()
            # Filter for notification-style comments
            notifs = []
            for c in comments:
                try:
                    payload = json.loads(c.body) if c.body else {}
                    if "from" in payload and "message" in payload:
                        notifs.append(payload)
                except (json.JSONDecodeError, TypeError):
                    pass
            if mark_read:
                pass  # Kanban comments are persistent
            return notifs
        except Exception as e:
            logger.debug("Kanban notifications query failed (fallback): %s", e)

    notifs = _atomic_read_json(NOTIFICATIONS_FILE)
    pending = notifs.pop(session_id, [])
    if mark_read and pending:
        _atomic_write_json(NOTIFICATIONS_FILE, notifs)
    return pending


def clear_notifications(session_id: str) -> None:
    """Clear all notifications for a session."""
    kdb = _get_kanban_db()
    if kdb:
        return  # Kanban notifications persist as comments — no explicit clear
    notifs = _atomic_read_json(NOTIFICATIONS_FILE)
    notifs.pop(session_id, None)
    _atomic_write_json(NOTIFICATIONS_FILE, notifs)


# ─── Init beim Laden ─────────────────────────────────────────────────────────

_ensure_shared_dir()
