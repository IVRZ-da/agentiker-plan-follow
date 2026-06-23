"""plan_sync.py — Externe Plan-Synchronisation.

Unterstützt:
- GitHub Issues Sync (via gh CLI oder REST API)
- Linear Sync (via Linear MCP)
- Markdown Export/Import
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("plan_follow")

_GH_AVAILABLE = None


def _check_gh() -> bool:
    """Check if GitHub CLI is available."""
    global _GH_AVAILABLE
    if _GH_AVAILABLE is None:
        try:
            subprocess.run(["gh", "--version"], capture_output=True, timeout=5)
            _GH_AVAILABLE = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _GH_AVAILABLE = False
    return _GH_AVAILABLE


def _run_gh(args: list[str], timeout: int = 30) -> dict:
    """Run a GitHub CLI command and return parsed JSON result."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"success": False, "error": result.stderr.strip()}
        if result.stdout.strip():
            return {"success": True, "data": json.loads(result.stdout)}
        return {"success": True, "data": None}
    except FileNotFoundError:
        return {"success": False, "error": "GitHub CLI (gh) not found. Install with: sudo apt install gh"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"GitHub CLI timed out after {timeout}s"}
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"JSON parse error: {e}"}


# ─── GitHub Issues Sync ────────────────────────────────────────────────────────


def sync_to_github(plan: dict, repo: str = "", prefix: str = "[Plan] ") -> dict:
    """Sync plan tasks to GitHub Issues.

    Creates or updates GitHub Issues for each task in the plan.

    Args:
        plan: Plan dict.
        repo: GitHub repo (owner/repo). Auto-detected if empty.
        prefix: Issue title prefix.

    Returns:
        Dict with sync results.
    """
    if not _check_gh():
        return {"success": False, "error": "GitHub CLI not available"}

    # Auto-detect repo from current git remote
    if not repo:
        try:
            r = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True, text=True, timeout=5,
            )
            remote = r.stdout.strip()
            if "github.com" in remote:
                # Parse owner/repo from URL
                parts = remote.replace("https://github.com/", "").replace("git@github.com:", "").split("/")
                if len(parts) >= 2:
                    repo = f"{parts[0]}/{parts[1].replace('.git', '')}"
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {"success": False, "error": "Could not detect GitHub repo"}

    if not repo:
        return {"success": False, "error": "repo is required (owner/repo)"}

    plan_id = plan.get("plan_id", "unknown")
    goal = plan.get("goal", "")
    tasks = plan.get("tasks", {})
    results = []

    for tid, task in tasks.items():
        title = f"{prefix}{task.get('name', tid)} ({plan_id})"
        body = (
            f"## Plan: {goal}\n"
            f"**Task ID:** {tid}\n"
            f"**Status:** {task.get('status', 'pending')}\n"
            f"**Files:** {', '.join(task.get('files', []))}\n\n"
            f"**Verify:** `{task.get('verify', '')}`\n\n"
            f"---\n"
            f"*Synced from plan_follow*"
        )
        gh_result = _run_gh([
            "issue", "create",
            "--repo", repo,
            "--title", title,
            "--body", body,
            "--label", "plan-follow",
        ])
        if gh_result["success"]:
            results.append({
                "task_id": tid,
                "status": "created",
                "url": gh_result.get("data", {}).get("url", ""),
            })
        else:
            results.append({
                "task_id": tid,
                "status": "error",
                "error": gh_result.get("error", "Unknown"),
            })

    return {
        "success": True,
        "repo": repo,
        "plan_id": plan_id,
        "results": results,
        "created": sum(1 for r in results if r["status"] == "created"),
        "failed": sum(1 for r in results if r["status"] == "error"),
    }


# ─── Markdown Export ────────────────────────────────────────────────────────────


