"""
plan_tools.py — Re-Export Facade für tool-handler Subpackage.

Alle Tool-Implementierungen wurden in tools/handlers_*.py aufgeteilt:
  - tools/handlers_crud.py   (15 Handler: create/update/delete/abort/...)
  - tools/handlers_git.py     (8 Handler: git-Tools + PR creation)
  - tools/handlers_review.py  (4 Handler: review/auto-review/save)
  - tools/handlers_misc.py    (9 Handler: session/lock/notify/...)

Dieses Modul importiert alle Handler re-exportiert sie, sodass
__init__.py und bestehende Tests KEINE Änderungen brauchen.
"""

import logging

from . import plan_core, plan_peer_review  # noqa: F401 — re-exported für Tests (conftest.py patch targets)
from ._fmt import fmt_err, fmt_info, fmt_ok, fmt_table  # noqa: F401 — re-exported für Tests (conftest.py patch targets)
from .plan_roadmap import plan_roadmap_handler  # noqa: F401 — importiert für __init__.py

# Re-Export aller Handler aus tools/handlers_*
from .tools.handlers_crud import (  # noqa: F401
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
    plan_template_tool,
    plan_update_tool,
    plan_validate_tool,
    plan_verify_tool,
)
from .tools.handlers_git import (  # noqa: F401
    plan_git_branch_tool,
    plan_git_init_tool,
    plan_git_push_tool,
    plan_git_stash_tool,
    plan_git_status_tool,
    plan_git_sync_tool,
    plan_git_tag_tool,
    plan_pr_create_tool,
)
from .tools.handlers_misc import (  # noqa: F401
    plan_decompose_tool,
    plan_history_tool,
    plan_lock_tool,
    plan_notify_tool,
    plan_session_tool,
    plan_simulate_tool,
    plan_suggest_tool,
    plan_sync_tool,
    plan_time_tool,
)
from .tools.handlers_review import (  # noqa: F401
    plan_auto_review_tool,
    plan_review_profiles_tool,
    plan_review_save_result_tool,
    plan_review_tool,
)

logger = logging.getLogger("plan_follow")
