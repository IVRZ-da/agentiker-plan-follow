"""review.py — Review helpers for plan_follow tools/ subpackage."""

from __future__ import annotations

from datetime import datetime, timezone

from .base import (
    _get_active_plan,
    _save_plan,
)

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
