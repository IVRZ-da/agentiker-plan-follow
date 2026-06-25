"""state.py — Shared mutable state for plan_follow modules.

This module replaces scattered module-level globals with a single
PlanState instance. All modules that modify _active_plan, _active_plan_id,
_tool_metrics, _drift_warnings or _SESSION_ID import STATE and use
STATE.attr instead of module-level globals + 'global' declarations.

Usage:
    from . state import STATE
    STATE.active_plan = plan
    STATE.active_plan_id = plan_id
    STATE.tool_metrics[tool_name] = ...
"""
from typing import Any, Optional


class PlanState:
    """Shared mutable state for plan_follow plugin."""

    def __init__(self) -> None:
        self.active_plan: Optional[dict] = None
        self.active_plan_id: Optional[str] = None
        self.tool_metrics: dict[str, Any] = {}
        self.drift_warnings: list[str] = []
        self.session_id: Optional[str] = None
        self.kanban_root_id: Optional[str] = None


STATE = PlanState()
