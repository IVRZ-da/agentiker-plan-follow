"""base.py — Module state + Persistence + Session for plan_follow tools/ subpackage."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .resolver import resolve_plans_dir, resolve_plans_index, resolve_roadmaps_dir
from .state import STATE

logger = logging.getLogger("plan_follow")

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
    except ImportError:
        _KANBAN_AVAILABLE = False
    return _KANBAN_AVAILABLE


def _kanban_db():
    try:
        from hermes_cli import kanban_db
        return kanban_db
    except ImportError:
        return None


def _kanban_profile() -> str:
    return os.environ.get("HERMES_PROFILE", "default")


def get_session_id() -> str:
    """Get the current Hermes session ID, with fallback.

    Uses HERMES_SESSION_ID first (set by Hermes runtime), then SESSION_ID,
    then a once-generated UUID as last resort. Cached in _SESSION_ID after
    first call so all callers within a plan_session lifecycle agree on the
    same ID.
    """
    if STATE.session_id is not None:
        return STATE.session_id
    sid = os.environ.get("HERMES_SESSION_ID") or os.environ.get("SESSION_ID") or ""
    if not sid:
        sid = str(uuid.uuid4())
    # Setze die Umgebungsvariable, damit Subprozesse die selbe Session-ID sehen
    os.environ.setdefault("HERMES_SESSION_ID", sid)
    STATE.session_id = sid
    return STATE.session_id


def reset_session_id() -> None:
    """Reset the cached session ID (for testing)."""
    STATE.session_id = None


# ─── In-Memory Cache ─────────────────────────────────────────────────────────

def _reset_cache():
    STATE.active_plan = None
    STATE.active_plan_id = None


# ─── Tool Usage Metrics ────────────────────────────────────────────────────────

def reset_tool_metrics():
    """Reset metrics and drift warnings for a new task."""
    STATE.tool_metrics = {}
    STATE.drift_warnings = []


def record_tool_call(tool_name: str, duration_ms: int, status: str):
    """Record a tool call for the active plan/task."""
    if not STATE.active_plan or not STATE.active_plan.get("current_task"):
        return
    tid = STATE.active_plan.get("current_task", "?")
    if tid not in STATE.tool_metrics:
        STATE.tool_metrics[tid] = {"total_calls": 0, "total_ms": 0, "by_category": {}}
    STATE.tool_metrics[tid]["total_calls"] += 1
    STATE.tool_metrics[tid]["total_ms"] += duration_ms
    cat = tool_name.split("_")[0] if "_" in tool_name else tool_name
    STATE.tool_metrics[tid].setdefault("by_category", {}).setdefault(cat, {"calls": 0, "ms": 0})
    STATE.tool_metrics[tid]["by_category"][cat]["calls"] += 1
    STATE.tool_metrics[tid]["by_category"][cat]["ms"] += duration_ms

def record_drift_warning(message: str):
    """Record a proactive drift warning from the post_tool_call hook."""
    if message not in STATE.drift_warnings:
        STATE.drift_warnings.append(message)
        logger.info("Drift warning recorded: %s", message)


def get_tool_metrics() -> dict:
    """Get current task's tool usage metrics."""
    if not STATE.active_plan or not STATE.active_plan.get("current_task"):
        return {}
    tid = STATE.active_plan["current_task"]
    return STATE.tool_metrics.get(tid, {})


def get_drift_warnings() -> list[str]:
    """Get drift warnings from the current session."""
    return list(STATE.drift_warnings)


# ─── Plans Index (Cross-Session Recovery) ─────────────────────────────────────


