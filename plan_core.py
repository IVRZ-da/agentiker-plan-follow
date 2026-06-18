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
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("plan_follow")

PLANS_DIR = Path.home() / ".hermes" / "plans"
PLANS_DIR.mkdir(parents=True, exist_ok=True)

HONCHO_URL = "http://127.0.0.1:8001"
HONCHO_WORKSPACE = "plan-follow"
HONCHO_PEER = "plan-follow-agent"


# ─── In-Memory Cache ─────────────────────────────────────────────────────────

_active_plan: Optional[dict] = None
_active_plan_id: Optional[str] = None


def _reset_cache():
    global _active_plan, _active_plan_id
    _active_plan = None
    _active_plan_id = None


# ─── JSON Persistence ─────────────────────────────────────────────────────────

def _plan_path(plan_id: str) -> Path:
    return PLANS_DIR / f"{plan_id}.json"


def _save_plan(plan: dict) -> None:
    path = _plan_path(plan["plan_id"])
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    global _active_plan, _active_plan_id
    _active_plan = plan
    _active_plan_id = plan["plan_id"]


def _load_plan(plan_id: str) -> Optional[dict]:
    path = _plan_path(plan_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _get_active_plan() -> Optional[dict]:
    global _active_plan
    return _active_plan


# ─── Honcho Integration ───────────────────────────────────────────────────────

def _ensure_honcho_workspace():
    """Create plan-follow workspace + peer if they don't exist."""
    import urllib.request

    try:
        req = urllib.request.Request(
            f"{HONCHO_URL}/v3/workspaces",
            data=json.dumps({"id": HONCHO_WORKSPACE}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)

        req = urllib.request.Request(
            f"{HONCHO_URL}/v3/workspaces/{HONCHO_WORKSPACE}/peers",
            data=json.dumps({"id": HONCHO_PEER}).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"Honcho workspace setup failed (non-fatal): {e}")


def _save_plan_state_to_honcho(plan_id: str, task_id: str, status: str):
    """Save plan state as Honcho conclusion for cross-session recall."""
    import urllib.request

    try:
        data = json.dumps({
            "conclusions": [{
                "observer_id": HONCHO_PEER,
                "observed_id": HONCHO_PEER,
                "content": f"plan_follow:{plan_id}:{task_id}={status}",
                "source": "plan-follow-plugin"
            }]
        }).encode()
        req = urllib.request.Request(
            f"{HONCHO_URL}/v3/workspaces/{HONCHO_WORKSPACE}/conclusions",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning(f"Honcho save failed (non-fatal): {e}")


def _load_plan_state_from_honcho() -> Optional[str]:
    """Load active plan ID from Honcho. Returns plan_id or None."""
    import urllib.request

    try:
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
            content: str = c.get("content", "")
            if "plan_follow:active=true" in content:
                # Format: "plan_follow:<plan_id>:active=true"
                parts = content.split(":")
                if len(parts) >= 2:
                    return parts[1]
    except Exception as e:
        logger.warning(f"Honcho load failed (non-fatal): {e}")
    return None


# ─── Plan CRUD ────────────────────────────────────────────────────────────────

def create_plan(goal: str, tasks: list, repo: str = "") -> str:
    """Create a new plan and persist it. Returns plan_id."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    plan_id = f"{now[:10]}-{goal.lower().replace(' ', '-')[:40]}"

    tasks_dict = {}
    for t in tasks:
        tasks_dict[t["id"]] = {
            "status": "pending",
            "name": t.get("name", ""),
            "files": t.get("files", []),
            "verify": t.get("verify", ""),
            "depends_on": t.get("depends_on", []),
        }

    plan = {
        "plan_id": plan_id,
        "goal": goal,
        "created": now,
        "repo": repo,
        "current_task": None,
        "tasks": tasks_dict,
    }

    _save_plan(plan)

    # First task that has no dependencies becomes current
    for tid, tdef in tasks_dict.items():
        if not tdef["depends_on"]:
            plan["current_task"] = tid
            tdef["status"] = "in_progress"
            _save_plan(plan)
            break

    # Honcho persistence
    _ensure_honcho_workspace()
    _save_plan_state_to_honcho(plan_id, "active", "true")

    return plan_id


def get_current_task() -> Optional[dict]:
    """Return the current task dict, or None if no active plan."""
    plan = _get_active_plan()
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
        "depends_on": task["depends_on"],
        "progress": _format_progress(plan),
    }


def complete_task(task_id: str) -> dict:
    """Mark a task as completed, advance to next. Returns result dict."""
    plan = _get_active_plan()
    if not plan:
        return {"status": "error", "message": "Kein aktiver Plan."}

    task = plan["tasks"].get(task_id)
    if not task:
        return {"status": "error", "message": f"Task '{task_id}' nicht gefunden."}

    if plan.get("current_task") != task_id:
        return {"status": "error", "message": f"Task '{task_id}' ist nicht der aktuelle Task."}

    # Mark as completed
    task["status"] = "completed"
    _save_plan_state_to_honcho(plan["plan_id"], task_id, "completed")

    # Find next task: first pending task whose dependencies are all completed
    next_task = None
    for tid, tdef in plan["tasks"].items():
        if tdef["status"] != "pending":
            continue
        deps = tdef.get("depends_on", [])
        if all(plan["tasks"].get(d, {}).get("status") == "completed" for d in deps):
            next_task = tid
            break

    if next_task:
        plan["current_task"] = next_task
        plan["tasks"][next_task]["status"] = "in_progress"
        _save_plan_state_to_honcho(plan["plan_id"], next_task, "in_progress")
    else:
        plan["current_task"] = None
        _save_plan_state_to_honcho(plan["plan_id"], "active", "false")

    _save_plan(plan)

    result = {
        "status": "completed",
        "task_id": task_id,
        "next_task": next_task,
    }
    return result


def update_task(task_id: str, changes: dict) -> Optional[dict]:
    """Update a task's properties (files, verify, depends_on)."""
    plan = _get_active_plan()
    if not plan:
        return None
    task = plan["tasks"].get(task_id)
    if not task:
        return None
    for key in ("files", "verify", "depends_on", "name"):
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
    return True


# ─── Drift Detection ─────────────────────────────────────────────────────────

def check_drift() -> list:
    """Compare git diff against current task's files. Returns list of unplanned files."""
    plan = _get_active_plan()
    if not plan or not plan.get("current_task"):
        return []

    tid = plan["current_task"]
    task = plan["tasks"].get(tid)
    if not task:
        return []

    allowed_files = set(task.get("files", []))
    repo = plan.get("repo", "")
    if not repo or not os.path.isdir(os.path.join(repo, ".git")):
        return []

    import subprocess
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=repo,
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return []

        changed = [f.strip() for f in result.stdout.split("\n") if f.strip()]
        unplanned = [f for f in changed if f not in allowed_files]
        return unplanned
    except Exception as e:
        logger.warning(f"Drift check failed: {e}")
        return []


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _format_progress(plan: dict) -> str:
    total = len(plan["tasks"])
    done = sum(1 for t in plan["tasks"].values() if t["status"] == "completed")
    task_ids = list(plan["tasks"].keys())
    current_idx = task_ids.index(plan.get("current_task")) if plan.get("current_task") in task_ids else -1
    if total == 0:
        return "0/0"
    parts = []
    for i, tid in enumerate(task_ids):
        if i < current_idx:
            parts.append(f"✅{tid}")
        elif i == current_idx:
            parts.append(f"▶️{tid}")
        else:
            parts.append(f"⬜{tid}")
    return f"{done}/{total} " + " → ".join(parts)


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

    # 2. Honcho
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"{HONCHO_URL}/health", timeout=3)
        if resp.status != 200:
            issues.append("Honcho: Health-Check fehlgeschlagen")
    except Exception as e:
        issues.append(f"Honcho: Nicht erreichbar ({e})")

    # 3. Serena MCP
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8002/mcp",
            data=b'{"method":"tools/list"}',
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=3)
        if resp.status != 200:
            issues.append("Serena MCP: Nicht verfügbar")
    except Exception as e:
        issues.append(f"Serena MCP: Nicht erreichbar ({e})")

    # 4. Firecrawl
    fc_tools = ["mcp_firecrawl_firecrawl_search", "mcp_firecrawl_firecrawl_scrape"]
    for t in fc_tools:
        if not registry.get_entry(t):
            issues.append(f"Firecrawl: Tool '{t}' nicht im Registry")
            break

    if issues:
        return {"status": "degraded", "issues": issues}
    return {"status": "ok"}