def export_to_markdown(plan: dict) -> str:
    """Export a plan as Markdown.

    Args:
        plan: Plan dict.

    Returns:
        Markdown string.
    """
    plan_id = plan.get("plan_id", "unknown")
    goal = plan.get("goal", "Untitled Plan")
    created = plan.get("created", "")
    tasks = plan.get("tasks", {})
    current_task = plan.get("current_task", "")
    parallel_groups = plan.get("parallel_groups", {})

    lines = [
        f"# {goal}",
        "",
        f"**Plan ID:** `{plan_id}`",
        f"**Created:** {created}",
        f"**Tasks:** {len(tasks)}",
        "",
        "## Status",
        "",
    ]

    # Status summary
    status_counts = {}
    for t in tasks.values():
        s = t.get("status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    for s, c in status_counts.items():
        icon = {"completed": "✅", "in_progress": "▶️", "pending": "⏳", "aborted": "⛔", "blocked": "🚫"}.get(s, "❓")
        lines.append(f"- {icon} **{s}**: {c}")
    lines.append("")

    # Current task
    if current_task and current_task in tasks:
        ct = tasks[current_task]
        lines.append(f"## Current Task: {ct.get('name', current_task)}")
        lines.append("")
        if ct.get("files"):
            lines.append(f"**Files:** `{'`, `'.join(ct['files'])}`")
        if ct.get("verify"):
            lines.append(f"**Verify:** `{ct['verify']}`")
        lines.append("")

    # All tasks
    lines.append("## Tasks")
    lines.append("")
    lines.append("| ID | Name | Status | Files | Review |")
    lines.append("|----|------|--------|-------|--------|")

    for tid in sorted(tasks.keys()):
        t = tasks[tid]
        icon = {"completed": "✅", "in_progress": "▶️", "pending": "⏳", "aborted": "⛔", "blocked": "🚫"}.get(t.get("status", ""), "❓")
        files = ", ".join(t.get("files", []))[:40]
        review = t.get("review_profile", "none")
        lines.append(f"| {tid} | {t.get('name', '')} | {icon} {t.get('status', '')} | `{files}` | {review} |")

    lines.append("")

    # Parallel groups
    if parallel_groups:
        lines.append("## Parallel Groups")
        lines.append("")
        for gid, g in parallel_groups.items():
            tasks_in_group = g.get("tasks", [])
            task_names = [f"`{tid}`" for tid in tasks_in_group]
            lines.append(f"- **{gid}**: {', '.join(task_names)} ({g.get('status', 'pending')})")
        lines.append("")

    return "\n".join(lines)


def import_from_markdown(markdown: str) -> Optional[dict]:
    """Import a plan from Markdown format.

    Tries to parse a plan from a structured Markdown file.
    This is a best-effort parser — for precise plans, use plan_create().

    Args:
        markdown: Markdown content.

    Returns:
        Plan dict if parsing succeeds, None otherwise.
    """
    import re

    lines = markdown.split("\n")
    goal = ""
    tasks = {}

    for line in lines:
        # Try to find the title (H1)
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            goal = m.group(1).strip()

        # Try to find task table rows
        m = re.match(r"^\|\s*(\w+)\s*\|\s*(.+?)\s*\|\s*(✅|▶️|⏳|⛔|🚫❓)\s*(\w+)\s*\|", line)
        if m:
            tid = m.group(1)
            name = m.group(2).strip()
            status_text = m.group(4).strip()

            status_map = {
                "done": "completed", "completed": "completed",
                "active": "in_progress", "in_progress": "in_progress",
                "pending": "pending", "aborted": "aborted", "blocked": "blocked",
            }
            status = status_map.get(status_text.lower(), "pending")

            tasks[tid] = {
                "id": tid,
                "name": name,
                "status": status,
                "files": [],
                "verify": "",
                "review_profile": "none",
                "review_result": None,
                "depends_on": [],
            }

    if not tasks:
        return None

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    plan_id = f"{now[:10]}-{goal.lower().replace(' ', '-')[:40]}" if goal else f"{now[:10]}-imported"

    return {
        "plan_id": plan_id,
        "goal": goal or "Imported Plan",
        "created": now,
        "current_task": None,
        "tasks": tasks,
    }