def _update_plans_index(plan: dict) -> None:
    """Write active plan info — via Kanban-DB or JSON index."""
    kdb = _kanban_db()
    if kdb:
        try:
            profile = _kanban_profile()
            plan_id = plan["plan_id"]
            goal = plan.get("goal", "")[:80]
            now = datetime.now(timezone.utc).isoformat()
            body = json.dumps({
                "type": "plan_index",
                "plan_id": plan_id,
                "goal": goal,
                "updated": now,
                "current_task": plan.get("current_task"),
            })
            # Upsert: create if not exists, update body if exists
            tid = f"plan_index:{_kanban_profile()}"
            conn = kdb.connect(board='plans')
            try:
                existing = kdb.get_task(conn, tid)
                if existing:
                    kdb.add_comment(conn, tid, author="system", body=body)  # Update via comment
                else:
                    from .state import STATE
                    plist = [STATE.kanban_root_id] if STATE.kanban_root_id else []
                    kdb.create_task(conn, title=f"active-plan:{profile}", body=body,
                                    assignee=profile, initial_status="running",
                                    workspace_kind="dir",
                                    skills=[],
                                    max_runtime_seconds=7200,
                                    max_retries=1,
                                    session_id=get_session_id(),
                                    parents=plist)
            except Exception:
                try:
                    from .state import STATE
                    plist = [STATE.kanban_root_id] if STATE.kanban_root_id else []
                    kdb.create_task(conn, title=f"active-plan:{profile}", body=body,
                                    assignee=profile, initial_status="running",
                                    parents=plist)
                except Exception:
                    pass
            finally:
                conn.close()
            return
        except Exception:
            logger.debug("Kanban plans_index update failed, fallback to JSON")

    # JSON-Fallback
    index = {}
    if resolve_plans_index().exists():
        try:
            index = json.loads(resolve_plans_index().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    index["active_plan_id"] = plan["plan_id"]
    index["active_goal"] = plan.get("goal", "")[:80]
    index["active_since"] = plan.get("created", "")
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        resolve_plans_index().write_text(json.dumps(index, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("plans_index.json could not be written")


def _clear_plans_index() -> None:
    """Remove active plan entry from plans_index.json."""
    index = {}
    if resolve_plans_index().exists():
        try:
            index = json.loads(resolve_plans_index().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    index.pop("active_plan_id", None)
    index.pop("active_goal", None)
    index.pop("active_since", None)
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        resolve_plans_index().write_text(json.dumps(index, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("plans_index.json could not be written")


def _recover_plan_from_disk() -> Optional[str]:
    """Find the most recent active plan — via Kanban-DB oder JSON.

    Search order:
    1. Kanban-DB: active_plan task for current profile
    2. plans_index.json → active_plan_id, only if plan has a current_task
    3. Newest .json with current_task set

    Returns plan_id or None (no in-progress plan found).
    """
    # 1. Kanban-DB: look for active plan marker for this profile
    kdb = _kanban_db()
    if kdb:
        try:
            profile = _kanban_profile()
            conn = kdb.connect()
            rows = conn.execute(
                "SELECT id, body FROM tasks WHERE "
                "body LIKE '%\"type\":\"plan_index\"%' "
                "AND assignee = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (profile,)
            ).fetchall()
            for row in rows:
                body = {}
                try:
                    body = json.loads(row[1]) if row[1] else {}
                except (json.JSONDecodeError, TypeError):
                    pass
                plan_id = body.get("plan_id")
                if plan_id and _plan_path(plan_id).exists():
                    plan = _load_plan(plan_id)
                    if plan and plan.get("current_task"):
                        logger.info("Disk-Recovery (Kanban): Plan '%s' recovered", plan_id)
                        return plan_id
        except Exception as e:
            logger.debug("Kanban recovery failed (fallback to JSON): %s", e)

    # 2. Index file — only if the plan has a valid current_task
    if resolve_plans_index().exists():
        try:
            index = json.loads(resolve_plans_index().read_text(encoding="utf-8"))
            pid = index.get("active_plan_id")
            if pid and _plan_path(pid).exists():
                plan = _load_plan(pid)
                if plan and plan.get("current_task"):
                    logger.info("Disk-Recovery (Index): Plan '%s' loaded from index", pid)
                    return pid
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    # 2. Neueste JSON mit current_task != null
    json_files = sorted(
        resolve_plans_dir().glob("*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for f in json_files:
        if f.name == "plans_index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("current_task"):
                pid = data.get("plan_id", f.stem)
                logger.info("Disk-Recovery (Active): Plan '%s' loaded from active JSON", pid)
                return pid
        except (json.JSONDecodeError, OSError):
            continue

    # No in-progress plan found — return None so _get_active_plan() stays empty
    return None


# ─── JSON Persistence ─────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    """Lazy init: create data dirs on first write (not at module import)."""
    resolve_plans_dir().mkdir(parents=True, exist_ok=True)
    resolve_roadmaps_dir().mkdir(parents=True, exist_ok=True)


def _plan_path(plan_id: str) -> Path:
    return resolve_plans_dir() / f"{plan_id}.json"


def _save_plan(plan: dict) -> None:
    _ensure_dirs()
    path = _plan_path(plan["plan_id"])
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    STATE.active_plan = plan
    STATE.active_plan_id = plan["plan_id"]
    _update_plans_index(plan)

    # Optional: Git-Commit wenn PLANS_DIR ein Git-Repo ist
    # Nur bei create_plan oder complete_task (nicht bei jedem update)
    from .coordination import _git_commit_if_active  # noqa: F811
    _git_commit_if_active(plan)


def _load_plan(plan_id: str) -> Optional[dict]:
    path = _plan_path(plan_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _get_active_plan() -> Optional[dict]:
    """Get the active plan with automatic recovery on cache miss.

    Fallback chain:
    1. In-Memory Cache (fastest)
    2. Disk-Scan via plans_index.json / newest JSON
    3. Honcho REST API (slowest)
    """
    # 1. In-Memory
    if STATE.active_plan is not None:
        return STATE.active_plan

    # 2. Disk-Scan
    plan_id = _recover_plan_from_disk()
    if plan_id:
        # Lazy import to avoid circular dependency
        from .task import set_active_plan  # noqa: F811
        if set_active_plan(plan_id):
            return STATE.active_plan

    # 3. Honcho
    try:
        from .coordination import _load_plan_state_from_honcho  # noqa: F811
        plan_id = _load_plan_state_from_honcho()
        if plan_id:
            from .task import set_active_plan  # noqa: F811
            if set_active_plan(plan_id):
                return STATE.active_plan
    except Exception:
        logger.debug("Honcho recovery failed (best-effort)")
        pass

    return None


def _get_cached_plan() -> Optional[dict]:
    """Get active plan from in-memory cache ONLY — no disk/Honcho recovery.

    Use this in the pre_llm_call hook to avoid leaking plans
    from other sessions. Plans on disk are still accessible
    via plan_list() + plan_select().
    """
    return STATE.active_plan


# ─── Module __getattr__: backward-compatible attribute access ────────────────
# These proxy to STATE so that `from .base import _active_plan` works correctly.
# (PEP 562 — Python 3.7+)

def __getattr__(name: str):
    if name == "_active_plan":
        return STATE.active_plan
    if name == "_active_plan_id":
        return STATE.active_plan_id
    if name == "_tool_metrics":
        return STATE.tool_metrics
    if name == "_drift_warnings":
        return STATE.drift_warnings
    if name == "_SESSION_ID":
        return STATE.session_id
    raise AttributeError(f"module 'plan_follow.tools.base' has no attribute '{name}'")


# ─── Archive ───────────────────────────────────────────────────────────────────
