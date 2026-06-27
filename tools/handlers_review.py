"""handlers_review.py — Backward-compat re-export from tools.review.

All handler functions have been merged into tools/review.py.
This file re-exports them for backward compatibility.
"""
from __future__ import annotations

from .review import (  # noqa: F401
    plan_auto_review_tool,
    plan_review_profiles_tool,
    plan_review_save_result_tool,
    plan_review_tool,
)
