"""
plan_core.py — Re-Export Facade (Module-Split v2)

All functions have been extracted into tools/ subpackage.
This file re-exports everything for backward compatibility.

Submodules:
  tools/base.py         — Module state, persistence, session
  tools/coordination.py — Honcho, Git, lock integration
  tools/task.py         — Task CRUD operations
  tools/status.py       — Status queries, list, progress
  tools/plan_mgmt.py    — Plan lifecycle (abort, delete, due, archive)
  tools/auto.py         — Auto-verify, auto-commit, drift
  tools/review.py       — Review helpers
  tools/health.py       — Health check
  tools/validation.py   — Plan validation
  tools/roadmap_data.py — Roadmap data functions
"""

# ─── Module State & Persistence ──────────────────────────────────────────────
from plan_follow.tools.base import (
    _ensure_dirs,
    _plan_path,
    _save_plan,
    _load_plan,
    _get_active_plan,
    _get_cached_plan,
    _update_plans_index,
    _recover_plan_from_disk,
    _reset_cache,
    get_session_id,
    reset_session_id,
    reset_tool_metrics,
    record_tool_call,
    record_drift_warning,
    get_tool_metrics,
    get_drift_warnings,
)

# ─── Honcho Integration ──────────────────────────────────────────────────────
from plan_follow.tools.coordination import (
    _retry_with_backoff,
    _dispatch_honcho_tool,
    _save_plan_state_to_honcho,
    _load_plan_state_from_honcho,
    _git_commit_if_active,
    _auto_lock_task_files,
    _auto_unlock_task_files,
)

# ─── Task CRUD Operations ────────────────────────────────────────────────────
from plan_follow.tools.task import (
    create_plan,
    get_current_task,
    get_current_task_cached,
    get_current_tasks,
    get_current_tasks_cached,
    _task_from_plan,
    _tasks_from_plan,
    _format_task,
    complete_task,
    _advance_parallel_group,
    _find_next_in_group,
    _advance_linear,
    update_task,
    set_active_plan,
)

# ─── Status & Progress ───────────────────────────────────────────────────────
from plan_follow.tools.status import (
    get_plan_status,
    list_plans,
    _list_plans_from_dir,
    _format_progress,
)

# ─── Plan Lifecycle ──────────────────────────────────────────────────────────
from plan_follow.tools.plan_mgmt import (
    abort_plan,
    delete_plan,
    select_plan,
    set_task_due,
    get_task_due_info,
    archive_plan,
    restore_plan,
)

# ─── Auto Operations ─────────────────────────────────────────────────────────
from plan_follow.tools.auto import (
    auto_verify_task,
    auto_commit,
    _get_repos,
    check_drift,
)

# ─── Review Helpers ──────────────────────────────────────────────────────────
from plan_follow.tools.review import (
    save_review_result,
    is_review_passed,
    get_task_review_state,
)

# ─── Health Check ────────────────────────────────────────────────────────────
from plan_follow.tools.health import (
    health_check,
)

# ─── Plan Validation ─────────────────────────────────────────────────────────
from plan_follow.tools.validation import (
    validate_plan,
)

# ─── Roadmap Data ────────────────────────────────────────────────────────────
from plan_follow.tools.roadmap_data import (
    _roadmap_path,
    _list_roadmaps,
    _load_roadmap,
    _save_roadmap,
    _parse_roadmap_yaml_simple,
)


# ─── Real Module-Level Attributes (for monkeypatch support) ─────────────────
# These are REAL attributes on the module, so tests can do
# monkeypatch.setattr(plan_core, "PLANS_DIR", tmp_path) and
# resolvers in tools/ will read the monkeypatched value at call time.

from pathlib import Path

PLANS_DIR: Path = Path.home() / ".hermes" / "plans"
PLANS_INDEX: Path = Path.home() / ".hermes" / "plans" / "plans_index.json"
ARCHIVE_DIR: Path = Path.home() / ".hermes" / "plans" / "archived"
ROADMAPS_DIR: Path = Path.home() / ".hermes" / "roadmaps"


# ─── Backward-Compatible Dynamic Access ──────────────────────────────────────
# Tests and external code access plan_core._active_plan_id, plan_core.HONCHO_*
# etc. HONCHO_* are not monkeypatched by tests, so they stay in __getattr__.
# Uses PEP 562 module __getattr__ / __setattr__ (Python 3.7+).

import sys
import plan_follow.tools.state as _state_mod

_HONCHO_DEFAULTS = {
    "HONCHO_URL": "http://127.0.0.1:8001",
    "HONCHO_WORKSPACE": "plan-follow",
    "HONCHO_PEER": "plan-follow-agent",
}


def __getattr__(name: str):
    """Dynamic attribute access for backward compatibility.

    Handles:
      - plan_core._active_plan      → STATE.active_plan
      - plan_core._active_plan_id   → STATE.active_plan_id
      - plan_core.HONCHO_URL etc.   → hardcoded defaults (not monkeypatched)
    """
    if name == "_active_plan":
        return _state_mod.STATE.active_plan
    if name == "_active_plan_id":
        return _state_mod.STATE.active_plan_id
    if name in _HONCHO_DEFAULTS:
        return _HONCHO_DEFAULTS[name]
    raise AttributeError(f"module 'plan_follow.plan_core' has no attribute '{name}'")


def __setattr__(name: str, value):
    """Dynamic attribute set for backward compatibility (e.g. monkeypatch).

    For _active_plan/_active_plan_id: proxy to STATE.
    For everything else: write to module __dict__ (supports monkeypatch).
    """
    if name == "_active_plan":
        _state_mod.STATE.active_plan = value
    elif name == "_active_plan_id":
        _state_mod.STATE.active_plan_id = value
    else:
        object.__setattr__(sys.modules[__name__], name, value)
