"""plugin_api.py — FastAPI Router für plan-follow-dashboard.

Bereitgestellt unter /api/plugins/plan-follow-dashboard/*
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger("plan-follow-dashboard")

router = APIRouter(prefix="/plan-follow-dashboard", tags=["plan-follow"])


def _get_plans_dir() -> Path:
    return Path.home() / ".hermes" / "plans"


def _load_plans() -> list[dict]:
    """Load all plan JSON files from the plans directory."""
    plans_dir = _get_plans_dir()
    plans = []
    if not plans_dir.exists():
        return plans
    for f in sorted(plans_dir.glob("*.json"), reverse=True):
        if f.name == "plans_index.json":
            continue
        if f.parent.parent.name == "archived" or "archived" in f.parts:
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
            })
        except (json.JSONDecodeError, OSError):
            continue
    return plans[:50]


@router.get("/plans")
async def list_plans(limit: int = Query(20, ge=1, le=100)):
    """List all plans with status summaries."""
    plans = _load_plans()
    return {"plans": plans[:limit], "total": len(plans)}


@router.get("/plans/{plan_id}")
async def get_plan(plan_id: str):
    """Get a plan by ID with full task details."""
    plans_dir = _get_plans_dir()
    f = plans_dir / f"{plan_id}.json"
    if not f.exists():
        # Try with .json appended
        for pf in plans_dir.glob(f"{plan_id}*.json"):
            f = pf
            break
        else:
            raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
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
                "review_state": t.get("review_result", {}).get("status") if t.get("review_result") else None,
            })
        return {
            "plan_id": data.get("plan_id"),
            "goal": data.get("goal", ""),
            "created": data.get("created", ""),
            "current_task": data.get("current_task"),
            "parallel_groups": data.get("parallel_groups"),
            "tasks": task_list,
            "task_count": len(task_list),
        }
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats():
    """Get overall plan statistics."""
    plans = _load_plans()
    total_plans = len(plans)
    active_plans = sum(1 for p in plans if p.get("current_task"))
    completed_tasks = 0
    pending_tasks = 0
    for p in plans:
        s = p.get("status_summary", {})
        completed_tasks += s.get("completed", 0)
        pending_tasks += s.get("pending", 0) + s.get("in_progress", 0)
    return {
        "total_plans": total_plans,
        "active_plans": active_plans,
        "completed_tasks": completed_tasks,
        "pending_tasks": pending_tasks,
        "completion_rate": round(completed_tasks / (completed_tasks + pending_tasks) * 100, 1)
        if (completed_tasks + pending_tasks) > 0 else 0,
    }
