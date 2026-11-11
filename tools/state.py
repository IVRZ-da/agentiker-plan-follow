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
        # Signatur der Plan-Datei zum Zeitpunkt des Ladens/Speicherns:
        # (mtime_ns, size, sha256). Ohne sie ist der Cache blind fuer externe
        # Aenderungen (execute_code, zweiter Prozess, Handedit) — genau so
        # meldete der Banner am 11.11.2026 "t1, 1/15" bei 14/14 auf der Platte.
        self.active_plan_sig: Optional[tuple] = None
        self.tool_metrics: dict[str, Any] = {}
        self.drift_warnings: list[str] = []
        self.session_id: Optional[str] = None


STATE = PlanState()
