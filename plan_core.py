"""
plan_core.py — Plan data model, JSON persistence, Honcho integration.

Plan format (stored in ~/.hermes/plans/<plan_id>.json):
{
    "plan_id": "2026-06-18-form-validation",
    "goal": "...",
    "created": "2026-06-18T13:00:00",
    "repo": "/home/jo/ivory-green-poc",
    "current_task": null,
    "tasks": {
        "p1": {
            "status": "pending|in_progress|completed|blocked",
            "name": "...",
            "files": ["lib/validation.ts"],
            "verify": "npm run test:unit -- validation",
            "depends_on": []
        }
    }
}
"""

import json
import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("plan_follow")

PLANS_DIR = Path.home() / ".hermes" / "plans"
# PLANS_DIR.mkdir() moved to _ensure_plans_dir() — lazy init on first write

HONCHO_URL = "http://127.0.0.1:8001"
HONCHO_WORKSPACE = "plan-follow"
HONCHO_PEER = "plan-follow-agent"

# ─── Centralized Session ID ────────────────────────────────────────────────────

_SESSION_ID: Optional[str] = None


def get_session_id() -> str:
    """Get the current Hermes session ID, with fallback.

    Uses HERMES_SESSION_ID first (set by Hermes runtime), then SESSION_ID,
    then a once-generated UUID as last resort. Cached in _SESSION_ID after
    first call so all callers within a plan_session lifecycle agree on the
    same ID.
    """
    global _SESSION_ID
    if _SESSION_ID is not None:
        return _SESSION_ID
    sid = os.environ.get("HERMES_SESSION_ID") or os.environ.get("SESSION_ID") or ""
    if not sid:
        sid = str(uuid.uuid4())
    # Setze die Umgebungsvariable, damit Subprozesse die selbe Session-ID sehen
    os.environ.setdefault("HERMES_SESSION_ID", sid)
    _SESSION_ID = sid
    return _SESSION_ID


def reset_session_id() -> None:
    """Reset the cached session ID (for testing)."""
    global _SESSION_ID
    _SESSION_ID = None


# ─── In-Memory Cache ─────────────────────────────────────────────────────────

_active_plan: Optional[dict] = None
_active_plan_id: Optional[str] = None


def _reset_cache():
    global _active_plan, _active_plan_id
    _active_plan = None
    _active_plan_id = None


# ─── Tool Usage Metrics ────────────────────────────────────────────────────────
# Per-task tool call counters and drift warnings, reset on plan change.

_tool_metrics: dict = {}
_drift_warnings: list[str] = []


def reset_tool_metrics():
    """Reset metrics and drift warnings for a new task."""
    global _tool_metrics, _drift_warnings
    _tool_metrics = {}
    _drift_warnings = []


def record_tool_call(tool_name: str, duration_ms: int, status: str):
    """Record a tool call for the active plan/task."""
    global _tool_metrics
    if not _active_plan or not _active_plan.get("current_task"):
        return
    tid = _active_plan["current_task"]
    if tid not in _tool_metrics:
        _tool_metrics[tid] = {"total_calls": 0, "total_ms": 0, "by_category": {}}
    _tool_metrics[tid]["total_calls"] += 1
    _tool_metrics[tid]["total_ms"] += duration_ms
    cat = tool_name.split("_")[0] if "_" in tool_name else tool_name
    _tool_metrics[tid].setdefault("by_category", {}).setdefault(cat, {"calls": 0, "ms": 0})
    _tool_metrics[tid]["by_category"][cat]["calls"] += 1
    _tool_metrics[tid]["by_category"][cat]["ms"] += duration_ms


def record_drift_warning(message: str):
    """Record a proactive drift warning from the post_tool_call hook."""
    global _drift_warnings
    if message not in _drift_warnings:
        _drift_warnings.append(message)
        logger.info(f"Drift warning recorded: {message}")


def get_tool_metrics() -> dict:
    """Get current task's tool usage metrics."""
    if not _active_plan or not _active_plan.get("current_task"):
        return {}
    tid = _active_plan["current_task"]
    return _tool_metrics.get(tid, {})


def get_drift_warnings() -> list[str]:
    """Get drift warnings from the current session."""
    return list(_drift_warnings)


# ─── Plans Index (Cross-Session Recovery) ─────────────────────────────────────

PLANS_INDEX = PLANS_DIR / "plans_index.json"


