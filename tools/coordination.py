"""coordination.py — Honcho + Git + Lock integration for plan_follow tools/ subpackage."""

from __future__ import annotations

import json
from typing import Any, Optional

from .base import (
    get_session_id,
    logger,
)
from .resolver import (
    resolve_honcho_peer,
    resolve_honcho_url,
    resolve_honcho_workspace,
    resolve_plans_dir,
)

# ─── Honcho Integration (Registry-Dispatch mit Fallback) ──────────────────────


def _retry_with_backoff(fn, max_attempts: int = 3) -> Any:
    """Execute fn with exponential backoff (1s, 2s, 4s). Returns result or raises last exception."""
    import time
    last_exc: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                wait = 2 ** attempt  # 1, 2, 4 seconds
                logger.debug("Honcho retry %s/%s in %ss: %s", attempt + 1, max_attempts, wait, e)
                time.sleep(wait)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("_retry_with_backoff: no exception was caught")


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
        logger.debug("Honcho dispatch failed (best-effort)")
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
                "observer_id": resolve_honcho_peer(),
                "observed_id": resolve_honcho_peer(),
                "content": json.dumps(payload),
                "source": "plan-follow-plugin"
            }]
        }).encode()
        req = urllib.request.Request(
            f"{resolve_honcho_url()}/v3/workspaces/{resolve_honcho_workspace()}/conclusions",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)

    try:
        _retry_with_backoff(_do_save)
    except Exception as e:
        logger.warning("Honcho save failed after retries (non-fatal): %s", e)


def _load_plan_state_from_honcho(*args, **kwargs) -> Optional[str]:
    """Entfernt in v0.5.32 — Honcho taugt nicht als Plan-Recovery.

    Drei unabhaengige Gruende (alle verifiziert):
      1. ``POST /v3/workspaces/{ws}/conclusions/query`` ist die semantische Suche
         und antwortet ohne observer/observed mit HTTP 422.
      2. Workspace/Peer des Plugins ('plan-follow'/'plan-follow-agent') passen
         nicht zu ``~/.hermes/honcho.json`` ('hermes'/'johannes').
      3. Honcho speichert nur die plan_id, nie den Planinhalt.

    Bleibt als No-op erhalten, damit Re-Exports und externe Aufrufer nicht brechen.
    Akzeptiert daher beliebige Positions-/Keyword-Argumente (alte Signaturen
    uebergeben teils plan_id/session_id).
    """
    return None


# ─── Git Commit Integration ────────────────────────────────────────────────────


def _git_commit_if_active(plan: dict) -> None:
    """Git-Commit des Plan-JSONs wenn PLANS_DIR/.git existiert.

    Nur bei relevanten Events (create/complete) — nicht bei jedem update.
    Fehlertolerant: Git-Fehler blockieren nicht das Speichern.
    """
    git_dir = resolve_plans_dir() / ".git"
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
            cwd=resolve_plans_dir(), capture_output=True, text=True, timeout=10,
        )
        if add.returncode != 0:
            return  # Git add failed — silent skip

        # Check if there's anything to commit
        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=resolve_plans_dir(), capture_output=True, text=True, timeout=10,
        )
        if not diff.stdout.strip():
            return  # No changes — silent skip

        # Commit
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=resolve_plans_dir(), capture_output=True, text=True, timeout=30,
        )
    except Exception:
        logger.debug("Auto Git-commit failed (best-effort)")
        pass  # Silent skip — Git-Fehler blockieren nicht


# ─── Auto Lock / Unlock ───────────────────────────────────────────────────────


def _auto_lock_task_files(task: dict) -> None:
    """Auto-acquire locks for all files in a task on activation.

    Best-effort: if coord_state isn't available, silently skip.
    Seit v0.5.33 nur mit PLAN_FOLLOW_LOCKS=1 — ohne Flag wuerde die Aktivierung
    eines Plans (auch die Recovery-Adoption) wieder Locks erzeugen, die niemand
    mehr freigibt.
    """
    import os

    if os.environ.get("PLAN_FOLLOW_LOCKS", "").strip().lower() not in ("1", "true", "yes", "on"):
        return
    files = task.get("files", [])
    if not files:
        return
    try:
        from ..coord_state import acquire_lock
        for f in files:
            acquire_lock(f, get_session_id())
    except Exception:
        logger.debug("Auto lock failed (best-effort)")
        pass  # Best-effort


def _auto_unlock_task_files(task: dict) -> None:
    """Auto-release locks for all files in a completed task."""
    files = task.get("files", [])
    if not files:
        return
    try:
        from ..coord_state import release_lock
        for f in files:
            release_lock(f, get_session_id())
    except Exception:
        logger.debug("Auto unlock failed (best-effort)")
        pass  # Best-effort
