"""
plan_tools.py — Re-Export Facade for plan_follow tool handlers.

All handler implementations live in tools/handlers_*.py.
This module re-exports them for backward compatibility with
existing tests and __init__.py registrations.
"""

from __future__ import annotations

# Backward-compat imports — tests patch these via plan_follow.plan_tools.attr
from . import plan_core, plan_peer_review  # noqa: F401
from ._fmt import fmt_err, fmt_info, fmt_ok, fmt_table  # noqa: F401
from .plan_roadmap import plan_roadmap_handler  # noqa: F401

# CRUD handlers
from .tools.handlers_crud import (
    plan_abort_tool,
    plan_archive_tool,
    plan_complete_tool,
    plan_create_tool,
    plan_current_tool,
    plan_delete_tool,
    plan_duedate_tool,
    plan_list_tool,
    plan_restore_tool,
    plan_select_tool,
    plan_status_tool,
    plan_suggest_tool,
    plan_template_tool,
    plan_update_tool,
    plan_validate_tool,
    plan_verify_tool,
)

# Git handlers
from .tools.handlers_git import (
    plan_git_branch_tool,
    plan_git_init_tool,
    plan_git_push_tool,
    plan_git_stash_tool,
    plan_git_status_tool,
    plan_git_sync_tool,
    plan_git_tag_tool,
    plan_history_tool,
    plan_pr_create_tool,
)

# Misc/coordination handlers
from .tools.handlers_misc import (
    plan_coord_cleanup_tool,
    plan_decompose_tool,
    plan_lock_tool,
    plan_notify_tool,
    plan_session_tool,
    plan_simulate_tool,
    plan_sync_tool,
    plan_time_tool,
)

# Review handlers
from .tools.handlers_review import (
    plan_auto_review_tool,
    plan_review_profiles_tool,
    plan_review_save_result_tool,
    plan_review_tool,
)

__all__ = [
    "plan_abort_tool",
    "plan_archive_tool",
    "plan_auto_review_tool",
    "plan_complete_tool",
    "plan_coord_cleanup_tool",
    "plan_create_tool",
    "plan_current_tool",
    "plan_decompose_tool",
    "plan_delete_tool",
    "plan_duedate_tool",
    "plan_git_branch_tool",
    "plan_git_init_tool",
    "plan_git_push_tool",
    "plan_git_status_tool",
    "plan_git_stash_tool",
    "plan_git_sync_tool",
    "plan_git_tag_tool",
    "plan_history_tool",
    "plan_list_tool",
    "plan_lock_tool",
    "plan_notify_tool",
    "plan_pr_create_tool",
    "plan_restore_tool",
    "plan_review_profiles_tool",
    "plan_review_save_result_tool",
    "plan_review_tool",
    "plan_roadmap_handler",
    "plan_select_tool",
    "plan_session_tool",
    "plan_simulate_tool",
    "plan_status_tool",
    "plan_suggest_tool",
    "plan_sync_tool",
    "plan_template_tool",
    "plan_time_tool",
    "plan_update_tool",
    "plan_validate_tool",
    "plan_verify_tool",
]
