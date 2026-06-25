"""coordination.py — Kanban + Git + Lock integration for plan_follow tools/.

Ersetzt die vorherige Honcho-Integration durch Kanban-DB:
  - _save_plan_state_to_honcho → Kanban-Task-Update
  - _load_plan_state_from_honcho → Kanban-Query
  - _auto_lock/unlock_task_files → coord_state.acquire_lock/release_lock (JSON+fcntl)
  - _git_commit_if_active → unverändert
"""

from __future__ import annotations

import json
from typing import Optional

from .base import (
    get_session_id,
    logger,
)
from .resolver import (
    resolve_plans_dir,
)

# ─── Kanban-DB Verfügbarkeit ─────────────────────────────────────────────────

def _kanban_db():
    try:
        from hermes_cli import kanban_db
        return kanban_db
    except ImportError:
        return None


def _kanban_profile() -> str:
    import os
    return os.environ.get("HERMES_PROFILE", "default")


# ─── Plan State via Kanban (ersetzt Honcho) ──────────────────────────────────


def _save_plan_state_to_kanban(plan_id: str, task_id: str, status: str) -> None:
    """Save plan state as a Kanban task comment/event.

    Data model (JSON-Body):
        {"source": "plan_follow", "plan_id": "...", "task_id": "...", "status": "..."}
    """
    kdb = _kanban_db()
    if not kdb:
        return

    try:
        profile = _kanban_profile()
        payload = json.dumps({
            "source": "plan_follow",
            "plan_id": plan_id,
            "task_id": task_id,
            "status": status,
        })
        # Append state as comment on the plan_index task
        tid = f"plan_index:{profile}"
        conn = kdb.connect(board='plans')
        try:
            kdb.add_comment(conn, tid, author="system", body=payload)
        finally:
            conn.close()
        logger.debug("Plan state saved to Kanban: %s/%s = %s", plan_id, task_id, status)
    except Exception as e:
        logger.debug("Kanban state save failed (non-fatal): %s", e)


def _load_plan_state_from_kanban() -> Optional[str]:
    """Load active plan ID from Kanban markers. Returns plan_id or None."""
    kdb = _kanban_db()
    if not kdb:
        return None

    try:
        profile = _kanban_profile()
        conn = kdb.connect()
        # Query the plan_index task for this profile
        rows = conn.execute(
            "SELECT body FROM tasks WHERE "
            "body LIKE '%\"type\":\"plan_index\"%' "
            "AND assignee = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (profile,)
        ).fetchall()
        for row in rows:
            try:
                body = json.loads(row[0]) if row[0] else {}
                if body.get("type") == "plan_index":
                    return body.get("plan_id")
            except (json.JSONDecodeError, TypeError):
                continue
        # Fallback: check comments on plan_index tasks
        rows2 = conn.execute(
            "SELECT c.body FROM task_comments c "
            "JOIN tasks t ON t.id = c.task_id "
            "WHERE t.body LIKE '%\"type\":\"plan_index\"%' "
            "AND t.assignee = ? "
            "ORDER BY c.created_at DESC LIMIT 5",
            (profile,)
        ).fetchall()
        for row in rows2:
            try:
                payload = json.loads(row[0]) if row[0] else {}
                if isinstance(payload, dict) and payload.get("source") == "plan_follow":
                    pid = payload.get("plan_id")
                    if pid:
                        return pid
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as e:
        logger.debug("Kanban state load failed: %s", e)

    return None


# ─── Aliase für Abwärtskompatibilität ────────────────────────────────────────


def _save_plan_state_to_honcho(plan_id: str, task_id: str, status: str) -> None:
    """Legacy alias — speichert Plan-State via Kanban."""
    _save_plan_state_to_kanban(plan_id, task_id, status)


def _load_plan_state_from_honcho() -> Optional[str]:
    """Legacy alias — lädt Plan-State via Kanban."""
    return _load_plan_state_from_kanban()


# ─── Git Commit Integration (unverändert) ────────────────────────────────────


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
        add = subprocess.run(
            ["git", "add", "--", f"{plan_id}.json"],
            cwd=resolve_plans_dir(), capture_output=True, text=True, timeout=10,
        )
        if add.returncode != 0:
            return

        diff = subprocess.run(
            ["git", "diff", "--cached", "--stat"],
            cwd=resolve_plans_dir(), capture_output=True, text=True, timeout=10,
        )
        if not diff.stdout.strip():
            return

        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=resolve_plans_dir(), capture_output=True, text=True, timeout=30,
        )
    except Exception:
        logger.debug("Auto Git-commit failed (best-effort)")
        pass


# ─── Auto Lock / Unlock (via coord_state — JSON+fcntl) ───────────────────────


def _create_review_task(plan_id: str, task_id: str, review_profile: str, files: list[str]) -> None:
    """Create a review task in Kanban gated on the completed task.

    The review task is assigned to plan-reviewer and depends on the
    implementation task being completed.
    """
    kdb = _kanban_db()
    if not kdb or review_profile in ("none", "", None):
        return

    try:
        import json

        review_body = json.dumps({
            "type": "review_task",
            "plan_id": plan_id,
            "task_id": task_id,
            "files": files,
            "review_profile": review_profile,
        })

        conn = kdb.connect(board='plans')
        try:
            from .state import STATE
            parents_list = [STATE.kanban_root_id] if STATE.kanban_root_id else []
            kdb.create_task(
                conn,
                title=f"Review {plan_id[:30]}:{task_id}",
                body=review_body,
                assignee="plan-reviewer",
                initial_status="blocked",
                skills=[f"review:{review_profile}"],
                parents=parents_list,
                workspace_kind="dir",
                max_runtime_seconds=1800,
                max_retries=1,
            )

        finally:
            conn.close()

        logger.info("Review-Task erstellt für %s/%s (Profil: %s)", plan_id, task_id, review_profile)
    except Exception as e:
        logger.debug("Review task creation failed (non-fatal): %s", e)


def _auto_lock_task_files(task: dict) -> None:
    """Auto-acquire locks for all files in a task on activation."""
    files = task.get("files", [])
    if not files:
        return
    try:
        from ..coord_state import acquire_lock
        for f in files:
            acquire_lock(f, get_session_id())
    except Exception:
        logger.debug("Auto lock failed (best-effort)")
        pass


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
        pass