def _update_plans_index(plan: dict) -> None:
    """Write active plan info to a small index file for session recovery."""
    index = {}
    if PLANS_INDEX.exists():
        try:
            index = json.loads(PLANS_INDEX.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    index["active_plan_id"] = plan["plan_id"]
    index["active_goal"] = plan.get("goal", "")[:80]
    index["active_since"] = plan.get("created", "")
    index["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        PLANS_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("plans_index.json could not be written")


def _recover_plan_from_disk() -> Optional[str]:
    """Find the most recent active plan on disk.

    Search order:
    1. plans_index.json → active_plan_id (exact match, fastest)
    2. Newest .json with current_task set (actively in progress)
    3. Newest .json overall (fallback — any plan)

    Returns plan_id or None.
    """
    # 1. Index file
    if PLANS_INDEX.exists():
        try:
            index = json.loads(PLANS_INDEX.read_text(encoding="utf-8"))
            pid = index.get("active_plan_id")
            if pid and _plan_path(pid).exists():
                plan = _load_plan(pid)
                if plan:
                    logger.info(f"Disk-Recovery (Index): Plan '{pid}' loaded from index")
                    return pid
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    # 2. Neueste JSON mit current_task != null
    json_files = sorted(
        PLANS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    for f in json_files:
        if f.name == "plans_index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("current_task"):
                pid = data.get("plan_id", f.stem)
                logger.info(f"Disk-Recovery (Active): Plan '{pid}' loaded from active JSON")
                return pid
        except (json.JSONDecodeError, OSError):
            continue

    # 3. Neueste JSON allgemein
    for f in json_files:
        if f.name == "plans_index.json":
            continue
        try:
            pid = json.loads(f.read_text(encoding="utf-8")).get("plan_id", f.stem)
            logger.info(f"Disk-Recovery (Fallback): Plan '{pid}' loaded from fallback JSON")
            return pid
        except (json.JSONDecodeError, OSError):
            continue

    return None


# ─── JSON Persistence ─────────────────────────────────────────────────────────

def _ensure_dirs() -> None:
    """Lazy init: create data dirs on first write (not at module import)."""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    ROADMAPS_DIR.mkdir(parents=True, exist_ok=True)


def _plan_path(plan_id: str) -> Path:
    return PLANS_DIR / f"{plan_id}.json"


def _save_plan(plan: dict) -> None:
    _ensure_dirs()
    path = _plan_path(plan["plan_id"])
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    global _active_plan, _active_plan_id
    _active_plan = plan
    _active_plan_id = plan["plan_id"]
    _update_plans_index(plan)

    # Optional: Git-Commit wenn PLANS_DIR ein Git-Repo ist
    # Nur bei create_plan oder complete_task (nicht bei jedem update)
    _git_commit_if_active(plan)


def _git_commit_if_active(plan: dict) -> None:
    """Git-Commit des Plan-JSONs wenn PLANS_DIR/.git existiert.
    
    Nur bei relevanten Events (create/complete) — nicht bei jedem update.
    Fehlertolerant: Git-Fehler blockieren nicht das Speichern.
    """
    git_dir = PLANS_DIR / ".git"
    if not git_dir.exists():
        return  # Optional — kein Git-Repo, stille Skip

    plan_id = plan.get("plan_id", "unknown")
    current_task = plan.get("current_task", "none")
    done = sum(1 for t in plan.get("tasks", {}).values() if t.get("status") == "completed")
    total = len(plan.get("tasks", {}))
    
    msg = f"plan: {plan_id[:50]} — task {current_task} ({done}/{total})"
    
    import subprocess
    try:
        # Add only this plan's JSON file
        add = subprocess.run(
            ["git", "add", "--", f"{plan_id}.json"],
            cwd=PLANS_DIR, capture_output=True, text=True, timeout=10,
        )
        if add.returncode != 0:
            return  # Git add failed — silent skip
        
        # Check if there's anything to commit
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=PLANS_DIR, capture_output=True, text=True, timeout=10,
        )
        if not diff.stdout.strip():
            return  # No changes — silent skip
        
        # Commit
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=PLANS_DIR, capture_output=True, text=True, timeout=30,
        )
    except Exception:
        pass  # Silent skip — Git-Fehler blockieren nicht


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
    global _active_plan

    # 1. In-Memory
    if _active_plan is not None:
        return _active_plan

    # 2. Disk-Scan
    plan_id = _recover_plan_from_disk()
    if plan_id and set_active_plan(plan_id):
        return _active_plan

    # 3. Honcho
    try:
        plan_id = _load_plan_state_from_honcho()
        if plan_id and set_active_plan(plan_id):
            return _active_plan
    except Exception:
        pass

    return None


def _get_cached_plan() -> Optional[dict]:
    """Get active plan from in-memory cache ONLY — no disk/Honcho recovery.

    Use this in the pre_llm_call hook to avoid leaking plans
    from other sessions. Plans on disk are still accessible
    via plan_list() + plan_select().
    """
    return _active_plan


# ─── Honcho Integration (Registry-Dispatch mit Fallback) ──────────────────────

def _retry_with_backoff(fn, max_attempts: int = 3) -> any:
    """Execute fn with exponential backoff (1s, 2s, 4s). Returns result or raises last exception."""
    import time
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                wait = 2 ** attempt  # 1, 2, 4 seconds
                logger.debug(f"Honcho retry {attempt+1}/{max_attempts} in {wait}s: {e}")
                time.sleep(wait)
    raise last_exc


def _dispatch_honcho_tool(tool_name: str, args: dict) -> Optional[dict]:
    """Dispatch a Honcho tool via registry (lose Kopplung). Returns None if tool unavailable."""
    try:
        from tools.registry import registry
        entry = registry.get_entry(tool_name)
        if entry is None:
            return None
        handler = getattr(entry, "handler", None)
        if not callable(handler):
            return None
        result = handler(args)
        if isinstance(result, str):
            return json.loads(result)
        return result
    except Exception:
        return None


def _save_plan_state_to_honcho(plan_id: str, task_id: str, status: str):
    """Save plan state as Honcho conclusion. Uses registry dispatch, falls back to HTTP.

    Data model (JSON instead of flat string):
        {"source": "plan_follow", "plan_id": "...", "task_id": "...", "status": "..."}
    """
    # Try registry dispatch first (lose Kopplung)
    payload = {
        "source": "plan_follow",
        "plan_id": plan_id,
        "task_id": task_id,
        "status": status,
    }
    registry_result = _dispatch_honcho_tool("honcho_conclude", {
        "conclusion": json.dumps(payload),
        "target": "memory",
    })
    if registry_result is not None:
        return  # Registry dispatch succeeded

    # Fallback: raw HTTP with exponential backoff
    import urllib.request
    def _do_save():
        data = json.dumps({
            "conclusions": [{
                "observer_id": HONCHO_PEER,
                "observed_id": HONCHO_PEER,
                "content": json.dumps(payload),
                "source": "plan-follow-plugin"
            }]
        }).encode()
        req = urllib.request.Request(
            f"{HONCHO_URL}/v3/workspaces/{HONCHO_WORKSPACE}/conclusions",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)

    try:
        _retry_with_backoff(_do_save)
    except Exception as e:
        logger.warning(f"Honcho save failed after retries (non-fatal): {e}")


def _load_plan_state_from_honcho() -> Optional[str]:
    """Load active plan ID from Honcho. Returns plan_id or None."""
    # Try registry dispatch first
    registry_result = _dispatch_honcho_tool("honcho_search", {
        "query": "plan_follow:active",
    })
    if registry_result is not None:
        conclusions = registry_result.get("conclusions", []) if isinstance(registry_result, dict) else []
        for c in conclusions:
            content = c.get("content", "") if isinstance(c, dict) else ""
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and parsed.get("source") == "plan_follow" and parsed.get("status") == "active":
                        return parsed.get("plan_id")
                except (json.JSONDecodeError, TypeError):
                    # Legacy format: "plan_follow:<plan_id>:active=true"
                    if "plan_follow:" in content and "active=true" in content:
                        parts = content.split(":")
                        if len(parts) >= 2:
                            return parts[1]
        return None

    # Fallback: raw HTTP with exponential backoff
    import urllib.request
    def _do_load():
        req = urllib.request.Request(
            f"{HONCHO_URL}/v3/workspaces/{HONCHO_WORKSPACE}/conclusions/query",
            data=json.dumps({
                "query": "plan_follow:active",
                "observer_id": HONCHO_PEER,
                "observed_id": HONCHO_PEER
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=5)
        conclusions = json.loads(resp.read())
        for c in conclusions:
            content = c.get("content", "")
            # Try JSON data model first
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    if isinstance(parsed, dict) and parsed.get("source") == "plan_follow" and parsed.get("status") == "active":
                        return parsed.get("plan_id")
                except (json.JSONDecodeError, TypeError):
                    pass
            # Legacy: "plan_follow:<plan_id>:active=true"
            if isinstance(content, str) and "plan_follow:" in content and "active=true" in content:
                parts = content.split(":")
                if len(parts) >= 2:
                    return parts[1]
        return None

    try:
        return _retry_with_backoff(_do_load)
    except Exception as e:
        logger.warning(f"Honcho load failed after retries (non-fatal): {e}")
        return None


# ─── Plan CRUD ────────────────────────────────────────────────────────────────

def create_plan(goal: str, tasks: list, repo: str = "", parallel_groups: Optional[dict] = None,
                repos: Optional[list[str]] = None) -> str:
    """Create a new plan and persist it. Returns plan_id.

    Args:
        goal: The plan goal.
        tasks: List of task dicts with id, name, files, verify, depends_on.
        repo: Optional single git repo path (legacy, use repos instead).
        parallel_groups: Optional dict of groups.
        repos: Optional list of git repo paths for drift detection across
            multiple repositories.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    plan_id = f"{now[:10]}-{goal.lower().replace(' ', '-')[:40]}"

    tasks_dict = {}
    for t in tasks:
        tasks_dict[t["id"]] = {
            "status": "pending",
            "name": t.get("name", ""),
            "files": t.get("files", []),
            "verify": t.get("verify", ""),
            "review_profile": t.get("review_profile", "none"),
            "review_result": None,
            "depends_on": t.get("depends_on", []),
        }

    plan = {
        "plan_id": plan_id,
        "goal": goal,
        "created": now,
        "plan_version": "1",
        "repo": repo,
        "current_task": None,
        "tasks": tasks_dict,
    }

    if repos:
        plan["repos"] = repos

    # Parallel groups
    if parallel_groups:
        plan["parallel_groups"] = {}
        ordered = sorted(parallel_groups.keys())
        for i, gid in enumerate(ordered):
            g = parallel_groups[gid]
            plan["parallel_groups"][gid] = {
                "tasks": g.get("tasks", []),
                "status": "in_progress" if i == 0 else "pending",
            }
        # Set first task of first group as current_task
        first_group = plan["parallel_groups"][ordered[0]]
        if first_group["tasks"]:
            first_tid = first_group["tasks"][0]
            plan["current_task"] = first_tid
            tasks_dict[first_tid]["status"] = "in_progress"
            for t_parallel in first_group["tasks"][1:]:
                tasks_dict[t_parallel]["status"] = "in_progress"
    else:
        # Linear mode: first task without dependencies becomes current
        for tid, tdef in tasks_dict.items():
            if not tdef["depends_on"]:
                plan["current_task"] = tid
                tdef["status"] = "in_progress"
                break

    reset_tool_metrics()
    _save_plan(plan)

    # Cross-Session: Session registrieren
    try:
        from .coord_state import register_session
        register_session(
            get_session_id(),
            plan_id=plan_id,
            goal=goal[:80],
            cwd=os.getcwd(),
        )
    except Exception:
        pass  # Best-effort

    # Honcho persistence (save plan state for cross-session recovery)
    _save_plan_state_to_honcho(plan_id, "active", "true")

    return plan_id


def get_current_task() -> Optional[dict]:
    """Return the current task dict, or None if no active plan.
    
    Uses full recovery chain (cache → disk → Honcho).
    For session-local check, use get_current_task_cached().
    """
    plan = _get_active_plan()
    return _task_from_plan(plan)


def get_current_task_cached() -> Optional[dict]:
    """Return current task from in-memory cache ONLY.
    
    No disk or Honcho recovery — prevents plan leaks across sessions.
    """
    plan = _get_cached_plan()
    return _task_from_plan(plan)


def _task_from_plan(plan: Optional[dict]) -> Optional[dict]:
    """Extract current task dict from a plan, or None."""
    if not plan or not plan.get("current_task"):
        return None
    tid = plan["current_task"]
    task = plan["tasks"].get(tid)
    if not task:
        return None
    return {
        "plan_id": plan["plan_id"],
        "goal": plan["goal"],
        "task_id": tid,
        "name": task["name"],
        "status": task["status"],
        "files": task["files"],
        "verify": task["verify"],
        "review_profile": task.get("review_profile", "none"),
        "review_result": task.get("review_result"),
        "depends_on": task["depends_on"],
        "progress": _format_progress(plan),
    }

def get_current_tasks() -> list[dict]:
    """Return ALL current tasks (supports parallel groups).

    In linear mode (no parallel_groups), returns a list with one task.
    In group mode, returns all tasks in the active group that are
    still in_progress or pending.
    
    Uses full recovery chain (cache → disk → Honcho).
    For session-local check, use get_current_tasks_cached().
    """
    plan = _get_active_plan()
    return _tasks_from_plan(plan)


def get_current_tasks_cached() -> list[dict]:
    """Return ALL current tasks from in-memory cache ONLY.
    
    No disk or Honcho recovery.
    """
    plan = _get_cached_plan()
    return _tasks_from_plan(plan)


def _tasks_from_plan(plan: Optional[dict]) -> list[dict]:
    """Extract current tasks list from a plan."""
    if not plan or not plan.get("current_task"):
        return []

    groups = plan.get("parallel_groups")
    if groups:
        for gid, group in groups.items():
            if group["status"] == "in_progress":
                result = []
                for tid in group["tasks"]:
                    t = plan["tasks"].get(tid)
                    if t and t["status"] in ("in_progress", "pending"):
                        result.append(_format_task(tid, t, plan))
                return result
        return []

    # Linear mode: return single current task
    t = get_current_task()
    return [t] if t else []


def _format_task(tid: str, task: dict, plan: dict) -> dict:
    """Format a task dict for API responses."""
    return {
        "plan_id": plan["plan_id"],
        "goal": plan["goal"],
        "task_id": tid,
        "name": task["name"],
        "status": task["status"],
        "files": task["files"],
        "verify": task["verify"],
        "review_profile": task.get("review_profile", "none"),
        "review_result": task.get("review_result"),
        "depends_on": task["depends_on"],
        "progress": _format_progress(plan),
    }


def complete_task(task_id: str) -> dict:
    """Mark a task as completed, advance to next. Returns result dict.

    Supports parallel groups: when all tasks in a group are completed,
    the next group is activated (all tasks set to in_progress).
    In linear mode, advances to the next task with satisfied dependencies.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    if plan.get("current_task") != task_id:
        return {"status": "error", "message": f"Task '{task_id}' is not the current task."}

    # Mark as completed
    task["status"] = "completed"
    _save_plan_state_to_honcho(plan["plan_id"], task_id, "completed")
    # Release locks for completed task
    _auto_unlock_task_files(task)

    # Handle parallel groups
    groups = plan.get("parallel_groups")
    if groups:
        _advance_parallel_group(plan, task_id, groups)
    else:
        # Linear mode: find next pending task with completed dependencies
        _advance_linear(plan)

    _save_plan(plan)

    # Cross-Session: Session-Update bei Task-Abschluss
    try:
        from .coord_state import update_session
        update_session(get_session_id(), plan_id=plan["plan_id"])
    except Exception:
        pass  # Best-effort

    result = {
        "status": "completed",
        "task_id": task_id,
        "next_task": plan.get("current_task"),
    }
    return result


def _auto_lock_task_files(task: dict) -> None:
    """Auto-acquire locks for all files in a task on activation.

    Best-effort: if coord_state isn't available, silently skip.
    """
    files = task.get("files", [])
    if not files:
        return
    try:
        from .coord_state import acquire_lock
        for f in files:
            acquire_lock(f, get_session_id())
    except Exception:
        pass  # Best-effort


def _auto_unlock_task_files(task: dict) -> None:
    """Auto-release locks for all files in a completed task."""
    files = task.get("files", [])
    if not files:
        return
    try:
        from .coord_state import release_lock
        for f in files:
            release_lock(f, get_session_id())
    except Exception:
        pass  # Best-effort


def _advance_parallel_group(plan: dict, task_id: str, groups: dict) -> None:
    """Advance to next group when all tasks in current group are done."""
    current_group_id = None
    for gid, group in groups.items():
        if group["status"] == "in_progress":
            current_group_id = gid
            break

    if not current_group_id:
        plan["current_task"] = None
        return

    current_group = groups[current_group_id]

    # Check if ALL tasks in current group are completed
    all_done = all(
        plan["tasks"].get(tid, {}).get("status") == "completed"
        for tid in current_group["tasks"]
    )

    if not all_done:
        # Keep current group, set current_task to next incomplete task
        next_task = _find_next_in_group(plan, current_group)
        plan["current_task"] = next_task
        return

    # Current group is fully done → mark as completed
    current_group["status"] = "completed"

    # Find next pending group
    next_group_id = None
    found_current = False
    for gid in groups:
        if gid == current_group_id:
            found_current = True
            continue
        if found_current and groups[gid]["status"] == "pending":
            next_group_id = gid
            break

    if next_group_id:
        next_group = groups[next_group_id]
        next_group["status"] = "in_progress"
        reset_tool_metrics()
        # Activate all tasks in next group
        for tid in next_group["tasks"]:
            t = plan["tasks"].get(tid)
            if t:
                t["status"] = "in_progress"
                _save_plan_state_to_honcho(plan["plan_id"], tid, "in_progress")
                _auto_lock_task_files(t)
        # Set current_task to first task in new group
        plan["current_task"] = next_group["tasks"][0] if next_group["tasks"] else None
    else:
        plan["current_task"] = None
        _save_plan_state_to_honcho(plan["plan_id"], "active", "false")


def _find_next_in_group(plan: dict, group: dict) -> Optional[str]:
    """Find the next incomplete task in a group (for progress within group)."""
    for tid in group["tasks"]:
        t = plan["tasks"].get(tid)
        if t and t["status"] != "completed":
            return tid
    return None


def _advance_linear(plan: dict) -> None:
    """Find next task in linear mode (first pending with satisfied deps)."""
    next_task = None
    for tid, tdef in plan["tasks"].items():
        if tdef["status"] != "pending":
            continue
        deps = tdef.get("depends_on", [])
        if all(plan["tasks"].get(d, {}).get("status") == "completed" for d in deps):
            next_task = tid
            break

    if next_task:
        reset_tool_metrics()
        plan["current_task"] = next_task
        plan["tasks"][next_task]["status"] = "in_progress"
        _save_plan_state_to_honcho(plan["plan_id"], next_task, "in_progress")
        _auto_lock_task_files(plan["tasks"][next_task])
    else:
        plan["current_task"] = None
        _save_plan_state_to_honcho(plan["plan_id"], "active", "false")


def update_task(task_id: str, changes: dict) -> Optional[dict]:
    """Update a task's properties (files, verify, depends_on)."""
    plan = _get_active_plan()
    if not plan:
        return None
    task = plan["tasks"].get(task_id)
    if not task:
        return None
    for key in ("files", "verify", "depends_on", "name", "review_profile"):
        if key in changes:
            task[key] = changes[key]
    _save_plan(plan)
    return task


def get_plan_status() -> Optional[dict]:
    """Return full plan status overview."""
    plan = _get_active_plan()
    if not plan:
        return None

    total = len(plan["tasks"])
    done = sum(1 for t in plan["tasks"].values() if t["status"] == "completed")
    blocked = sum(1 for t in plan["tasks"].values() if t["status"] == "blocked")

    tasks_list = []
    for tid, tdef in plan["tasks"].items():
        entry = {"id": tid, "name": tdef["name"], "status": tdef["status"]}
        if tdef["status"] == "blocked":
            deps = [d for d in tdef.get("depends_on", [])
                    if plan["tasks"].get(d, {}).get("status") != "completed"]
            entry["blocked_by"] = deps
        tasks_list.append(entry)

    return {
        "plan_id": plan["plan_id"],
        "goal": plan["goal"],
        "progress": f"{done}/{total} tasks ({total and done*100//total}%)",
        "current_task": plan.get("current_task"),
        "tasks": tasks_list,
    }


def set_active_plan(plan_id: str) -> bool:
    """Load a plan from disk and set it as active. Returns True on success."""
    plan = _load_plan(plan_id)
    if not plan:
        return False
    global _active_plan, _active_plan_id
    _active_plan = plan
    _active_plan_id = plan_id
    # Auto-lock current task's files when activating a plan
    current_task_id = plan.get("current_task")
    if current_task_id:
        current_task = plan["tasks"].get(current_task_id)
        if current_task:
            _auto_lock_task_files(current_task)
    return True


# ─── Plan Management ────────────────────────────────────────────────────────────

def list_plans(include_archived: bool = False) -> list[dict]:
    """List all plans from PLANS_DIR, newest first (including completed/aborted).

    Args:
        include_archived: If True, also list plans from the archive directory.

    Returns:
        List of plan summary dicts.
    """
    plans = _list_plans_from_dir(PLANS_DIR, is_active=True)

    if include_archived:
        arch_dir = PLANS_DIR / "archived"
        if arch_dir.exists():
            archived_plans = _list_plans_from_dir(arch_dir, is_active=False)
            for ap in archived_plans:
                ap["is_archived"] = True
            plans.extend(archived_plans)

    return plans


def _list_plans_from_dir(directory: Path, is_active: bool = False) -> list[dict]:
    """List plans from a specific directory."""
    plans = []
    for f in sorted(directory.glob("*.json"), reverse=True):
        if f.name == "plans_index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            tasks = data.get("tasks", {})
            total = len(tasks)
            completed = sum(1 for t in tasks.values() if t.get("status") == "completed")
            plans.append({
                "plan_id": data.get("plan_id", f.stem),
                "goal": data.get("goal", "")[:60],
                "created": data.get("created", ""),
                "current_task": data.get("current_task"),
                "total_tasks": total,
                "completed_tasks": completed,
                "progress": f"{completed}/{total}" if total else "0/0",
                "is_active": data.get("plan_id") == _active_plan_id if is_active else False,
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return plans


def abort_plan(task_id: str = "") -> dict:
    """Abort the active plan or a specific task.

    Args:
        task_id: If provided, abort only this task. Otherwise abort entire plan.

    Returns:
        Dict with status and plan_id.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}

    if task_id:
        task = plan["tasks"].get(task_id)
        if not task:
            return {"status": "error", "message": f"Task '{task_id}' not found."}
        task["status"] = "aborted"
        _auto_unlock_task_files(task)
        if plan.get("current_task") == task_id:
            plan["current_task"] = None
        msg = f"Task '{task_id}' aborted."
    else:
        for tid, t in plan["tasks"].items():
            if t["status"] == "in_progress":
                t["status"] = "aborted"
                _auto_unlock_task_files(t)
        plan["current_task"] = None
        msg = "Whole plan aborted."

    _save_plan(plan)

    # Cross-Session: Deregistrierung bei Abbruch
    try:
        from .coord_state import unregister_session
        unregister_session(get_session_id())
    except Exception:
        pass  # Best-effort

    return {"status": "aborted", "plan_id": plan["plan_id"], "message": msg}


def delete_plan(plan_id: str) -> dict:
    """Permanently delete a plan from disk.

    Args:
        plan_id: The plan ID to delete.

    Returns:
        Dict with status and message.
    """
    path = _plan_path(plan_id)
    if not path.exists():
        return {"status": "error", "message": f"Plan '{plan_id}' not found."}

    global _active_plan, _active_plan_id
    if _active_plan_id == plan_id:
        _active_plan = None
        _active_plan_id = None

    path.unlink()

    # Cross-Session: Deregistrierung bei Löschung
    try:
        from .coord_state import unregister_session
        unregister_session(get_session_id())
    except Exception:
        pass  # Best-effort

    return {"status": "deleted", "plan_id": plan_id, "message": f"Plan '{plan_id}' deleted."}


def select_plan(plan_id: str) -> dict:
    """Switch to a different plan as the active one.

    Args:
        plan_id: The plan ID to activate.

    Returns:
        Dict with status and current_task info.
    """
    ok = set_active_plan(plan_id)
    if not ok:
        return {"status": "error", "message": f"Plan '{plan_id}' not found."}
    return {
        "status": "selected",
        "plan_id": plan_id,
        "goal": _active_plan.get("goal", "")[:60],
        "current_task": _active_plan.get("current_task"),
    }


# ─── Auto-Verify & Auto-Commit ─────────────────────────────────────────────────

def auto_verify_task(verify_cmd: str, timeout: int = 120) -> dict:
    """Run a verify command as a subprocess and return results.

    Args:
        verify_cmd: Shell command to execute.
        timeout: Max seconds to wait (default 120).

    Returns:
        Dict with status (passed/failed/skipped), exit_code, stdout, stderr.
    """
    if not verify_cmd or not verify_cmd.strip():
        return {"status": "skipped", "message": "No verify command configured."}

    import subprocess
    try:
        result = subprocess.run(
            verify_cmd, shell=True, capture_output=True, text=True, timeout=timeout,
        )
        std_out = result.stdout[-1000:] if result.stdout else ""
        std_err = result.stderr[-1000:] if result.stderr else ""
        return {
            "status": "passed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "stdout": std_out,
            "stderr": std_err,
        }
    except subprocess.TimeoutExpired:
        return {"status": "failed", "message": f"verify-Command timeout ({timeout}s)"}
    except Exception as e:
        return {"status": "failed", "message": str(e)}


def auto_commit(task_id: str, files: list[str], repo: str = "") -> dict:
    """Git-commit only the task's files.

    Args:
        task_id: Task identifier for the commit message.
        files: List of file paths to add.
        repo: Git repository path.

    Returns:
        Dict with status (committed/skipped/failed) and output.
    """
    if not repo or not os.path.isdir(os.path.join(repo, ".git")):
        return {"status": "skipped", "message": "No git repo configured."}
    if not files:
        return {"status": "skipped", "message": "No files to commit."}

    import subprocess
    temp_dir = None
    try:
        # Add files
        for f in files:
            subprocess.run(
                ["git", "add", "--", f],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )

        # Check if anything changed
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=repo, capture_output=True, text=True, timeout=10,
        )
        if not diff.stdout.strip():
            return {"status": "skipped", "message": "No changes to commit."}

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", f"plan: {task_id} — auto-commit"],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
        return {
            "status": "committed" if result.returncode == 0 else "failed",
            "output": (result.stdout[:300] + result.stderr[:300]),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ─── Drift Detection ─────────────────────────────────────────────────────────

def _get_repos(plan: dict) -> list[str]:
    """Normalize repo/repos to a list. Supports legacy single 'repo' and new 'repos' array."""
    repos = plan.get("repos", [])
    if isinstance(repos, list) and repos:
        return repos
    single = plan.get("repo", "")
    if single:
        return [single]
    return []


def check_drift() -> list:
    """Compare git diff against current task's files. Returns list of unplanned files.
    Supports multiple repos — checks all configured repositories."""
    plan = _get_active_plan()
    if not plan or not plan.get("current_task"):
        return []

    tid = plan["current_task"]
    task = plan["tasks"].get(tid)
    if not task:
        return []

    allowed_files = set(task.get("files", []))
    repos = _get_repos(plan)
    if not repos:
        return []

    import subprocess
    unplanned = []
    for repo in repos:
        if not os.path.isdir(os.path.join(repo, ".git")):
            continue
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=repo, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                changed = [f.strip() for f in result.stdout.split("\n") if f.strip()]
                unplanned.extend(f for f in changed if f not in allowed_files)
        except Exception as e:
            logger.warning(f"Drift check failed for repo {repo}: {e}")
            continue

    return unplanned


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_progress(plan: dict) -> str:
    total = len(plan["tasks"])
    done = sum(1 for t in plan["tasks"].values() if t["status"] == "completed")
    if total == 0:
        return "0/0"

    groups = plan.get("parallel_groups")
    if groups:
        # Show group-level progress
        group_parts = []
        for gid, group in groups.items():
            g_tasks = group.get("tasks", [])
            g_done = sum(1 for t in g_tasks if plan["tasks"].get(t, {}).get("status") == "completed")
            g_total = len(g_tasks)
            if group["status"] == "completed":
                group_parts.append(f"✅{gid}({g_done}/{g_total})")
            elif group["status"] == "in_progress":
                group_parts.append(f"▶️{gid}({g_done}/{g_total})")
            else:
                group_parts.append(f"⬜{gid}({g_done}/{g_total})")
        return f"{done}/{total} " + " → ".join(group_parts)

    # Linear mode: show individual task progress
    task_ids = list(plan["tasks"].keys())
    current_idx = task_ids.index(plan.get("current_task")) if plan.get("current_task") in task_ids else -1
    parts = []
    for i, tid in enumerate(task_ids):
        if i < current_idx:
            parts.append(f"✅{tid}")
        elif i == current_idx:
            parts.append(f"▶️{tid}")
        else:
            parts.append(f"⬜{tid}")
    return f"{done}/{total} " + " → ".join(parts)


# ─── Review Helpers ────────────────────────────────────────────────────────────

def save_review_result(task_id: str, result: dict) -> bool:
    """Persist review result for a task.

    Args:
        task_id: Task ID
        result: Dict with 'status', 'issues', 'summary' keys

    Returns:
        True if saved successfully, False otherwise.
    """
    plan = _get_active_plan()
    if not plan or task_id not in plan["tasks"]:
        return False
    from datetime import datetime, timezone
    plan["tasks"][task_id]["review_result"] = {
        "status": result.get("status", "failed"),
        "issues": result.get("issues", []),
        "summary": result.get("summary", ""),
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save_plan(plan)
    return True


def is_review_passed(task: dict) -> bool:
    """Check if a task has passed its review (if required).

    If review_profile is 'none', the task is considered passed.
    Otherwise, requires review_result with status='passed'.

    Args:
        task: Task dict from the plan

    Returns:
        True if review passed or not required.
    """
    profile = task.get("review_profile", "none")
    if profile == "none":
        return True
    result = task.get("review_result")
    if not result:
        return False
    return result.get("status") == "passed"


def get_task_review_state(task: dict) -> str:
    """Get the human-readable review state for a task.

    Returns one of:
      - 'not_required' — no review_profile set
      - 'in_review' — review_profile != none, but no result yet
      - 'passed' — review passed
      - 'failed' — review failed
      - 'pending' — review in progress (result exists, but neither passed nor failed)

    Args:
        task: Task dict from the plan

    Returns:
        String status
    """
    profile = task.get("review_profile", "none")
    if profile == "none":
        return "not_required"
    result = task.get("review_result")
    if not result:
        return "in_review"
    status = result.get("status", "pending")
    if status in ("passed", "failed"):
        return status
    return "pending"


# ─── Health Check ─────────────────────────────────────────────────────────────

def health_check() -> dict:
    """Check all core systems including this plugin. Returns {"status": "ok"} or {"status": "degraded", "issues": [...]}."""
    issues = []

    # 0. plan_follow plugin self-check
    from tools.registry import registry
    plan_tools = ["plan_create", "plan_current", "plan_complete", "plan_verify", "plan_status", "plan_update"]
    for t in plan_tools:
        if not registry.get_entry(t):
            issues.append(f"plan_follow: Eigenes Tool '{t}' nicht im Registry — Plugin defekt!")
            break

    # 1. agentiker_code_intel (code_* Tools)
    code_tools = ["code_search", "code_refactor", "code_definition"]
    for t in code_tools:
        if not registry.get_entry(t):
            issues.append(f"agentiker_code_intel: Tool '{t}' nicht im Registry")
            break

    # 2. Honcho — try registry dispatch first, fallback to HTTP
    honcho_ok = _dispatch_honcho_tool("honcho_search", {"query": "health"})
    if honcho_ok is None:
        import urllib.request
        try:
            resp = urllib.request.urlopen(f"{HONCHO_URL}/health", timeout=3)
            if resp.status != 200:
                issues.append("Honcho: Health check failed")
        except Exception as e:
            issues.append(f"Honcho: Nicht erreichbar ({e})")
    elif not isinstance(honcho_ok, dict):
        issues.append("Honcho: Registry dispatch returned unexpected format")

    if issues:
        return {"status": "degraded", "issues": issues}
    return {"status": "ok"}


# ─── Plan Validation ──────────────────────────────────────────────────────────

def validate_plan(plan_id: str = "") -> dict:
    """Validate the integrity of a plan.

    Checks:
    - All depends_on references exist (no orphan deps)
    - No circular dependencies (DAG check via topological sort)
    - All verify commands are non-empty (or at least syntactically valid)
    - parallel_groups tasks all exist in tasks
    - Review profiles are valid
    - No orphan tasks (not reachable from root tasks)

    Args:
        plan_id: Plan ID to validate. If empty, validates the active plan.

    Returns:
        Dict with status, plan_id, and list of issues/errors.
    """
    # 1. Load plan
    if plan_id:
        plan = _load_plan(plan_id)
        if not plan:
            return {"status": "error", "plan_id": plan_id, "errors": [f"Plan '{plan_id}' not found."]}
    else:
        plan = _get_active_plan()
        if not plan:
            return {"status": "error", "plan_id": "", "errors": ["No active plan."]}
        plan_id = plan["plan_id"]

    errors = []
    warnings = []

    tasks = plan.get("tasks", {})
    all_task_ids = set(tasks.keys())
    groups = plan.get("parallel_groups", {})
    valid_profiles = {"none", "unit-test", "api-route", "ui-component", "security", "full"}

    # 2. Check each task
    for tid, tdef in tasks.items():
        # depends_on checks
        for dep in tdef.get("depends_on", []):
            if dep not in all_task_ids:
                errors.append(f"Task '{tid}': depends_on '{dep}' does not exist.")

        # verify command check
        verify = tdef.get("verify", "")
        if verify and len(verify) < 3:
            warnings.append(f"Task '{tid}': verify-Command '${verify}' seems too short.")

        # review profile check
        profile = tdef.get("review_profile", "none")
        if profile not in valid_profiles and profile is not None:
            warnings.append(f"Task '{tid}': review_profile '{profile}' is not a valid profile.")

        # status check
        valid_statuses = {"pending", "in_progress", "completed", "blocked", "aborted"}
        status = tdef.get("status", "pending")
        if status not in valid_statuses:
            errors.append(f"Task '{tid}': invalid status '{status}'.")

    # 3. Circular dependency check (DAG via topological sort)
    in_degree = {tid: 0 for tid in all_task_ids}
    adj = {tid: [] for tid in all_task_ids}

    for tid, tdef in tasks.items():
        for dep in tdef.get("depends_on", []):
            if dep in all_task_ids:
                adj[dep].append(tid)
                in_degree[tid] = in_degree.get(tid, 0) + 1

    # Kahn's algorithm
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if visited != len(all_task_ids):
        cycle_tasks = [tid for tid, deg in in_degree.items() if deg > 0]
        errors.append(f"Circular dependencies detected between: {', '.join(cycle_tasks)}")

    # 4. Orphan tasks (no incoming depends_on and not reachable)
    if len(all_task_ids) > 1:
        reachable = set()
        root_tasks = [tid for tid, deg in in_degree.items() if deg == 0]
        # BFS from roots
        stack = list(root_tasks)
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            for neighbor in adj.get(node, []):
                stack.append(neighbor)
        orphaned = all_task_ids - reachable
        if orphaned and len(orphaned) < len(all_task_ids):
            # Only show as warning if not ALL tasks are orphaned (single-task plan)
            orphans_str = ", ".join(sorted(orphaned)[:5])
            if len(orphaned) > 5:
                orphans_str += f" ... and {len(orphaned)-5} more"
            warnings.append(f"Orphaned tasks (no connection to root): {orphans_str}")

    # 5. parallel_groups consistency
    if groups:
        all_group_task_ids = set()
        for gid, group in groups.items():
            for group_tid in group.get("tasks", []):
                if group_tid not in all_task_ids:
                    errors.append(f"parallel_group '{gid}': Task '{group_tid}' does not exist in tasks.")
                all_group_task_ids.add(group_tid)

    result = {
        "status": "valid" if not errors else "invalid",
        "plan_id": plan_id,
        "goal": plan.get("goal", "")[:60],
    }
    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings
    if not errors and not warnings:
        result["summary"] = "Plan ist konsistent und vollständig."
    return result


# ─── Due Date / Deadline ──────────────────────────────────────────────────────

def set_task_due(task_id: str, due_date: str) -> dict:
    """Set a due date for a task.

    Args:
        task_id: Task ID.
        due_date: ISO-8601 date string (e.g. '2026-06-25') or empty string to clear.

    Returns:
        Dict with status and task info, or error dict.
    """
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "No active plan."}
    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' not found."}

    if due_date:
        # Basic ISO-8601 validation
        if not (len(due_date) >= 10 and due_date[4] == "-" and due_date[7] == "-"):
            return {"status": "error", "message": f"Invalid date format '{due_date}'. Expected: ISO-8601 (e.g. 2026-06-25)."}
        plan["tasks"][task_id]["due"] = due_date
    else:
        plan["tasks"][task_id].pop("due", None)

    _save_plan(plan)
    return {"status": "ok", "task_id": task_id, "due": due_date or None}


def get_task_due_info(task_id: str = "") -> Optional[dict]:
    """Get due date info for a task. Returns None if no due date or no active plan.

    Args:
        task_id: Task ID. If empty, uses current task.

    Returns:
        Dict with task_id, due (ISO date string), overdue (bool), days_remaining (int), or None.
    """
    plan = _get_active_plan()
    if not plan:
        return None
    if not task_id:
        task_id = plan.get("current_task", "")
    if not task_id or task_id not in plan["tasks"]:
        return None

    task = plan["tasks"][task_id]
    due = task.get("due", "")
    if not due:
        return None

    from datetime import datetime, timezone

    days_remaining = 0
    overdue = False
    try:
        due_dt = datetime.fromisoformat(due)
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = (due_dt - now).days
        days_remaining = max(delta, 0) if delta >= 0 else delta
        overdue = delta < 0
    except (ValueError, TypeError):
        return {"task_id": task_id, "due": due, "error": "Cannot parse date"}

    return {
        "task_id": task_id,
        "due": due,
        "overdue": overdue,
        "days_remaining": days_remaining,
        "status": "overdue" if overdue else "pending",
    }


# ─── Archive / Restore ────────────────────────────────────────────────────────

ARCHIVE_DIR = PLANS_DIR / "archived"


def archive_plan(plan_id: str) -> dict:
    """Move a plan to the archive directory.

    Args:
        plan_id: The plan ID to archive.

    Returns:
        Dict with status and message.
    """
    path = _plan_path(plan_id)
    if not path.exists():
        return {"status": "error", "message": f"Plan '{plan_id}' not found."}

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ARCHIVE_DIR / f"{plan_id}.json"

    import shutil
    try:
        shutil.move(str(path), str(dest))
    except OSError as e:
        return {"status": "error", "message": f"Archiving failed: {e}"}

    # Clear from active cache if it was the active plan
    global _active_plan, _active_plan_id
    if _active_plan_id == plan_id:
        _active_plan = None
        _active_plan_id = None

    return {
        "status": "archived", "plan_id": plan_id,
        "message": f"Plan '{plan_id}' archived (→ {ARCHIVE_DIR.relative_to(Path.home()) if Path.home() in ARCHIVE_DIR.parents else ARCHIVE_DIR}/).",
    }


def restore_plan(plan_id: str) -> dict:
    """Restore a plan from the archive back to the plans directory.

    Args:
        plan_id: The plan ID to restore.

    Returns:
        Dict with status and message.
    """
    archived = ARCHIVE_DIR / f"{plan_id}.json"
    if not archived.exists():
        return {"status": "error", "message": f"Archived plan '{plan_id}' not found. Use plan_list(include_archived=true) to search."}

    dest = _plan_path(plan_id)
    import shutil
    try:
        shutil.move(str(archived), str(dest))
    except OSError as e:
        return {"status": "error", "message": f"Restore failed: {e}"}

    return {
        "status": "restored", "plan_id": plan_id,
        "message": f"Plan '{plan_id}' restored from archive.",
    }


# ─── Roadmap Data Model ──────────────────────────────────────────────────────

ROADMAPS_DIR = Path.home() / ".hermes" / "roadmaps"
# ROADMAPS_DIR.mkdir() moved to _ensure_dirs() — lazy init on first write


def _roadmap_path(name: str) -> Path:
    """Get the filesystem path for a roadmap YAML file.

    Args:
        name: Roadmap name (with or without .yaml extension).

    Raises:
        ValueError: If name contains path traversal (..) or is absolute.
    """
    if ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid roadmap name: '{name}' (path traversal blocked)")
    if name.endswith(".yaml"):
        name = name[:-5]
    return ROADMAPS_DIR / f"{name}.yaml"


def _list_roadmaps() -> list[dict]:
    """List all available roadmap files.

    Returns:
        List of dicts with 'name' and 'path' keys, sorted by modification time (newest first).
    """
    roadmaps = []
    for f in sorted(ROADMAPS_DIR.glob("*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True):
        roadmaps.append({
            "name": f.stem,
            "path": str(f),
            "modified": f.stat().st_mtime,
        })
    return roadmaps


def _load_roadmap(name: str) -> Optional[dict]:
    """Load a roadmap from a YAML file.

    Args:
        name: Roadmap name (with or without .yaml).

    Returns:
        Parsed roadmap dict, or None if file not found or invalid.
    """
    path = _roadmap_path(name)
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")

        # Try JSON first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try python yaml if available
        try:
            import yaml
            return yaml.safe_load(content)
        except ImportError:
            pass

        # Fallback: simple hand-rolled parser (same as plan_templates)
        return _parse_roadmap_yaml_simple(content)
    except Exception:
        logger.warning(f"Roadmap '{name}' could not be loaded")
        return None


def _save_roadmap(name: str, data: dict) -> bool:
    """Save a roadmap as YAML file.

    Args:
        name: Roadmap name (without .yaml).
        data: Roadmark dict with 'name', 'goal', 'phases' etc.

    Returns:
        True on success, False on failure.
    """
    _ensure_dirs()
    path = _roadmap_path(name)
    try:
        # Try to use yaml for prettier output
        try:
            import yaml
            content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except ImportError:
            # Fallback to JSON
            import json
            content = json.dumps(data, indent=2, ensure_ascii=False)

        path.write_text(content, encoding="utf-8")
        logger.info(f"Roadmap '{name}' saved to {path}")
        return True
    except Exception as e:
        logger.warning(f"Roadmap '{name}' could not be saved: {e}")
        return False


def _parse_roadmap_yaml_simple(content: str) -> Optional[dict]:
    """Simple YAML parser for roadmap files.

    Handles: top-level keys, list of phases with nested fields.
    Uses indentation to distinguish top-level from phase-level keys.
    """
    try:
        result = {}
        current_phase = None
        phases = []
        in_phases = False

        for line in content.split("\n"):
            # Skip empty and comment lines
            if not line.strip() or line.strip().startswith("#"):
                continue

            stripped = line.strip()
            indent = len(line) - len(line.lstrip())

            # If we're inside phases and this line has indentation, it's a phase field
            if in_phases and indent > 0:
                # Phase list item
                if stripped.startswith("-"):
                    if current_phase:
                        phases.append(current_phase)
                    current_phase = {}
                    rest = stripped[1:].strip()
                    if rest:
                        for part in rest.split("  "):
                            part = part.strip()
                            if ":" in part:
                                k, _, v = part.partition(":")
                                k = k.strip()
                                v = v.strip().strip('"').strip("'")
                                if v.startswith("[") and v.endswith("]"):
                                    v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",")]
                                current_phase[k] = v
                # Phase field (indented key: value)
                elif ":" in stripped:
                    k, _, v = stripped.partition(":")
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if v.startswith("[") and v.endswith("]"):
                        v = [x.strip().strip('"').strip("'") for x in v[1:-1].split(",")]
                    current_phase[k] = v
                continue

            # Phase task list item (indented - with no key: value)
            if in_phases and indent > 0 and stripped.startswith("-"):
                # Already handled above
                continue

            # Top-level key: value (no indentation)
            if indent == 0 and ":" in stripped:
                key, _, val = stripped.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key == "phases":
                    in_phases = True
                elif key == "name":
                    result["name"] = val
                elif key == "goal":
                    result["goal"] = val
                elif key == "created":
                    result["created"] = val
                else:
                    result[key] = val
                continue

            # If we hit a non-indented, non-empty line after phases, we're out of phases
            if in_phases and indent == 0 and current_phase is not None:
                # Could be a new top-level key after phases
                pass

        if current_phase:
            phases.append(current_phase)
        if phases:
            result["phases"] = phases

        if result:
            return result
    except Exception:
        pass

    return None
