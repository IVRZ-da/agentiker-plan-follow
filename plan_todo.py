"""plan_todo.py — Eigene Todo-API backed by plan_follow Daten.

Ersetzt das built-in Hermes `todo` Tool im Plan-Workflow.
Statt session-lokalem In-Memory-Store werden die plan_follow Tasks
als Todo-Liste dargestellt und Status-Änderungen werden an plan_core
delegiert (complete_task, update_task, get_plan_status).

Usage:
    plan_todo()                                 → Alle Tasks als Todo-Liste
    plan_todo(todos=[{id,status,...}], merge=True) → Status updaten (completed → plan_complete)

Output-Format identisch zu built-in todo:
    {"todos": [...], "summary": {total, pending, in_progress, completed, cancelled}}
"""

import logging
import sys
from pathlib import Path

from ._fmt import fmt_ok

logger = logging.getLogger("plan_follow")

# Relative Import (Plugin-Kontext) oder absoluter Fallback (Standalone-Test)
try:
    from . import plan_core
except ImportError as e:
    logger.warning("plan_todo: relative import failed, trying sys.path fallback: %s", e)
    # Fallback: sys.path vor Plugin-root setzen
    _plugin_root = Path(__file__).resolve().parent
    if str(_plugin_root) not in sys.path:
        sys.path.insert(0, str(_plugin_root))
    import plan_core

VALID_STATUSES = {"pending", "in_progress", "completed", "cancelled"}

PLAN_STATUS_MAP = {
    "pending": "pending",
    "in_progress": "in_progress",
    "completed": "completed",
    "blocked": "pending",  # blocked tasks erscheinen als pending in der Todo-Liste
}


def _get_todo_list() -> list:
    """Lese alle Tasks aus dem aktiven Plan und formatiere als Todo-Liste.

    Returns: Liste von {id, content, status} passend zum built-in todo Format.
    """
    status = plan_core.get_plan_status()
    if not status:
        return []

    todos = []
    for t in status.get("tasks", []):
        tid = t["id"]
        raw_status = t.get("status", "pending")
        mapped_status = PLAN_STATUS_MAP.get(raw_status, "pending")
        content = t.get("name", f"Task {tid}")

        # Bei blocked: Hinweis in content
        if raw_status == "blocked" and t.get("blocked_by"):
            blocked_by = ", ".join(t["blocked_by"])
            content = f"{content} (blocked by: {blocked_by})"

        todos.append({
            "id": tid,
            "content": content,
            "status": mapped_status,
        })

    return todos


def _build_summary(todos: list) -> dict:
    """Baue Summary-Counts identisch zum built-in todo Tool."""
    return {
        "total": len(todos),
        "pending": sum(1 for t in todos if t["status"] == "pending"),
        "in_progress": sum(1 for t in todos if t["status"] == "in_progress"),
        "completed": sum(1 for t in todos if t["status"] == "completed"),
        "cancelled": sum(1 for t in todos if t["status"] == "cancelled"),
    }


def _apply_write(todos: list) -> list:
    """Wende Status-Änderungen aus der übergebenen Todo-Liste an.

    - 'completed' → plan_core.complete_task()
    - Andere Status-Änderungen werden via plan_core.update_task() versucht
      (falls erlaubt) oder ignoriert.
    """
    for item in todos:
        tid = str(item.get("id", "")).strip()
        new_status = str(item.get("status", "")).strip().lower()
        if not tid or new_status not in VALID_STATUSES:
            continue

        # Hole aktuellen Task-Status aus dem Plan
        status = plan_core.get_plan_status()
        if not status:
            continue
        current_task = next(
            (t for t in status.get("tasks", []) if t["id"] == tid),
            None,
        )
        if not current_task:
            continue
        old_status = current_task.get("status", "")

        if old_status == new_status:
            continue  # Nichts zu tun

        if new_status == "completed":
            # Delegiere an plan_core.complete_task()
            try:
                # complete_task prüft selbst ob task_id == current_task
                result = plan_core.complete_task(tid)
                if result and result.get("status") in ("completed", "already_completed"):
                    pass
            except Exception as e:
                logger.warning("plan_todo: complete_task(%s) failed: %s", tid, e)
        elif new_status in ("in_progress", "pending"):
            # Bei in_progress/pending: Versuche update_task (wenn unterstützt)
            try:
                result = plan_core.update_task(tid, {"status": new_status})
                if result:
                    pass
            except Exception as e:
                # update_task unterstützt kein status-Feld → silent skip
                logger.debug("update_task status change failed: %s", e)

    # Neu einlesen nach Änderungen
    todos = _get_todo_list()

    return todos


def plan_todo_tool(args: dict, **kwargs) -> str:
    """Eigene Todo-API backed by plan_follow Daten.

    Ersetzt das built-in Hermes `todo` Tool im Plan-Workflow.

    Read mode (keine todos):
        Gibt alle Tasks des aktiven Plans als Todo-Liste zurück.
        Format identisch zu built-in todo: {todos: [...], summary: {...}}

    Write mode (todos + merge):
        Erlaubt Status-Änderungen:
        - 'completed' → delegiert an plan_core.complete_task()
        - Andere → werden ignoriert (Plan verwaltet Status selbst)

    Returns:
        JSON mit {todos: [...], summary: {total, pending, in_progress, completed, cancelled}}
    """
    write_todos = args.get("todos", None)
    merge = args.get("merge", False)

    if write_todos is not None and merge:
        # Write mode
        result_todos = _apply_write(write_todos)
    else:
        # Read mode
        result_todos = _get_todo_list()

    summary = _build_summary(result_todos)

    return fmt_ok({
        "todos": result_todos,
        "summary": summary,
    })
