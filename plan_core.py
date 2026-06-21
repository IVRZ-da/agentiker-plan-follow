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
# ─── Real Module-Level Attributes (for monkeypatch support) ─────────────────
# These are REAL attributes on the module, so tests can do
# monkeypatch.setattr(plan_core, "PLANS_DIR", tmp_path) and
# resolvers in tools/ will read the monkeypatched value at call time.
from pathlib import Path

# ─── Auto Operations ─────────────────────────────────────────────────────────

# ─── Honcho Integration ──────────────────────────────────────────────────────

# ─── Health Check ────────────────────────────────────────────────────────────

# ─── Plan Lifecycle ──────────────────────────────────────────────────────────

# ─── Review Helpers ──────────────────────────────────────────────────────────

# ─── Roadmap Data ────────────────────────────────────────────────────────────

# ─── Status & Progress ───────────────────────────────────────────────────────

# ─── Task CRUD Operations ────────────────────────────────────────────────────

# ─── Plan Validation ─────────────────────────────────────────────────────────

PLANS_DIR: Path = Path.home() / ".hermes" / "plans"
PLANS_INDEX: Path = Path.home() / ".hermes" / "plans" / "plans_index.json"
ARCHIVE_DIR: Path = Path.home() / ".hermes" / "plans" / "archived"
ROADMAPS_DIR: Path = Path.home() / ".hermes" / "roadmaps"


# ─── Backward-Compatible Dynamic Access ──────────────────────────────────────
# Tests and external code access plan_core._active_plan_id, plan_core.HONCHO_*
# etc. HONCHO_* are not monkeypatched by tests, so they stay in __getattr__.
# Uses PEP 562 module __getattr__ / __setattr__ (Python 3.7+).

import sys  # noqa: E402

from .tools import state as _state_mod  # noqa: E402

_HONCHO_DEFAULTS = {
    "HONCHO_URL": "http://127.0.0.1:8001",
    "HONCHO_WORKSPACE": "plan-follow",
    "HONCHO_PEER": "plan-follow-agent",
}

# ─── Sub-Module Attribute Resolution ───────────────────────────────────────
# After module split, lazy imports for backward-compatible attribute resolution.
# This mapping covers all public/private symbols from tools/* submodules that
# are still imported from plan_core by tests and internal modules.
_SUBMODULE_ATTRS = {
    # tools/base
    "_ensure_dirs": ".tools.base",
    "_get_active_plan": ".tools.base",
    "_get_cached_plan": ".tools.base",
    "_load_plan": ".tools.base",
    "_plan_path": ".tools.base",
    "_recover_plan_from_disk": ".tools.base",
    "_reset_cache": ".tools.base",
    "_save_plan": ".tools.base",
    "_update_plans_index": ".tools.base",
    "get_drift_warnings": ".tools.base",
    "get_session_id": ".tools.base",
    "get_tool_metrics": ".tools.base",
    "record_drift_warning": ".tools.base",
    "record_tool_call": ".tools.base",
    "reset_session_id": ".tools.base",
    "reset_tool_metrics": ".tools.base",
    # tools/task
    "_advance_linear": ".tools.task",
    "_advance_parallel_group": ".tools.task",
    "_find_next_in_group": ".tools.task",
    "_format_task": ".tools.task",
    "_task_from_plan": ".tools.task",
    "_tasks_from_plan": ".tools.task",
    "complete_task": ".tools.task",
    "create_plan": ".tools.task",
    "get_current_task": ".tools.task",
    "get_current_task_cached": ".tools.task",
    "get_current_tasks": ".tools.task",
    "get_current_tasks_cached": ".tools.task",
    "set_active_plan": ".tools.task",
    "update_task": ".tools.task",
    # tools/status
    "_format_progress": ".tools.status",
    "_list_plans_from_dir": ".tools.status",
    "get_plan_status": ".tools.status",
    "list_plans": ".tools.status",
    # tools/plan_mgmt
    "abort_plan": ".tools.plan_mgmt",
    "archive_plan": ".tools.plan_mgmt",
    "delete_plan": ".tools.plan_mgmt",
    "get_task_due_info": ".tools.plan_mgmt",
    "restore_plan": ".tools.plan_mgmt",
    "select_plan": ".tools.plan_mgmt",
    "set_task_due": ".tools.plan_mgmt",
    # tools/coordination
    "_auto_lock_task_files": ".tools.coordination",
    "_auto_unlock_task_files": ".tools.coordination",
    "_dispatch_honcho_tool": ".tools.coordination",
    "_git_commit_if_active": ".tools.coordination",
    "_load_plan_state_from_honcho": ".tools.coordination",
    "_retry_with_backoff": ".tools.coordination",
    "_save_plan_state_to_honcho": ".tools.coordination",
    # tools/auto
    "_get_repos": ".tools.auto",
    "auto_commit": ".tools.auto",
    "auto_verify_task": ".tools.auto",
    "check_drift": ".tools.auto",
    # tools/review
    "get_task_review_state": ".tools.review",
    "is_review_passed": ".tools.review",
    "save_review_result": ".tools.review",
    # tools/health
    "_http_ok": ".tools.health",
    "_mod_available": ".tools.health",
    "health_check": ".tools.health",
    # tools/validation
    "validate_plan": ".tools.validation",
    # tools/roadmap_data
    "_list_roadmaps": ".tools.roadmap_data",
    "_load_roadmap": ".tools.roadmap_data",
    "_parse_roadmap_yaml_simple": ".tools.roadmap_data",
    "_roadmap_path": ".tools.roadmap_data",
    "_save_roadmap": ".tools.roadmap_data",
    "ROADMAPS_DIR": ".tools.roadmap_data",
}


def __getattr__(name: str):
    """Dynamic attribute access for backward compatibility.

    Handles:
      - plan_core._active_plan      → STATE.active_plan
      - plan_core._active_plan_id   → STATE.active_plan_id
      - plan_core._list_roadmaps    → tools.roadmap_data._list_roadmaps
      - plan_core._load_roadmap     → tools.roadmap_data._load_roadmap
      - plan_core._save_roadmap     → tools.roadmap_data._save_roadmap
      - plan_core.HONCHO_URL etc.   → hardcoded defaults (not monkeypatched)
    """
    if name == "_active_plan":
        return _state_mod.STATE.active_plan
    if name == "_active_plan_id":
        return _state_mod.STATE.active_plan_id
    if name in _SUBMODULE_ATTRS:
        mod_path = _SUBMODULE_ATTRS[name]
        # lazy import based on mod_path
        if mod_path == ".tools.roadmap_data":
            from .tools import roadmap_data as _m
        elif mod_path == ".tools.task":
            from .tools import task as _m
        elif mod_path.startswith(".tools.base"):
            from .tools import base as _m
        elif mod_path == ".tools.status":
            from .tools import status as _m
        elif mod_path == ".tools.plan_mgmt":
            from .tools import plan_mgmt as _m
        elif mod_path == ".tools.coordination":
            from .tools import coordination as _m
        elif mod_path == ".tools.auto":
            from .tools import auto as _m
        elif mod_path == ".tools.review":
            from .tools import review as _m
        elif mod_path == ".tools.health":
            from .tools import health as _m
        elif mod_path == ".tools.validation":
            from .tools import validation as _m
        else:
            raise AttributeError(f"module 'plan_follow.plan_core' has no attribute '{name}'")
        return getattr(_m, name)
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
