"""
plan_tools.py — Re-Export Facade for plan_follow tool handlers.

All handler implementations now live in their logical modules.
This module re-exports them for __init__.py's tool registration.
"""
from __future__ import annotations

# Core logic re-exports (used by handler modules and tests)
from . import plan_core, plan_peer_review  # noqa: F401
from ._fmt import fmt_err, fmt_info, fmt_ok, fmt_table  # noqa: F401

# Coordination & session handlers
from .coord_state import (  # noqa: F401
    plan_coord_cleanup_tool,
    plan_lock_tool,
    plan_notify_tool,
    plan_session_tool,
)

# Plan utilities
from .plan_decompose import plan_decompose_tool  # noqa: F401
from .plan_roadmap import plan_roadmap_handler  # noqa: F401
from .plan_suggest import (  # noqa: F401
    plan_simulate_tool,
    plan_suggest_tool,
    plan_time_tool,
)
from .plan_sync import plan_sync_tool  # noqa: F401
from .plan_templates import plan_template_tool  # noqa: F401
from .tools.auto import plan_verify_tool  # noqa: F401

# Git handlers
from .tools.git import (  # noqa: F401
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
from .tools.plan_mgmt import (  # noqa: F401
    plan_abort_tool,
    plan_archive_tool,
    plan_delete_tool,
    plan_duedate_tool,
    plan_restore_tool,
)

# Review handlers
from .tools.review import (  # noqa: F401
    plan_auto_review_tool,
    plan_review_profiles_tool,
    plan_review_save_result_tool,
    plan_review_tool,
)
from .tools.status import (  # noqa: F401
    plan_current_tool,
    plan_list_tool,
    plan_status_tool,
)

# Task & Plan-management handlers
from .tools.task import (  # noqa: F401
    plan_complete_tool,
    plan_create_tool,
    plan_select_tool,
    plan_update_tool,
)
from .tools.validation import plan_validate_tool  # noqa: F401

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
