"""status.py — Status + List + Progress for plan_follow tools/ subpackage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .. import plan_core
from .._fmt import fmt_info, fmt_ok
from .base import (
    _get_active_plan,
)
from .resolver import resolve_plans_dir
from .state import STATE


def get_plan_status() -> Optional[dict]:
    """Return full plan status overview."""
    plan = _get_active_plan()
    if not plan:
        return None

    total = len(plan["tasks"])
    done = sum(1 for t in plan["tasks"].values() if t["status"] == "completed")
    sum(1 for t in plan["tasks"].values() if t["status"] == "blocked")

    tasks_list = []
    for tid, tdef in plan["tasks"].items():
        entry = {"id": tid, "name": tdef.get("name", tid), "status": tdef["status"]}
        if tdef["status"] == "blocked":
            deps = [d for d in tdef.get("depends_on", [])
                    if plan["tasks"].get(d, {}).get("status") != "completed"]
            entry["blocked_by"] = deps
        tasks_list.append(entry)

    return {
        "plan_id": plan.get("plan_id", "?"),
        "goal": plan.get("goal", ""),
        "progress": f"{done}/{total} tasks ({total and done*100//total}%)",
        "current_task": plan.get("current_task"),
        "tasks": tasks_list,
    }


def list_plans(include_archived: bool = False, limit: int = 0) -> list[dict]:
    """List all plans from PLANS_DIR, newest first (including completed/aborted).

    Args:
        include_archived: If True, also list plans from the archive directory.
        limit: If > 0, nur die ersten N Eintraege zurueckgeben.

    Returns:
        List of plan summary dicts.
    """
    plans = _list_plans_from_dir(resolve_plans_dir(), is_active=True)

    if include_archived:
        arch_dir = resolve_plans_dir() / "archived"
        if arch_dir.exists():
            archived_plans = _list_plans_from_dir(arch_dir, is_active=False)
            for ap in archived_plans:
                ap["is_archived"] = True
            plans.extend(archived_plans)

    if limit and limit > 0:
        return plans[:limit]
    return plans


def _list_plans_from_dir(directory: Path, is_active: bool = False) -> list[dict]:
    """List plans from a specific directory.

    Leere/beschaedigte Plan-Dateien (kein ``plan_id`` oder keine ``tasks``) werden
    uebersprungen — nach dem Datenverlust vom 10.11.2026 lagen 80 solcher
    2-Byte-``{}``-Dateien im Verzeichnis und machten das Listing unbrauchbar.
    Sortiert wird nach ``created`` (nicht nach Dateiname), damit die Reihenfolge
    der Realitaet entspricht.
    """
    plans = []
    active_id = STATE.active_plan_id
    for f in directory.glob("*.json"):
        if f.name == "plans_index.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        plan_id = data.get("plan_id")
        tasks = data.get("tasks")
        if not plan_id or not isinstance(tasks, dict) or not tasks:
            continue  # leere/beschaedigte Datei ueberspringen

        total = len(tasks)
        completed = sum(1 for t in tasks.values() if t.get("status") == "completed")
        plans.append({
            "plan_id": plan_id,
            "goal": str(data.get("goal", ""))[:60],
            "created": data.get("created", ""),
            "current_task": data.get("current_task"),
            "total_tasks": total,
            "completed_tasks": completed,
            "progress": f"{completed}/{total}",
            "is_active": bool(is_active and active_id) and plan_id == active_id,
            # Nur Sortierhilfe: 'created' hat Sekundengenauigkeit, zwei kurz
            # nacheinander erzeugte Plaene sind damit gleich alt.
            "_mtime": f.stat().st_mtime,
        })

    plans.sort(key=lambda p: (str(p.get("created") or ""), p.get("_mtime", 0.0)), reverse=True)
    for p in plans:
        p.pop("_mtime", None)
    return plans


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
                group_parts.append(f"\u2705{gid}({g_done}/{g_total})")
            elif group["status"] == "in_progress":
                group_parts.append(f"\u25b6\ufe0f{gid}({g_done}/{g_total})")
            else:
                group_parts.append(f"\u2b1c{gid}({g_done}/{g_total})")
        return f"{done}/{total} " + " \u2192 ".join(group_parts)

    # Linear mode: show individual task progress
    task_ids = list(plan["tasks"].keys())
    current_idx = task_ids.index(plan.get("current_task")) if plan.get("current_task") in task_ids else -1
    parts = []
    for i, tid in enumerate(task_ids):
        if i < current_idx:
            parts.append(f"\u2705{tid}")
        elif i == current_idx:
            parts.append(f"\u25b6\ufe0f{tid}")
        else:
            parts.append(f"\u2b1c{tid}")
    return f"{done}/{total} " + " \u2192 ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# CRUD Handler Functions (moved from handlers_crud.py)
# ═══════════════════════════════════════════════════════════════════════════════


def plan_current_tool(args: dict, **kwargs) -> str:
    """Show the current task. Only ONE task is visible at a time."""
    current = plan_core.get_current_task()
    if not current:
        return fmt_info("No active plan. Use plan_create() to start one.")
    return fmt_ok(current)


def plan_status_tool(args: dict, **kwargs) -> str:
    """Show all tasks with their status."""
    status = plan_core.get_plan_status()
    if not status:
        return fmt_info("No active plan.")
    return fmt_ok(status)


def plan_list_tool(args: dict, **kwargs) -> str:
    """List all plans (including completed/aborted), newest first.

    Parameters:
    - include_archived (bool, optional): auch archivierte Plaene zeigen
    - limit (int, optional): max. Eintraege (default 20, 0 = alle)

    Die Ausgabe ist bewusst begrenzt: 81 Plaene erzeugten ~22k Zeichen
    Tool-Result, davon 80 leere Dateien ohne Erkenntniswert.
    """
    include_archived = bool(args.get("include_archived", False))
    try:
        limit = int(args.get("limit", 20) or 0)
    except (TypeError, ValueError):
        limit = 20

    all_plans = plan_core.list_plans(include_archived=include_archived)
    total = len(all_plans)
    shown = all_plans[:limit] if limit and limit > 0 else all_plans
    return fmt_ok({
        "status": "ok",
        "count": len(shown),
        "total": total,
        "has_more": total > len(shown),
        "plans": shown,
    })
