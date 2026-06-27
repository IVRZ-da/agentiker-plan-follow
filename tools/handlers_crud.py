"""
Backward-compat re-export — handler functions now live in their logical modules.

plan_create_tool, plan_complete_tool, plan_update_tool, plan_select_tool  → tools/task.py
plan_current_tool, plan_status_tool, plan_list_tool                      → tools/status.py
plan_verify_tool                                                         → tools/auto.py
plan_abort_tool, plan_delete_tool, plan_duedate_tool                     → tools/plan_mgmt.py
plan_archive_tool, plan_restore_tool                                     → tools/plan_mgmt.py
plan_validate_tool                                                       → tools/validation.py
plan_template_tool                                                       → plan_templates.py
plan_suggest_tool                                                        → plan_suggest.py
"""
from __future__ import annotations

from ..plan_suggest import plan_suggest_tool  # noqa: F401
from ..plan_templates import plan_template_tool  # noqa: F401
from .auto import plan_verify_tool  # noqa: F401
from .plan_mgmt import (  # noqa: F401
    plan_abort_tool,
    plan_archive_tool,
    plan_delete_tool,
    plan_duedate_tool,
    plan_restore_tool,
)
from .status import plan_current_tool, plan_list_tool, plan_status_tool  # noqa: F401
from .task import (  # noqa: F401
    plan_complete_tool,
    plan_create_tool,
    plan_select_tool,
    plan_update_tool,
)
from .validation import plan_validate_tool  # noqa: F401
