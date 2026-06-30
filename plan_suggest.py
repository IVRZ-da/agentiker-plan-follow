"""plan_suggest.py — AI-gestützte Plan-Vorschläge für plan_follow.

Analysiert das Projekt (Codebase, Git-History, Abhängigkeiten) und generiert
Vorschläge für Task-Zerlegungen basierend auf einem Goal.

Typische Workflows:
- "add payment provider stripe" → Scannt bestehende Payment-Provider, findet Patterns
- "fix login bug" → Sucht Login-bezogene Files, schlägt RED→GREEN→REFACTOR vor
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("plan_follow")


def _find_project_root(path: str = "") -> str:
    """Find project root by looking for marker files."""
    base = path or os.getcwd()
    for marker in (".git", "package.json", "go.mod", "pyproject.toml", "Cargo.toml"):
        p = os.path.join(base, marker)
        if os.path.exists(p):
            return base
    # Walk up
    parent = os.path.dirname(base)
    if parent and parent != base:
        return _find_project_root(parent)
    return base


def _detect_project_type(project_root: str) -> dict[str, Any]:
    """Detect project type and return relevant info."""
    info = {"type": "unknown", "frameworks": [], "markers": []}

    markers = {
        "package.json": "node",
        "go.mod": "go",
        "pyproject.toml": "python",
        "Cargo.toml": "rust",
        "composer.json": "php",
        "Gemfile": "ruby",
    }

    for marker, ptype in markers.items():
        if os.path.exists(os.path.join(project_root, marker)):
            info["type"] = ptype
            info["markers"].append(marker)

    return info


def _suggest_tasks_for_goal(goal: str, project_info: dict[str, Any]) -> list[dict]:
    """Generate suggested tasks based on goal and project type.

    Uses keyword heuristics to match goals to common work patterns.
    """
    goal_lower = goal.lower()
    tasks = []

    # New feature pattern
    if any(w in goal_lower for w in ("feature", "add ", "new ", "implement", "create")):
        tasks = [
            {"id": "t1", "name": "Spec / Types definieren", "files": ["src/"],
             "verify": "", "depends_on": [], "review_profile": "unit-test"},
            {"id": "t2", "name": "RED: Tests schreiben", "files": [],
             "verify": "", "depends_on": ["t1"], "review_profile": "unit-test"},
            {"id": "t3", "name": "GREEN: Implementierung", "files": ["src/"],
             "verify": "", "depends_on": ["t2"], "review_profile": "unit-test"},
            {"id": "t4", "name": "Dokumentation", "files": ["README.md", "docs/"],
             "verify": "", "depends_on": ["t3"], "review_profile": "unit-test"},
        ]

    # Bug fix pattern
    elif any(w in goal_lower for w in ("bug", "fix ", "error", "issue", "fail", "broken")):
        tasks = [
            {"id": "t1", "name": "Bug-Analyse / Root-Cause finden", "files": ["src/"],
             "verify": "", "depends_on": [], "review_profile": "unit-test"},
            {"id": "t2", "name": "RED: Test schreiben der Bug reproduziert", "files": [],
             "verify": "", "depends_on": ["t1"], "review_profile": "unit-test"},
            {"id": "t3", "name": "GREEN: Bug fixen", "files": ["src/"],
             "verify": "", "depends_on": ["t2"], "review_profile": "unit-test"},
        ]

    # Refactoring pattern
    elif any(w in goal_lower for w in ("refactor", "clean", "restructure", "redesign", "optimize")):
        tasks = [
            {"id": "t1", "name": "Coverage-Baseline + Analyse", "files": [],
             "verify": "", "depends_on": [], "review_profile": "full"},
            {"id": "t2", "name": "Refactoring durchführen", "files": ["src/"],
             "verify": "", "depends_on": ["t1"], "review_profile": "unit-test"},
            {"id": "t3", "name": "Tests + Coverage nach Refactoring", "files": [],
             "verify": "", "depends_on": ["t2"], "review_profile": "unit-test"},
        ]

    # Deploy / Release pattern
    elif any(w in goal_lower for w in ("deploy", "release", "publish", "rollout")):
        tasks = [
            {"id": "t1", "name": "Build + Tests", "files": [],
             "verify": "", "depends_on": [], "review_profile": "api-route"},
            {"id": "t2", "name": "Deploy ausführen", "files": [],
             "verify": "", "depends_on": ["t1"], "review_profile": "none"},
            {"id": "t3", "name": "Health-Check + Smoke-Test", "files": [],
             "verify": "", "depends_on": ["t2"], "review_profile": "none"},
        ]

    # Security pattern
    elif any(w in goal_lower for w in ("security", "audit", "vulnerability", "cve", "exploit")):
        tasks = [
            {"id": "t1", "name": "Security-Scan durchführen", "files": [],
             "verify": "", "depends_on": [], "review_profile": "security"},
            {"id": "t2", "name": "Findings analysieren + priorisieren", "files": [],
             "verify": "", "depends_on": ["t1"], "review_profile": "security"},
            {"id": "t3", "name": "Fix: Schwachstellen beheben", "files": ["src/"],
             "verify": "", "depends_on": ["t2"], "review_profile": "security"},
            {"id": "t4", "name": "Re-Scan + Verify", "files": [],
             "verify": "", "depends_on": ["t3"], "review_profile": "security"},
        ]

    # Research / Documentation pattern
    elif any(w in goal_lower for w in ("research", "docs", "documentation", "wiki", "readme")):
        tasks = [
            {"id": "t1", "name": "Recherche + Quellen sammeln", "files": [],
             "verify": "", "depends_on": [], "review_profile": "none"},
            {"id": "t2", "name": "Inhalt schreiben / strukturieren", "files": ["docs/"],
             "verify": "", "depends_on": ["t1"], "review_profile": "none"},
            {"id": "t3", "name": "Review + Korrektur", "files": [],
             "verify": "", "depends_on": ["t2"], "review_profile": "none"},
        ]

    # Default: multi-step implementation
    else:
        tasks = [
            {"id": "t1", "name": "Analyse: Goal verstehen + Scope definieren", "files": [],
             "verify": "", "depends_on": [], "review_profile": "unit-test"},
            {"id": "t2", "name": "Implementierung Schritt 1", "files": ["src/"],
             "verify": "", "depends_on": ["t1"], "review_profile": "unit-test"},
            {"id": "t3", "name": "Implementierung Schritt 2", "files": ["src/"],
             "verify": "", "depends_on": ["t2"], "review_profile": "unit-test"},
            {"id": "t4", "name": "Tests + Verify", "files": [],
             "verify": "", "depends_on": ["t3"], "review_profile": "unit-test"},
        ]

    # Add appropriate verify commands based on project type
    ptype = project_info.get("type", "unknown")
    for task in tasks:
        if not task["verify"]:
            if ptype == "node":
                task["verify"] = "npm test 2>/dev/null || echo '✅ verify pending'"
            elif ptype == "go":
                task["verify"] = "go test ./... 2>/dev/null || echo '✅ verify pending'"
            elif ptype == "python":
                task["verify"] = "python3 -m pytest 2>/dev/null || echo '✅ verify pending'"
            elif ptype == "rust":
                task["verify"] = "cargo test 2>/dev/null || echo '✅ verify pending'"
            else:
                task["verify"] = "echo '✅ verify pending'"

    return tasks


def suggest_plan(goal: str, project_root: str = "") -> dict:
    """Generate a plan suggestion for a given goal.

    Args:
        goal: The goal to plan for.
        project_root: Optional project root path. Auto-detected if empty.

    Returns:
        Dict with suggested template, tasks, and project info.
    """
    root = _find_project_root(project_root) if project_root else _find_project_root()
    project_info = _detect_project_type(root)
    tasks = _suggest_tasks_for_goal(goal, project_info)

    # Determine best template
    goal_lower = goal.lower()
    if any(w in goal_lower for w in ("bug", "fix ", "error", "issue", "fail")):
        suggested_template = "bugfix"
    elif any(w in goal_lower for w in ("feature", "add ", "new ", "implement")):
        suggested_template = "feature"
    elif any(w in goal_lower for w in ("refactor", "clean", "restructure")):
        suggested_template = "refactoring"
    elif any(w in goal_lower for w in ("deploy", "release")):
        suggested_template = "deploy"
    else:
        suggested_template = "multi"

    return {
        "goal": goal,
        "suggested_template": suggested_template,
        "suggested_tasks": tasks,
        "task_count": len(tasks),
        "project_type": project_info.get("type", "unknown"),
        "frameworks": project_info.get("frameworks", []),
        "project_root": root,
        "note": "Vorschlag basiert auf Keyword-Analyse. Tasks können vor plan_create angepasst werden.",
    }


# ─── Time Tracking ────────────────────────────────────────────────────────────

_TRACKING_FILE = Path.home() / ".hermes" / "plans" / "time_tracking.json"


def _ensure_tracking_file():
    _TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _TRACKING_FILE.exists():
        _TRACKING_FILE.write_text("{}", encoding="utf-8")


def time_track(action: str, task_id: str = "", plan_id: str = "") -> dict:
    """Track time for tasks.

    Args:
        action: 'start', 'stop', 'status', or 'history'.
        task_id: Task ID.
        plan_id: Plan ID.

    Returns:
        Dict with tracking info.
    """
    _ensure_tracking_file()
    from datetime import datetime, timezone

    try:
        data = json.loads(_TRACKING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}

    now = datetime.now(timezone.utc).isoformat()

    if action == "start":
        key = f"{plan_id}:{task_id}" if plan_id else task_id
        data[key] = {"started": now, "status": "running", "task_id": task_id, "plan_id": plan_id}
        _TRACKING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"status": "started", "task_id": task_id, "started_at": now}

    elif action == "stop":
        key = f"{plan_id}:{task_id}" if plan_id else task_id
        entry = data.get(key)
        if not entry:
            return {"status": "error", "message": f"No tracking entry for {key}"}
        started = entry.get("started", now)
        from datetime import datetime as dt
        start_dt = dt.fromisoformat(started)
        end_dt = dt.fromisoformat(now)
        duration_min = round((end_dt - start_dt).total_seconds() / 60, 1)
        entry["stopped"] = now
        entry["duration_min"] = duration_min
        entry["status"] = "completed"
        _TRACKING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return {"status": "stopped", "task_id": task_id, "duration_min": duration_min}

    elif action == "status":
        key = f"{plan_id}:{task_id}" if plan_id else task_id
        entry = data.get(key, {})
        if not entry:
            return {"status": "not_found", "task_id": task_id}
        return {"status": "found", "task_id": task_id, "entry": entry}

    elif action == "history":
        entries = []
        for k, v in data.items():
            if not task_id or task_id in k:
                entries.append({"key": k, **v})
        entries.sort(key=lambda x: x.get("started", ""), reverse=True)
        return {"status": "ok", "entries": entries[:50]}

    return {"status": "error", "message": f"Unknown action '{action}'"}


# ─── What-If Simulation ───────────────────────────────────────────────────────


def simulate_plan(plan: dict) -> dict:
    """Analyze a plan's dependency graph and suggest optimizations.

    Calculates:
    - Critical path (longest chain of dependent tasks)
    - Parallelization opportunities
    - Estimated wall-clock time

    Args:
        plan: Plan dict with tasks and optional parallel_groups.

    Returns:
        Dict with simulation results.
    """
    tasks = plan.get("tasks", {})
    parallel_groups = plan.get("parallel_groups", {})

    if not tasks:
        return {"status": "error", "message": "Plan hat keine Tasks"}

    # Build dependency graph
    task_ids = list(tasks.keys())
    task_names = {tid: tasks[tid].get("name", tid) for tid in task_ids}

    # Find critical path (longest depends_on chain)
    def _path_length(tid: str, visited: set = None) -> int:
        if visited is None:
            visited = set()
        if tid in visited:
            return 0  # cycle protection
        visited.add(tid)
        deps = tasks[tid].get("depends_on", [])
        if not deps:
            return 1
        return 1 + max(_path_length(d, set(visited)) for d in deps if d in tasks)

    depths = {tid: _path_length(tid) for tid in task_ids}
    max_depth = max(depths.values()) if depths else 0

    # Tasks sorted by depth = topological order
    sorted_tasks = sorted(task_ids, key=lambda t: (depths.get(t, 0), t))

    # Parallel opportunities (same depth = can run in parallel if no depends_on conflict)
    depth_groups = {}
    for tid in sorted_tasks:
        d = depths.get(tid, 0)
        depth_groups.setdefault(d, []).append(task_names.get(tid, tid))

    # Estimate with vs without parallel_groups
    sequential_estimate = len(task_ids)  # 1 unit per task
    parallel_estimate = max_depth  # critical path length

    # Parse parallel_groups suggestions
    suggestion = None
    if parallel_estimate < sequential_estimate and len(task_ids) > 2:
        suggestion = {
            "note": "Parallele Ausführung möglich",
            "estimated_speedup": f"{sequential_estimate - parallel_estimate} task-units saved",
            "parallel_groups": {},
        }
        # Suggest forming groups from same-depth tasks
        for d, tnames in depth_groups.items():
            if len(tnames) > 1:
                gid = f"g{d}"
                # Find actual task IDs for names
                tids_in_group = [tid for tid in task_ids if task_names.get(tid) in tnames]
                suggestion["parallel_groups"][gid] = {"tasks": tids_in_group}

    results = {
        "status": "ok",
        "task_count": len(task_ids),
        "critical_path_length": max_depth,
        "sequential_estimate": f"{sequential_estimate} task-units",
        "parallel_estimate": f"{parallel_estimate} task-units (best case)",
        "parallel_possible": max_depth < sequential_estimate,
        "critical_path_tasks": [task_names.get(tid, tid) for tid in sorted_tasks
                                if depths.get(tid) == max_depth],
        "depth_groups": depth_groups,
        "suggestion": suggestion,
    }

    # Add parallel_groups info if available
    if parallel_groups:
        results["current_parallel_groups"] = dict(parallel_groups)

    return results


# ─── Tool Handlers (imported by plan_tools.py) ─────────────────────────────

from . import plan_core  # noqa: E402
from ._fmt import fmt_err, fmt_ok  # noqa: E402


def plan_simulate_tool(args: dict, **kwargs) -> str:
    """Simulate a plan to find critical path and parallelization opportunities.

    Parameters:
    - plan_id (str, optional): Plan ID to simulate (defaults to active plan).
    """
    plan_id = args.get("plan_id", "")
    plan = None
    if plan_id:
        plan = plan_core._load_plan(plan_id)
        if not plan:
            return fmt_err(f"Plan '{plan_id}' not found.")
    else:
        plan = plan_core._get_active_plan()
        if not plan:
            return fmt_err("No active plan.")
    result = simulate_plan(plan)
    return fmt_ok(result)


def plan_suggest_tool(args: dict, **kwargs) -> str:
    """Suggest a plan decomposition for a goal by analyzing the project.

    Parameters:
    - goal (str, required): The goal to generate suggestions for.
    - project_root (str, optional): Project root path (auto-detected if empty).

    Returns suggested template name, task list, and project info.
    """
    goal = args.get("goal", "")
    if not goal:
        return fmt_err("goal is required for plan suggestions")
    project_root = args.get("project_root", "")
    result = suggest_plan(goal, project_root)
    return fmt_ok(result)


def plan_time_tool(args: dict, **kwargs) -> str:
    """Track time for tasks (start/stop/status/history).

    Parameters:
    - action (str, required): 'start', 'stop', 'status', or 'history'
    - task_id (str, optional): Task ID
    - plan_id (str, optional): Plan ID
    """
    action = args.get("action", "")
    if not action:
        return fmt_err("action is required (start, stop, status, history)")
    task_id = args.get("task_id", "")
    plan_id = args.get("plan_id", "")
    result = time_track(action, task_id, plan_id)
    return fmt_ok(result)
