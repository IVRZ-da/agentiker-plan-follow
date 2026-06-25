"""plugin_api.py — FastAPI Router für plan-follow-dashboard.

Bereitgestellt unter /api/plugins/plan-follow-dashboard/*
Unterstützt zwei Backends:
  1. Kanban-DB (primär, nach Migration)
  2. JSON-Dateien (Legacy, bis Migration abgeschlossen)

Beide Backends liefern das gleiche API-Format.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("plan-follow-dashboard")

router = APIRouter(prefix="/plan-follow-dashboard", tags=["plan-follow"])

# ─── Kanban-DB Backend (primär) ─────────────────────────────────────────────

def _kanban_available() -> bool:
    """Check if the Kanban DB is available and has plan tasks."""
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        row = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE body LIKE '%\"type\":\"plan\"%'"
        ).fetchone()
        return row is not None and row[0] > 0
    except Exception:
        return False


def _load_plans_from_kanban(limit: int = 50) -> list[dict]:
    """Load plans from Kanban DB (tasks with type='plan' in body)."""
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        rows = conn.execute(
            "SELECT id, title, body, assignee, status, priority, created_at, "
            "current_run_id FROM tasks "
            "WHERE body LIKE '%\"type\":\"plan\"%' "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
        plans = []
        for row in rows:
            body = {}
            try:
                body = json.loads(row[2]) if row[2] else {}
            except (json.JSONDecodeError, TypeError):
                pass
            task_count = body.get("task_count", 0)
            status_summary = body.get("status_summary", {})
            plans.append({
                "plan_id": row[0],
                "goal": body.get("goal", row[1])[:80],
                "created": row[6] or "",
                "current_task": body.get("current_task"),
                "task_count": task_count,
                "status_summary": status_summary,
                "has_tasks": task_count > 0,
                "source": "kanban",
                "assignee": row[3],
                "status": row[4],
                "priority": row[5],
            })
        return plans
    except Exception as e:
        logger.warning("Kanban plan load failed: %s", e)
        return []


def _get_plan_from_kanban(plan_id: str) -> Optional[dict]:
    """Get a single plan with all child tasks from Kanban DB."""
    try:
        from hermes_cli import kanban_db
        conn = kanban_db.connect()
        # Root plan task
        row = conn.execute(
            "SELECT id, title, body, assignee, status, priority, created_at "
            "FROM tasks WHERE id = ?",
            (plan_id,)
        ).fetchone()
        if not row:
            return None

        body = {}
        try:
            body = json.loads(row[2]) if row[2] else {}
        except (json.JSONDecodeError, TypeError):
            pass

        # Child tasks (Plan-Unter-Tasks)
        child_rows = conn.execute(
            "SELECT t.id, t.title, t.body, t.assignee, t.status, "
            "t.priority, t.created_at, t.current_run_id "
            "FROM task_links l JOIN tasks t ON t.id = l.child_id "
            "WHERE l.parent_id = ? ORDER BY t.created_at",
            (plan_id,)
        ).fetchall()

        tasks = []
        for c in child_rows:
            c_body = {}
            try:
                c_body = json.loads(c[2]) if c[2] else {}
            except (json.JSONDecodeError, TypeError):
                pass
            tasks.append({
                "id": c[0],
                "name": c_body.get("name", c[1]),
                "status": c[4],
                "assignee": c[3],
                "files": c_body.get("files", []),
                "verify": c_body.get("verify", ""),
                "review_profile": c_body.get("review_profile", "none"),
            })

        return {
            "plan_id": row[0],
            "goal": body.get("goal", row[1]),
            "created": row[6] or body.get("created", ""),
            "current_task": body.get("current_task"),
            "parallel_groups": body.get("parallel_groups"),
            "tasks": tasks,
            "task_count": len(tasks),
            "source": "kanban",
            "assignee": row[3],
            "status": row[4],
        }
    except Exception as e:
        logger.warning("Kanban plan detail failed: %s", e)
        return None


# ─── JSON-Backend (Legacy) ──────────────────────────────────────────────────

def _get_plans_dir() -> Path:
    return Path.home() / ".hermes" / "plans"


def _load_plans_from_json() -> list[dict]:
    """Load all plan JSON files from the plans directory (Legacy)."""
    plans_dir = _get_plans_dir()
    plans = []
    if not plans_dir.exists():
        return plans
    for f in sorted(plans_dir.glob("*.json"), reverse=True):
        if f.name == "plans_index.json":
            continue
        if "archived" in f.parts:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            tasks = data.get("tasks", {})
            status_counts = {}
            for t in tasks.values():
                s = t.get("status", "unknown")
                status_counts[s] = status_counts.get(s, 0) + 1
            plans.append({
                "plan_id": data.get("plan_id", f.stem),
                "goal": data.get("goal", "")[:80],
                "created": data.get("created", ""),
                "current_task": data.get("current_task"),
                "task_count": len(tasks),
                "status_summary": status_counts,
                "has_tasks": len(tasks) > 0,
                "source": "json",
            })
        except (json.JSONDecodeError, OSError):
            continue
    return plans[:50]


def _get_plan_from_json(plan_id: str) -> Optional[dict]:
    """Get a single plan from JSON files (Legacy)."""
    plans_dir = _get_plans_dir()
    f = plans_dir / f"{plan_id}.json"
    if not f.exists():
        for pf in plans_dir.glob(f"{plan_id}*.json"):
            f = pf
            break
        else:
            return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        tasks = data.get("tasks", {})
        task_list = []
        for tid, t in tasks.items():
            task_list.append({
                "id": tid,
                "name": t.get("name", ""),
                "status": t.get("status", "pending"),
                "files": t.get("files", []),
                "review_profile": t.get("review_profile", "none"),
                "review_state": (
                    t.get("review_result", {}).get("status")
                    if t.get("review_result") else None
                ),
            })
        return {
            "plan_id": data.get("plan_id"),
            "goal": data.get("goal", ""),
            "created": data.get("created", ""),
            "current_task": data.get("current_task"),
            "parallel_groups": data.get("parallel_groups"),
            "tasks": task_list,
            "task_count": len(task_list),
            "source": "json",
        }
    except (json.JSONDecodeError, OSError):
        return None


# ─── API Endpoints ──────────────────────────────────────────────────────────


def _load_plans(limit: int = 50) -> list[dict]:
    """Load plans — tries Kanban first, falls back to JSON."""
    kanban_plans = _load_plans_from_kanban(limit)
    if kanban_plans:
        return kanban_plans
    return _load_plans_from_json()


def _get_plan(plan_id: str) -> Optional[dict]:
    """Get a plan — tries Kanban first, falls back to JSON."""
    plan = _get_plan_from_kanban(plan_id)
    if plan:
        return plan
    return _get_plan_from_json(plan_id)


@router.get("/plans")
async def list_plans(limit: int = Query(20, ge=1, le=100)):
    """List all plans with status summaries."""
    plans = _load_plans(limit)
    return {"plans": plans[:limit], "total": len(plans)}


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    """Get a plan by ID with full task details."""
    plan = _get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
    return plan


@router.get("/backends")
async def list_backends():
    """Show which backends are available and active."""
    kanban = _kanban_available()
    return {
        "backends": {
            "kanban": {"available": kanban, "active": kanban},
            "json": {"available": True, "active": not kanban},
        },
        "active_backend": "kanban" if kanban else "json",
    }


@router.get("/stats")
async def get_stats():
    """Get overall plan statistics."""
    plans = _load_plans(100)
    total_plans = len(plans)
    active_plans = sum(1 for p in plans if p.get("current_task"))
    completed_tasks = 0
    pending_tasks = 0
    for p in plans:
        s = p.get("status_summary", {})
        completed_tasks += s.get("completed", 0)
        pending_tasks += s.get("pending", 0) + s.get("in_progress", 0)
    total = completed_tasks + pending_tasks
    return {
        "total_plans": total_plans,
        "active_plans": active_plans,
        "completed_tasks": completed_tasks,
        "pending_tasks": pending_tasks,
        "completion_rate": round(completed_tasks / total * 100, 1) if total > 0 else 0,
    }
