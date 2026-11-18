"""state.py — Shared mutable state for plan_follow modules.

This module replaces scattered module-level globals with a single
PlanState instance. All modules that modify _active_plan, _active_plan_id,
_tool_metrics, _drift_warnings or _SESSION_ID import STATE and use
STATE.attr instead of module-level globals + 'global' declarations.

**Session-Scope:** ``active_plan``, ``active_plan_id`` und ``active_plan_sig`` sind pro
Session getrennt (Schlüssel aus ``session_scope.scope_key()``). Ohne diese Trennung nimmt
eine parallele Session im selben Prozess der anderen den aktiven Plan weg — der State war
prozessweit, die Pläne sind es nicht. Aufrufstellen bleiben unverändert: sie lesen und
schreiben weiter ``STATE.active_plan``; die Properties wählen den Slot der laufenden
Session. Ohne Runtime-Session (CLI, Test, Subprozess) greift ein gemeinsamer Fallback-Slot,
also genau das Verhalten von vorher.

``tool_metrics`` und ``drift_warnings`` bleiben bewusst prozessweit: sie werden pro Task
geleert und richten keinen sessionsübergreifenden Schaden an.

Usage:
    from . state import STATE
    STATE.active_plan = plan
    STATE.active_plan_id = plan_id
    STATE.tool_metrics[tool_name] = ...
"""
from typing import Any, Optional

from .session_scope import scope_key

_EMPTY = {"active_plan": None, "active_plan_id": None, "active_plan_sig": None}


class PlanState:
    """Shared mutable state for plan_follow plugin (active plan session-scoped)."""

    def __init__(self) -> None:
        self._slots: dict[str, dict[str, Any]] = {}
        self._fallback: dict[str, Any] = dict(_EMPTY)
        self.session_id: Optional[str] = None
        self.tool_metrics: dict[str, Any] = {}
        self.drift_warnings: list[str] = []

    # ─── intern ────────────────────────────────────────────────────────────────
    def _slot(self) -> dict[str, Any]:
        key = scope_key()
        if not key:
            return self._fallback
        slot = self._slots.get(key)
        if slot is None:
            slot = dict(_EMPTY)
            self._slots[key] = slot
        return slot

    def _store(self, field: str, value: Any) -> None:
        key = scope_key()
        slot = self._slot()
        slot[field] = value
        # Leere Slots nicht sammeln: jede besuchte Session wuerde sonst Speicher halten.
        if key and all(v is None for v in slot.values()):
            self._slots.pop(key, None)

    # ─── Properties (Aufrufstellen bleiben unveraendert) ───────────────────────
    @property
    def active_plan(self) -> Optional[dict]:
        return self._slot()["active_plan"]

    @active_plan.setter
    def active_plan(self, value: Optional[dict]) -> None:
        self._store("active_plan", value)

    @property
    def active_plan_id(self) -> Optional[str]:
        return self._slot()["active_plan_id"]

    @active_plan_id.setter
    def active_plan_id(self, value: Optional[str]) -> None:
        self._store("active_plan_id", value)

    @property
    def active_plan_sig(self) -> Optional[tuple]:
        return self._slot()["active_plan_sig"]

    @active_plan_sig.setter
    def active_plan_sig(self, value: Optional[tuple]) -> None:
        self._store("active_plan_sig", value)


STATE = PlanState()
